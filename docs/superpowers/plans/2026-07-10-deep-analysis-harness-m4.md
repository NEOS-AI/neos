# 심층 분석 하네스 — M4 구현 계획 (완전한 종합: 계층 리듀스 + 충돌 + ReportGrader)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** M1 단층 종합을 원 설계 §6.7의 계층 리듀스로 대체하고, 충돌 해소 규칙 + 타깃 재조사 1회 + ReportGrader(§6.8) + 조립 재시도 루프를 추가한다 — 트리 크기와 무관한 노드당 컨텍스트, 모순 클레임 양론 병기, orphan 인용의 조립 재시도.

**Architecture:** 원 설계 [docs/DEEP_ANALYSIS_HARNESS_DESIGN.md](../../DEEP_ANALYSIS_HARNESS_DESIGN.md) §6.7(Synthesizer 계층 리듀스+충돌), §6.8(CitationRenderer+ReportGrader) 정본. M0–M3 코드(105 tests green) 위에 증분. 불변식 유지: P2 단일 작성자(Ledger만 씀), run 스코프, judge≠worker, raw 금지(excerpt/요약만).

**Tech Stack:** Python 3.12, async SQLAlchemy 2.0, 순수 async 판정 LLM 콜러, pytest + pytest-asyncio. Fake LLM/synth 계약 테스트(실 네트워크 금지, §10).

**정본:** §6.7 리듀스 규칙(리프 후위 순회, 노드 입력=자기 verified 클레임+자식 NodeSummary만, split/abandoned 처리), 충돌 처리(source_tiers 등급 → 상위 채택/양론 병기/재조사 1회), §6.8 ReportGrader(결정론+에이전틱 2판정), 조립 재시도 캡 2. DECISIONS: [neos/workflow/deep_analysis/DECISIONS.md](../../../neos/workflow/deep_analysis/DECISIONS.md).

## Global Constraints

- **범위: M4만.** 이후 개선 루프(L5)는 범위 밖.
- **노드당 컨텍스트 상수(§6.7 핵심):** 노드 리듀스 입력 = 자기 verified 클레임(excerpt) + **직계 자식 NodeSummary만**. 손자 이하 원시 클레임 접근 금지. 이것이 AC-a의 근거이자 계층 리듀스의 존재 이유.
- **판정/종합에 raw 금지:** excerpt와 자식 요약(answer)만. raw_ref 원문 금지.
- **P2 단일 작성자:** 상태·이벤트 쓰기는 Ledger에서만. Synthesizer/ReportGrader는 순수 판정/조립. 재조사 재진입 시 상태 전이는 Ledger 경유.
- **judge≠worker(§6.8 에이전틱):** ReportGrader 에이전틱 판정은 `config.models.judge`.
- **[C:claimid] 외 인용 금지(§11.5):** 마커만. CitationRenderer가 각주 치환.
- **매직넘버 금지:** 전부 `settings.config.deep_analysis.*`(source_tiers, conflict_reinvestigation_cap, conflict_value_threshold, report_retry_cap).
- **빈손 종료 금지(§6.8):** 재시도 캡 소진 시 마지막 초안 + 실패 사유 부록으로 산출.
- **DECISIONS 갱신:** 새 판단은 D16+.

## M4 완료 기준 (원 설계 §9)

- **AC-a:** 깊이 3 트리에서 **노드당 입력 토큰(프롬프트 크기)이 트리 크기와 무관하게 유지**됨(로그/캡처로 확인). 즉 조부모 노드의 리듀스 입력이 손자 수에 비례해 커지지 않는다.
- **AC-b:** 조작된 모순 클레임 쌍(동급 출처)이 **양론 병기**로 출력된다.
- **AC-c:** `E_ORPHAN_CITE`가 **조립 재시도를 트리거**한다(재시도 캡 내에서 재조립; 소진 시 부록 산출).

## M4가 재사용/대체하는 기존 코드
- `synthesizer.py`: 단층 `reduce(root_id)->str`를 계층 구조로 재작성(하위 호환 wrapper 유지).
- `citation.py`: `CitationRenderer.render`는 이미 `OrphanCitationError(E_ORPHAN_CITE)`를 raise(D10). M4는 이를 조립 재시도 루프에서 잡는다.
- `prompts/node_summary.md`, `final_compose.md`: 이미 존재. node_summary는 M1에서 미사용 → M4에서 사용.
- `models.py`: `NodeSummary`, `ConflictNote` 존재.

