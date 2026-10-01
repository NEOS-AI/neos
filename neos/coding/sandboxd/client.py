"""Host side of the `neos-sandboxd` framed RPC.

The channel is whatever byte stream the provider client gives us: a vendor
exec with stdin/stdout piped to ``neos-sandboxd connect``, or a local unix
socket in tests. The first exchange is the handshake; a protocol version,
bundle digest, or capability mismatch closes the channel before any other
request is sent.

Guest errors arrive as ``(kind, code)`` pairs and become the sanitized
`SandboxError` subclasses the coding loop already understands.
"""

from __future__ import annotations

import asyncio
import hmac
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from neos.coding.sandbox.base import (
    ReplayGap,
    SandboxNotFound,
    SandboxPolicyViolation,
    SandboxStateConflict,
    SandboxTimeout,
    SandboxUnavailable,
)
from neos.coding.sandboxd.guest import (
    CAPABILITIES,
    PROTOCOL_VERSION,
    SECRET_ENV_CAPABILITY,
    FrameError,
    bundle_digest,
    decode_payload,
    encode_frame,
    frame_length,
)

_HEADER_BYTES = 4
_CONNECTION_LOST = "sandboxd_connection_lost"
#: Capabilities a session checks per call instead of requiring at handshake.
#: A guest pinned by an older digest still serves everything else; only the
#: feature it does not advertise is refused (track Q6b: secrets).
OPTIONAL_CAPABILITIES = frozenset({SECRET_ENV_CAPABILITY})


class SandboxdChannel(Protocol):
    async def read_exactly(self, size: int) -> bytes: ...

    async def write(self, data: bytes) -> None: ...

    async def close(self) -> None: ...


