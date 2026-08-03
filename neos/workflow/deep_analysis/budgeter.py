"""예산 기반 선택 + 정지 판단. 원 설계 §6.2. 상태(aging/라운드)는 인메모리(D1)."""
from __future__ import annotations

from neos.config.settings import settings

from .models import Effort
from .token_budget import TokenBudget


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
        token_budget: TokenBudget | None = None,
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
        self.token_budget = token_budget
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

    async def base_score(self, ledger, question) -> float:
        """설계 §6.2 점수의 aging 제외 항: value_est×(1−conf)×gain_decay.

        질문의 '남은 실제 가치'를 나타낸다. 정지 판단(should_stop)은 이
        값만 본다 — aging은 기아 방지용 선택 우선순위 신호일 뿐이며(D1/D20),
        정지 조건에 섞이면 미선택 질문의 aging 누적만으로 score_floor를
        영원히 넘겨 조기 정지가 무력화되기 때문이다.
        """
        history = await ledger.gain_history(question.id, last_n=3)
        return (
            question.value_est
            * (1.0 - question.confidence)
            * self.gain_decay(history)
        )

    async def score(self, ledger, question) -> float:
        return await self.base_score(ledger, question) + self.aging(
            question.id
        )

    def ladder(self, question) -> Effort:
        if question.fail_streak >= 2:
            return Effort.SPLIT
        if question.spent_tokens >= question.cap_tokens:
            return Effort.SPLIT
        if question.confidence < 0.3 and question.spent_tokens > 0:
            return Effort.DIG
        return Effort.SCOUT

    async def select(self, ledger, k: int | None = None):
        k = self.parallel_workers if k is None else k
        self._round += 1
        open_questions = await ledger.open_questions()
        if not open_questions:
            return []

        # 첫 라운드: breadth pass (루트 직계 자식 전원 SCOUT, 30% 한도 내)
        if self._round == 1:
            spent = await ledger.total_spent()
            if spent < self.breadth_pass_ratio * self.global_token_cap:
                root = await ledger.root_question()
                children = await ledger.children(root.id) if root else []
                open_ids = {q.id for q in open_questions}
                breadth = [q for q in children if q.id in open_ids]
                if breadth:
                    for q in breadth:
                        self._last_selected[q.id] = self._round
                    return [(q, Effort.SCOUT) for q in breadth]

        scored = [(await self.score(ledger, q), q) for q in open_questions]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        chosen = [q for _score, q in scored[:k]]
        picks = []
        for q in chosen:
            self._last_selected[q.id] = self._round
            picks.append((q, self.ladder(q)))
        return picks

    async def should_stop(self, ledger) -> bool:
        if self.token_budget is not None:
            # The floor belongs to finalization. Investigation is done once it
            # is all that remains -- continuing only produces refused
            # reservations and wasted rounds.
            if self.token_budget.available_for_investigation <= 0:
                return True
        spent = await ledger.total_spent()
        if spent >= self.global_token_cap:
            return True
        open_questions = await ledger.open_questions()
        if not open_questions:
            return True
        # D20: 정지 판단은 base_score(aging 제외)로 한다. aging을 포함하면
        # 미선택 질문의 라운드 누적만으로 floor를 넘겨 조기 정지가 사실상
        # 발동 불가가 된다(aging_per_round == score_floor == 0.05).
        for q in open_questions:
            if (await self.base_score(ledger, q)) >= self.score_floor:
                return False
        return True
