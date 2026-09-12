from __future__ import annotations

import asyncio
import errno
import hashlib
import http.client
import inspect
import ipaddress
import re
import socket
import ssl
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import Any, Literal
from urllib.parse import parse_qsl, urljoin, urlparse

from neos.coding.sandbox.base import (
    CommandRequest,
    CommandResult,
    FileEntry,
    SandboxError,
    SandboxNotFound,
    SandboxPolicyViolation,
    SandboxSession,
    SandboxTimeout,
    SearchMatch,
)
from neos.coding.sandbox.observability import bounded_executable_category
from neos.coding.sandbox.paths import normalize_workspace_path
from neos.coding.tools.registry import CodingToolRegistry, ValidatedToolCall

_WEB_FETCH_TIMEOUT_SEC = 15
_WEB_FETCH_MAX_BYTES = 200_000
_WEB_FETCH_MAX_REDIRECTS = 5
_MISSING_PARENT_REASON = "workspace_path_not_resolvable"
_PARENTS_FIX: dict[str, object] = {"parents": True}
_BINARY_EXTENSIONS = frozenset(
    {
        "exe",
        "png",
        "jpg",
        "jpeg",
        "gif",
        "webp",
        "pdf",
        "zip",
        "pyc",
        "so",
        "dylib",
        "woff",
        "woff2",
        "class",
    }
)
_UNCHANGED_PREVIEW = "File unchanged since last read."
_WEB_FETCH_TEXT_TYPES = frozenset(
    {"text/html", "text/plain", "text/markdown", "application/json"}
)


@dataclass(frozen=True, slots=True)
class _ReadStamp:
    mtime: datetime
    digest: str
    full: bool
    offset: int | None = None
    limit: int | None = None


