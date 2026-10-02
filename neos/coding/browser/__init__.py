"""에이전트 브라우저 -- 트랙 Q14a (docs/Q14_AGENT_BROWSER_DESIGN_261001.md).

`driver`(계약) · `egress`(요청마다의 web_fetch 판정) · `session`(태스크마다 휘발 세션) ·
`playwright_driver`(실제 구현). 이 패키지를 여는 자리는 `build_browser_sessions` 하나다.
"""
