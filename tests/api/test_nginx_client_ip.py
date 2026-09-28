"""nginx 가 rate limit 을 BFF 가 아니라 **사용자** IP 로 세는가.

프론트(Vercel)의 BFF 가 백엔드를 부르므로 nginx 의 접속 IP 는 BFF 의 것이다. BFF 는
사용자 IP 를 `X-Neos-Client-IP` 에, 공유 비밀을 `X-Neos-Proxy-Auth` 에 싣는다
(`web/lib/client-ip.ts`). nginx 는 비밀이 맞을 때만 그 IP 로 센다.

비밀을 확인하는 map 은 컨테이너 시작 때 `config/nginx/40-neos-client-ip.sh` 가 쓴다.
정적 설정에 두면 비밀이 없는 배포에서 빈 문자열끼리 일치해 **누구나 IP 를 골라**
보낼 수 있다 -- 그래서 비밀이 없으면 아무 헤더도 믿지 않는 map 을 쓰고, 형식이
잘못된 비밀이면 시작을 막는다.

그리고 인증 전용 제한은 한때 `^/api/v1/(login|register|token)` 에 걸려 있었다. 실제
경로는 `/api/v1/auth/login` 이라 **한 번도 적용되지 않았다**. 경로를 백엔드 라우터에서
읽어 대조한다.
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "config" / "nginx" / "40-neos-client-ip.sh"
NGINX = ROOT / "config" / "nginx" / "nginx.conf"
AUTH_HANDLERS = ROOT / "neos" / "api" / "handlers" / "auth.py"


def _generate(tmp_path: pathlib.Path, secret: str | None) -> tuple[int, str]:
    env = {k: v for k, v in os.environ.items() if k != "NEOS_CLIENT_IP_SECRET"}
    env["NEOS_NGINX_CONF_D"] = str(tmp_path)
    if secret is not None:
        env["NEOS_CLIENT_IP_SECRET"] = secret
    result = subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, text=True)
    out = tmp_path / "neos-client-ip.conf"
    return result.returncode, out.read_text() if out.exists() else ""


def test_without_a_secret_no_header_is_trusted(tmp_path):
    code, conf = _generate(tmp_path, None)
    assert code == 0
    assert "default 0;" in conf
    assert " 1;" not in conf


def test_an_empty_secret_is_the_same_as_none(tmp_path):
    code, conf = _generate(tmp_path, "")
    assert code == 0
    assert " 1;" not in conf


def test_a_valid_secret_is_the_only_trusted_value(tmp_path):
    secret = "a" * 40
    code, conf = _generate(tmp_path, secret)
    assert code == 0
    assert f'"{secret}" 1;' in conf
    assert "default 0;" in conf


def test_a_short_or_quoted_secret_refuses_to_start(tmp_path):
    for secret in ("short", 'x" 1; default 1; "' + "a" * 40, "a" * 31):
        code, conf = _generate(tmp_path / str(len(secret)), secret)
        assert code != 0, secret
        assert conf == ""


def _auth_location() -> re.Pattern[str]:
    match = re.search(r"location ~ (\S+) \{\s*limit_req zone=auth_limit", NGINX.read_text())
    assert match, "no auth_limit location"
    return re.compile(match.group(1))


def _auth_paths() -> set[str]:
    routes = re.findall(r'@router\.post\("([^"]+)"', AUTH_HANDLERS.read_text())
    return {f"/api/v1/auth{route}" for route in routes}


def test_the_auth_limit_covers_the_real_credential_routes():
    location = _auth_location()
    paths = _auth_paths()
    credential = {
        "/api/v1/auth/login",
        "/api/v1/auth/register",
        "/api/v1/auth/guest",
        "/api/v1/auth/oauth/google",
    }
    assert credential <= paths, "auth router no longer declares these routes"
    assert sorted(p for p in credential if not location.search(p)) == []


def test_token_refresh_stays_on_the_general_api_limit():
    # 갱신은 로그인한 사용자가 15분마다 한다. 분당 5회 버킷에 넣을 이유가 없다.
    assert not _auth_location().search("/api/v1/auth/refresh")


def test_both_limits_count_the_client_key():
    conf = NGINX.read_text()
    zones = re.findall(r"limit_req_zone (\S+) zone=(\w+)", conf)
    assert dict((zone, key) for key, zone in zones) == {
        "api_limit": "$client_rate_key",
        "auth_limit": "$client_rate_key",
    }


def test_the_proof_header_never_reaches_the_backend():
    conf = NGINX.read_text()
    for block in re.findall(r"location [^{]+\{(.*?)\n        \}", conf, re.S):
        if "proxy_pass" in block:
            assert 'proxy_set_header X-Neos-Proxy-Auth "";' in block, block[:80]
