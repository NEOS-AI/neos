from neos.workflow.harness.task_dag import TaskDAG, TaskDAGNode


def test_ready_nodes_returns_only_dependency_satisfied_nodes():
    dag = TaskDAG(
        nodes=[
            TaskDAGNode(node_id="a", description="Collect sources"),
            TaskDAGNode(node_id="b", description="Write report", depends_on=["a"]),
        ]
    )

    assert [node.node_id for node in dag.ready_nodes()] == ["a"]

    dag.mark_done("a", artifact_ref="artifact://sources")

    assert [node.node_id for node in dag.ready_nodes()] == ["b"]


def test_rollback_subtree_resets_failed_node_and_descendants():
    dag = TaskDAG(
        nodes=[
            TaskDAGNode(node_id="a", description="Root"),
            TaskDAGNode(
                node_id="b",
                description="Child",
                parent_id="a",
                depends_on=["a"],
            ),
            TaskDAGNode(
                node_id="c",
                description="Grandchild",
                parent_id="b",
                depends_on=["b"],
            ),
        ]
    )
    dag.mark_done("a", artifact_ref="artifact://a")
    dag.mark_done("b", artifact_ref="artifact://b")
    dag.mark_done("c", artifact_ref="artifact://c")

    dag.rollback_subtree("b")

    assert dag.by_id("a").status == "done"
    assert dag.by_id("b").status == "pending"
    assert dag.by_id("c").status == "pending"
    assert dag.by_id("b").artifact_ref is None
    assert dag.by_id("c").rollback_generation == 1


def test_task_dag_records_failure_and_round_trips_state():
    dag = TaskDAG(
        nodes=[
            TaskDAGNode(node_id="a", description="Draft candidate"),
        ]
    )

    dag.mark_failed("a", error="gate_failed")
    dag.mark_done(
        "a",
        artifact_ref="artifact://candidate",
        harness_run_id="harness-run-1",
    )

    restored = TaskDAG.from_state(dag.to_state())
    node = restored.by_id("a")

    assert node.status == "done"
    assert node.attempts == 1
    assert node.metadata["error"] == "gate_failed"
    assert node.artifact_ref == "artifact://candidate"
    assert node.harness_run_id == "harness-run-1"
