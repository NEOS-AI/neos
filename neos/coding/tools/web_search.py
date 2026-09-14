"""Coding-loop web search. Tavily only; not the workflow MCP client."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

_TAVILY_URL = "https://api.tavily.com/search"
_SEARCH_BEGIN = "----- begin untrusted web search -----"
_SEARCH_END = "----- end untrusted web search -----"
_SEARCH_TOKEN = "untrusted web search"


class WebSearchError(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def neutralize_search_delimiters(text: str) -> str:
    return text.replace(_SEARCH_TOKEN, "untrusted-web-search")


def wrap_search_text(text: str) -> str:
    return f"{_SEARCH_BEGIN}\n{neutralize_search_delimiters(text)}\n{_SEARCH_END}"


def tavily_search(
    query: str,
    *,
    api_key: str,
    max_results: int,
    timeout_sec: float = 15,
) -> tuple[dict[str, object], ...]:
    payload = json.dumps(
        {
            "api_key": api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        _TAVILY_URL,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            body = response.read()
            status = int(getattr(response, "status", 200) or 200)
    except TimeoutError as error:
        raise WebSearchError("sandbox_timeout") from error
    except urllib.error.HTTPError as error:
        if error.code in {401, 403}:
            raise WebSearchError("policy_web_search_unconfigured") from error
        raise WebSearchError("web_search_failed") from error
    except urllib.error.URLError as error:
        reason = error.reason
        if isinstance(reason, TimeoutError):
            raise WebSearchError("sandbox_timeout") from error
        raise WebSearchError("web_search_failed") from error
    if status != 200:
        raise WebSearchError("web_search_failed")
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise WebSearchError("web_search_failed") from error
    raw_results = parsed.get("results")
    if not isinstance(raw_results, list):
        return ()
    results: list[dict[str, object]] = []
    for item in raw_results[:max_results]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        title = neutralize_search_delimiters(str(item.get("title") or ""))
        snippet = neutralize_search_delimiters(str(item.get("content") or ""))
        results.append(
            {
                "title": title,
                "url": url,
                "snippet": wrap_search_text(snippet),
            }
        )
    return tuple(results)
