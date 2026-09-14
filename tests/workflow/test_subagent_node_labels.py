"""트랙 I GS5 -- 템플릿 노드와 진행 라벨의 짝을 **양방향으로** 건다.

트랙 C 의 fixture+AST 대조는 심층분석 원장 kind 전용이다. 설계된 그래프에서 화면에
닿는 표면은 `on_node_start(step_name=get_node_label(node))` 이고, 스트림 핸들러가 그
값을 `step_name` 으로 싣는다. 라벨이 빠지면 조용히 노드 이름의 title-case 가 나간다 --
FE1 이 이벤트 8종에서 겪은 "라벨이 따라오지 않는" 실패의 이 경로판이다.

한 방향만 걸면 면제가 조용히 낡는다: 템플릿을 지워도 라벨이 남아 있으면 아무도 모른다.
"""

from neos.workflow.enums import WorkflowNode
from neos.workflow.events import NODE_LABELS, get_node_label
from neos.workflow.subagent_nodes import SUBAGENT_NODE_TEMPLATES


def test_every_registered_template_has_its_own_label() -> None:
    for name, template in SUBAGENT_NODE_TEMPLATES.items():
        assert NODE_LABELS.get(name) == template.label, (
            f"{name}: NODE_LABELS 에 템플릿 라벨 '{template.label}' 이 없거나 다르다"
        )
        assert get_node_label(name) != name.replace("_", " ").title()


def test_every_label_belongs_to_a_static_node_or_a_registered_template() -> None:
    known = {node.value for node in WorkflowNode} | set(SUBAGENT_NODE_TEMPLATES)
    orphans = sorted(set(NODE_LABELS) - known)
    assert orphans == [], f"노드도 템플릿도 아닌 라벨: {orphans}"


def test_template_labels_do_not_shadow_static_labels() -> None:
    static = {node.value for node in WorkflowNode}
    assert not set(SUBAGENT_NODE_TEMPLATES) & static