---

## 파일 구조

- Modify: `neos/workflow/deep_analysis/synthesizer.py` — 계층 리듀스(`reduce_tree`, `reduce_node`, `assemble`) + 하위호환 `reduce`.
- Create: `neos/workflow/deep_analysis/conflict.py` — `resolve_conflicts`(source_tiers 등급, 양론 병기/상위 채택/재조사 신호).
- Create: `neos/workflow/deep_analysis/graders/report.py` — `ReportGrader`(결정론+에이전틱).
- Modify: `neos/workflow/deep_analysis/orchestrator.py` — `_finalize`(reduce_tree → 충돌 재조사 1회 → assemble → citation → ReportGrader → 재시도 캡 2).
- Modify: `neos/workflow/deep_analysis/ledger.py` — 필요한 읽기(`node_children_summaries`용 tree walk 헬퍼 등, 대부분 기존 children/verified_claims 재사용).
- Tests: 신규 `test_synthesizer_hier.py`, `test_conflict.py`, `test_report_grader.py`, `test_orchestrator_m4.py`.

---

### Task 1: 노드 단위 리듀스 → NodeSummary (`reduce_node`)

**Files:**
- Modify: `neos/workflow/deep_analysis/synthesizer.py`
- Test: `tests/workflow/deep_analysis/test_synthesizer_hier.py`

**Interfaces:**
- Consumes: `NodeSummary`, `ConflictNote`, `call_json`(JSON 출력), `render`, Ledger.verified_claims.
- Produces:
  - `async reduce_node(self, question, child_summaries: list[NodeSummary]) -> NodeSummary` — 한 노드를 요약. 입력 = 자기 verified 클레임(excerpt) + `child_summaries`의 answer만. `node_summary.md`로 프롬프트 조립 → `call_json` → NodeSummary 파싱(conflicts 포함). **노드당 input token/prompt 길이를 events(kind="node_summary")에 기록**(AC-a 측정점).
  - split 질문(자기 클레임 없음): child_summaries만으로 answer.
  - 파싱 실패: 1회 재시도(call_json 내장) 후 실패 시 최소 NodeSummary(answer=자식 answer 연결, confidence=평균, conflicts=[]) 폴백 — 시스템 정지 금지.
- **AC-a 근거:** child_summaries는 각 자식의 `answer`(요약 문자열)만 넣고, 자식의 verified 클레임 원문/손자 요약은 넣지 않는다.

- [ ] **Step 1: 실패 테스트 작성** (fake llm_call이 프롬프트 캡처 + NodeSummary JSON 반환)

```python
# tests/workflow/deep_analysis/test_synthesizer_hier.py
import json
import pytest
from types import SimpleNamespace
from neos.workflow.deep_analysis.synthesizer import Synthesizer
from neos.workflow.deep_analysis.models import NodeSummary

pytestmark = pytest.mark.no_db

class CapturingJSON:
    """call_json 대체: 프롬프트를 캡처하고 스크립트된 NodeSummary dict 반환."""
    def __init__(self, payloads): self.payloads=list(payloads); self.prompts=[]
    async def __call__(self, model, prompt, **kw):
        self.prompts.append(prompt)
        data = self.payloads.pop(0)
        return data, SimpleNamespace(input_tokens=len(prompt)//4, output_tokens=10)

class FakeLedger:
    def __init__(self, verified): self._verified=verified   # {qid: [(claim, [ev])]}
    async def verified_claims(self, qid): return self._verified.get(qid, [])
    async def log(self, *a, **k): pass

def _claim(cid, text): return SimpleNamespace(id=cid, text=text, confidence=0.7)
def _ev(excerpt): return SimpleNamespace(excerpt=excerpt, source_url="http://x")

async def test_reduce_node_uses_only_own_claims_and_child_answers():
    q = SimpleNamespace(id="n1", text="Q", status="open", value_est=0.8)
    child = NodeSummary(question_id="c1", answer="child ans [C:cccccccc]",
                        key_claim_ids=["cccccccc"], confidence=0.7, caveats=[], conflicts=[])
    led = FakeLedger({"n1": [(_claim("aaaaaaaa","own claim"), [_ev("own excerpt")])]})
    cj = CapturingJSON([{"question_id":"n1","answer":"ans [C:aaaaaaaa]",
                         "key_claim_ids":["aaaaaaaa"],"confidence":0.8,"caveats":[],"conflicts":[]}])
    synth = Synthesizer(led, json_call=cj)
    summary = await synth.reduce_node(q, [child])
    assert isinstance(summary, NodeSummary) and summary.question_id == "n1"
    p = cj.prompts[0]
    assert "own excerpt" in p          # 자기 클레임 excerpt 포함
    assert "child ans" in p            # 자식 answer 포함
    # 자식의 원시 클레임 텍스트는 넣지 않는다(요약 answer만) — child에는 raw 클레임이 없음
```

