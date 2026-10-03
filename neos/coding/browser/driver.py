"""브라우저 드라이버 계약 -- 트랙 Q14a.

세션 관리(`session.py`)는 이 프로토콜만 안다. 실제 구현은 `playwright_driver.py`,
테스트는 가짜를 쓴다. 프로토콜의 메서드는 Playwright 의 **실제 호출 하나씩**에
대응한다(각 줄의 주석) -- 가짜가 실제 API 에 없는 필드를 지어내지 않게.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class InterceptedRequest:
    """`route.request` 에서 읽은 것: `url` · `method` · `all_headers()` · `post_data_buffer`."""

    url: str
    method: str
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class ServedResponse:
    """`route.fulfill(status=, headers=, body=)` 에 그대로 넘긴다."""

    status: int
    headers: Mapping[str, str]
    body: bytes = field(repr=False)


#: 요청 하나를 받아 응답을 주거나 `None`(= `route.abort()`).
RequestServer = Callable[[InterceptedRequest], Awaitable[ServedResponse | None]]


class BrowserActionError(Exception):
    """드라이버가 올리는 유일한 예외. `kind` 는 `timeout` | `failed`.

    Playwright 의 오류 문구는 **싣지 않는다** -- 페이지가 고른 문자열(선택자·URL·
    콘솔)이 섞여 모델·원장으로 새는 길이 되기 때문이다.
    """

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


class BrowserPage(Protocol):
    def url(self) -> str: ...  # page.url

    async def title(self) -> str: ...  # page.title()

    async def goto(self, url: str, *, timeout_ms: float) -> int | None: ...  # page.goto -> Response.status

    async def snapshot(self, *, timeout_ms: float) -> str: ...  # locator("body").aria_snapshot(mode="ai")

    async def password_values(self) -> tuple[str, ...]: ...  # page.frames 마다 frame.eval_on_selector_all(..)

    async def element_origin(self, ref: str, *, timeout_ms: float) -> str: ...  # locator.evaluate(origin)

    async def click(self, ref: str, *, timeout_ms: float) -> None: ...  # locator("aria-ref=..").click

    async def fill(self, ref: str, value: str, *, timeout_ms: float) -> None: ...  # locator.fill

    async def press_enter(self, ref: str, *, timeout_ms: float) -> None: ...  # locator.press("Enter")


class BrowserContext(Protocol):
    async def open_page(self) -> BrowserPage: ...  # context.new_page()

    async def close(self) -> None: ...  # context.close()


class BrowserDriver(Protocol):
    #: 트랙 Q14c MB4: 이 드라이버가 페이지에 넣는 값이 지나는 길이 비밀을 실어도 될 만큼 사적인가.
    #: 호스트 드라이버는 참(값은 워커 메모리에서 같은 기계의 Playwright 파이프로만 간다),
    #: 관리형은 거짓 고정. 선언하지 않은 구현은 거짓으로 읽는다(fail closed) -- 세션이 `getattr` 로 본다.
    confidential_channel: bool

    #: `task_id` 는 컨텍스트의 주인이다. 호스트 드라이버는 쓰지 않고(프로세스 하나에 브라우저 하나),
    #: 관리형은 그 태스크의 샌드박스를 고른다(Q14c).
    async def new_context(self, serve: RequestServer, *, task_id: str = "") -> BrowserContext: ...

    async def aclose(self) -> None: ...
