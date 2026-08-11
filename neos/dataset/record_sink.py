"""LLM 호출 레코드의 내구 싱크 -- 만들어지는 순간 디스크에 남긴다.

영속화가 `graph.py` 의 `_auto_save_dataset()` 한 곳에서만 일어나던 것이
D1b 가 고친 문제다. Celery 워커와 deep-analysis job 서비스는 그 지점을
지나가지 않는 **별도 프로세스**이므로, 거기서 만들어진 레코드는 프로세스와
함께 사라졌다(로드맵 §11.1 장애물 ②).

배출구를 더 만드는 길 -- 워커 teardown, job 완료, `atexit` -- 은 택하지
않았다. 새 진입점이 생길 때마다 누군가 flush 를 기억해야 하고, 잊으면
조용히 사라진다. 이 저장소가 반복해서 다친 실패 모드가 정확히 그것이다.
대신 `add_record` 자체를 영속화 지점으로 만들어 **flush 라는 개념을
없앤다.**

설계 제약 셋:

- **동기 I/O.** `create_llm_call_record` 가 동기 함수라 sync 호출부(`invoke`)
  에서도 불린다. async 싱크였다면 그쪽에서 쓸 수 없다.
- **프로세스당 파일.** 잠금 없이 여러 워커가 동시에 쓴다. 파일명이 PID 를
  담으므로 어느 프로세스가 남긴 것인지도 남는다.
- **절대 던지지 않는다.** 수집 실패는 데이터 손실이지만, 예외를 올려보내면
  그 LLM 호출 자체가 죽는다. 계측이 본업을 막으면 안 된다.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import asdict, fields
from datetime import datetime
from pathlib import Path
from typing import Iterable, List

from .models import LLMCallRecord

logger = logging.getLogger(__name__)

_FIELD_NAMES = {f.name for f in fields(LLMCallRecord)}

# `save_jsonl()` 이 쓰는 데이터셋 산출물과 같은 뿌리 아래, 다른 디렉터리에
# 둔다. 저것은 "정리된 데이터셋"이고 이것은 "원시 수집분"이라 수명과 소비자가
# 다르다.
_RECORDS_DIRNAME = "records"


def records_root() -> Path:
    """원시 레코드가 쌓이는 디렉터리.

    경로는 설정(`dataset.base_path`)에서 온다 -- 설계 §1 의 "매직넘버 금지".
    설정을 못 읽어도 수집이 멈추면 안 되므로 기본값으로 떨어진다.
    """
    try:
        from neos.config.settings import settings

        base = settings.config.dataset.base_path
    except Exception:  # noqa: BLE001 - 설정 실패가 수집을 막지 않는다
        base = "datasets"
    return Path(base) / _RECORDS_DIRNAME


class RecordSink:
    """레코드 1건 = JSONL 1줄. 이 프로세스가 소유한 파일에 append 한다."""

    def __init__(self, base_path: Path | str) -> None:
        self.base_path = Path(base_path)
        # 날짜로 나눠 두면 오래된 것을 통째로 옮기거나 지우기 쉽다.
        day = datetime.now().strftime("%Y%m%d")
        name = f"{os.getpid()}-{uuid.uuid4().hex[:8]}.jsonl"
        self.path = self.base_path / day / name
        self._failed = False

    def append(self, record: LLMCallRecord) -> None:
        """한 줄 append. 실패해도 호출자에게 전파하지 않는다."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(asdict(record), ensure_ascii=False, default=str)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except Exception as exc:  # noqa: BLE001 - 계측은 본업을 막지 않는다
            if not self._failed:
                # 매 호출마다 로그를 쏟으면 진짜 신호가 묻힌다. 처음 한 번만.
                self._failed = True
                logger.warning(
                    "LLM call record sink unavailable (%s): %s",
                    type(exc).__name__,
                    self.path,
                )

    @classmethod
    def read_all(cls, base_path: Path | str) -> List[LLMCallRecord]:
        """어느 프로세스가 남겼든 전부 모아 읽는다.

        잘린 줄은 건너뛴다 -- 프로세스가 쓰다 죽으면 마지막 줄이 불완전할 수
        있고, 그 한 줄 때문에 앞의 멀쩡한 레코드를 잃을 이유가 없다.
        """
        records: List[LLMCallRecord] = []
        for path in sorted(Path(base_path).rglob("*.jsonl")):
            records.extend(cls._read_file(path))
        return records

    @staticmethod
    def _read_file(path: Path) -> Iterable[LLMCallRecord]:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            logger.warning("Unreadable record file %s: %s", path, exc)
            return []

        out: List[LLMCallRecord] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except ValueError:
                continue  # 잘린 마지막 줄
            if not isinstance(payload, dict):
                continue
            # 스키마가 나중에 넓어져도 옛 파일을 읽을 수 있어야 한다.
            known = {k: v for k, v in payload.items() if k in _FIELD_NAMES}
            try:
                out.append(LLMCallRecord(**known))
            except TypeError:
                continue
        return out
