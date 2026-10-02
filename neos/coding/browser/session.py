"""태스크마다 하나인 휘발 브라우저 세션 -- 트랙 Q14a.

- 컨텍스트는 태스크마다 새로 연다. 프로필·쿠키는 태스크를 건너지 않는다(W6)
- 태스크가 끝나면(루프의 terminal) 닫고, 쉬거나 오래 살면 `sweep` 이 닫는다
- 모델에게 가는 모든 문자열(스냅샷 · 제목 · URL)은 이 세션이 입력한 비밀과
  비밀번호 칸의 값으로 가린 뒤 자르고 untrusted 로 감싼다(W7·W9)
- 오류는 **코드만** 돌려준다. 드라이버·페이지의 문구는 싣지 않는다
- 비밀은 그 주인이 적은 출처(`browser_origins`)에만 입력한다 -- 트랙 Q14b X1
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from neos.coding.browser.driver import (
    BrowserActionError,
    BrowserContext,
    BrowserDriver,
    BrowserPage,
    InterceptedRequest,
    ServedResponse,
)
from neos.coding.browser.egress import (
    EgressRefused,
    TypedSecret,
    egress_refusal,
    fetch_one_hop,
    request_origin,
)
from neos.coding.secrets import (
    ResolvedSecret,
    ResolvedSecrets,
    SecretLookup,
    SecretNotFound,
    secret_ref_name,
)
from neos.coding.tools.registry import BROWSER_SECRET_TOOL, ValidatedToolCall

_PASSWORD_MASK = "<masked:password>"
#: 이보다 짧은 비밀번호 칸 값은 가리면 무해한 글자까지 지운다 -- Chromium 은 접근성
#: 트리에서 비밀번호 값을 이미 가리므로 이것은 심층 방어다.
_PASSWORD_MASK_MIN = 4
_TRUNCATED = "\n[snapshot truncated]"


@dataclass(frozen=True, slots=True)
class BrowserLimits:
    navigation_timeout_sec: float = 15
    action_timeout_sec: float = 10
    max_navigations: int = 30
    max_requests: int = 500
    max_response_bytes: int = 5 * 1024 * 1024
    max_request_body_bytes: int = 1024 * 1024
    snapshot_max_chars: int = 20_000
    idle_timeout_sec: float = 300
    max_lifetime_sec: float = 1800
    max_contexts: int = 2

    @classmethod
    def from_config(cls, browser: Any) -> BrowserLimits:
        return cls(
            navigation_timeout_sec=browser.navigation_timeout_sec,
            action_timeout_sec=browser.action_timeout_sec,
            max_navigations=browser.max_navigations,
            max_requests=browser.max_requests,
            max_response_bytes=browser.max_response_bytes,
            max_request_body_bytes=browser.max_request_body_bytes,
            snapshot_max_chars=browser.snapshot_max_chars,
            idle_timeout_sec=browser.idle_timeout_sec,
            max_lifetime_sec=browser.max_lifetime_sec,
            max_contexts=browser.max_contexts,
        )


@dataclass(frozen=True, slots=True)
class BrowserOutcome:
    """실행기가 `ToolResult` 로 옮긴다. 여기 있는 문자열은 전부 이미 가려졌다."""

    status: Literal["ok", "error", "denied"]
    reason: str
    url: str = ""
    title: str = ""
    text: str = ""
    blocked: Mapping[str, int] = field(default_factory=dict)
    secret_refs: tuple[str, ...] = ()


@dataclass
class _Session:
    task_id: str
    context: BrowserContext
    page: BrowserPage
    created: float
    last_used: float
    navigations: int = 0
    requests: int = 0
    loaded: bool = False
    typed: dict[str, TypedSecret] = field(default_factory=dict, repr=False)
    blocked: Counter = field(default_factory=Counter)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def scrubber(self) -> ResolvedSecrets:
        return ResolvedSecrets(
            {name: ResolvedSecret("", secret.value) for name, secret in self.typed.items()}
        )


def _default_allowlist() -> tuple[str, ...]:
    from neos.coding.tools.executor import _web_fetch_hosts

    return _web_fetch_hosts()


class BrowserSessions:
    """프로세스 하나의 브라우저 세션들. 루프가 하나를 들고 태스크마다 `bind` 한다."""

    def __init__(
        self,
        driver: BrowserDriver,
        limits: BrowserLimits | None = None,
        *,
        allowlist: Callable[[], tuple[str, ...]] = _default_allowlist,
        fetch: Callable[..., ServedResponse] = fetch_one_hop,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._driver = driver
        self._limits = limits or BrowserLimits()
        self._allowlist = allowlist
        self._fetch = fetch
        self._clock = clock
        self._sessions: dict[str, _Session] = {}
        self._opening = asyncio.Lock()

    def __repr__(self) -> str:
        return f"BrowserSessions(open={len(self._sessions)})"

    def bind(self, task_id: str) -> BoundBrowser:
        return BoundBrowser(self, task_id)

    def is_open(self, task_id: str) -> bool:
        return task_id in self._sessions

    async def close(self, task_id: str) -> None:
        session = self._sessions.pop(task_id, None)
        if session is None:
            return
        session.typed.clear()
        try:
            await session.context.close()
        except Exception:  # noqa: BLE001 -- 닫기 실패가 태스크를 실패시키지 않는다
            pass

    async def sweep(self) -> None:
        """쉬었거나 오래 산 세션을 닫는다. 루프의 매 단계와 매 브라우저 호출이 부른다."""
        now = self._clock()
        expired = [
            task_id
            for task_id, session in self._sessions.items()
            if now - session.last_used > self._limits.idle_timeout_sec
            or now - session.created > self._limits.max_lifetime_sec
        ]
        for task_id in expired:
            await self.close(task_id)

    async def close_all(self) -> None:
        for task_id in list(self._sessions):
            await self.close(task_id)
        try:
            await self._driver.aclose()
        except Exception:  # noqa: BLE001
            pass

    # -- 요청 하나 ---------------------------------------------------------------

    def _server(self, holder: dict[str, _Session]):
        async def serve(request: InterceptedRequest) -> ServedResponse | None:
            session = holder.get("session")
            if session is None or self._sessions.get(session.task_id) is not session:
                return None  # 닫힌 세션의 늦은 요청
            session.requests += 1
            if session.requests > self._limits.max_requests:
                session.blocked["browser_request_cap"] += 1
                return None
            reason = egress_refusal(
                request,
                allowlist=self._allowlist(),
                typed=session.typed,
                max_request_body_bytes=self._limits.max_request_body_bytes,
            )
            if reason is not None:
                session.blocked[reason] += 1
                return None
            try:
                return await asyncio.to_thread(
                    self._fetch,
                    request,
                    timeout_sec=self._limits.navigation_timeout_sec,
                    max_response_bytes=self._limits.max_response_bytes,
                )
            except EgressRefused as error:
                session.blocked[error.reason] += 1
                return None
            except Exception:  # noqa: BLE001 -- 원인과 상관없이 내보내지 않는다
                session.blocked["browser_fetch_failed"] += 1
                return None

        return serve

    async def _open(self, task_id: str) -> _Session | str:
        async with self._opening:
            existing = self._sessions.get(task_id)
            if existing is not None:
                return existing
            await self.sweep()
            if len(self._sessions) >= self._limits.max_contexts:
                return "browser_capacity"
            holder: dict[str, _Session] = {}
            try:
                context = await self._driver.new_context(self._server(holder), task_id=task_id)
                page = await context.open_page()
            except Exception:  # noqa: BLE001 -- 브라우저가 없으면 다른 길로 돌지 않는다
                return "browser_unavailable"
            now = self._clock()
            session = _Session(task_id, context, page, created=now, last_used=now)
            holder["session"] = session
            self._sessions[task_id] = session
            return session

    # -- 행동 -------------------------------------------------------------------

    async def run(
        self, task_id: str, call: ValidatedToolCall, *, secrets: SecretLookup | None
    ) -> BrowserOutcome:
        await self.sweep()
        action = "fill_secret" if call.name == BROWSER_SECRET_TOOL else str(call.input["action"])
        if action == "close":
            await self.close(task_id)
            return BrowserOutcome("ok", "ok", text="closed")
        opened = await self._open(task_id)
        if isinstance(opened, str):
            return BrowserOutcome("error" if opened == "browser_unavailable" else "denied", opened)
        session = opened
        async with session.lock:
            session.last_used = self._clock()
            try:
                outcome = await self._act(session, action, call, secrets)
            except BrowserActionError as error:
                reason = "browser_timeout" if error.kind == "timeout" else "browser_action_failed"
                outcome = BrowserOutcome("error", reason)
            except Exception:  # noqa: BLE001 -- 문구를 싣지 않는다
                outcome = BrowserOutcome("error", "browser_action_failed")
            session.last_used = self._clock()
        return outcome

    async def _act(
        self,
        session: _Session,
        action: str,
        call: ValidatedToolCall,
        secrets: SecretLookup | None,
    ) -> BrowserOutcome:
        limits = self._limits
        action_ms = limits.action_timeout_sec * 1000
        data = call.input
        if action == "navigate":
            return await self._navigate(session, str(data["url"]))
        if not session.loaded:
            return BrowserOutcome("denied", "browser_no_page")
        if action == "click":
            await session.page.click(str(data["ref"]), timeout_ms=action_ms)
        elif action == "type":
            ref = str(data["ref"])
            await session.page.fill(ref, str(data["text"]), timeout_ms=action_ms)
            if data.get("submit"):
                await session.page.press_enter(ref, timeout_ms=action_ms)
        elif action == "fill_secret":
            refused = await self._fill_secret(session, data, secrets)
            if refused is not None:
                return refused
        return await self._snapshot(session, secret_refs=self._refs_of(call))

    @staticmethod
    def _refs_of(call: ValidatedToolCall) -> tuple[str, ...]:
        name = secret_ref_name(call.input.get("secret")) if call.name == BROWSER_SECRET_TOOL else None
        return (name,) if name else ()

    async def _navigate(self, session: _Session, raw_url: str) -> BrowserOutcome:
        from neos.coding.tools.executor import _upgrade_to_https

        url = _upgrade_to_https(raw_url)
        if session.navigations >= self._limits.max_navigations:
            return BrowserOutcome("denied", "browser_navigation_cap")
        # 최상위 URL 은 브라우저에 넘기기 전에 같은 판정으로 먼저 본다 -- 모델이 받는
        # 사유가 "요청 하나가 막혔다" 가 아니라 이름 있는 거절이 되게.
        reason = egress_refusal(
            InterceptedRequest(url, "GET"),
            allowlist=self._allowlist(),
            typed=session.typed,
            max_request_body_bytes=self._limits.max_request_body_bytes,
        )
        if reason == "policy_web_fetch_host_denied":
            return BrowserOutcome("denied", reason)
        if reason is not None:
            return BrowserOutcome("error", reason)
        session.navigations += 1
        await session.page.goto(url, timeout_ms=self._limits.navigation_timeout_sec * 1000)
        session.loaded = True
        return await self._snapshot(session)

    async def _fill_secret(
        self, session: _Session, data: Mapping[str, Any], secrets: SecretLookup | None
    ) -> BrowserOutcome | None:
        from neos.coding.tools.executor import _web_fetch_host_allowed

        name = secret_ref_name(data.get("secret"))
        origin = str(data.get("origin") or "")
        if name is None or not origin:
            return BrowserOutcome("denied", "policy_schema_invalid")
        # 값이 지날 길이 사적이라고 선언한 드라이버에만 넣는다(트랙 Q14c MB4). 관리형은 벤더
        # exec 중계라 거짓 고정이다 -- 금고를 열기 **전에** 거절한다. 선언이 없으면 거짓(fail closed).
        if not getattr(self._driver, "confidential_channel", False):
            return BrowserOutcome("denied", "browser_secret_channel_unavailable")
        action_ms = self._limits.action_timeout_sec * 1000
        # 비밀은 이 출처의 칸에만 들어간다: 지금 페이지 · 그 칸이 사는 문서 · 허용 호스트 셋 다.
        if request_origin(session.page.url()) != origin:
            return BrowserOutcome("denied", "browser_secret_origin_mismatch")
        ref = str(data["ref"])
        if await session.page.element_origin(ref, timeout_ms=action_ms) != origin:
            return BrowserOutcome("denied", "browser_secret_origin_mismatch")
        host = origin.removeprefix("https://").rsplit(":", 1)[0]
        if not _web_fetch_host_allowed(host, self._allowlist()):
            return BrowserOutcome("denied", "policy_web_fetch_host_denied")
        if secrets is None:
            return BrowserOutcome("denied", "browser_secret_unavailable")
        try:
            resolved = await secrets([name])
        except SecretNotFound:
            return BrowserOutcome("denied", "secret_not_found")
        except Exception:  # noqa: BLE001 -- 풀지 못한 값으로 돌리지 않는다
            return BrowserOutcome("error", "secret_store_unavailable")
        secret = resolved.values.get(name)
        if secret is None:
            return BrowserOutcome("denied", "secret_not_found")
        # 비밀의 주인이 적은 출처에만 들어간다(Q14b X1, S3 의 브라우저판). 묶임이 없으면 어디에도.
        if origin not in secret.browser_origins:
            return BrowserOutcome("denied", "secret_origin_mismatch")
        # 칸에 넣기 **전에** 기록한다 -- 입력 이벤트가 곧바로 내는 요청도 출구 검사를 받는다.
        session.typed[name] = TypedSecret(name, origin, secret.value)
        await session.page.fill(ref, secret.value, timeout_ms=action_ms)
        if data.get("submit"):
            await session.page.press_enter(ref, timeout_ms=action_ms)
        return None

    async def _snapshot(
        self, session: _Session, *, secret_refs: tuple[str, ...] = ()
    ) -> BrowserOutcome:
        from neos.coding.tools.executor import _wrap_untrusted_web_content

        page = session.page
        raw = await page.snapshot(timeout_ms=self._limits.action_timeout_sec * 1000)
        masks = tuple(
            value for value in await page.password_values() if len(value) >= _PASSWORD_MASK_MIN
        )
        scrub = session.scrubber()

        def clean(value: str) -> str:
            for mask in sorted(masks, key=len, reverse=True):
                value = value.replace(mask, _PASSWORD_MASK)
            return scrub.scrub_text(value)

        text = clean(raw)
        cap = self._limits.snapshot_max_chars
        if len(text) > cap:
            text = text[:cap] + _TRUNCATED
        return BrowserOutcome(
            "ok",
            "ok",
            url=clean(page.url()),
            title=clean(await page.title()),
            text=_wrap_untrusted_web_content(text),
            blocked=dict(session.blocked),
            secret_refs=secret_refs,
        )


@dataclass(frozen=True, slots=True)
class BoundBrowser:
    """한 태스크에 묶인 손잡이. 실행기는 이것만 받는다 -- 다른 태스크의 세션에 닿지 못한다."""

    sessions: BrowserSessions
    task_id: str

    async def run(
        self, call: ValidatedToolCall, *, secrets: SecretLookup | None = None
    ) -> BrowserOutcome:
        return await self.sessions.run(self.task_id, call, secrets=secrets)


def build_browser_sessions(
    config: Any, *, managed_channels: Any | None = None
) -> BrowserSessions | None:
    """`None` 이 off 다. 켜졌는지 판단하는 자리는 이 팩토리 하나다.

    설정 검증(`validate_coding_browser`)을 거치지 않고 만든 설정이어도 development
    밖에서 운영자 동의 없이 열리지 않는다 -- 같은 조건을 여기서 다시 본다.

    `provider: managed`(트랙 Q14c)는 관리형 샌드박스 평면이 켜져 있어야 하고, 태스크의
    샌드박스에 guest 채널을 여는 `managed_channels`(`BrowserChannelOpener`)가 주입돼야 한다.
    그 배선(B2 의 할당 평면 + 벤더 `open_stdio`)이 아직 없으므로 오늘 runtime 은 주입하지
    않고, 켜라고 하면 여기서 시끄럽게 실패한다 -- 호스트 브라우저로 대신 돌지 않는다(MB2).
    """
    browser = config.coding_model.browser
    if not browser.enabled:
        return None
    if config.environment != "development" and not browser.allow_outside_development:
        raise ValueError("coding_model.browser outside development needs allow_outside_development")
    limits = BrowserLimits.from_config(browser)
    if getattr(browser, "provider", "host") == "managed":
        sandbox = config.sandbox
        if sandbox.provider != "managed" or not sandbox.managed.enabled:
            raise ValueError("coding_model.browser.provider=managed needs the managed sandbox plane")
        if managed_channels is None:
            raise ValueError(
                "coding_model.browser.provider=managed has no guest channel opener "
                "(B2 runtime wiring is not landed)"
            )
        from neos.coding.browser.managed_driver import ManagedBrowserDriver

        return BrowserSessions(ManagedBrowserDriver(managed_channels), limits)
    from neos.coding.browser.playwright_driver import PlaywrightDriver

    return BrowserSessions(PlaywrightDriver(), limits)
