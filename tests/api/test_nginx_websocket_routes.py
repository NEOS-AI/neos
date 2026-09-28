"""nginx 가 백엔드의 모든 WebSocket 라우트를 업그레이드해 넘기는가.

`config/nginx/nginx.conf` 의 `location /api/` 는 keepalive 를 위해
`Connection ""` 을 싣는다. 그 블록을 지나는 WebSocket 은 업그레이드가 떨어져
백엔드에 평범한 GET 으로 닿고 404 가 된다 -- 2026-09-27 에 nginx:alpine 에 이 설정을
그대로 올려 코딩 소켓 셋이 전부 404 인 것을 확인했다. 그래서 소켓 경로는 따로
`Upgrade`/`Connection "upgrade"` 를 싣는 location 으로 받는다.

여기서는 백엔드가 선언한 소켓 경로를 소스에서 모아, 그중 어느 것도 업그레이드
location 밖으로 새지 않는지 본다. 소켓을 새로 만들면 nginx 도 같이 고치라고 빨개진다.
SSE 는 해당 없다 -- 백엔드가 `X-Accel-Buffering: no` 를 보내 nginx 가 버퍼링을 끈다.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
NGINX = ROOT / "config" / "nginx" / "nginx.conf"
API_PREFIX = "/api/v1"


def _socket_paths() -> set[str]:
    paths = set()
    for path in (ROOT / "neos" / "api").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text()
        prefix = re.search(r'APIRouter\(\s*prefix="([^"]*)"', source)
        for route in re.findall(r'@router\.websocket\("([^"]+)"\)', source):
            paths.add(API_PREFIX + (prefix.group(1) if prefix else "") + route)
    return paths


def _upgrade_locations() -> list[re.Pattern[str]]:
    conf = NGINX.read_text()
    patterns = []
    for match in re.finditer(r"location ~ (\S+) \{(.*?)\n        \}", conf, re.S):
        body = match.group(2)
        if "proxy_set_header Upgrade $http_upgrade;" in body and (
            'proxy_set_header Connection "upgrade";' in body
        ):
            patterns.append(re.compile(match.group(1)))
    return patterns


def test_the_scanner_finds_the_coding_sockets():
    assert _socket_paths() >= {
        "/api/v1/coding/ws",
        "/api/v1/coding/workspace/ws",
        "/api/v1/coding/pty/ws",
    }


def test_every_backend_socket_has_an_upgrade_location_in_nginx():
    locations = _upgrade_locations()
    unrouted = sorted(
        path
        for path in _socket_paths()
        if not any(pattern.search(path) for pattern in locations)
    )
    assert unrouted == []
