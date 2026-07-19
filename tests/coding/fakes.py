from typing import Any


class InMemoryCodingRunRepository:
    def __init__(self, *, completed_tools=None, active_run=None) -> None:
        self.completed_tools = dict(completed_tools or {})
        self.active_run = active_run
        self.checkpoints = []
        self.tool_execution_calls = []
        self.created_runs = []
        self.interrupt_calls = []
        self.applied_steering = []
        self.steering_requests = []

    async def create_run(self, run) -> None:
        self.created_runs.append(run)
        self.active_run = run

    async def latest_run(self, task_id: str):
        if self.active_run is None or self.active_run.task_id != task_id:
            return None
        return self.active_run

    async def save_checkpoint(self, checkpoint) -> None:
        if not any(
            existing.checkpoint_id == checkpoint.checkpoint_id
            for existing in self.checkpoints
        ):
            self.checkpoints.append(checkpoint)

    async def latest_checkpoint(self, task_id: str):
        matches = [item for item in self.checkpoints if item.task_id == task_id]
        return max(matches, key=lambda item: item.seq, default=None)

    async def completed_tool_result(self, task_id: str, tool_call_id: str):
        return self.completed_tools.get((task_id, tool_call_id)) or (
            self.completed_tools.get(tool_call_id)
        )

    async def record_tool_result(self, **record: Any) -> None:
        self.tool_execution_calls.append(record)
        key = (record["task_id"], record["tool_call_id"])
        self.completed_tools.setdefault(key, record["result"])

    async def queue_steering(self, request) -> None:
        self.steering_requests.append(request)

    async def claim_pending_steering(self, task_id: str):
        for request in self.steering_requests:
            if request.task_id == task_id and request not in self.applied_steering:
                return request
        return None
