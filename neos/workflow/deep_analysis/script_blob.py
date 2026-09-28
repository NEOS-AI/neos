"""워커 스크립트를 원장 blob 으로 (J1.5, 계약 §4 `script_ref`).

스크립트도 원장 blob 이다 -- 재실행이 그 바이트를 읽어야 한다. 그런데 blob
테이블에는 fetch 한 원문과 **같은 모양**으로 앉는다. 표시가 없으면 워커가 자기
스크립트를 quote 클레임의 증거로 인용하거나 계산의 `inputs` 에 넣어 통과시킬
수 있다 -- "워커가 쓴 파일은 증거가 될 수 없다"(I4)가 무너지는 자리다. 그래서
URL 머리로 표시하고 두 채점기가 그것을 본다.

**왜 `fetch.py` 가 아닌가.** 채점기가 이 판별을 import 한다. `fetch.py` 는
httpx·trafilatura·설정을 끌고 오고, 채점기는 "네트워크도 샌드박스도 모른다"
(`graders/computed.py`). 판별은 의존이 없어야 한다.
"""

from __future__ import annotations

from .models import ProposedBlob

SCRIPT_URL_SCHEME = "sandbox-script://"


def script_blob(text: str, *, question_id: str, path: str) -> ProposedBlob:
    """워커 스크립트 하나를 원장 blob 제안으로.

    주소는 fetch 와 **같은 함수**다 -- `script_ref` 는 `inputs` 의 raw_ref 와
    같은 폭이어야 한다(계약 §4, VARCHAR(16)). 같은 바이트의 원문 blob 이 먼저
    있으면 `_store_blob` 이 그 행을 남기고 이 표시는 붙지 않는다. 바이트가
    같으므로 재실행도 같고, 그 행은 실제로 fetch 한 원문이다.
    """
    from .fetch import _content_hash

    return ProposedBlob(
        content_hash=_content_hash(text),
        source_url=f"{SCRIPT_URL_SCHEME}{question_id}/{path}",
        http_status=200,
        raw_text=text,
    )


def is_script_blob(blob: object) -> bool:
    """원장 행(`DABlob.url`)이든 제안(`source_url`)이든 읽는다."""
    url = getattr(blob, "url", None) or getattr(blob, "source_url", None) or ""
    return str(url).startswith(SCRIPT_URL_SCHEME)