def _parse_known_stamp(raw: Mapping[str, object]) -> _ReadStamp | None:
    mtime_raw = raw.get("mtime")
    digest = raw.get("digest")
    if not isinstance(mtime_raw, str) or not isinstance(digest, str) or not digest:
        return None
    try:
        parsed = datetime.fromisoformat(mtime_raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    offset_raw = raw.get("offset")
    limit_raw = raw.get("limit")
    offset = offset_raw if isinstance(offset_raw, int) else None
    limit = limit_raw if isinstance(limit_raw, int) else None
    return _ReadStamp(
        parsed, digest, bool(raw.get("full", True)), offset, limit
    )


def _is_binary_path(path: str) -> bool:
    name = PurePosixPath(path).name
    if "." not in name or name.startswith("."):
        return False
    return name.rsplit(".", 1)[-1].casefold() in _BINARY_EXTENSIONS


def _normalize_text(content: bytes) -> str:
    text = content.decode("utf-8", errors="replace")
    if text.startswith("\ufeff"):
        text = text[1:]
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _write_accepts_parents(write_file: Any) -> bool:
    try:
        return "parents" in inspect.signature(write_file).parameters
    except (TypeError, ValueError):
        return False


def _write_file_kwargs(write_file: Any, call: ValidatedToolCall) -> dict[str, bool]:
    if not _write_accepts_parents(write_file):
        return {}
    return {
        "parents": call.input.get("parents") is True
        or call.input.get("create_parents") is True
    }


def _is_missing_parent_error(error: BaseException) -> bool:
    if isinstance(error, FileNotFoundError):
        return True
    if isinstance(error, SandboxPolicyViolation):
        return str(error) == _MISSING_PARENT_REASON
    return isinstance(error, OSError) and error.errno == errno.ENOENT


def _missing_parent_result() -> ToolResult:
    return ToolResult(
        "error",
        _MISSING_PARENT_REASON,
        None,
        None,
        False,
        None,
        "unknown",
        retryable=True,
        fix=dict(_PARENTS_FIX),
    )


class _WebFetchHostDenied(Exception):
    pass


class _WebFetchUnsafe(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


_WEB_FETCH_SECRET_QUERY_NAMES = frozenset(
    {
        "token",
        "api_key",
        "access_token",
        "password",
        "secret",
        "authorization",
        "key",
    }
)
_WEB_FETCH_BLOCKED_NETWORKS = (
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)
_WEB_FETCH_IMDS = ipaddress.ip_address("169.254.169.254")


def _web_fetch_hosts() -> tuple[str, ...]:
    try:
        from neos.config.settings import settings

        return tuple(settings.config.coding_model.web_fetch_hosts)
    except Exception:
        return ()


def _web_fetch_host_allowed(host: str | None, allowlist: tuple[str, ...]) -> bool:
    if not allowlist or not host:
        return False
    candidate = host.lower().rstrip(".")
    for raw in allowlist:
        allowed = raw.strip().lower()
        if not allowed:
            continue
        if allowed.startswith("."):
            suffix = allowed.lstrip(".")
            if candidate == suffix or candidate.endswith("." + suffix):
                return True
        elif candidate == allowed:
            return True
    return False


def _web_fetch_url_allowed(url: str, allowlist: tuple[str, ...]) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    return _web_fetch_host_allowed(parsed.hostname, allowlist)


def _web_fetch_query_blocked(url: str) -> bool:
    parsed = urlparse(url)
    for name, _value in parse_qsl(parsed.query, keep_blank_values=True):
        if name.lower() in _WEB_FETCH_SECRET_QUERY_NAMES:
            return True
    return False


def _web_fetch_ip_blocked(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return True
    if address.version == 6 and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if address == _WEB_FETCH_IMDS:
        return True
    return any(address in network for network in _WEB_FETCH_BLOCKED_NETWORKS)


def _web_fetch_resolve(host: str) -> tuple[str, ...]:
    infos = socket.getaddrinfo(host, None)
    addresses: list[str] = []
    for info in infos:
        sockaddr = info[4]
        if sockaddr:
            addresses.append(str(sockaddr[0]))
    return tuple(addresses)


def _web_fetch_resolved_public(host: str) -> bool:
    try:
        addresses = _web_fetch_resolve(host)
    except OSError:
        return False
    if not addresses:
        return False
    return all(not _web_fetch_ip_blocked(address) for address in addresses)


def _upgrade_to_https(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme == "http":
        return parsed._replace(scheme="https").geturl()
    return url


def _web_fetch_media_type(content_type: str) -> str:
    return content_type.split(";", 1)[0].strip().lower()


def _response_media_type(response: object) -> str:
    headers = getattr(response, "headers", None)
    if headers is None:
        return ""
    raw = headers.get("Content-Type") or headers.get("content-type") or ""
    return _web_fetch_media_type(str(raw))


class _HTMLTextParser(HTMLParser):
    _SKIP = frozenset({"script", "style", "noscript"})

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self._SKIP:
            self._skip += 1
        elif tag in {"br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        elif tag in {"p", "div", "tr", "li", "h1", "h2", "h3", "h4"}:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._chunks.append(data)

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "".join(self._chunks)).strip()


def _html_to_text(value: str) -> str:
    parser = _HTMLTextParser()
    parser.feed(value)
    parser.close()
    return parser.text()


def _web_fetch_safety_reason(url: str, allowlist: tuple[str, ...]) -> str | None:
    parsed = urlparse(url)
    if parsed.username is not None or parsed.password is not None:
        return "web_fetch_userinfo"
    if not _web_fetch_url_allowed(url, allowlist):
        return "policy_web_fetch_host_denied"
    if _web_fetch_query_blocked(url):
        return "web_fetch_blocked"
    host = parsed.hostname
    if not host or not _web_fetch_resolved_public(host):
        return "web_fetch_ssrf"
    return None


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, pinned_ip: str) -> None:
        super().__init__()
        self._pinned_ip = pinned_ip

    def https_open(self, req):
        pinned_ip = self._pinned_ip

        class Bound(http.client.HTTPSConnection):
            def connect(self) -> None:
                sock = socket.create_connection(
                    (pinned_ip, self.port), self.timeout
                )
                context = self._context or ssl.create_default_context()
                self.sock = context.wrap_socket(
                    sock, server_hostname=self.host
                )
                try:
                    peer = str(self.sock.getpeername()[0])
                except Exception:
                    peer = pinned_ip
                if _web_fetch_ip_blocked(peer):
                    self.sock.close()
                    raise OSError("web_fetch_ssrf")

        return self.do_open(Bound, req)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, code, msg, headers, newurl
        return None


def _raise_web_fetch_reason(reason: str) -> None:
    if reason == "policy_web_fetch_host_denied":
        raise _WebFetchHostDenied
    raise _WebFetchUnsafe(reason)


def _http_get(url: str, allowlist: tuple[str, ...]) -> tuple[str, str, bytes]:
    current = _upgrade_to_https(url)
    for _ in range(_WEB_FETCH_MAX_REDIRECTS + 1):
        current = _upgrade_to_https(current)
        reason = _web_fetch_safety_reason(current, allowlist)
        if reason is not None:
            _raise_web_fetch_reason(reason)
        host = urlparse(current).hostname or ""
        try:
            addresses = [
                address
                for address in _web_fetch_resolve(host)
                if not _web_fetch_ip_blocked(address)
            ]
        except OSError as error:
            raise _WebFetchUnsafe("web_fetch_ssrf") from error
        if not addresses:
            raise _WebFetchUnsafe("web_fetch_ssrf")
        opener = urllib.request.build_opener(
            _NoRedirect(), _PinnedHTTPSHandler(addresses[0])
        )
        request = urllib.request.Request(current, method="GET")
        response: urllib.request.addinfourl | urllib.error.HTTPError | None = None
        try:
            try:
                response = opener.open(request, timeout=_WEB_FETCH_TIMEOUT_SEC)
            except urllib.error.HTTPError as error:
                if error.code in {301, 302, 303, 307, 308}:
                    location = error.headers.get("Location")
                    error.close()
                    if not location:
                        raise _WebFetchUnsafe("web_fetch_ssrf") from error
                    current = urljoin(current, location)
                    continue
                response = error
            media = _response_media_type(response)
            if media not in _WEB_FETCH_TEXT_TYPES:
                raise _WebFetchUnsafe("web_fetch_unsupported_type")
            return current, media, response.read(_WEB_FETCH_MAX_BYTES)
        finally:
            if response is not None:
                response.close()
    raise _WebFetchUnsafe("web_fetch_ssrf")


@dataclass(frozen=True, slots=True)
class ToolResult:
    status: Literal["ok", "error", "denied"]
    reason_code: str
    preview: str | None
    original_bytes: int | None
    truncated: bool
    checksum: str | None
    workspace_revision: str
    entries: tuple[Mapping[str, object], ...] = ()
    stdout: Mapping[str, object] | None = None
    stderr: Mapping[str, object] | None = None
    exit_code: int | None = None
    audit: Mapping[str, object] | None = None
    retryable: bool = False
    fix: dict[str, object] | None = None
    start_line: int | None = None
    total_lines: int | None = None
    unchanged: bool = False
    matches: int | None = None

    @classmethod
    def ok(
        cls,
        *,
        workspace_revision: str,
        entries: tuple[Mapping[str, object], ...] = (),
    ) -> ToolResult:
        return cls("ok", "ok", None, None, False, None, workspace_revision, entries)

    def to_mapping(self) -> Mapping[str, object]:
        return asdict(self)


class SandboxToolExecutor:
    def __init__(self, max_preview_bytes: int, max_entries: int) -> None:
        if max_preview_bytes < 1 or max_entries < 1:
            raise ValueError("executor limits must be positive")
        self._max_preview_bytes = max_preview_bytes
        self._max_entries = max_entries
        self._read_paths: dict[str, set[str]] = {}
        self._read_stamps: dict[str, dict[str, _ReadStamp]] = {}

    async def execute(
        self,
        session: SandboxSession,
        call: ValidatedToolCall,
        *,
        known_reads: frozenset[str] = frozenset(),
        known_stamps: Mapping[str, Mapping[str, object]] | None = None,
    ) -> ToolResult:
        self._hydrate_stamps(session, known_stamps)
        result = await self._attempt(session, call, known_reads=known_reads)
        if result.status != "error" or not result.retryable or result.fix is None:
            return result
        merged = ValidatedToolCall(
            call.name,
            {**dict(call.input), **result.fix},
            call.risk,
        )
        return await self._attempt(session, merged, known_reads=known_reads)

    def export_read_stamps(self) -> dict[str, dict[str, object]]:
        exported: dict[str, dict[str, object]] = {}
        for stamps in self._read_stamps.values():
            for path, stamp in stamps.items():
                exported[path] = {
                    "mtime": stamp.mtime.isoformat(),
                    "digest": stamp.digest,
                    "full": stamp.full,
                    "offset": stamp.offset,
                    "limit": stamp.limit,
                }
        return exported

    def _hydrate_stamps(
        self,
        session: SandboxSession,
        known_stamps: Mapping[str, Mapping[str, object]] | None,
    ) -> None:
        if not known_stamps:
            return
        dest = self._read_stamps.setdefault(session.sandbox_id, {})
        for raw_path, raw_stamp in known_stamps.items():
            if not isinstance(raw_stamp, Mapping):
                continue
            parsed = _parse_known_stamp(raw_stamp)
            if parsed is None:
                continue
            normalized = str(normalize_workspace_path(str(raw_path)))
            dest.setdefault(normalized, parsed)

    async def _attempt(
        self,
        session: SandboxSession,
        call: ValidatedToolCall,
        *,
        known_reads: frozenset[str],
    ) -> ToolResult:
        try:
            return await self._execute(session, call, known_reads=known_reads)
        except SandboxTimeout:
            return self._failure("error", "sandbox_timeout")
        except SandboxPolicyViolation:
            return self._failure("denied", "sandbox_policy_violation")
        except (SandboxNotFound, FileNotFoundError):
            return self._failure("error", "sandbox_not_found")
        except SandboxError:
            return self._failure("error", "sandbox_error")

    async def _execute(
        self,
        session: SandboxSession,
        call: ValidatedToolCall,
        *,
        known_reads: frozenset[str],
    ) -> ToolResult:
        if call.name == "read_file.v1":
            return await self._read_file(session, call)
        if call.name == "write_file.v1":
            return await self._write_file(session, call, known_reads=known_reads)
        if call.name == "edit_file.v1":
            return await self._edit_file(session, call, known_reads=known_reads)
        return await self._dispatch_non_file_tool(session, call)

    async def _read_file(
        self, session: SandboxSession, call: ValidatedToolCall
    ) -> ToolResult:
        path = str(call.input["path"])
        offset = int(call.input.get("offset", 1))
        raw_limit = call.input.get("limit")
        limit = int(raw_limit) if raw_limit is not None else None
        if _is_binary_path(path):
            return await self._denied(session, "policy_binary_file")
        ranged = False
        try:
            content = await session.read_file(path, offset=offset, limit=limit)
            ranged = True
        except TypeError:
            content = await session.read_file(path)
        if b"\x00" in content[:8192]:
            return await self._denied(session, "policy_binary_file")
        text = _normalize_text(content)
        lines = text.splitlines(keepends=True)
        if ranged and limit is not None:
            sliced = lines
            omitted = offset > 1 or len(lines) >= limit
            total_lines = offset + len(lines) - 1 if lines else 0
        else:
            start = max(offset - 1, 0)
            end = None if limit is None else start + limit
            sliced = lines[start:end]
            omitted = start > 0 or (end is not None and end < len(lines))
            total_lines = len(lines)
        numbered = "".join(
            f"{number:>6}|{line}" for number, line in enumerate(sliced, start=offset)
        )
        digest = hashlib.sha256(content).hexdigest()
        stamp = self._stamp_for(session, path)
        if (
            stamp is not None
            and stamp.offset is not None
            and stamp.offset == offset
            and stamp.limit == limit
            and stamp.digest == digest
        ):
            same_mtime = False
            try:
                entry = await session.stat(path)
                same_mtime = entry.modified_at == stamp.mtime
            except Exception:
                same_mtime = False
            if same_mtime:
                return ToolResult(
                    status="ok",
                    reason_code="ok",
                    preview=_UNCHANGED_PREVIEW,
                    original_bytes=len(content),
                    truncated=False,
                    checksum=digest,
                    workspace_revision=await self._revision(session),
                    start_line=offset,
                    total_lines=total_lines,
                    unchanged=True,
                )
        result = self._bounded_bytes(
            numbered.encode("utf-8"),
            workspace_revision=await self._revision(session),
            already_truncated=omitted,
            original_bytes=len(content),
            start_line=offset,
            total_lines=total_lines,
        )
        await self._mark_read(
            session,
            path,
            content,
            full=offset <= 1 and raw_limit is None,
            offset=offset,
            limit=limit,
        )
        return result

    async def _write_file(
        self,
        session: SandboxSession,
        call: ValidatedToolCall,
        *,
        known_reads: frozenset[str],
    ) -> ToolResult:
        path = str(call.input["path"])
        denied = await self._deny_unread_existing(
            session, path, known_reads=known_reads
        )
        if denied is not None:
            return denied
        stale = await self._deny_stale_since_read(session, path)
        if stale is not None:
            return stale
        payload = str(call.input["content"]).encode()
        try:
            revision = await session.write_file(
                path,
                payload,
                **_write_file_kwargs(session.write_file, call),
            )
        except (FileNotFoundError, OSError, SandboxPolicyViolation) as error:
            if _is_missing_parent_error(error):
                return _missing_parent_result()
            raise
        await self._mark_read(
            session, path, payload, full=True, modified=datetime.now(UTC)
        )
        return ToolResult.ok(workspace_revision=str(revision))

    async def _edit_file(
        self,
        session: SandboxSession,
        call: ValidatedToolCall,
        *,
        known_reads: frozenset[str],
    ) -> ToolResult:
        path = str(call.input["path"])
        denied = await self._deny_unread_existing(
            session, path, known_reads=known_reads
        )
        if denied is not None:
            return denied
        stale = await self._deny_stale_since_read(session, path)
        if stale is not None:
            return stale
        content = await session.read_file(path)
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            return await self._denied(session, "edit_not_text")
        old_string = str(call.input["old_string"])
        new_string = str(call.input["new_string"])
        replace_all = bool(call.input.get("replace_all", False))
        if old_string == new_string:
            return await self._denied(session, "edit_noop")
        matches = text.count(old_string)
        if matches == 0:
            return await self._denied(session, "edit_old_string_not_found")
        if matches > 1 and not replace_all:
            return await self._denied(
                session, "edit_old_string_not_unique", matches=matches
            )
        updated = (
            text.replace(old_string, new_string)
            if replace_all
            else text.replace(old_string, new_string, 1)
        )
        try:
            revision = await session.write_file(
                path,
                updated.encode("utf-8"),
                **_write_file_kwargs(session.write_file, call),
            )
        except (FileNotFoundError, OSError, SandboxPolicyViolation) as error:
            if _is_missing_parent_error(error):
                return _missing_parent_result()
            raise
        await self._mark_read(
            session,
            path,
            updated.encode("utf-8"),
            full=True,
            modified=datetime.now(UTC),
        )
        return ToolResult.ok(workspace_revision=str(revision))

    async def _deny_unread_existing(
        self,
        session: SandboxSession,
        path: str,
        *,
        known_reads: frozenset[str],
    ) -> ToolResult | None:
        if not await self._path_exists(session, path):
            return None
        if self._was_read(session, path, known_reads=known_reads):
            stamp = self._stamp_for(session, path)
            if stamp is not None and not stamp.full:
                return await self._denied(session, "precondition_read_required")
            return None
        return await self._denied(session, "precondition_read_required")

    async def _deny_stale_since_read(
        self, session: SandboxSession, path: str
    ) -> ToolResult | None:
        stamp = self._stamp_for(session, path)
        if stamp is None:
            return None
        try:
            entry = await session.stat(path)
            disk = await session.read_file(path)
        except (SandboxNotFound, FileNotFoundError, SandboxPolicyViolation):
            return None
        digest = hashlib.sha256(disk).hexdigest()
        if entry.modified_at > stamp.mtime and digest != stamp.digest:
            return await self._denied(session, "precondition_stale_read")
        return None

    async def _path_exists(self, session: SandboxSession, path: str) -> bool:
        try:
            await session.stat(path)
        except (SandboxNotFound, FileNotFoundError):
            return False
        except SandboxPolicyViolation as error:
            if str(error) == "workspace_path_not_resolvable":
                return False
            raise
        return True

    async def _mark_read(
        self,
        session: SandboxSession,
        path: str,
        content: bytes,
        *,
        full: bool,
        modified: datetime | None = None,
        offset: int | None = None,
        limit: int | None = None,
    ) -> None:
        normalized = str(normalize_workspace_path(path))
        self._read_paths.setdefault(session.sandbox_id, set()).add(normalized)
        if modified is None:
            try:
                entry = await session.stat(path)
                modified = entry.modified_at
            except Exception:
                modified = datetime.now(UTC)
        self._read_stamps.setdefault(session.sandbox_id, {})[normalized] = _ReadStamp(
            modified,
            hashlib.sha256(content).hexdigest(),
            full,
            offset,
            limit,
        )

    def _stamp_for(self, session: SandboxSession, path: str) -> _ReadStamp | None:
        stamps = self._read_stamps.get(session.sandbox_id) or {}
        return stamps.get(str(normalize_workspace_path(path)))

    def _was_read(
        self,
        session: SandboxSession,
        path: str,
        *,
        known_reads: frozenset[str],
    ) -> bool:
        normalized = str(normalize_workspace_path(path))
        if normalized in known_reads:
            return True
        recorded = self._read_paths.get(session.sandbox_id, set())
        return normalized in recorded

    async def _denied(
        self,
        session: SandboxSession,
        reason: str,
        *,
        matches: int | None = None,
    ) -> ToolResult:
        return ToolResult(
            "denied",
            reason,
            None,
            None,
            False,
            None,
            await self._revision(session),
            matches=matches,
        )

    async def _dispatch_non_file_tool(
        self, session: SandboxSession, call: ValidatedToolCall
    ) -> ToolResult:
        if call.name == "todo_write.v1":
            return self._todo_write(call)
        if call.name == "set_phase.v1":
            return self._set_phase(call)
        if call.name == "ask_user.v1":
            return self._ask_user(call)
        if call.name == "load_skill.v1":
            return self._load_skill(call)
        if call.name == "search_tools.v1":
            return self._search_tools(call)
        if call.name == "spawn_agent.v1":
            return self._spawn_agent()
        if call.name == "web_fetch.v1":
            return await self._web_fetch(session, call)
        if call.name == "glob_files.v1":
            paths = await session.glob_files(
                str(call.input["pattern"]),
                limit=int(call.input.get("limit", 100)),
            )
            entries = tuple(
                {"path": path} for path in paths[: self._max_entries]
            )
            return ToolResult(
                "ok",
                "ok",
                None,
                None,
                len(paths) > len(entries),
                None,
                await self._revision(session),
                entries,
            )
        if call.name == "list_tree.v1":
            entries = await session.list_tree(str(call.input["path"]))
            return self._entry_result(entries, await self._revision(session))
        if call.name == "stat.v1":
            entry = await session.stat(str(call.input["path"]))
            return self._entry_result((entry,), await self._revision(session))
        if call.name == "search_text.v1":
            output_mode = str(call.input.get("output_mode", "content"))
            kwargs: dict[str, Any] = {
                "paths": tuple(str(path) for path in call.input["paths"]),
                "regex": bool(call.input["regex"]),
                "limit": int(call.input["limit"]),
                "before": int(call.input.get("before", 0)),
                "after": int(call.input.get("after", 0)),
                "output_mode": output_mode,
            }
            extras: dict[str, Any] = {}
            if call.input.get("ignore_case"):
                extras["ignore_case"] = True
            if call.input.get("multiline"):
                extras["multiline"] = True
            context = int(call.input.get("context") or 0)
            if context:
                extras["context"] = context
            search_root = call.input.get("path")
            if search_root:
                extras["path"] = str(search_root)
            try:
                matches = await session.search_text(
                    str(call.input["query"]), **kwargs, **extras
                )
            except TypeError:
                matches = await session.search_text(
                    str(call.input["query"]), **kwargs
                )
            return self._search_text_result(
                matches,
                await self._revision(session),
                output_mode=output_mode,
            )
        if call.name == "git_status.v1":
            result = await session.git_status()
            return self._command_result(result, await self._revision(session))
        if call.name == "git_diff.v1":
            result = await session.git_diff(staged=bool(call.input["staged"]))
            return self._command_result(result, await self._revision(session))
        if call.name == "git_log.v1":
            result = await session.git_log(limit=int(call.input["limit"]))
            return self._command_result(result, await self._revision(session))
        if call.name == "execute.v1":
            argv = tuple(str(value) for value in call.input["argv"])
            request = CommandRequest(
                argv=argv,
                cwd=str(call.input["cwd"]),
                env={str(key): str(value) for key, value in dict(call.input["env"]).items()},
                stdin=str(call.input["stdin"]).encode(),
                timeout_sec=float(call.input["timeout_sec"]),
                max_output_bytes=int(call.input["max_output_bytes"]),
            )
            result = await session.execute(request)
            return self._command_result(
                result,
                await self._revision(session),
                audit={"executable_category": bounded_executable_category(argv[0])},
            )
        return ToolResult(
            "denied",
            "unknown_tool",
            None,
            None,
            False,
            None,
            await self._revision(session),
        )

    @staticmethod
    def _todo_write(call: ValidatedToolCall) -> ToolResult:
        entries = tuple(dict(item) for item in call.input["todos"])
        return ToolResult.ok(workspace_revision="unknown", entries=entries)

    @staticmethod
    def _set_phase(call: ValidatedToolCall) -> ToolResult:
        return ToolResult.ok(
            workspace_revision="unknown",
            entries=({"phase": str(call.input["phase"])},),
        )

    @staticmethod
    def _ask_user(call: ValidatedToolCall) -> ToolResult:
        questions = []
        for item in call.input["questions"]:
            if isinstance(item, Mapping):
                questions.append(dict(item))
            else:
                questions.append(str(item))
        raw_answers = call.input.get("answers")
        answers = (
            [str(item) for item in raw_answers]
            if isinstance(raw_answers, list)
            else []
        )
        pairs = []
        for index, question in enumerate(questions):
            prompt = (
                str(question.get("prompt") or "")
                if isinstance(question, Mapping)
                else str(question)
            )
            pairs.append(
                {
                    "question": prompt,
                    "answer": answers[index] if index < len(answers) else "",
                }
            )
        return ToolResult.ok(
            workspace_revision="unknown",
            entries=({"questions": questions, "answers": answers, "pairs": pairs},),
        )

    @staticmethod
    def _search_tools(call: ValidatedToolCall) -> ToolResult:
        entries = CodingToolRegistry.search_definitions(str(call.input["query"]))
        return ToolResult.ok(workspace_revision="unknown", entries=entries)

    @staticmethod
    def _spawn_agent() -> ToolResult:
        return ToolResult.ok(
            workspace_revision="unknown",
            entries=({"delegated": True},),
        )

    async def _web_fetch(
        self, session: SandboxSession, call: ValidatedToolCall
    ) -> ToolResult:
        url = _upgrade_to_https(str(call.input["url"]))
        allowlist = _web_fetch_hosts()
        reason = _web_fetch_safety_reason(url, allowlist)
        if reason == "policy_web_fetch_host_denied":
            return await self._denied(session, reason)
        if reason is not None:
            return self._failure("error", reason)
        try:
            final_url, media, body = await asyncio.to_thread(
                _http_get, url, allowlist
            )
        except _WebFetchHostDenied:
            return await self._denied(session, "policy_web_fetch_host_denied")
        except _WebFetchUnsafe as error:
            return self._failure("error", error.reason)
        except TimeoutError:
            return self._failure("error", "sandbox_timeout")
        except urllib.error.URLError as error:
            reason = error.reason
            if isinstance(reason, TimeoutError):
                return self._failure("error", "sandbox_timeout")
            return self._failure("error", "sandbox_error")
        except OSError:
            return self._failure("error", "sandbox_error")
        text = body.decode("utf-8", errors="replace")
        if media == "text/html":
            text = _html_to_text(text)
        bounded = self._bytes_mapping(text.encode("utf-8"))
        return ToolResult(
            status="ok",
            reason_code="ok",
            preview=str(bounded["preview"]),
            original_bytes=len(body),
            truncated=bool(bounded["truncated"]),
            checksum=str(bounded["checksum"]),
            workspace_revision=await self._revision(session),
            entries=({"url": final_url, "text": text},),
        )

    @staticmethod
    def _load_skill(call: ValidatedToolCall) -> ToolResult:
        from neos.skills.markdown_catalog import default_catalog

        name = str(call.input.get("name", ""))
        markdown = default_catalog().load_markdown(name)
        if markdown is None:
            return ToolResult(
                "denied", "unknown_skill", None, None, False, None, "unknown"
            )
        return ToolResult.ok(
            workspace_revision="unknown",
            entries=({"name": name, "markdown": markdown},),
        )

    def _bounded_bytes(
        self,
        content: bytes,
        *,
        workspace_revision: str,
        already_truncated: bool = False,
        original_bytes: int | None = None,
        start_line: int | None = None,
        total_lines: int | None = None,
    ) -> ToolResult:
        bounded = self._bytes_mapping(content, already_truncated=already_truncated)
        return ToolResult(
            status="ok",
            reason_code="ok",
            preview=str(bounded["preview"]),
            original_bytes=len(content) if original_bytes is None else original_bytes,
            truncated=bool(bounded["truncated"]),
            checksum=str(bounded["checksum"]),
            workspace_revision=workspace_revision,
            start_line=start_line,
            total_lines=total_lines,
        )

    def _bytes_mapping(
        self, content: bytes, *, already_truncated: bool = False
    ) -> Mapping[str, object]:
        preview = content[: self._max_preview_bytes]
        return {
            "preview": preview.decode("utf-8", errors="replace"),
            "original_bytes": len(content),
            "truncated": already_truncated or len(content) > len(preview),
            "checksum": hashlib.sha256(content).hexdigest(),
        }

    def _search_text_result(
        self,
        matches: tuple[SearchMatch, ...],
        revision: str,
        *,
        output_mode: str,
    ) -> ToolResult:
        if output_mode == "files":
            paths: list[str] = []
            seen: set[str] = set()
            for match in matches:
                if match.path in seen:
                    continue
                seen.add(match.path)
                paths.append(match.path)
            entries = tuple({"path": path} for path in paths[: self._max_entries])
            return ToolResult(
                "ok",
                "ok",
                None,
                None,
                len(paths) > len(entries),
                None,
                revision,
                entries,
            )
        if output_mode == "count":
            counts: dict[str, int] = {}
            order: list[str] = []
            for match in matches:
                increment = match.count if match.count is not None else 1
                if match.path not in counts:
                    order.append(match.path)
                    counts[match.path] = increment
                else:
                    counts[match.path] += increment
            entries = tuple(
                {"path": path, "count": counts[path]}
                for path in order[: self._max_entries]
            )
            return ToolResult(
                "ok",
                "ok",
                None,
                None,
                len(order) > len(entries),
                None,
                revision,
                entries,
            )
        entries = tuple(
            {
                key: value
                for key, value in self._json_entry(match).items()
                if key != "count"
            }
            for match in matches[: self._max_entries]
        )
        return ToolResult(
            "ok",
            "ok",
            None,
            None,
            len(matches) > len(entries),
            None,
            revision,
            entries,
        )

    def _entry_result(
        self,
        values: tuple[FileEntry, ...] | tuple[SearchMatch, ...],
        revision: str,
    ) -> ToolResult:
        entries = tuple(self._json_entry(value) for value in values[: self._max_entries])
        return ToolResult(
            "ok",
            "ok",
            None,
            None,
            len(values) > len(entries),
            None,
            revision,
            entries,
        )

    def _command_result(
        self,
        result: CommandResult,
        revision: str,
        *,
        audit: Mapping[str, object] | None = None,
    ) -> ToolResult:
        failed = result.timed_out or result.exit_code not in {0, None}
        status: Literal["ok", "error", "denied"] = "error" if failed else "ok"
        reason = (
            "sandbox_timeout"
            if result.timed_out
            else "command_failed"
            if result.exit_code not in {0, None}
            else "ok"
        )
        stdout = self._bytes_mapping(
            result.stdout, already_truncated=result.stdout_truncated
        )
        stderr = self._bytes_mapping(
            result.stderr, already_truncated=result.stderr_truncated
        )
        return ToolResult(
            status,
            reason,
            None,
            None,
            bool(stdout["truncated"]) or bool(stderr["truncated"]),
            None,
            revision,
            stdout=stdout,
            stderr=stderr,
            exit_code=result.exit_code,
            audit=audit,
        )

    @staticmethod
    def _failure(
        status: Literal["error", "denied"],
        reason: str,
    ) -> ToolResult:
        return ToolResult(
            status, reason, None, None, False, None, "unknown"
        )

    async def _revision(self, session: SandboxSession) -> str:
        return str(await session.workspace_revision())

    @staticmethod
    def _json_entry(value: FileEntry | SearchMatch) -> Mapping[str, object]:
        raw = asdict(value)
        return {
            key: item.isoformat() if isinstance(item, datetime) else item
            for key, item in raw.items()
        }