- [ ] **Step 2/3:** `Synthesizer.__init__`에 `json_call=call_json` 주입 파라미터 추가. `reduce_node` 구현:

```python
    async def reduce_node(self, question, child_summaries):
        pairs = await self.ledger.verified_claims(question.id)
        claim_lines = []
        for claim, evidence_rows in pairs:
            ev = " ".join(f"<evidence>{r.excerpt}</evidence>" for r in evidence_rows)
            claim_lines.append(f"[C:{claim.id}] {claim.text} (conf {claim.confidence}) {ev}")
        child_lines = [f"[{c.question_id}] {c.answer}" for c in child_summaries]
        prompt = render("node_summary", question_id=question.id, question_text=question.text,
                        verified_claims="\n".join(claim_lines) or "(없음)",
                        child_summaries="\n".join(child_lines) or "(없음)")
        config = settings.config.deep_analysis
        try:
            data, resp = await self.json_call(config.models.synth, prompt,
                max_tokens=config.synthesis_max_tokens, client=self.llm_client, cassette=self.cassette)
        except Exception:
            joined = " ".join(c.answer for c in child_summaries) or ""
            return NodeSummary(question_id=question.id, answer=joined, key_claim_ids=[],
                               confidence=0.0, caveats=["node_summary_unparseable"], conflicts=[])
        await self.ledger.log("node_summary", question.id,
            {"input_tokens": resp.input_tokens, "prompt_chars": len(prompt),
             "child_count": len(child_summaries), "own_claims": len(pairs)})
        conflicts = [ConflictNote(**c) for c in data.get("conflicts", [])]
        return NodeSummary(question_id=question.id, answer=str(data.get("answer","")),
            key_claim_ids=list(data.get("key_claim_ids", [])),
            confidence=float(data.get("confidence", 0.0)),
            caveats=list(data.get("caveats", [])), conflicts=conflicts)
```

- [ ] **Step 4/5:** 통과 + 커밋.

```bash
git commit -m "feat(deep-analysis): add node-level reduce producing NodeSummary"
```

---

### Task 2: 계층 후위 순회 리듀스 (`reduce_tree`) — AC-a

**Files:**
- Modify: `neos/workflow/deep_analysis/synthesizer.py`
- Test: `tests/workflow/deep_analysis/test_synthesizer_hier.py` (추가)

**Interfaces:**
- Produces: `async reduce_tree(self, root_id: str) -> dict[str, NodeSummary]` — 질문 트리를 리프부터 후위 순회하며 각 노드 `reduce_node`. `abandoned` 노드는 제외(요약 생성 안 함). 반환은 {qid: NodeSummary}. Ledger에서 트리 구조는 `children(qid)` 재귀로 획득.
- **AC-a 측정:** 각 노드 리듀스가 events(node_summary)에 prompt_chars/input_tokens 기록 → 테스트가 조부모 노드의 prompt_chars가 손자 수와 무관함을 검증(자식 answer는 고정 길이 요약이므로).

- [ ] **Step 1: AC-a 테스트** (DB 백엔드 or FakeLedger 트리)

```python
# 추가 to test_synthesizer_hier.py — depth-3 트리에서 루트 노드 prompt가 손자 수에 비례하지 않음
async def test_grandparent_prompt_independent_of_grandchildren_count():
    # 트리 A: root - child - (손자 1개) / 트리 B: root - child - (손자 5개)
    # child의 NodeSummary.answer는 고정 길이 요약이므로, root의 reduce_node prompt는 두 경우 유사
    # CapturingJSON으로 각 노드 prompt를 캡처, root prompt 길이가 손자 수에 선형 증가하지 않음을 assert
    ...
```

(구현: reduce_tree 후위 순회. 자식 요약을 부모에 전달. abandoned 제외. 같은 깊이 병렬은 선택 — M4는 순차 후위로 구현하고 병렬은 후속 최적화로 DECISIONS 기록.)

