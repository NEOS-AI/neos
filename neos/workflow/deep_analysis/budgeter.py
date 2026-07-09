"""M1 budgeter stub: sequential SCOUT selection only."""

from .models import Effort


class Budgeter:
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