class StreamSandboxdChannel:
    """A channel over an asyncio stream pair."""

    def __init__(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._reader = reader
        self._writer = writer

    async def read_exactly(self, size: int) -> bytes:
        try:
            return await self._reader.readexactly(size)
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            raise SandboxUnavailable(_CONNECTION_LOST) from None

    async def write(self, data: bytes) -> None:
        try:
            self._writer.write(data)
            await self._writer.drain()
        except (ConnectionError, OSError, RuntimeError):
            raise SandboxUnavailable(_CONNECTION_LOST) from None

    async def close(self) -> None:
        self._writer.close()
        try:
            await self._writer.wait_closed()
        except (ConnectionError, OSError, RuntimeError):
            pass


@dataclass(frozen=True, slots=True)
class SandboxdExpectation:
    """What the host requires from the guest before it opens a session."""

    bundle_digest: str
    protocol_version: int = PROTOCOL_VERSION
    required_capabilities: frozenset[str] = field(
        default_factory=lambda: frozenset(CAPABILITIES) - OPTIONAL_CAPABILITIES
    )

    @classmethod
    def bundled(cls) -> SandboxdExpectation:
        """Pin the guest shipped in this source tree."""
        return cls(bundle_digest=bundle_digest())


@dataclass(frozen=True, slots=True)
class SandboxdHello:
    protocol_version: int
    bundle_digest: str
    capabilities: frozenset[str]
    revision: int


_ERRORS: Mapping[str, type[Exception]] = {
    "policy": SandboxPolicyViolation,
    "not_found": SandboxNotFound,
    "conflict": SandboxStateConflict,
    "timeout": SandboxTimeout,
    "gap": ReplayGap,
    "file_not_found": FileNotFoundError,
}


def _guest_error(error: object) -> Exception:
    if not isinstance(error, dict):
        return SandboxUnavailable("sandboxd_response_invalid")
    kind = error.get("kind")
    code = error.get("code")
    if not isinstance(kind, str) or not isinstance(code, str):
        return SandboxUnavailable("sandboxd_response_invalid")
    if kind == "protocol":
        return SandboxUnavailable(f"sandboxd_protocol_error:{code}")
    return _ERRORS.get(kind, SandboxUnavailable)(code)


class SandboxdClient:
    def __init__(
        self,
        channel: SandboxdChannel,
        *,
        request_timeout_sec: float = 60.0,
    ) -> None:
        self._channel = channel
        self._request_timeout_sec = request_timeout_sec
        self._pending: dict[int, asyncio.Future[dict]] = {}
        self._next_id = 1
        self._write_lock = asyncio.Lock()
        self._reader_task: asyncio.Task[None] | None = None
        self._closed = False
        self.hello: SandboxdHello | None = None

    @property
    def closed(self) -> bool:
        return self._closed

    def supports(self, capability: str) -> bool:
        """Did the pinned guest advertise ``capability`` in its hello?"""
        return self.hello is not None and capability in self.hello.capabilities

    async def handshake(
        self,
        expectation: SandboxdExpectation,
        *,
        base_revision: int = 0,
    ) -> SandboxdHello:
        if self._reader_task is not None or self._closed:
            raise SandboxUnavailable("sandboxd_handshake_repeated")
        try:
            async with asyncio.timeout(self._request_timeout_sec):
                await self._channel.write(
                    encode_frame(
                        {
                            "v": PROTOCOL_VERSION,
                            "id": 0,
                            "op": "hello",
                            "args": {
                                "protocol_version": expectation.protocol_version,
                                "base_revision": base_revision,
                            },
                        }
                    )
                )
                response = await self._read_message()
        except TimeoutError:
            await self.close()
            raise SandboxUnavailable("sandboxd_handshake_timeout") from None
        except (SandboxUnavailable, FrameError):
            await self.close()
            raise SandboxUnavailable("sandboxd_handshake_failed") from None
        try:
            hello = self._verify(response, expectation)
        except SandboxUnavailable:
            await self.close()
            raise
        self.hello = hello
        self._reader_task = asyncio.create_task(self._read_loop())
        return hello

    @staticmethod
    def _verify(response: dict, expectation: SandboxdExpectation) -> SandboxdHello:
        if response.get("ok") is not True or not isinstance(response.get("result"), dict):
            raise SandboxUnavailable("sandboxd_handshake_failed")
        result = response["result"]
        version = result.get("protocol_version")
        digest = result.get("bundle_digest")
        capabilities = result.get("capabilities")
        revision = result.get("revision")
        if version != expectation.protocol_version:
            raise SandboxUnavailable("sandboxd_protocol_mismatch")
        if not isinstance(digest, str) or not hmac.compare_digest(
            digest, expectation.bundle_digest
        ):
            raise SandboxUnavailable("sandboxd_digest_mismatch")
        if not isinstance(capabilities, list) or not all(
            isinstance(item, str) for item in capabilities
        ):
            raise SandboxUnavailable("sandboxd_handshake_failed")
        missing = expectation.required_capabilities - set(capabilities)
        if missing:
            raise SandboxUnavailable(
                f"sandboxd_capability_missing:{sorted(missing)[0]}"
            )
        if not isinstance(revision, int) or revision < 0:
            raise SandboxUnavailable("sandboxd_handshake_failed")
        return SandboxdHello(
            protocol_version=version,
            bundle_digest=digest,
            capabilities=frozenset(capabilities),
            revision=revision,
        )

    async def call(
        self,
        op: str,
        args: Mapping[str, Any] | None = None,
        *,
        timeout_sec: float | None = None,
    ) -> dict:
        if self._reader_task is None:
            raise SandboxUnavailable("sandboxd_handshake_required")
        if self._closed:
            raise SandboxUnavailable(_CONNECTION_LOST)
        message_id = self._next_id
        self._next_id += 1
        try:
            frame = encode_frame(
                {"v": PROTOCOL_VERSION, "id": message_id, "op": op, "args": dict(args or {})}
            )
        except FrameError:
            raise SandboxPolicyViolation("sandboxd_request_too_large") from None
        future: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        self._pending[message_id] = future
        try:
            async with self._write_lock:
                await self._channel.write(frame)
            async with asyncio.timeout(timeout_sec or self._request_timeout_sec):
                response = await future
        except TimeoutError:
            raise SandboxTimeout("sandboxd_request_timeout") from None
        finally:
            self._pending.pop(message_id, None)
        if response.get("ok") is True:
            result = response.get("result")
            if not isinstance(result, dict):
                raise SandboxUnavailable("sandboxd_response_invalid")
            return result
        raise _guest_error(response.get("error"))

    async def _read_message(self) -> dict:
        header = await self._channel.read_exactly(_HEADER_BYTES)
        payload = await self._channel.read_exactly(frame_length(header))
        return decode_payload(payload)

    async def _read_loop(self) -> None:
        try:
            while True:
                message = await self._read_message()
                message_id = message.get("id")
                future = self._pending.get(message_id) if isinstance(message_id, int) else None
                if future is None:
                    if message_id is None:
                        # An unaddressed error is a protocol failure.
                        break
                    continue
                if not future.done():
                    future.set_result(message)
        except (SandboxUnavailable, FrameError):
            pass
        finally:
            self._fail_pending()

    def _fail_pending(self) -> None:
        self._closed = True
        for future in self._pending.values():
            if not future.done():
                future.set_exception(SandboxUnavailable(_CONNECTION_LOST))

    async def close(self) -> None:
        self._closed = True
        task = self._reader_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._fail_pending()
        await self._channel.close()