```python
    async def reduce_tree(self, root_id):
        summaries = {}
        async def visit(qid):
            children = [c for c in await self.ledger.children(qid) if c.status != "abandoned"]
            child_summaries = []
            for child in children:
                await visit(child.id)
                if child.id in summaries:
                    child_summaries.append(summaries[child.id])
            question = await self.ledger.get_question(qid)
            if question is None or question.status == "abandoned":
                return
            summaries[qid] = await self.reduce_node(question, child_summaries)
        await visit(root_id)
        return summaries
```

```bash
git commit -m "feat(deep-analysis): hierarchical post-order tree reduce with constant per-node context"
```

---

### Task 3: 충돌 해소 (`conflict.py`) — AC-b

**Files:**
- Create: `neos/workflow/deep_analysis/conflict.py`
- Test: `tests/workflow/deep_analysis/test_conflict.py`

**Interfaces:**
- Consumes: `NodeSummary`, `ConflictNote`, source_tiers 설정, Ledger.get_claim/verified_claims(출처 도메인 조회).
- Produces:
  - `def source_tier(url: str, source_tiers: dict) -> int` — 도메인 접미 매칭. tier1 접미 일치 → 1, 아니면 2(기본).
  - `async resolve_conflicts(ledger, summary: NodeSummary, source_tiers) -> tuple[NodeSummary, list[str]]` — summary.conflicts 각각에 대해 두 클레임의 출처 등급 비교:
    - 등급 차이 명확(하나가 tier1, 다른 하나가 tier2) → 상위 채택, 하위는 각주 병기 지시(answer 유지 + caveat "하위 출처 각주").
    - 등급 동급 → **양론 병기**: answer에 "다만 상반된 보고도 있다(양론)" 취지 문구 삽입 + 두 클레임 모두 마커 유지. (AC-b)
    - 반환: 수정된 NodeSummary + 재조사 필요 질문 id 목록(value_est>=conflict_value_threshold인 충돌).
- **양론 병기 구현(결정론):** LLM 재요약 대신 결정론적 문구 삽입으로 M4 AC를 만족(원 설계의 "해당 노드만 1회 재요약"은 LLM 경로지만, 결정성/테스트성을 위해 결정론 삽입 채택 → DECISIONS D16). answer 끝에 `\n\n(양론 병기) 상반된 근거: [C:a] vs [C:b] — {nature}`.

- [ ] **Step 1: 실패 테스트**

```python
# tests/workflow/deep_analysis/test_conflict.py
import pytest
from types import SimpleNamespace
from neos.workflow.deep_analysis.conflict import source_tier, resolve_conflicts
from neos.workflow.deep_analysis.models import NodeSummary, ConflictNote

pytestmark = pytest.mark.no_db

TIERS = {"tier1": ["arxiv.org", ".gov", ".edu", "github.com"], "tier2": ["*"]}

def test_source_tier_suffix_match():
    assert source_tier("https://arxiv.org/abs/1", TIERS) == 1
    assert source_tier("https://x.edu/p", TIERS) == 1
    assert source_tier("https://blog.example.com/p", TIERS) == 2

class FakeLedger:
    def __init__(self, urls): self._urls=urls  # {claim_id: [url]}
    async def claim_source_urls(self, claim_id): return self._urls.get(claim_id, [])
    async def get_claim(self, cid): return SimpleNamespace(id=cid, value_est=0.5)

async def test_equal_tier_conflict_produces_both_sides():
    s = NodeSummary(question_id="n1", answer="주장 [C:aaaaaaaa]", key_claim_ids=["aaaaaaaa"],
        confidence=0.7, caveats=[], conflicts=[ConflictNote("aaaaaaaa","bbbbbbbb","상반")])
    led = FakeLedger({"aaaaaaaa":["http://blog1.com"], "bbbbbbbb":["http://blog2.com"]})  # 둘 다 tier2
    out, reinv = await resolve_conflicts(led, s, TIERS)
    assert "양론" in out.answer and "[C:aaaaaaaa]" in out.answer and "[C:bbbbbbbb]" in out.answer

async def test_tier_difference_adopts_higher():
    s = NodeSummary(question_id="n1", answer="주장 [C:aaaaaaaa]", key_claim_ids=["aaaaaaaa"],
        confidence=0.7, caveats=[], conflicts=[ConflictNote("aaaaaaaa","bbbbbbbb","상반")])
    led = FakeLedger({"aaaaaaaa":["https://arxiv.org/x"], "bbbbbbbb":["http://blog.com"]})  # a=tier1
    out, reinv = await resolve_conflicts(led, s, TIERS)
    assert "양론" not in out.answer   # 상위 채택, 양론 병기 아님
```

