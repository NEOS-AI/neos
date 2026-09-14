"""Exec transports that let remote managed sandboxes serve a coding session.

Same discipline as `adapters/e2b.py` and `adapters/modal.py`: **no vendor SDK
import.** Each transport translates a narrow client protocol into
`SandboxExecTransport`. The opt-in factories refuse to run without an injected
client -- an SDK call nobody has executed against a real account looks
implemented and is not. Bind a real client together with an opt-in smoke
test that has credentials.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

from neos.coding.sandbox.base import SandboxError, SandboxUnavailable
from neos.coding.sandbox.remote import ExecResult


class E2BCommandClient(Protocol):
    async def run_command(
        self,
        sandbox_id: str,
        argv: Sequence[str],
        *,
        cwd: str,
        envs: Mapping[str, str],
        stdin: bytes,
        timeout_sec: float,
    ) -> ExecResult: ...


class ModalExecClient(Protocol):
    async def exec(
        self,
        sandbox_id: str,
        argv: Sequence[str],
        *,
        workdir: str,
        env: Mapping[str, str],
        stdin: bytes,
        timeout_sec: float,
    ) -> ExecResult: ...


class E2BExecTransport:
    def __init__(self, *, client: E2BCommandClient, sandbox_id: str) -> None:
        self._client = client
        self._sandbox_id = sandbox_id

    @property
    def name(self) -> str:
        return "e2b"

    async def exec(
        self,
        argv: Sequence[str],
        *,
        workdir: str,
        env: Mapping[str, str],
        stdin: bytes,
        timeout_sec: float,
    ) -> ExecResult:
        try:
            return await self._client.run_command(
                self._sandbox_id,
                tuple(argv),
                cwd=workdir,
                envs=dict(env),
                stdin=stdin,
                timeout_sec=timeout_sec,
            )
        except SandboxError:
            raise
        except Exception as error:  # noqa: BLE001 - vendor errors are opaque
            raise SandboxUnavailable("e2b_transport_error") from error


class ModalExecTransport:
    def __init__(self, *, client: ModalExecClient, sandbox_id: str) -> None:
        self._client = client
        self._sandbox_id = sandbox_id

    @property
    def name(self) -> str:
        return "modal"

    async def exec(
        self,
        argv: Sequence[str],
        *,
        workdir: str,
        env: Mapping[str, str],
        stdin: bytes,
        timeout_sec: float,
    ) -> ExecResult:
        try:
            return await self._client.exec(
                self._sandbox_id,
                tuple(argv),
                workdir=workdir,
                env=dict(env),
                stdin=stdin,
                timeout_sec=timeout_sec,
            )
        except SandboxError:
            raise
        except Exception as error:  # noqa: BLE001 - vendor errors are opaque
            raise SandboxUnavailable("modal_transport_error") from error


def create_e2b_transport_factory(
    *,
    enabled: bool,
    api_key: str | None,
    client: E2BCommandClient | None = None,
) -> Callable[[str], E2BExecTransport]:
    if not enabled:
        raise RuntimeError("e2b_opt_in_disabled")
    if not api_key:
        raise RuntimeError("e2b_credentials_missing")
    if client is None:
        raise RuntimeError(
            "e2b_exec_client_not_bound: inject an E2BCommandClient; the vendor "
            "SDK binding is intentionally absent until exercised against a real "
            "account"
        )
    return lambda sandbox_id: E2BExecTransport(client=client, sandbox_id=sandbox_id)


def create_modal_transport_factory(
    *,
    enabled: bool,
    token_id: str | None,
    token_secret: str | None,
    client: ModalExecClient | None = None,
) -> Callable[[str], ModalExecTransport]:
    if not enabled:
        raise RuntimeError("modal_opt_in_disabled")
    if not token_id or not token_secret:
        raise RuntimeError("modal_credentials_missing")
    if client is None:
        raise RuntimeError(
            "modal_exec_client_not_bound: inject a ModalExecClient; the vendor "
            "SDK binding is intentionally absent until exercised against a real "
            "account"
        )
    return lambda sandbox_id: ModalExecTransport(client=client, sandbox_id=sandbox_id)
