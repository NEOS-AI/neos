from pathlib import Path

import pytest


pytestmark = pytest.mark.no_db


WEB_ENV_FILES = (
    "web/lib/backend-api.ts",
    "web/app/(auth)/auth.ts",
    "web/app/(auth)/api/auth/guest/route.ts",
    "web/app/(auth)/actions.ts",
    "web/app/(chat)/api/files/upload/route.ts",
    "web/lib/ai/providers.ts",
    "web/proxy.ts",
)


def test_web_server_config_wrapper_exists_with_expected_exports():
    text = Path("web/lib/server-config.ts").read_text(encoding="utf-8")

    for export_name in (
        "getBackendUrl",
        "getAuthSecret",
        "getGoogleOAuthConfig",
        "getAiGatewayApiKey",
    ):
        assert f"function {export_name}" in text


def test_web_server_env_access_is_centralized():
    for file_name in WEB_ENV_FILES:
        text = Path(file_name).read_text(encoding="utf-8")

        assert "process.env.BACKEND_URL" not in text
        assert "process.env.AUTH_SECRET" not in text
        assert "process.env.GOOGLE_CLIENT_ID" not in text
        assert "process.env.GOOGLE_CLIENT_SECRET" not in text
        assert "process.env.AI_GATEWAY_API_KEY" not in text