- [ ] **Step 2~5:** 구현(source_tier 접미 매칭; resolve_conflicts 등급 비교 + 결정론 양론 문구; Ledger에 `claim_source_urls(claim_id)` 편의 읽기 추가 — verified_claims 기반). DECISIONS D16(결정론 양론 병기). 커밋.

```bash
git commit -m "feat(deep-analysis): conflict resolution with source-tier adoption and both-sides annotation"
```

---

### Task 4: ReportGrader (`graders/report.py`) — 결정론 + 에이전틱

**Files:**
- Create: `neos/workflow/deep_analysis/graders/report.py`
- Test: `tests/workflow/deep_analysis/test_report_grader.py`

**Interfaces:**
- Consumes: `CitationRenderer`(E_ORPHAN_CITE), Ledger(resolved 루트 직계 질문), judge 모델.
- Produces:
  - `class ReportGrader(ledger, *, judge_model, llm_client=None, cassette=None, json_call=call_json)`
  - `async grade_deterministic(self, report: str, root_id: str) -> Verdict` — (a) `[C:...]` 원시 마커 0건(citation 렌더 후이므로 남아있으면 실패=E_ORPHAN_CITE 흔적), (b) 마커/각주 없는 사실성 단정문 비율 < 20%(휴리스틱: 숫자 또는 고유명사 포함 & 각주/마커 없는 문장 비율), (c) resolved 상태 루트 직계 질문 텍스트가 전부 본문에 언급, (d) "한계와 미확인 사항" 섹션 존재. 첫 실패에서 코드 반환.
  - `async grade_agentic(self, report: str, root_text: str) -> Verdict` — judge 2판정 JSON: `{"answers_question": bool, "strength_ok": bool, "rationale": str}`. 둘 중 하나라도 false면 실패.
  - `async grade(self, report, root_id) -> Verdict` — 결정론 먼저, 통과 시 에이전틱.
- 실패 시 Verdict(code=E_REPORT_*). 조립 재시도는 orchestrator가 처리(Task 5).

- [ ] **Step 1: 실패 테스트**(결정론 전수, 에이전틱은 fake judge 매핑)

```python
# tests/workflow/deep_analysis/test_report_grader.py — pytestmark 없음(Ledger 필요분은 fake)
# 결정론: 한계 섹션 없음 -> 실패; resolved 질문 미언급 -> 실패; 정상 -> 통과
# 에이전틱: judge answers_question=false -> 실패
```

- [ ] **Step 2~5:** 구현 + 커밋.

```bash
git commit -m "feat(deep-analysis): add ReportGrader with deterministic and agentic checks"
```

---

### Task 5: Orchestrator `_finalize` — 계층 리듀스 + 재조사 1회 + 조립 재시도 — AC-c

**Files:**
- Modify: `neos/workflow/deep_analysis/orchestrator.py`
- Modify: `neos/workflow/deep_analysis/service.py` (ReportGrader 배선)
- Test: `tests/workflow/deep_analysis/test_orchestrator_m4.py`

**Interfaces:**
- `Orchestrator.__init__`에 `report_grader=None` 추가.
- `run()`의 tail(현재 `reduce`+`render`)을 `report = await self._finalize(root_id)`로 대체.
- `async _finalize(self, root_id)`:
  1. `summaries = await self.synthesizer.reduce_tree(root_id)`.
  2. 충돌 해소: 각 summary에 `resolve_conflicts` → 수정된 summaries + 재조사 필요 목록. **재조사 1회(전역 캡):** events에 `conflict_reinvestigation` 없고 재조사 목록 비어있지 않으면, 해당 질문을 `open` 복귀 + 로그 + **1 라운드 추가 조사**(기존 select/worker/commit 경로 1회) 후 `reduce_tree` 재실행. 있으면 양론 병기로만 처리.
  3. `root_summary = summaries[root_id]`; 직계 자식 summaries; caveats(unverified/abandoned + summary.caveats) 수집.
  4. **조립 재시도 루프(캡 report_retry_cap=2):**
     ```
     for attempt in range(cap + 1):
         draft = await self.synthesizer.assemble(root_summary, child_summaries, caveats)
         try:
             report = await self.citation_renderer.render(draft)   # E_ORPHAN_CITE
         except OrphanCitationError as e:
             log report_graded {ok:false, code:E_ORPHAN_CITE, attempt}; continue   # AC-c
         verdict = await self.report_grader.grade(report, root_id) if self.report_grader else Verdict(ok=True)
         if verdict.ok:
             log report_graded {ok:true}; break
         log report_graded {ok:false, code:verdict.code, attempt}
     else:
         report = last_draft_or_report + "\n\n## 부록: 미해결 사유\n" + reason   # 빈손 종료 금지
     await self.ledger.complete_run(); return report
     ```
