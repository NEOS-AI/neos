"""M4 Task 1: node-level reduce -> NodeSummary (bounded per-node context)."""

import pytest
from types import SimpleNamespace
from neos.workflow.deep_analysis.synthesizer import Synthesizer
from neos.workflow.deep_analysis.models import NodeSummary

pytestmark = pytest.mark.no_db


class CapturingJSON:
    """call_json 대체: 프롬프트를 캡처하고 스크립트된 NodeSummary dict 반환."""

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.prompts = []

    async def __call__(self, model, prompt, **kw):
        self.prompts.append(prompt)
        data = self.payloads.pop(0)
        return data, SimpleNamespace(input_tokens=len(prompt) // 4, output_tokens=10)


class FakeLedger:
    def __init__(self, verified):
        self._verified = verified  # {qid: [(claim, [ev])]}
        self.logged = []

    async def verified_claims(self, qid):
        return self._verified.get(qid, [])

    async def log(self, *a, **k):
        self.logged.append((a, k))


class TreeFakeLedger(FakeLedger):
    """FakeLedger + a fixed tree shape for reduce_tree tests.

    tree: {qid: [child_qid, ...]} -- adjacency list.
    statuses: {qid: status}; defaults to "resolved" if unset.
    """

    def __init__(self, verified, tree, statuses=None):
        super().__init__(verified)
        self._tree = tree
        self._statuses = dict(statuses or {})

    async def children(self, qid):
        return [
            SimpleNamespace(
                id=cid, status=self._statuses.get(cid, "resolved")
            )
            for cid in self._tree.get(qid, [])
        ]

    async def get_question(self, qid):
        if qid not in self._tree and qid not in self._statuses:
            return None
        return SimpleNamespace(
            id=qid,
            text=qid,
            status=self._statuses.get(qid, "resolved"),
        )


def _claim(cid, text):
    return SimpleNamespace(id=cid, text=text, confidence=0.7)


def _ev(excerpt):
    return SimpleNamespace(excerpt=excerpt, source_url="http://x")


async def test_reduce_node_uses_only_own_claims_and_child_answers():
    q = SimpleNamespace(id="n1", text="Q", status="open", value_est=0.8)
    child = NodeSummary(
        question_id="c1",
        answer="child ans [C:cccccccc]",
        key_claim_ids=["cccccccc"],
        confidence=0.7,
        caveats=[],
        conflicts=[],
    )
    led = FakeLedger({"n1": [(_claim("aaaaaaaa", "own claim"), [_ev("own excerpt")])]})
    cj = CapturingJSON(
        [
            {
                "question_id": "n1",
                "answer": "ans [C:aaaaaaaa]",
                "key_claim_ids": ["aaaaaaaa"],
                "confidence": 0.8,
                "caveats": [],
                "conflicts": [],
            }
        ]
    )
    synth = Synthesizer(led, json_call=cj)
    summary = await synth.reduce_node(q, [child])
    assert isinstance(summary, NodeSummary) and summary.question_id == "n1"
    p = cj.prompts[0]
    assert "own excerpt" in p  # 자기 클레임 excerpt 포함
    assert "child ans" in p  # 자식 answer 포함
    # 자식의 원시 클레임 텍스트는 넣지 않는다(요약 answer만) — child에는 raw 클레임이 없음
    assert summary.answer == "ans [C:aaaaaaaa]"
    assert summary.confidence == 0.8
    assert summary.key_claim_ids == ["aaaaaaaa"]


async def test_reduce_node_logs_node_summary_event_with_prompt_size():
    q = SimpleNamespace(id="n1", text="Q", status="open", value_est=0.8)
    led = FakeLedger({"n1": [(_claim("aaaaaaaa", "own claim"), [_ev("own excerpt")])]})
    cj = CapturingJSON(
        [
            {
                "question_id": "n1",
                "answer": "ans [C:aaaaaaaa]",
                "key_claim_ids": ["aaaaaaaa"],
                "confidence": 0.8,
                "caveats": [],
                "conflicts": [],
            }
        ]
    )
    synth = Synthesizer(led, json_call=cj)
    await synth.reduce_node(q, [])
    assert len(led.logged) == 1
    args, kwargs = led.logged[0]
    assert args[0] == "node_summary"
    assert args[1] == "n1"
    payload = args[2]
    assert "input_tokens" in payload
    assert "prompt_chars" in payload


async def test_reduce_node_uses_the_injected_ceiling():
    """§7: 세 호출부(assemble/reduce/reduce_node) 모두 주입된 상한을 써야 한다.

    `assemble`만 검증되어 있었다. `reduce_node`가 여전히 전역 설정을 직접
    읽는 회귀는 dev 프로파일의 finalization floor 산식(§4.2, 4,400)이 실제로
    쓰는 상한과 어긋난다 -- floor는 주입된 1,200을 가정하고 계산됐다.
    """
    q = SimpleNamespace(id="n1", text="Q", status="open", value_est=0.8)
    led = FakeLedger({"n1": []})
    seen = []

    async def recording_json_call(model, prompt, **kw):
        seen.append(kw["max_tokens"])
        return (
            {
                "question_id": "n1",
                "answer": "ans",
                "key_claim_ids": [],
                "confidence": 0.5,
                "caveats": [],
                "conflicts": [],
            },
            SimpleNamespace(input_tokens=10, output_tokens=10),
        )

    synth = Synthesizer(
        led, json_call=recording_json_call, synthesis_max_tokens=1200
    )
    await synth.reduce_node(q, [])

    assert seen == [1200]


async def test_reduce_node_split_question_uses_only_child_summaries():
    """자기 클레임이 없는 split 질문: child_summaries만으로 answer."""
    q = SimpleNamespace(id="n2", text="split Q", status="open", value_est=0.5)
    child = NodeSummary(
        question_id="c1",
        answer="child ans only",
        key_claim_ids=[],
        confidence=0.6,
        caveats=[],
        conflicts=[],
    )
    led = FakeLedger({})  # no verified claims for n2
    cj = CapturingJSON(
        [
            {
                "question_id": "n2",
                "answer": "combined [C:cccccccc]",
                "key_claim_ids": [],
                "confidence": 0.6,
                "caveats": [],
                "conflicts": [],
            }
        ]
    )
    synth = Synthesizer(led, json_call=cj)
    summary = await synth.reduce_node(q, [child])
    p = cj.prompts[0]
    assert "child ans only" in p
    assert "(없음)" in p  # own verified_claims block is empty
    assert summary.answer == "combined [C:cccccccc]"


async def test_reduce_node_parse_failure_falls_back_without_crashing():
    q = SimpleNamespace(id="n1", text="Q", status="open", value_est=0.8)
    child1 = NodeSummary(
        question_id="c1", answer="answer one", key_claim_ids=[], confidence=0.5,
        caveats=[], conflicts=[],
    )
    child2 = NodeSummary(
        question_id="c2", answer="answer two", key_claim_ids=[], confidence=0.5,
        caveats=[], conflicts=[],
    )

    class RaisingJSON:
        async def __call__(self, model, prompt, **kw):
            raise ValueError("boom: unparseable JSON")

    led = FakeLedger({"n1": [(_claim("aaaaaaaa", "own claim"), [_ev("own excerpt")])]})
    synth = Synthesizer(led, json_call=RaisingJSON())
    summary = await synth.reduce_node(q, [child1, child2])
    assert isinstance(summary, NodeSummary)
    assert summary.confidence == 0.0
    assert "node_summary_unparseable" in summary.caveats
    assert "answer one" in summary.answer
    assert "answer two" in summary.answer


async def test_reduce_node_parses_conflicts():
    q = SimpleNamespace(id="n1", text="Q", status="open", value_est=0.8)
    led = FakeLedger({"n1": [(_claim("aaaaaaaa", "own claim"), [_ev("own excerpt")])]})
    cj = CapturingJSON(
        [
            {
                "question_id": "n1",
                "answer": "ans [C:aaaaaaaa]",
                "key_claim_ids": ["aaaaaaaa"],
                "confidence": 0.5,
                "caveats": [],
                "conflicts": [
                    {"claim_a": "aaaaaaaa", "claim_b": "bbbbbbbb", "nature": "수치 불일치"}
                ],
            }
        ]
    )
    synth = Synthesizer(led, json_call=cj)
    summary = await synth.reduce_node(q, [])
    assert len(summary.conflicts) == 1
    assert summary.conflicts[0].claim_a == "aaaaaaaa"
    assert summary.conflicts[0].nature == "수치 불일치"


# --- M4 Task 2: reduce_tree (hierarchical post-order) -----------------


def _payload(qid, answer):
    return {
        "question_id": qid,
        "answer": answer,
        "key_claim_ids": [],
        "confidence": 0.7,
        "caveats": [],
        "conflicts": [],
    }


async def test_reduce_tree_reduces_leaves_before_parents_post_order():
    """root -> child -> grandchild: all three get summarized bottom-up."""
    tree = {"root": ["child"], "child": ["gc"], "gc": []}
    verified = {
        "gc": [(_claim("aaaaaaaa", "leaf claim"), [_ev("leaf excerpt")])],
    }
    led = TreeFakeLedger(verified, tree)
    cj = CapturingJSON(
        [
            _payload("gc", "leaf ans [C:aaaaaaaa]"),
            _payload("child", "child ans"),
            _payload("root", "root ans"),
        ]
    )
    synth = Synthesizer(led, json_call=cj)
    summaries = await synth.reduce_tree("root")

    assert set(summaries) == {"root", "child", "gc"}
    # leaf reduced first (its prompt is captured before child's)
    assert "leaf excerpt" in cj.prompts[0]
    # child's prompt carries the leaf's *summary answer*, not raw claims
    assert "leaf ans" in cj.prompts[1]
    assert "leaf excerpt" not in cj.prompts[1]
    # root's prompt carries the child's summary answer only
    assert "child ans" in cj.prompts[2]
    assert summaries["root"].answer == "root ans"


async def test_reduce_tree_excludes_abandoned_children_from_parent_context():
    tree = {"root": ["good", "bad"], "good": [], "bad": []}
    statuses = {"bad": "abandoned"}
    verified = {
        "good": [(_claim("aaaaaaaa", "good claim"), [_ev("good excerpt")])],
    }
    led = TreeFakeLedger(verified, tree, statuses)
    cj = CapturingJSON(
        [
            _payload("good", "good ans"),
            _payload("root", "root ans"),
        ]
    )
    synth = Synthesizer(led, json_call=cj)
    summaries = await synth.reduce_tree("root")

    assert "bad" not in summaries
    assert "good" in summaries and "root" in summaries
    # root prompt must not mention the abandoned sibling at all
    root_prompt = cj.prompts[-1]
    assert "bad" not in root_prompt


async def test_reduce_tree_skips_summary_when_root_itself_abandoned():
    """Children are still visited (post-order visits before the self-status
    check), but the abandoned node itself gets no summary."""
    tree = {"root": ["child"], "child": []}
    statuses = {"root": "abandoned"}
    verified = {
        "child": [(_claim("aaaaaaaa", "c claim"), [_ev("c excerpt")])],
    }
    led = TreeFakeLedger(verified, tree, statuses)
    cj = CapturingJSON([_payload("child", "child ans")])
    synth = Synthesizer(led, json_call=cj)
    summaries = await synth.reduce_tree("root")

    assert "root" not in summaries
    assert "child" in summaries


async def test_grandparent_prompt_independent_of_grandchildren_count():
    """AC-a: root's reduce_node prompt is bounded regardless of how many
    grandchildren live under its single child, because root only ever
    sees the child's fixed-shape NodeSummary.answer -- never grandchild
    raw claims or excerpts.
    """

    async def run_tree(num_grandchildren):
        grandchild_ids = [f"g{i}" for i in range(num_grandchildren)]
        tree = {"root": ["child"], "child": grandchild_ids}
        for gid in grandchild_ids:
            tree[gid] = []

        verified = {}
        for i, gid in enumerate(grandchild_ids):
            verified[gid] = [
                (
                    _claim(f"{i:08d}", f"grandchild claim content {i}"),
                    [_ev(f"UNIQUE_GRANDCHILD_EXCERPT_{i}")],
                )
            ]

        led = TreeFakeLedger(verified, tree)
        payloads = [_payload(gid, f"g{i} summary") for i, gid in enumerate(grandchild_ids)]
        # child's answer is a FIXED-length summary regardless of how many
        # grandchildren fed into it -- this is what keeps root's context
        # bounded.
        payloads.append(_payload("child", "CHILD_FIXED_LENGTH_SUMMARY_TOKEN"))
        payloads.append(_payload("root", "root ans"))

        cj = CapturingJSON(payloads)
        synth = Synthesizer(led, json_call=cj)
        summaries = await synth.reduce_tree("root")
        return led, cj, summaries

    led_a, cj_a, summaries_a = await run_tree(1)
    led_b, cj_b, summaries_b = await run_tree(5)

    root_prompt_a = cj_a.prompts[-1]
    root_prompt_b = cj_b.prompts[-1]

    # Robust assertion: root's prompt never contains any grandchild-level
    # content (raw excerpts or per-grandchild summary text), in either tree.
    for i in range(5):
        assert f"UNIQUE_GRANDCHILD_EXCERPT_{i}" not in root_prompt_a
        assert f"UNIQUE_GRANDCHILD_EXCERPT_{i}" not in root_prompt_b
        assert f"g{i} summary" not in root_prompt_a
        assert f"g{i} summary" not in root_prompt_b

    # Tight-band assertion: root prompt size does not grow with grandchild
    # count -- it only depends on the child's constant-length answer, so
    # the two prompts should be (near-)identical in length.
    assert abs(len(root_prompt_a) - len(root_prompt_b)) <= 5

    # Sanity: both trees actually completed full bottom-up reduction.
    assert "root" in summaries_a and "child" in summaries_a and "g0" in summaries_a
    assert "root" in summaries_b
    assert all(f"g{i}" in summaries_b for i in range(5))

    # Cross-check via the logged node_summary event's prompt_chars for the
    # root node in each run (same signal the plan calls out).
    def _root_prompt_chars(led):
        for args, _kwargs in led.logged:
            if args[0] == "node_summary" and args[1] == "root":
                return args[2]["prompt_chars"]
        raise AssertionError("no node_summary event logged for root")

    chars_a = _root_prompt_chars(led_a)
    chars_b = _root_prompt_chars(led_b)
    assert abs(chars_a - chars_b) <= 5


# --- M4 final review fix wave: malformed-JSON / cycle guards ----------


async def test_reduce_node_null_confidence_degrades_gracefully():
    """A well-formed JSON response with confidence: null must not crash
    reduce_node -- float(None) would raise TypeError if unguarded."""
    q = SimpleNamespace(id="n1", text="Q", status="open", value_est=0.8)
    led = FakeLedger({"n1": [(_claim("aaaaaaaa", "own claim"), [_ev("own excerpt")])]})
    cj = CapturingJSON(
        [
            {
                "question_id": "n1",
                "answer": "ans [C:aaaaaaaa]",
                "key_claim_ids": ["aaaaaaaa"],
                "confidence": None,
                "caveats": [],
                "conflicts": [],
            }
        ]
    )
    synth = Synthesizer(led, json_call=cj)
    summary = await synth.reduce_node(q, [])
    assert isinstance(summary, NodeSummary)
    assert summary.confidence == 0.0
    assert summary.answer == "ans [C:aaaaaaaa]"


async def test_reduce_node_malformed_conflict_entry_is_skipped():
    """A conflicts entry with an extra/unexpected key must not crash
    reduce_node -- ConflictNote(**c) would raise TypeError if unguarded,
    but explicit-kwarg construction tolerates it and still produces a
    valid ConflictNote. A conflicts entry MISSING a required key (e.g.
    claim_b) must be skipped rather than crashing the whole node."""
    q = SimpleNamespace(id="n1", text="Q", status="open", value_est=0.8)
    led = FakeLedger({"n1": [(_claim("aaaaaaaa", "own claim"), [_ev("own excerpt")])]})
    cj = CapturingJSON(
        [
            {
                "question_id": "n1",
                "answer": "ans [C:aaaaaaaa]",
                "key_claim_ids": ["aaaaaaaa"],
                "confidence": 0.5,
                "caveats": [],
                "conflicts": [
                    {
                        "claim_a": "aaaaaaaa",
                        "claim_b": "bbbbbbbb",
                        "nature": "수치 불일치",
                        "unexpected_extra_key": "boom",
                    },
                    {"claim_a": "cccccccc"},  # missing claim_b -- skipped
                ],
            }
        ]
    )
    synth = Synthesizer(led, json_call=cj)
    summary = await synth.reduce_node(q, [])
    assert isinstance(summary, NodeSummary)
    # extra-key entry tolerated and parsed; missing-key entry skipped --
    # no exception raised either way.
    assert len(summary.conflicts) == 1
    assert summary.conflicts[0].claim_a == "aaaaaaaa"
    assert summary.conflicts[0].claim_b == "bbbbbbbb"
    assert summary.confidence == 0.5


class BackEdgeTreeLedger(FakeLedger):
    """A ledger whose `children` reports a back-edge: one node's child
    points back to an ancestor, forming a cycle in the question tree."""

    async def children(self, qid):
        # root -> child -> root (cycle)
        edges = {"root": ["child"], "child": ["root"]}
        return [
            SimpleNamespace(id=cid, status="resolved")
            for cid in edges.get(qid, [])
        ]

    async def get_question(self, qid):
        return SimpleNamespace(id=qid, text=qid, status="resolved")


async def test_reduce_tree_terminates_on_back_edge_cycle():
    """A cyclic question tree (child points back to an ancestor) must not
    cause unbounded recursion / RecursionError."""
    verified = {}
    led = BackEdgeTreeLedger(verified)
    # Post-order: "child" is fully reduced (its back-edge to "root" is
    # skipped since "root" is already in `visited`) before "root" itself.
    cj = CapturingJSON([_payload("child", "child ans"), _payload("root", "root ans")])
    synth = Synthesizer(led, json_call=cj)
    summaries = await synth.reduce_tree("root")
    assert "root" in summaries
    assert "child" in summaries


def _logged(ledger, kind):
    """kind 로 이벤트를 고른다. 인덱스로 고르면 안 된다 -- `reduce_node` 는
    절삭이 발동하면 `finalization_prompt_clamped` 를 먼저 남기므로 0번이
    상황에 따라 다른 이벤트가 된다."""
    for args, _kwargs in ledger.logged:
        if args[0] == kind:
            return args[2]
    raise AssertionError(f"{kind} 이벤트가 없다: {[a[0][0] for a in ledger.logged]}")


# --- CITE1: 리덕션 층이 마커를 몇 개 실어 올렸는지 원장이 답한다 -------------
#
# D91 은 인용 생산 손실을 이 층으로 좁히고 거기서 멈췄다 -- `NodeSummary.answer`
# 가 어디에도 영속화되지 않아 "모델이 마커를 산문에 실었는가" 를 저장된 데이터로
# 물을 수 없었다. 아래 넷이 그 질문을 원장 안으로 들여온다.


async def test_node_summary_records_markers_the_model_dropped():
    """성공한 리덕션의 캐리율. **떨어뜨렸을 때 떨어뜨렸다고 말해야 한다.**

    프롬프트에 마커 둘을 넣고 답에는 하나만 싣는다 -- §8.1.2 가 적은 대로
    계측기를 보는 것은 통과를 보는 게 아니라 **실패해야 할 때 실패하는지**
    보는 것이다. 두 수가 같기만 하면 공허하게 성립하는 단언이 된다.
    """
    q = SimpleNamespace(id="n1", text="Q", status="open", value_est=0.8)
    led = FakeLedger(
        {
            "n1": [
                (_claim("aaaaaaaa", "claim a"), [_ev("ex a")]),
                (_claim("bbbbbbbb", "claim b"), [_ev("ex b")]),
            ]
        }
    )
    cj = CapturingJSON(
        [
            {
                "question_id": "n1",
                "answer": "모델은 하나만 인용했다 [C:aaaaaaaa]",
                "key_claim_ids": ["aaaaaaaa"],
                "confidence": 0.8,
                "caveats": [],
                "conflicts": [],
            }
        ]
    )
    synth = Synthesizer(led, json_call=cj)
    await synth.reduce_node(q, [])

    payload = _logged(led, "node_summary")
    assert payload["distinct_claims_prompt"] == 2
    assert payload["distinct_claims_answer"] == 1


async def test_degraded_join_names_the_branch_it_took():
    """🔴 이 한 문자열이 CITE1 의 핵심이다.

    `answer_chars` 는 분기 **뒤에** 기록되므로 0 이 아니라는 사실만으로는
    자식 join 인지 자기 클레임 join 인지 알 수 없다. #21·#22 백테스트가
    자기 클레임 유실을 **상한으로만** 잴 수 있었던 이유이고, 그 상한은
    쓸모없을 만큼 헐거웠다.

    여기서는 자식이 답을 갖고 있고 이 노드도 자기 클레임을 갖는다 --
    `if not answer and pairs` 가 **발동하지 않으므로 자기 클레임이 버려진다.**
    """
    q = SimpleNamespace(id="n1", text="Q", status="open", value_est=0.8)
    led = FakeLedger({"n1": [(_claim("aaaaaaaa", "버려지는 클레임"), [_ev("ex")])]})

    async def json_call(model, prompt, **kw):
        raise RuntimeError("리덕션 실패 -- 강등 경로로 간다")

    child = NodeSummary(
        question_id="n2",
        answer="자식 답 [C:bbbbbbbb]",
        key_claim_ids=["bbbbbbbb"],
        confidence=0.5,
        caveats=[],
    )
    synth = Synthesizer(led, json_call=json_call)
    summary = await synth.reduce_node(q, [child])

    payload = _logged(led, "node_reduction_degraded")
    assert payload["answer_source"] == "children_join"
    # 버려졌다는 것이 원장에서 읽힌다: 쓸 수 있었던 클레임이 1개인데
    # 답에는 자식의 마커만 있다.
    assert payload["own_claims_available"] == 1
    assert "[C:aaaaaaaa]" not in summary.answer


async def test_degraded_leaf_says_it_used_its_own_claims():
    """같은 이벤트의 반대쪽 값. 둘을 구별하지 못하면 이름이 무의미하다."""
    q = SimpleNamespace(id="n1", text="Q", status="open", value_est=0.8)
    led = FakeLedger({"n1": [(_claim("aaaaaaaa", "자기 클레임"), [_ev("ex")])]})

    async def json_call(model, prompt, **kw):
        raise RuntimeError("리덕션 실패")

    synth = Synthesizer(led, json_call=json_call)
    summary = await synth.reduce_node(q, [])

    payload = _logged(led, "node_reduction_degraded")
    assert payload["answer_source"] == "own_claims"
    assert payload["own_claims_available"] == 1
    assert "[C:aaaaaaaa]" in summary.answer


async def test_degraded_bounding_reports_the_markers_halving_took():
    """절단 손실을 join 손실과 분리해 센다 -- 고칠 곳이 다르다.

    자식 답들이 상한을 크게 넘고 **뒤쪽 자식이 마커를 든다.** 반절씩 자르는
    `_bound_degraded_answer` 가 그 마커들을 가져간다.
    """
    q = SimpleNamespace(id="n1", text="Q", status="open", value_est=0.8)
    led = FakeLedger({})

    async def json_call(model, prompt, **kw):
        raise RuntimeError("리덕션 실패")

    children = [
        NodeSummary(
            question_id=f"n{i}",
            answer=("가" * 3_000) + f" [C:{chr(97 + i) * 8}]",
            key_claim_ids=[],
            confidence=0.4,
            caveats=[],
        )
        for i in range(4)
    ]
    synth = Synthesizer(led, json_call=json_call, synthesis_max_tokens=300)
    await synth.reduce_node(q, children)

    payload = _logged(led, "node_reduction_degraded")
    assert payload["answer_truncated"] is True
    assert payload["distinct_claims_before_bound"] == 4
    # 절단이 실제로 마커를 가져갔다는 것을 주장한다 -- "<=" 로 쓰면 절단이
    # 아무것도 안 가져가도 통과하고, 그것이 D60 이 고친 공허한 불변식이다.
    assert payload["distinct_claims_after_bound"] < 4
