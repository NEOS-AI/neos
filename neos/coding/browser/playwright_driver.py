"""Playwright 로 `BrowserDriver` 를 구현한다 -- 트랙 Q14a.

Chromium 은 **네트워크 없이** 띄운다(W2): 모든 이름 풀이를 실패시키고(`--host-resolver-rules`)
죽은 프록시를 건다. 그래서 페이지의 바이트는 `context.route` → `serve` → `route.fulfill`
로만 들어온다. 라우팅을 빠져나가는 요청(웹소켓·프리페치 등)은 갈 곳이 없다 -- 웹소켓은
`route_web_socket` 으로 서버에 잇지 않고 닫는다. 서비스 워커·다운로드는 막는다.
"""

from __future__ import annotations

import asyncio
from typing import Any

from neos.coding.browser.driver import (
    BrowserActionError,
    InterceptedRequest,
    RequestServer,
)

_LAUNCH_ARGS = (
    "--host-resolver-rules=MAP * ~NOTFOUND",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-domain-reliability",
    "--disable-sync",
    "--no-pings",
    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--webrtc-ip-handling-policy=disable_non_proxied_udp",
)
#: 닿을 수 없는 프록시. 라우팅을 빠져나간 요청은 여기서 연결이 거절된다.
_DEAD_PROXY = {"server": "http://127.0.0.1:9"}
_ORIGIN_JS = "element => element.ownerDocument.location.origin"
_PASSWORDS_JS = "elements => elements.map(element => element.value || '')"


def _translate(error: BaseException) -> BrowserActionError:
    from playwright.async_api import TimeoutError as PlaywrightTimeout

    return BrowserActionError("timeout" if isinstance(error, PlaywrightTimeout) else "failed")


class _Page:
    def __init__(self, page: Any) -> None:
        self._page = page

    def _ref(self, ref: str) -> Any:
        return self._page.locator(f"aria-ref={ref}")

    def url(self) -> str:
        return str(self._page.url)

    async def title(self) -> str:
        try:
            return str(await self._page.title())
        except Exception as error:  # noqa: BLE001
            raise _translate(error) from None

    async def goto(self, url: str, *, timeout_ms: float) -> int | None:
        try:
            response = await self._page.goto(url, timeout=timeout_ms, wait_until="load")
        except Exception as error:  # noqa: BLE001
            raise _translate(error) from None
        return None if response is None else int(response.status)

    async def snapshot(self, *, timeout_ms: float) -> str:
        try:
            return str(await self._page.locator("body").aria_snapshot(timeout=timeout_ms, mode="ai"))
        except Exception as error:  # noqa: BLE001
            raise _translate(error) from None

    async def password_values(self) -> tuple[str, ...]:
        # 모든 프레임을 본다(트랙 Q14b X6) -- 로그인 칸이 iframe 안에 있는 사이트가 흔하다.
        # 한 프레임이라도 읽지 못하면 실패다: 못 본 칸을 가렸다고 치지 않는다.
        found: list[str] = []
        try:
            for frame in self._page.frames:
                values = await frame.eval_on_selector_all("input[type=password]", _PASSWORDS_JS)
                found.extend(str(value) for value in values or () if value)
        except Exception as error:  # noqa: BLE001
            raise _translate(error) from None
        return tuple(found)

    async def element_origin(self, ref: str, *, timeout_ms: float) -> str:
        try:
            return str(await self._ref(ref).evaluate(_ORIGIN_JS, timeout=timeout_ms))
        except Exception as error:  # noqa: BLE001
            raise _translate(error) from None

    async def click(self, ref: str, *, timeout_ms: float) -> None:
        try:
            await self._ref(ref).click(timeout=timeout_ms)
        except Exception as error:  # noqa: BLE001
            raise _translate(error) from None

    async def fill(self, ref: str, value: str, *, timeout_ms: float) -> None:
        try:
            await self._ref(ref).fill(value, timeout=timeout_ms)
        except Exception as error:  # noqa: BLE001
            raise _translate(error) from None

    async def press_enter(self, ref: str, *, timeout_ms: float) -> None:
        try:
            await self._ref(ref).press("Enter", timeout=timeout_ms)
        except Exception as error:  # noqa: BLE001
            raise _translate(error) from None


class _Context:
    def __init__(self, context: Any) -> None:
        self._context = context
        self._page: Any = None

    async def open_page(self) -> _Page:
        page = await self._context.new_page()
        self._page = page
        # 대화상자는 닫고, 새 창(팝업)은 열리는 대로 닫는다 -- 세션은 페이지 하나다.
        page.on("dialog", lambda dialog: asyncio.ensure_future(dialog.dismiss()))
        self._context.on(
            "page",
            lambda extra: None if extra is self._page else asyncio.ensure_future(extra.close()),
        )
        return _Page(page)

    async def close(self) -> None:
        await self._context.close()


class PlaywrightDriver:
    """브라우저 프로세스 하나를 게으르게 띄우고, 태스크마다 새 컨텍스트를 연다."""

    #: 값은 이 프로세스에서 같은 기계의 Playwright 드라이버 파이프로만 간다(트랙 Q14c MB4).
    confidential_channel = True

    def __init__(
        self, *, chromium_sandbox: bool = True, executable_path: str | None = None
    ) -> None:
        self._chromium_sandbox = chromium_sandbox
        self._executable_path = executable_path
        self._playwright: Any = None
        self._browser: Any = None
        self._lock = asyncio.Lock()

    async def _ensure_browser(self) -> Any:
        async with self._lock:
            if self._browser is not None and self._browser.is_connected():
                return self._browser
            from playwright.async_api import async_playwright

            if self._playwright is None:
                self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=list(_LAUNCH_ARGS),
                proxy=_DEAD_PROXY,
                chromium_sandbox=self._chromium_sandbox,
                executable_path=self._executable_path,
            )
            return self._browser

    async def new_context(self, serve: RequestServer, *, task_id: str = "") -> _Context:
        browser = await self._ensure_browser()
        context = await browser.new_context(
            service_workers="block",
            accept_downloads=False,
            java_script_enabled=True,
            ignore_https_errors=False,
        )

        async def handle(route: Any) -> None:
            request = route.request
            try:
                headers = await request.all_headers()
            except Exception:  # noqa: BLE001
                headers = {}
            served = await serve(
                InterceptedRequest(
                    url=str(request.url),
                    method=str(request.method),
                    headers=dict(headers),
                    body=request.post_data_buffer,
                )
            )
            if served is None:
                await route.abort("blockedbyclient")
                return
            await route.fulfill(
                status=served.status, headers=dict(served.headers), body=served.body
            )

        async def refuse_socket(ws: Any) -> None:
            await ws.close()

        await context.route("**/*", handle)
        await context.route_web_socket("**/*", refuse_socket)
        return _Context(context)

    async def aclose(self) -> None:
        async with self._lock:
            if self._browser is not None:
                await self._browser.close()
                self._browser = None
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None