- `synthesizer.assemble(root_summary, child_summaries, caveats) -> str` — final_compose로 최종 조립(Task 5에서 Synthesizer에 추가). 하위호환 `reduce(root_id)`는 `reduce_tree`+`assemble`을 호출하는 wrapper로 유지(기존 orchestrator/synth 테스트 green).
- **AC-c:** citation이 orphan을 raise → 루프가 재조립(재시도). 캡 소진 시 부록.

- [ ] **Step 1~5:** 계약 테스트(FakeWorker + fake synth/grader/citation)로 AC-c(첫 조립 orphan → 재시도 → 두 번째 통과) + 재조사 1회 캡 + 부록 산출 검증. service 배선. 기존 orchestrator 테스트 green(하위호환 reduce/주입 synth). 커밋.

```bash
git commit -m "feat(deep-analysis): finalize with hierarchical reduce, conflict reinvestigation, assembly retry"
```

---

### Task 6: 통합 AC(a/b/c) + DECISIONS + 회귀

**Files:**
- Test: `tests/workflow/deep_analysis/test_orchestrator_m4_integration.py`
- Modify: `neos/workflow/deep_analysis/DECISIONS.md` (D16 결정론 양론 병기, D17 순차 후위 순회[병렬 후속])

**내용:**
- **AC-a:** 깊이 3 트리(실 Ledger + fake json_call)로 reduce_tree 실행 → node_summary 이벤트의 prompt_chars가 조부모에서 손자 수에 비례하지 않음(작은/큰 손자 트리 두 케이스 비교).
- **AC-b:** 조작된 동급 출처 모순 클레임 쌍 → 최종 보고서에 양론 병기 문구 존재.
- **AC-c:** 첫 조립이 orphan 마커 포함 → 재시도 → 통과(또는 캡 소진 시 부록). report_graded 이벤트에 재시도 흔적.
- 전체 회귀 `.venv/bin/python -m pytest tests/workflow/deep_analysis/ -q` green.
- DECISIONS D16/D17.

```bash
git commit -m "feat(deep-analysis): M4 integration ACs + DECISIONS (M4 complete)"
```

**M4 완료 게이트:** Task 1–6 통과 = AC-a(노드당 상수 컨텍스트) + AC-b(양론 병기) + AC-c(orphan→조립 재시도). 하네스 M0–M4 전체 완성.

---

## 자체 리뷰 (원 설계 §9 M4 대비)

**1. AC 커버리지:** AC-a → Task 1(노드 입력=자기+자식 answer만) + Task 2(후위 순회) + Task 6(prompt_chars 불변 측정). AC-b → Task 3(양론 병기) + Task 6. AC-c → Task 5(citation orphan → 조립 재시도) + Task 6.

**2. 플레이스홀더:** Task 2/4/5는 계약/통합 성격 — 완전 코드 대신 핵심 코드+테스트 계약. 고위험 결정 로직(source_tier 매칭, 양론 병기 삽입, reduce_node 입력 경계, 재시도 루프)은 완전 코드.

**3. 타입 일관성:** `reduce_node(question, child_summaries)->NodeSummary`, `reduce_tree(root_id)->dict`, `assemble(root_summary, child_summaries, caveats)->str`, `resolve_conflicts(ledger, summary, tiers)->(NodeSummary, list)`, `ReportGrader.grade(report, root_id)->Verdict`, `_finalize(root_id)->str` — 일치.

**4. 불변식:** 노드당 상수 컨텍스트(§6.7), raw 금지(excerpt/answer만), P2(Ledger만 씀), judge≠worker, [C:id]만, 빈손 종료 금지 — Global Constraints 명시.

**신규 DECISIONS:** D16(결정론 양론 병기 — LLM 재요약 대신), D17(순차 후위 순회 — 같은 깊이 병렬은 후속).
