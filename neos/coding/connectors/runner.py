"""`tools/call` 한 번 -- 풀고 -> 부르고 -> 가리고 -> 감싼다 (트랙 Q11a).

Q6 의 세 걸음을 그대로 쓴다(`neos/coding/secrets.py` 머리말). 풀린 값은 이 함수의
지역 변수와 연결 객체 안에서만 산다 -- 결과·사유·로그 어디에도 나가지 않는다.
결과 본문은 신뢰하지 않는 글이다(M9): 값 자체를 가리고 -> 자르고 -> 정규식 규칙을
걸고 -> `wrap_untrusted_document` 로 감싼다. 루프가 그 위에 `redact_sensitive` 를 한 번 더 건다.

고정한 도구(트랙 Q11b)는 부르기 **전에** 같은 연결에서 `tools/list` 로 서버의 것과 맞춰
본다 -- 없거나 스키마가 다르면 `tools/call` 을 보내지 않는다(N4). 이 확인은 승인된 호출
안에서 같은 자격증명으로 돈다 -- 비밀을 따로 푸는 순간이 없다(N5).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from neos.coding.connectors.catalog import (
    ConnectorCatalog,
    ConnectorTool,
    canonical_schema,
    materialize_credentials,
)
from neos.coding.connectors.protocol import ConnectorError, open_session
from neos.coding.secrets import ResolvedSecrets, SecretLookup, SecretNotFound, secret_ref_name
from neos.univer.ports import wrap_untrusted_document

logger = logging.getLogger(__name__)

#: 모델에게 돌려주는 사유의 다음 걸음. 승인 거절 문구(`approvals._DENIAL_REASONS`)와 같은 말투.
CONNECTOR_FIX_NOTES = {
    "connector_unavailable": "the connector is unreachable; do not retry now",
    "connector_timeout": "the connector timed out; retry once at most",
    "connector_message_too_large": "the connector reply was too large; ask for less",
    "connector_protocol_error": "the connector spoke an unexpected protocol; do not retry",
    "connector_call_failed": "the connector rejected the call; fix the arguments",
    "connector_tool_error": "the connector tool reported an error; read it before retrying",
    "connector_tool_missing": (
        "the connector no longer offers this tool; do not retry -- tell the user the "
        "operator must update the pinned tool list"
    ),
    "connector_schema_drift": (
        "the connector changed this tool's input schema; do not retry -- tell the user "
        "the operator must update the pinned tool list"
    ),
    "secret_not_found": "no stored secret has that name; do not retry -- ask the user to add it",
    "secret_env_name_mismatch": "that secret is bound to a different environment variable",
    "secret_store_unavailable": "the secret store is unavailable; do not retry now",
}


@dataclass(frozen=True, slots=True)
class ConnectorOutcome:
    status: Literal["ok", "error", "denied"]
    reason_code: str
    #: 감싼 본문(가린 뒤). 실패에도 서버의 문구가 있으면 감싸서 싣는다.
    text: str | None = None
    original_bytes: int | None = None
    truncated: bool = False
    secret_refs: tuple[str, ...] = ()


def pin_drift(tool: ConnectorTool, listed: list[Mapping[str, Any]]) -> str | None:
    """고정한 도구가 서버와 어긋났는가(N4). `None` 이 일치다.

    이름이 없으면 `connector_tool_missing`, 같은 이름의 항목 중 하나라도 `inputSchema` 의
    정규형이 다르면 `connector_schema_drift`. 설명·annotations 는 보지 않는다 -- 프롬프트에
    실리는 것은 운영자가 고정한 설명이고, 위험은 서버의 말이 아니다(M4).
    """
    if not listed:
        return "connector_tool_missing"
    for item in listed:
        try:
            live = canonical_schema(item.get("inputSchema"))
        except (TypeError, ValueError):
            return "connector_schema_drift"
        if live != tool.pinned_schema:
            return "connector_schema_drift"
    return None


def render_content(result: Mapping[str, Any]) -> tuple[str, bool]:
    """`tools/call` 결과 -> (글, isError). 텍스트만 싣고 나머지는 자리표시만 남긴다."""
    parts: list[str] = []
    content = result.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, Mapping):
                continue
            kind = item.get("type")
            if kind == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif kind == "resource" and isinstance(item.get("resource"), Mapping):
                text = item["resource"].get("text")
                parts.append(text if isinstance(text, str) else "[resource omitted]")
            elif kind == "resource_link":
                parts.append(f"[resource link: {str(item.get('uri') or '')[:200]}]")
            else:
                parts.append(f"[{str(kind or 'unknown')[:20]} content omitted]")
    if not parts and "structuredContent" in result:
        try:
            parts.append(json.dumps(result["structuredContent"], ensure_ascii=False))
        except (TypeError, ValueError):
            parts.append("[structured content omitted]")
    return "\n".join(parts), result.get("isError") is True


class ConnectorRunner:
    def __init__(self, catalog: ConnectorCatalog, *, opener: Any = open_session) -> None:
        self._catalog = catalog
        self._opener = opener

    def tool(self, name: str) -> ConnectorTool | None:
        return self._catalog.get(name)

    def _sealed(
        self, data: bytes, resolved: ResolvedSecrets, source: str, cap: int
    ) -> tuple[str, bool, int]:
        # 값 자체를 **자르기 전에** 가린다 -- 그러면 잘린 꼬리에 비밀의 앞부분이 남지 않는다(S6).
        scrubbed = resolved.scrub_bytes(data)
        truncated = len(scrubbed) > cap
        text = resolved.scrub_text(scrubbed[:cap].decode("utf-8", errors="replace"))
        return wrap_untrusted_document(text, source), truncated, len(data)

    async def call(
        self,
        tool: ConnectorTool,
        arguments: Mapping[str, object],
        *,
        secrets: SecretLookup | None,
        output_cap: int | None = None,
    ) -> ConnectorOutcome:
        """`output_cap` 은 부르는 쪽의 미리보기 상한 -- 감싼 글의 닫는 꼬리가 잘리지 않게."""
        server = self._catalog.servers[tool.server]
        settings = self._catalog.settings
        cap = settings.max_output_bytes
        if output_cap is not None:
            cap = max(1, min(cap, output_cap))
        resolved = ResolvedSecrets({})
        if tool.secret_refs:
            if secrets is None:
                return ConnectorOutcome("error", "secret_store_unavailable")
            try:
                resolved = await secrets(list(tool.secret_refs))
            except SecretNotFound:
                return ConnectorOutcome("denied", "secret_not_found")
            except Exception:  # noqa: BLE001 -- 원인과 상관없이 부르지 않는다
                return ConnectorOutcome("error", "secret_store_unavailable")
            if any(name not in resolved.values for name in tool.secret_refs):
                return ConnectorOutcome("denied", "secret_not_found")
            # S3: 비밀은 주인이 묶은 환경변수에만 들어간다 -- 운영자 설정도 예외가 아니다.
            for env_name, raw in server.env.items():
                name = secret_ref_name(raw)
                if name is not None and resolved.values[name].env_name != env_name:
                    return ConnectorOutcome("denied", "secret_env_name_mismatch")
        env, headers = materialize_credentials(server, resolved)
        source = f"mcp:{tool.server}/{tool.tool}"
        try:
            async with asyncio.timeout(settings.call_timeout_sec):
                async with self._opener(
                    server,
                    env=env,
                    headers=headers,
                    max_message_bytes=settings.max_message_bytes,
                    timeout_sec=settings.call_timeout_sec,
                ) as session:
                    if tool.pinned_schema is not None:
                        drift = pin_drift(tool, await session.find_tool(tool.tool))
                        if drift is not None:
                            logger.warning("mcp call %s refused (%s)", tool.name, drift)
                            return ConnectorOutcome(
                                "error", drift, secret_refs=resolved.names
                            )
                    raw = await session.call_tool(tool.tool, arguments)
        except ConnectorError as error:
            logger.info("mcp call %s failed (%s)", tool.name, error.reason)
            text = None
            if error.detail:
                text, _, _ = self._sealed(
                    error.detail.encode("utf-8"), resolved, source, cap
                )
            return ConnectorOutcome(
                "error", error.reason, text=text, secret_refs=resolved.names
            )
        except TimeoutError:
            logger.info("mcp call %s failed (connector_timeout)", tool.name)
            return ConnectorOutcome("error", "connector_timeout", secret_refs=resolved.names)
        except Exception as error:  # noqa: BLE001 -- 예외 문구에 풀린 값이 있을 수 있다
            logger.info("mcp call %s failed (%s)", tool.name, type(error).__name__)
            return ConnectorOutcome("error", "connector_unavailable", secret_refs=resolved.names)
        body, is_error = render_content(raw)
        text, truncated, original = self._sealed(body.encode("utf-8"), resolved, source, cap)
        return ConnectorOutcome(
            "error" if is_error else "ok",
            "connector_tool_error" if is_error else "ok",
            text=text,
            original_bytes=original,
            truncated=truncated,
            secret_refs=resolved.names,
        )


def build_connector_runner(catalog: ConnectorCatalog | None) -> ConnectorRunner | None:
    if catalog is None or not catalog.tools:
        return None
    return ConnectorRunner(catalog)


__all__ = [
    "CONNECTOR_FIX_NOTES",
    "ConnectorOutcome",
    "ConnectorRunner",
    "build_connector_runner",
    "pin_drift",
    "render_content",
]
