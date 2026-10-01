"""MCP 의 JSON-RPC 2.0 -- 세션 하나와 두 전송 (트랙 Q11a).

SDK 를 쓰지 않는다(M3). 쓰는 메서드는 `initialize` · `notifications/initialized` ·
`tools/list` · `tools/call` 넷이다.

- stdio: 줄 하나가 메시지 하나(UTF-8 JSON, 줄바꿈 없음). 서버의 stderr 는 버린다 --
  풀린 비밀을 되풀이할 수 있고 로그로 보낼 이유가 없다(M8)
- streamable HTTP: 요청마다 POST. 응답은 `application/json` 이거나 `text/event-stream`.
  리다이렉트를 따르지 않는다 -- 인증 헤더가 다른 호스트로 간다(M8)

실패는 전부 `ConnectorError(reason)` 하나다. `str(error)` 는 사유 코드뿐이고, 서버가
보낸 문구(`detail`)는 비밀을 담을 수 있으므로 부르는 쪽이 가린 뒤에만 쓴다.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

#: 우리가 먼저 내미는 판. 서버가 다른 판으로 답하면 아래 집합 안에서만 받는다.
PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = frozenset({"2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"})
CLIENT_INFO = {"name": "neos-coding", "version": "q11a"}
#: `tools/list` 페이지를 끝없이 넘기는 서버를 끊는다.
MAX_LIST_PAGES = 16
_DETAIL_MAX_CHARS = 500
#: stdio 서버 프로세스가 물려받는 워커 환경 -- 이것뿐이다(M8). 워커 환경에는 NEOS 의
#: 키가 전부 있다.
INHERITED_ENV_NAMES = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT")
_CLOSE_GRACE_SEC = 1.0


class ConnectorError(Exception):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail[:_DETAIL_MAX_CHARS]


def _encode(message: Mapping[str, Any]) -> bytes:
    return json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _decode(raw: bytes) -> list[Mapping[str, Any]]:
    try:
        parsed = json.loads(raw)
    except (UnicodeDecodeError, ValueError) as error:
        raise ConnectorError("connector_protocol_error") from error
    items = parsed if isinstance(parsed, list) else [parsed]
    if not all(isinstance(item, Mapping) for item in items):
        raise ConnectorError("connector_protocol_error")
    return items


def _reply_to_server_request(message: Mapping[str, Any]) -> dict[str, Any]:
    """서버가 클라이언트에게 묻는 것. `ping` 만 답하고 나머지(sampling·roots·elicitation)는
    하지 않는다 -- 그 능력을 `initialize` 에서 내밀지 않았다."""
    if message.get("method") == "ping":
        return {"jsonrpc": "2.0", "id": message["id"], "result": {}}
    return {
        "jsonrpc": "2.0",
        "id": message["id"],
        "error": {"code": -32601, "message": "method not supported by this client"},
    }


def _is_server_request(message: Mapping[str, Any]) -> bool:
    return "method" in message and "id" in message


class StdioTransport:
    def __init__(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        cwd: str | None,
        max_message_bytes: int,
    ) -> None:
        self._argv = tuple(argv)
        self._env = dict(env)
        self._cwd = cwd
        self._max = max_message_bytes
        self._process: asyncio.subprocess.Process | None = None

    def __repr__(self) -> str:  # env 에 풀린 비밀이 있다
        return f"StdioTransport({self._argv[0] if self._argv else ''!r})"

    async def start(self) -> None:
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self._argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=self._env,
                cwd=self._cwd,
                limit=self._max + 1,
                start_new_session=True,
            )
        except (OSError, ValueError) as error:
            raise ConnectorError("connector_unavailable") from error

    async def send(self, message: Mapping[str, Any]) -> None:
        process = self._require()
        assert process.stdin is not None
        try:
            process.stdin.write(_encode(message) + b"\n")
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as error:
            raise ConnectorError("connector_unavailable") from error

    async def request(self, message: Mapping[str, Any]) -> Mapping[str, Any]:
        await self.send(message)
        while True:
            line = await self._readline()
            if not line.strip():
                continue
            for item in _decode(line):
                if item.get("id") == message["id"] and "method" not in item:
                    return item
                if _is_server_request(item):
                    await self.send(_reply_to_server_request(item))

    async def _readline(self) -> bytes:
        process = self._require()
        assert process.stdout is not None
        try:
            line = await process.stdout.readline()
        except (asyncio.LimitOverrunError, ValueError) as error:
            raise ConnectorError("connector_message_too_large") from error
        if not line:
            raise ConnectorError("connector_unavailable")
        if len(line) > self._max + 1:
            raise ConnectorError("connector_message_too_large")
        return line

    def _require(self) -> asyncio.subprocess.Process:
        if self._process is None:
            raise ConnectorError("connector_unavailable")
        return self._process

    async def close(self) -> None:
        process = self._process
        if process is None:
            return
        if process.stdin is not None:
            with contextlib.suppress(Exception):
                process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), _CLOSE_GRACE_SEC)
        except TimeoutError:
            self._kill_group(process)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(process.wait(), _CLOSE_GRACE_SEC)
        except BaseException:
            # 취소 중에도 프로세스를 남기지 않는다.
            self._kill_group(process)
            raise

    @staticmethod
    def _kill_group(process: asyncio.subprocess.Process) -> None:
        # `npx` 처럼 손자 프로세스를 띄우는 서버가 있다 -- 그룹째 끈다.
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.killpg(process.pid, signal.SIGKILL)
        with contextlib.suppress(ProcessLookupError):
            process.kill()


class HttpTransport:
    def __init__(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        max_message_bytes: int,
        timeout_sec: float,
        transport: Any = None,
    ) -> None:
        import httpx

        self._url = url
        self._headers = dict(headers)
        self._max = max_message_bytes
        self._session_id: str | None = None
        self.protocol_version: str | None = None
        # trust_env=False: 프록시·`.netrc` 를 환경에서 줍지 않는다 -- `.netrc` 는 자격증명이다.
        self._client = httpx.AsyncClient(
            follow_redirects=False,
            timeout=timeout_sec,
            transport=transport,
            trust_env=False,
        )

    def __repr__(self) -> str:  # 헤더에 풀린 비밀이 있다
        return "HttpTransport()"

    async def start(self) -> None:
        return None

    def _request_headers(self) -> dict[str, str]:
        headers = {
            **self._headers,
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self._session_id is not None:
            headers["Mcp-Session-Id"] = self._session_id
        if self.protocol_version is not None:
            headers["MCP-Protocol-Version"] = self.protocol_version
        return headers

    async def send(self, message: Mapping[str, Any]) -> None:
        import httpx

        try:
            response = await self._client.post(
                self._url, content=_encode(message), headers=self._request_headers()
            )
        except httpx.TimeoutException as error:
            raise TimeoutError() from error
        except httpx.HTTPError as error:
            raise ConnectorError("connector_unavailable") from error
        if not 200 <= response.status_code < 300:
            raise ConnectorError("connector_unavailable")

    async def request(self, message: Mapping[str, Any]) -> Mapping[str, Any]:
        import httpx

        try:
            async with self._client.stream(
                "POST", self._url, content=_encode(message), headers=self._request_headers()
            ) as response:
                if not 200 <= response.status_code < 300:
                    # 3xx 도 여기다 -- 리다이렉트는 따르지 않는다.
                    raise ConnectorError("connector_unavailable")
                session_id = response.headers.get("mcp-session-id")
                if session_id and self._session_id is None:
                    self._session_id = session_id
                media = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if media == "text/event-stream":
                    async for item in self._events(response.aiter_bytes()):
                        if item.get("id") == message["id"] and "method" not in item:
                            return item
                        if _is_server_request(item):
                            await self.send(_reply_to_server_request(item))
                    raise ConnectorError("connector_protocol_error")
                body = await self._capped(response.aiter_bytes())
        except httpx.TimeoutException as error:
            raise TimeoutError() from error
        except httpx.HTTPError as error:
            raise ConnectorError("connector_unavailable") from error
        for item in _decode(body):
            if item.get("id") == message["id"] and "method" not in item:
                return item
        raise ConnectorError("connector_protocol_error")

    async def _capped(self, chunks: AsyncIterator[bytes]) -> bytes:
        buffer = bytearray()
        async for chunk in chunks:
            buffer.extend(chunk)
            if len(buffer) > self._max:
                raise ConnectorError("connector_message_too_large")
        return bytes(buffer)

    async def _events(self, chunks: AsyncIterator[bytes]) -> AsyncIterator[Mapping[str, Any]]:
        """SSE 의 `data:` 줄을 메시지로. 스트림 전체가 메시지 상한 하나를 넘지 못한다."""
        buffer = b""
        seen = 0
        async for chunk in chunks:
            seen += len(chunk)
            if seen > self._max:
                raise ConnectorError("connector_message_too_large")
            buffer += chunk.replace(b"\r\n", b"\n")
            while b"\n\n" in buffer:
                block, buffer = buffer.split(b"\n\n", 1)
                data = b"\n".join(
                    line[5:].lstrip(b" ")
                    for line in block.split(b"\n")
                    if line.startswith(b"data:")
                )
                if data.strip():
                    for item in _decode(data):
                        yield item

    async def close(self) -> None:
        import httpx

        if self._session_id is not None:
            with contextlib.suppress(httpx.HTTPError, Exception):
                await self._client.delete(self._url, headers=self._request_headers())
        with contextlib.suppress(Exception):
            await self._client.aclose()


class McpSession:
    def __init__(self, transport: StdioTransport | HttpTransport) -> None:
        self._transport = transport
        self._next_id = 0
        self.protocol_version: str | None = None

    async def _call(self, method: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        self._next_id += 1
        response = await self._transport.request(
            {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": dict(params)}
        )
        error = response.get("error")
        if error is not None:
            message = error.get("message") if isinstance(error, Mapping) else None
            raise ConnectorError("connector_call_failed", str(message or ""))
        result = response.get("result")
        if not isinstance(result, Mapping):
            raise ConnectorError("connector_protocol_error")
        return result

    async def initialize(self) -> None:
        result = await self._call(
            "initialize",
            {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENT_INFO},
        )
        version = result.get("protocolVersion")
        if version not in SUPPORTED_PROTOCOL_VERSIONS:
            raise ConnectorError("connector_protocol_error")
        self.protocol_version = str(version)
        if isinstance(self._transport, HttpTransport):
            self._transport.protocol_version = self.protocol_version
        await self._transport.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    async def list_tools(self, *, max_tools: int) -> list[Mapping[str, Any]]:
        tools: list[Mapping[str, Any]] = []
        cursor: str | None = None
        for _ in range(MAX_LIST_PAGES):
            params: dict[str, Any] = {} if cursor is None else {"cursor": cursor}
            result = await self._call("tools/list", params)
            page = result.get("tools")
            if not isinstance(page, list):
                raise ConnectorError("connector_protocol_error")
            tools.extend(item for item in page if isinstance(item, Mapping))
            next_cursor = result.get("nextCursor")
            if not isinstance(next_cursor, str) or not next_cursor or len(tools) >= max_tools:
                break
            cursor = next_cursor
        return tools[:max_tools]

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        return await self._call("tools/call", {"name": name, "arguments": dict(arguments)})


def stdio_env(configured: Mapping[str, str]) -> dict[str, str]:
    """서버 프로세스의 환경: 워커에서 `INHERITED_ENV_NAMES` 만 + 설정(풀린 값 포함)."""
    base = {name: os.environ[name] for name in INHERITED_ENV_NAMES if name in os.environ}
    return {**base, **configured}


@contextlib.asynccontextmanager
async def open_session(
    server: Any,
    *,
    env: Mapping[str, str],
    headers: Mapping[str, str],
    max_message_bytes: int,
    timeout_sec: float,
    http_transport: Any = None,
) -> AsyncIterator[McpSession]:
    """연결 -> 초기화 -> (부르는 쪽) -> 닫기. 연결은 호출마다 새로 연다(M8)."""
    transport: StdioTransport | HttpTransport
    if server.transport == "stdio":
        transport = StdioTransport(
            server.command,
            env=stdio_env(env),
            cwd=server.cwd,
            max_message_bytes=max_message_bytes,
        )
    else:
        transport = HttpTransport(
            str(server.url),
            headers=headers,
            max_message_bytes=max_message_bytes,
            timeout_sec=timeout_sec,
            transport=http_transport,
        )
    try:
        await transport.start()
        session = McpSession(transport)
        await session.initialize()
        yield session
    finally:
        await transport.close()


__all__ = [
    "CLIENT_INFO",
    "ConnectorError",
    "HttpTransport",
    "INHERITED_ENV_NAMES",
    "McpSession",
    "PROTOCOL_VERSION",
    "SUPPORTED_PROTOCOL_VERSIONS",
    "StdioTransport",
    "open_session",
    "stdio_env",
]
