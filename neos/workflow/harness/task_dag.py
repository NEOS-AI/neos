from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class TaskDAGNode:
    node_id: str
    description: str
    parent_id: str | None = None
    status: str = "pending"
    attempts: int = 0
    depends_on: list[str] = field(default_factory=list)
    artifact_ref: str | None = None
    harness_run_id: str | None = None
    rollback_generation: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TaskDAG:
    nodes: list[TaskDAGNode] = field(default_factory=list)

    def by_id(self, node_id: str) -> TaskDAGNode:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        raise KeyError(node_id)

    def ready_nodes(self) -> list[TaskDAGNode]:
        done = {node.node_id for node in self.nodes if node.status == "done"}
        return [
            node
            for node in self.nodes
            if node.status == "pending"
            and all(dependency in done for dependency in node.depends_on)
        ]

    def mark_done(
        self,
        node_id: str,
        *,
        artifact_ref: str | None = None,
        harness_run_id: str | None = None,
    ) -> None:
        node = self.by_id(node_id)
        node.status = "done"
        node.artifact_ref = artifact_ref
        node.harness_run_id = harness_run_id

    def mark_failed(self, node_id: str, *, error: str) -> None:
        node = self.by_id(node_id)
        node.status = "failed"
        node.attempts += 1
        node.metadata["error"] = error

    def rollback_subtree(self, node_id: str) -> None:
        targets = {node_id}
        changed = True
        while changed:
            changed = False
            for node in self.nodes:
                if node.parent_id in targets and node.node_id not in targets:
                    targets.add(node.node_id)
                    changed = True

        for target in targets:
            node = self.by_id(target)
            node.status = "pending"
            node.artifact_ref = None
            node.harness_run_id = None
            node.rollback_generation += 1

    def to_state(self) -> dict[str, Any]:
        return {"nodes": [node.to_dict() for node in self.nodes]}

    @classmethod
    def from_state(cls, state: dict[str, Any] | None) -> TaskDAG:
        if not state:
            return cls()
        return cls(
            nodes=[
                TaskDAGNode(**item)
                for item in state.get("nodes", [])
            ]
        )
