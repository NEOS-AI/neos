from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Protocol

from neos.config.settings import settings
from neos.utils.llm_factory import create_llm
from neos.utils.llm_wrapper import extract_text_from_response


class HarnessModelJudge(Protocol):
    async def judge(self, prompt: str, *, timeout_seconds: float) -> dict[str, Any]:
        raise NotImplementedError


class LangChainHarnessModelJudge:
    def __init__(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        self.provider = provider
        self.model = model

    async def judge(self, prompt: str, *, timeout_seconds: float) -> dict[str, Any]:
        provider = self.provider or settings.RESEARCH_HARNESS_MODEL_CHECK_PROVIDER or None
        model = self.model or settings.RESEARCH_HARNESS_MODEL_CHECK_MODEL or None
        llm = create_llm(
            provider=provider,
            model=model,
            temperature=0.0,
        )
        response = await asyncio.wait_for(
            llm.ainvoke(prompt),
            timeout=timeout_seconds,
        )
        return parse_judge_json(extract_text_from_response(response))


def parse_judge_json(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(_extract_json_object(raw))
    except Exception as exc:
        return _failed_payload(f"Model judge returned invalid JSON: {exc}")
    if not isinstance(payload, dict):
        return _failed_payload("Model judge returned a non-object JSON payload.")
    return _normalize_payload(payload)


def build_factuality_prompt(
    *,
    report: str,
    sources: list[dict[str, Any]],
    claims: list[str],
) -> str:
    source_lines = []
    for source in sources:
        source_id = source.get("id") or source.get("source_id") or "unknown"
        title = source.get("title") or "Untitled source"
        url = source.get("url") or ""
        content = source.get("content") or source.get("snippet") or source.get("summary") or ""
        source_lines.append(
            f"[{source_id}] {title}\nURL: {url}\nSnippet: {str(content)[:1200]}"
        )

    return (
        "You are judging factual support for a research report. "
        "Compare the sampled claims against the provided source snippets. "
        "Return only JSON with keys: score, passed, failed_items, evidence, summary.\n\n"
        f"Sampled claims:\n{json.dumps(claims, ensure_ascii=False, indent=2)}\n\n"
        f"Sources:\n{chr(10).join(source_lines)}\n\n"
        f"Report:\n{report[:6000]}"
    )


def build_bias_perspective_prompt(
    *,
    report: str,
    sources: list[dict[str, Any]],
    high_risk_categories: list[str],
) -> str:
    source_summaries = []
    for source in sources:
        source_summaries.append(
            {
                "id": source.get("id") or source.get("source_id"),
                "title": source.get("title"),
                "domain": source.get("domain") or source.get("url"),
                "source_type": source.get("source_type"),
            }
        )
    return (
        "You are judging perspective balance for a research report. "
        "Check for overreliance on one perspective, missing counterarguments, "
        "loaded framing, and stakeholder diversity. Return only JSON with keys: "
        "score, passed, failed_items, evidence, summary.\n\n"
        f"High-risk categories: {json.dumps(high_risk_categories, ensure_ascii=False)}\n"
        f"Sources: {json.dumps(source_summaries, ensure_ascii=False, indent=2)}\n\n"
        f"Report:\n{report[:6000]}"
    )


def _extract_json_object(raw: str) -> str:
    text = str(raw or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    score = payload.get("score", 0.0)
    try:
        score = max(0.0, min(1.0, float(score)))
    except (TypeError, ValueError):
        score = 0.0
    failed_items = payload.get("failed_items") if isinstance(payload.get("failed_items"), list) else []
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), list) else []
    passed = bool(payload.get("passed")) and not failed_items
    return {
        "score": score,
        "passed": passed,
        "failed_items": failed_items,
        "evidence": evidence,
        "summary": str(payload.get("summary") or "Model judge completed."),
    }


def _failed_payload(summary: str) -> dict[str, Any]:
    return {
        "score": 0.0,
        "passed": False,
        "failed_items": [{"reason": summary}],
        "evidence": [],
        "summary": summary,
    }
