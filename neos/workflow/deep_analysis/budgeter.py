"""예산 기반 선택 + 정지 판단. 원 설계 §6.2. 상태(aging/라운드)는 인메모리(D1)."""
from __future__ import annotations

from neos.config.settings import settings

from .models import Effort


class Budgeter:
    def __init__(
        self,
        *,
        score_floor: float | None = None,
        aging_per_round: float | None = None,
        breadth_pass_ratio: float | None = None,
        global_token_cap: int | None = None,
        max_depth: int | None = None,
        parallel_workers: int | None = None,
    ) -> None:
        config = settings.config.deep_analysis
        self.score_floor = config.score_floor if score_floor is None else score_floor
        self.aging_per_round = (
            config.aging_per_round if aging_per_round is None else aging_per_round
        )
        self.breadth_pass_ratio = (
            config.breadth_pass_ratio if breadth_pass_ratio is None else breadth_pass_ratio
        )
        self.global_token_cap = (
            settings.DEEP_ANALYSIS_GLOBAL_TOKEN_CAP
            if global_token_cap is None
            else global_token_cap
        )
        self.max_depth = config.max_depth if max_depth is None else max_depth
        self.parallel_workers = (
            config.parallel_workers if parallel_workers is None else parallel_workers
        )
        self._round = 0
        self._last_selected: dict[str, int] = {}

    def gain_decay(self, counts: list[int]) -> float:
        if not counts:
            return 1.0
        g = sum(counts) / len(counts)
        if g >= 2:
            return 1.0
        if g >= 1:
            return 0.6
        return 0.3

    def aging(self, question_id: str) -> float:
        last = self._last_selected.get(question_id)
        elapsed = self._round if last is None else (self._round - last)
        return elapsed * self.aging_per_round

    async def score(self, ledger, question) -> float:
        history = await ledger.gain_history(question.id, last_n=3)
        base = question.value_est * (1.0 - question.confidence) * self.gain_decay(history)
        return base + self.aging(question.id)

    def ladder(self, question) -> Effort:
        if question.fail_streak >= 2:
            return Effort.SPLIT
        if question.spent_tokens >= question.cap_tokens:
            return Effort.SPLIT
        if question.confidence < 0.3 and question.spent_tokens > 0:
            return Effort.DIG
        return Effort.SCOUT

    async def select(self, ledger, k: int = 1):
        questions = await ledger.open_questions()
        return [
            (question, Effort.SCOUT)
            for question in questions[:k]
        ]

    def should_stop(
        self,
        spent: int,
        cap: int,
        picks: list,
    ) -> bool:
        return spent >= cap or not picks

