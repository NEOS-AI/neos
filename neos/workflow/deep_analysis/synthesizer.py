"""M1 single-layer synthesis over verified claims only."""

from __future__ import annotations

import re

from neos.config.settings import settings

from .llm import call_json, call_text, prompt_input_bound
from .model_roles import resolve_harness_model
from .models import ConflictNote, NodeSummary
from .prompt_clamp import clamp_prompt, halve
from .prompt_loader import render
from .token_budget import TokenBudgetExhausted, active_token_budget

# A `[C:` that the truncation cut through, with fewer than the 8 hex digits
# and the closing bracket a real marker carries.
_DANGLING_MARKER = re.compile(r"\[C:[0-9a-f]{0,8}$")

# A whole claim address, capturing its id. Deliberately the same shape
# `citation._MARKER` and `graders.report._RAW_MARKER` match: this counts the
# very things the renderer will later resolve into footnotes, so a looser
# pattern here would report markers the renderer cannot use.
_CLAIM_MARKER = re.compile(r"\[C:([0-9a-f]{8})\]")


# Sentence-ish pieces. A citation binds to the sentence it sits in, so this
# is the unit that can be kept or shed without stranding a marker on prose
# that no longer says anything.
_SEGMENT = re.compile(r"[^.!?\n]*[.!?\n]|[^.!?\n]+")


def compact_keeping_claims(text: str) -> str:
    """Halve `text`, shedding claim-free segments before cited ones (D62).

    `halve` cuts at a character offset and takes whatever is past it. That
    destroys citations faster than characters: samples #14 and #15 measured
    the assembly clamp retaining 36% / 33% of its characters while distinct
    claims fell to 9% / 15%. And the loss is terminal in a way lost prose is
    not -- a claim that never reaches the composer cannot be cited, and
    sample #15 showed footnote counts equal to surviving claims in five runs
    of six exactly.

    Same character budget as `halve`, so the clamp converges exactly as
    before; only the choice of *which* characters changes. Segments carrying
    a marker are taken first in their original order, then the rest fill
    whatever budget is left.

    Falls back to `halve` when it cannot do better -- a single segment, or a
    budget too small for any whole segment. `prompt_clamp._progress` also
    guards the shrink-must-shrink contract, so a fallback here can only cost
    quality, never termination.
    """

    budget = len(text) // 2
    segments = _SEGMENT.findall(text)
    if len(segments) < 2 or budget <= 0:
        return halve(text)

    keep = [False] * len(segments)
    used = 0
    for cited in (True, False):
        for index, segment in enumerate(segments):
            if keep[index] or bool(_CLAIM_MARKER.search(segment)) is not cited:
                continue
            if used + len(segment) <= budget:
                keep[index] = True
                used += len(segment)
    kept = "".join(s for i, s in enumerate(segments) if keep[i])
    return kept if 0 < len(kept) < len(text) else halve(text)


def _distinct_claims(*texts: str) -> set[str]:
    """The distinct claim ids these texts address.

    Distinct, not occurrences (D59). `CitationRenderer` gives one footnote
    per claim however many times the draft cites it, so occurrences answer a
    different question than the one being asked -- and the same claim
    routinely appears in both a child block and the root summary that
    summarizes it, which double-counts every one of them. Sample #14's counts
    are occurrence counts and must not be pooled with these.
    """

    found: set[str] = set()
    for text in texts:
        found.update(_CLAIM_MARKER.findall(text))
    return found


def _degradation_reason(exc: TokenBudgetExhausted) -> str:
    """강등 이벤트의 `reason` -- 예외 타입이 아니라 거절 사유에서 온다.

    이 두 자리는 `"token_budget_exhausted"` 를 하드코딩하고 있었다.
    `reserve` 가 캡 소진과 `input_bound` 거절에 같은 예외를 던지므로, 여유가
    남은 채 거절된 run 도 "예산 소진"으로 기록됐다 -- G9 가 정지 사유에서
    없앤 것과 같은 종류의 거짓이다.

    `tier_floor` 는 옛 문자열을 그대로 낸다. 이미 원장에 쌓인 강등 이벤트가
    그 어휘를 쓰고 있어 경계 전후 집계가 이어져야 하기 때문이다. 새 문자열은
    지금까지 존재하지 않던 구별에만 붙는다.
    """
    if exc.cause == "input_bound":
        return "input_bound"
    return "token_budget_exhausted"


class Synthesizer:
    def __init__(
        self,
        ledger,
        *,
        # `call_text` 는 잘린 조립에 한 번 더 큰 시도를 준다. 예전 기본값
        # `call_llm` 은 잘림을 기록만 했고, 그래서 조립만 회복하지 못했다
        # (2026-08-08 표본 #2: 18/18 잘림, 필수 마지막 절이 매번 소실).
        llm_call=call_text,
        json_call=call_json,
        llm_client=None,
        cassette=None,
        synthesis_max_tokens: int | None = None,
    ) -> None:
        self.ledger = ledger
        self.llm_call = llm_call
        self.json_call = json_call
        self.llm_client = llm_client
        self.cassette = cassette
        # None means "use the global default" so every existing construction
        # site keeps working; service.py passes the profile-resolved value.
        self._synthesis_max_tokens = synthesis_max_tokens

    @property
    def synthesis_max_tokens(self) -> int:
        if self._synthesis_max_tokens is not None:
            return self._synthesis_max_tokens
        return settings.config.deep_analysis.synthesis_max_tokens

    @property
    def assembly_input_allowance(self) -> int:
        """Input bytes report_assembly's prompt may occupy.

        Derived here rather than injected: the ratio is global policy, and
        `synthesis_max_tokens` above is whatever ceiling this Synthesizer was
        built with. Threading two more constructor arguments through
        service.py would give the same number two sources.

        W1-m2 -- be precise about "whatever ceiling it was built with". On the
        production path `service.py` passes the profile-resolved value, so the
        allowance is profile-scoped. A Synthesizer constructed elsewhere
        WITHOUT `synthesis_max_tokens` falls back to the **global** setting
        (see the property above), and its allowance is global too. That is the
        documented fallback, not a bug -- `test_synthesizer_falls_back_to_the_
        global_ceiling` fixes it -- but the earlier wording here claimed the
        value was "already profile-resolved" unconditionally, which is false
        for that construction and would mislead anyone sizing a prompt against
        it outside the production path.
        """
        ratio = settings.config.deep_analysis.assembly_input_ratio
        return int(ratio * self.synthesis_max_tokens)

    @property
    def reduction_input_allowance(self) -> int:
        ratio = settings.config.deep_analysis.reduction_input_ratio
        return int(ratio * self.synthesis_max_tokens)

    def effective_reduction_allowance(self) -> int:
        """`reduction_input_allowance`, capped by what the tier can grant.

        BUDGET2. The static allowance is a *policy* number -- a ratio of
        `synthesis_max_tokens`, fixed for the whole run. What `reserve()`
        charges against is `available_for_reduction`, which **shrinks with
        every reduction that has already run**. The clamp was aiming at the
        first and being graded by the second, so once the tier fell below the
        allowance the clamp declared the prompt "fitting" and `reserve()`
        refused it. That is the whole of the 152: sample #21/#22 recorded
        `node_summary` 79 against `node_reduction_degraded` 152, and **all
        152** carried `reason=input_bound` -- a single mechanism, not a
        distribution of causes.

        `min_viable_output_tokens` is subtracted because a reservation is not
        granted for fitting; it is granted for leaving room to answer.
        `reserve()` refuses when `ceiling - input_bound < viability`, so an
        allowance that ignores that margin aims one viable call too high and
        reproduces the same refusal at a smaller size (G8 learned the
        output-side half of this: a budget floor must ask "can one valid call
        be made", not "is one token left").

        Returns the static allowance when no budget is in scope. That is the
        test and script path, and it is the pre-BUDGET2 behaviour exactly --
        this method can only *lower* an allowance, never raise one.

        **`assemble` deliberately does not get the same treatment.** The same
        arithmetic gap exists there (`assembly_input_allowance` is static,
        `available_for_assembly` shrinks), but that tier is not currently
        failing this way -- sample #21 recorded clamp `exhausted` at **0**.
        Changing a healthy tier would add a second sample boundary to answer
        a question nobody has asked, and §13.5 already costs one boundary for
        this change. If assembly starts refusing with `input_bound`, this is
        the shape of the fix.
        """
        static = self.reduction_input_allowance
        budget = active_token_budget()
        if budget is None:
            return static
        grantable = (
            budget.available_for_reduction - budget.min_viable_output_tokens
        )
        return max(0, min(static, grantable))

    async def _log_clamp(
        self,
        stage: str,
        qid: str,
        result,
        allowance: int,
        *,
        claims_before: int | None = None,
    ) -> None:
        """Record a clamp only when it actually cut something.

        Logging every call would bury the signal: the interesting event is
        a finalization prompt that did not fit, not one that did.

        `claims_before` is the domain half of the measurement (D58). The
        clamp reports sizes because sizes are all it knows; only the caller
        knows that those characters carry `[C:xxxxxxxx]` claim addresses, and
        the number of those **surviving into the prompt** is the ceiling on
        how many citations the report can possibly carry. Sample #13 left
        that unanswerable: footnote counts in delivered reports fell 12 -> 7
        -> 2 -> 2 while nothing on record said whether the markers ever
        reached the composer.

        Renamed from `markers_*` rather than corrected in place (D59). The
        first version counted occurrences and, at `node_reduction`, counted a
        "before" that omitted material the prompt actually contains -- so its
        totals read 35 -> 90, an "after" larger than its "before". Both are
        now distinct claim ids over the full input. Keeping the old key would
        let two incompatible measurements be pooled across samples, which is
        the mistake D48 already cost a sample to.
        """
        if not (result.clamped or result.exhausted):
            return
        await self.ledger.log(
            "finalization_prompt_clamped",
            qid,
            {
                "stage": stage,
                "bound_before": result.bound_before,
                "bound_after": result.bound_after,
                "allowance": allowance,
                "dropped_primary": result.dropped_primary,
                "dropped_secondary": result.dropped_secondary,
                "exhausted": result.exhausted,
                # Halving the root answer leaves no mark on the dropped
                # counts, so without these a prompt that kept every child
                # block by cutting its root summary to a fifth looks
                # identical to one that never needed clamping at all.
                "anchor_chars_before": result.anchor_chars_before,
                "anchor_chars_after": result.anchor_chars_after,
                # Same for the child blocks (D58): halving precedes dropping,
                # so `dropped_primary=0` was reported by clamps that cut every
                # block to a fraction of itself.
                "primary_chars_before": result.primary_chars_before,
                "primary_chars_after": result.primary_chars_after,
                **(
                    {
                        "distinct_claims_before": claims_before,
                        "distinct_claims_after": len(
                            _distinct_claims(result.prompt)
                        ),
                    }
                    if claims_before is not None
                    else {}
                ),
            },
        )

    async def reduce(self, root_id: str) -> str:
        root = await self.ledger.root_question()
        if root is None or root.id != root_id:
            raise KeyError(f"root question not found: {root_id}")

        claim_blocks: list[str] = []
        caveat_lines: list[str] = []
        children = await self.ledger.children(root_id)
        questions = [root, *children]
        for question in questions:
            for claim, evidence_rows in await self.ledger.verified_claims(
                question.id
            ):
                evidence = "\n".join(
                    f"<evidence>{row.excerpt}</evidence>"
                    for row in evidence_rows
                )
                claim_blocks.append(
                    f"- 질문: {question.text}\n"
                    f"  클레임 [C:{claim.id}]: {claim.text}\n"
                    f"  confidence: {claim.confidence}\n"
                    f"  {evidence}"
                )
            for text in await self.ledger.unverified_and_deadends(
                question.id
            ):
                caveat_lines.append(f"미확인: {text}")

        for question in await self.ledger.questions():
            if question.status == "abandoned":
                caveat_lines.append(f"미조사: {question.text}")

        if caveat_lines:
            caveats = "\n".join(caveat_lines)
        elif claim_blocks:
            caveats = "(없음)"
        else:
            caveats = "검증된 클레임을 확보하지 못함"
        prompt = render(
            "final_compose",
            root_summary=root.text,
            child_summaries="\n".join(claim_blocks)
            or "(검증된 발견 없음)",
            caveats=caveats,
            # `reduce` is the single-pass M1 path -- no retry loop, so there
            # is never a previous rejection. Supplied anyway because `render`
            # leaves unfilled placeholders as literal text, and a stray
            # "{revision_note}" in the prompt is worse than an empty one.
            revision_note="(없음 -- 재시도 없는 경로)",
        )
        synth_model = resolve_harness_model("synth").model
        response = await self.llm_call(
            synth_model,
            prompt,
            max_tokens=self.synthesis_max_tokens,
            client=self.llm_client,
            cassette=self.cassette,
            stage="report_assembly",
        )
        await self.ledger.log(
            "synth_pass",
            root_id,
            {
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "verified_claims": len(claim_blocks),
            },
        )
        return response.text

    async def assemble(
        self,
        root_summary: NodeSummary | None,
        child_summaries: list[NodeSummary],
        caveats: list[str],
        revision_hints: list[str] | None = None,
    ) -> str:
        """Final compose (§6.8) over the root ``NodeSummary`` + direct-child
        ``NodeSummary`` answers + collected caveats.

        This is the M4 assembly seam driven by the orchestrator's
        ``_finalize`` retry loop. ``reduce`` (single-layer, M1) is kept intact
        as a backward-compatible path for callers/tests that still summarize
        straight from the ledger; ``assemble`` instead composes from
        already-reduced hierarchical ``NodeSummary`` objects.
        """
        root_answer = root_summary.answer if root_summary is not None else ""
        # The question comes before its answer (W3-i). A block used to be
        # `- [{question_id}] {answer}`, which named the question only by an
        # opaque id -- the composer could not tell what any answer was an
        # answer *to*, and the report gate's "every resolved child question
        # must be mentioned" check demanded text the composer had never been
        # shown.
        child_blocks = [
            f"- [{child.question_id}] 질문: {child.question_text}\n"
            f"  답: {child.answer}"
            if child.question_text
            else f"- [{child.question_id}] {child.answer}"
            for child in child_summaries
        ]
        synth_model = resolve_harness_model("synth").model
        qid = root_summary.question_id if root_summary is not None else ""

        def render_assembly(
            blocks: list[str], notes: list[str], root: str
        ) -> str:
            # Computed from this call's own `blocks`, not the pre-clamp
            # `child_blocks` -- the clamp can drop every child block and
            # leave `root_answer` empty too, and this must reflect that
            # (F10): the closure is pure with respect to its arguments.
            # `root` likewise: it is now clamped material (D54), so reading
            # the captured `root_answer` here would describe a prompt this
            # call is not sending.
            has_content = bool(root.strip()) or bool(blocks)
            if notes:
                caveats_text = "\n".join(notes)
            elif has_content:
                caveats_text = "(없음)"
            else:
                caveats_text = "검증된 클레임을 확보하지 못함"
            return render(
                "final_compose",
                root_summary=root or "(요약 없음)",
                child_summaries="\n".join(blocks) or "(검증된 발견 없음)",
                caveats=caveats_text,
                # Not clamped alongside `blocks`: the hints name the exact
                # lines to fix, and dropping them would put the attempt back
                # where the previous one already failed. `_uncited_hints`
                # caps their size at the source for the same reason.
                revision_note="\n".join(revision_hints or [])
                or "(없음 -- 첫 시도)",
            )

        clamp = clamp_prompt(
            model=synth_model,
            allowance=self.assembly_input_allowance,
            render_prompt=render_assembly,
            primary=child_blocks,
            secondary=list(caveats),
            compact=compact_keeping_claims,
            # The root answer is clamped material now (D54). It is still the
            # most protected -- only halved, never dropped -- but it can no
            # longer be paid for by every child block in the prompt.
            anchor=root_answer,
        )
        await self._log_clamp(
            "report_assembly",
            qid,
            clamp,
            self.assembly_input_allowance,
            # Counted over every slot the clamp can cut. The anchor belongs
            # here because a degraded root answer is a join of child answers
            # and carries their markers; the caveats belong here because
            # node summaries mark their caveats too -- D44 found 3 of sample
            # #7's 30 doing it, which is how raw markers once reached the
            # final text. Omitting either slot is the same defect D59 found
            # at `node_reduction`: an "after" that can exceed its "before".
            claims_before=len(
                _distinct_claims(
                    "\n".join(child_blocks), root_answer, "\n".join(caveats)
                )
            ),
        )
        try:
            response = await self.llm_call(
                synth_model,
                clamp.prompt,
                max_tokens=self.synthesis_max_tokens,
                client=self.llm_client,
                cassette=self.cassette,
                stage="report_assembly",
            )
        except TokenBudgetExhausted as exc:
            # Falling back to a template is correct -- no empty-handed exit
            # (§6.8) -- but it must not look like success. Every recorded run
            # took this path and nothing said so.
            await self.ledger.log(
                "report_assembly_degraded",
                qid,
                {"reason": _degradation_reason(exc)},
            )
            return self.deterministic_report(
                root_summary,
                child_summaries,
                caveats,
            )
        if not response.text.strip():
            # A blank assembly used to log `synth_pass` and return "" -- the
            # call succeeded, so nothing looked wrong. Measured 2026-08-08
            # (sample #2, `a82648e3`): three blank assemblies, three
            # `synth_pass` events, and a report that was the empty string.
            # S1 counts `synth_pass`, so the one metric that says "an LLM
            # actually wrote a report" was counting reports that did not exist.
            #
            # `report_assembly_degraded` is deliberate rather than a new kind:
            # it is already registered in `_DEGRADATION_KINDS` (ledger.py) and
            # `degradationKind()` (progress.ts), so this reaches the user's
            # screen without touching either copy of that vocabulary.
            await self.ledger.log(
                "report_assembly_degraded",
                qid,
                {"reason": "empty_assembly"},
            )
            return self.deterministic_report(
                root_summary,
                child_summaries,
                caveats,
            )
        await self.ledger.log(
            "synth_pass",
            qid,
            {
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "child_count": len(child_summaries),
            },
        )
        return response.text

    @staticmethod
    def deterministic_report(
        root_summary: NodeSummary | None,
        child_summaries: list[NodeSummary],
        caveats: list[str],
    ) -> str:
        root_answer = (
            root_summary.answer.strip()
            if root_summary is not None and root_summary.answer.strip()
            else "검증된 요약을 확보하지 못했습니다."
        )
        body = "\n\n".join(
            f"### {child.question_id}\n{child.answer}"
            for child in child_summaries
            if child.answer.strip()
        ) or root_answer
        limitations = [*caveats, "전체 심층분석 토큰 상한에 도달했습니다."]
        return (
            f"## 요약\n{root_answer}\n\n"
            f"## 본문\n{body}\n\n"
            "## 한계와 미확인 사항\n"
            + "\n".join(f"- {item}" for item in limitations)
            + "\n\n## 출처\n"
        )

    async def reduce_node(
        self, question, child_summaries: list[NodeSummary]
    ) -> NodeSummary:
        """Summarize ONE node from its own verified claims + direct
        children's NodeSummary.answer strings only (never grandchild raw
        claims). This bounded per-node context is the AC-a invariant.
        """
        pairs = await self.ledger.verified_claims(question.id)
        claim_lines = []
        for claim, evidence_rows in pairs:
            ev = " ".join(
                f"<evidence>{row.excerpt}</evidence>" for row in evidence_rows
            )
            claim_lines.append(
                f"[C:{claim.id}] {claim.text} (conf {claim.confidence}) {ev}"
            )
        child_lines = [
            f"[{c.question_id}] {c.answer}" for c in child_summaries
        ]
        synth_model = resolve_harness_model("synth").model

        def render_node(
            claims: list[str], children: list[str], _anchor: str = ""
        ) -> str:
            # `reduce_node` passes no anchor -- the question text is tiny and
            # must never shrink, so it stays outside the clamp entirely.
            return render(
                "node_summary",
                question_id=question.id,
                question_text=question.text,
                verified_claims="\n".join(claims) or "(없음)",
                child_summaries="\n".join(children) or "(없음)",
            )

        # BUDGET2: the budget-aware allowance, not the static one. See
        # `effective_reduction_allowance` -- clamping to a number the tier can
        # no longer grant is what turned two of every three reductions into an
        # `input_bound` degradation.
        allowance = self.effective_reduction_allowance()
        clamp = clamp_prompt(
            model=synth_model,
            allowance=allowance,
            render_prompt=render_node,
            primary=claim_lines,
            secondary=child_lines,
            compact=compact_keeping_claims,
        )
        await self._log_clamp(
            "node_reduction",
            question.id,
            clamp,
            allowance,
            # Reductions carry markers too, and a marker lost here never
            # reaches the assembly to be lost there -- attributing the drop
            # to the report tier requires ruling this tier out first.
            #
            # `child_lines` belongs here and was missing (D59). It is the
            # other half of what `render_node` puts in the prompt and it
            # carries the children's markers, so leaving it out produced an
            # "after" larger than its "before" (35 -> 90 across sample #14)
            # and made the whole reduction-tier reading unusable.
            claims_before=len(
                _distinct_claims("\n".join(claim_lines), "\n".join(child_lines))
            ),
        )
        prompt = clamp.prompt
        # BUDGET2's guard. Clamping to a shrinking tier is right up to the
        # point where it strips every claim address out of the prompt: past
        # that the model can still write fluent prose, but nothing it writes
        # is citable, and an uncitable summary is *worse* than degrading --
        # `_degraded_summary` joins the same claims with their `[C:...]`
        # markers intact and deterministically. Spending a reservation to
        # replace citable text with uncitable text is the silent-failure
        # shape this repo keeps paying for (§3.2), so the guard reports a
        # named reason instead of a fluent answer.
        #
        # Only fires when input carried claims and the clamped prompt carries
        # none: a genuinely claim-free node (no verified claims, no cited
        # children) has nothing to lose and goes to the model as before.
        had_claims = _distinct_claims(
            "\n".join(claim_lines), "\n".join(child_lines)
        )
        if had_claims and not _distinct_claims(prompt):
            return await self._degraded_summary(
                question,
                child_summaries,
                "reduction_allowance_below_claim_floor",
                pairs,
            )
        try:
            data, resp = await self.json_call(
                synth_model,
                prompt,
                max_tokens=self.synthesis_max_tokens,
                client=self.llm_client,
                cassette=self.cassette,
                stage="node_reduction",
            )
        except TokenBudgetExhausted as exc:
            return await self._degraded_summary(
                question, child_summaries, _degradation_reason(exc), pairs
            )
        except Exception:
            return await self._degraded_summary(
                question,
                child_summaries,
                "node_summary_unparseable",
                pairs,
            )
        # Read before logging, because the two counts below need it (CITE1).
        answer = str(data.get("answer") or "")
        await self.ledger.log(
            "node_summary",
            question.id,
            {
                "input_tokens": resp.input_tokens,
                "prompt_chars": len(prompt),
                "child_count": len(child_summaries),
                "own_claims": len(pairs),
                # CITE1. D91 put the citation-production loss in this tier
                # and could go no further: it ruled out the clamp (1 of 27
                # non-root clamps cut a claim) and showed the assembly gets
                # exactly what the root reduction got, but `NodeSummary.
                # answer` is persisted nowhere, so no stored data could say
                # whether the model carried its markers into the prose.
                #
                # These two answer that. `prompt` rather than `claim_lines`
                # is the denominator on purpose: the model may cite anything
                # it was shown, including a child answer's markers, and it
                # matches `distinct_claims_after` at `finalization_prompt_
                # clamped` -- so a clamped reduction reports the same number
                # twice and the two instruments check each other. An
                # unclamped one now reports it at all, which is new.
                "distinct_claims_prompt": len(_distinct_claims(prompt)),
                "distinct_claims_answer": len(_distinct_claims(answer)),
            },
        )
        conflicts: list[ConflictNote] = []
        for c in data.get("conflicts", []) or []:
            try:
                conflicts.append(
                    ConflictNote(
                        claim_a=c["claim_a"],
                        claim_b=c["claim_b"],
                        nature=c.get("nature", ""),
                    )
                )
            except (KeyError, TypeError, AttributeError):
                # malformed conflict entry (missing keys / wrong shape) --
                # skip it rather than crashing the whole node's summary.
                continue
        try:
            confidence = float(data.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        key_claim_ids_raw = data.get("key_claim_ids") or []
        try:
            key_claim_ids = list(key_claim_ids_raw)
        except TypeError:
            key_claim_ids = []
        caveats_raw = data.get("caveats") or []
        try:
            caveats = list(caveats_raw)
        except TypeError:
            caveats = []
        return NodeSummary(
            question_id=question.id,
            answer=answer,
            key_claim_ids=key_claim_ids,
            confidence=confidence,
            caveats=caveats,
            conflicts=conflicts,
        )

    def _bound_degraded_answer(self, answer: str) -> str:
        """Cut a degraded join down to the ceiling a real answer obeys.

        The ceiling is `synthesis_max_tokens` -- the same number that caps
        `reduce_node`'s output -- measured with `prompt_input_bound`, the
        ruler `reserve()` charges with. Halving rather than a computed cut:
        it is scale-free, converges in O(log n) regardless of how oversized
        the join is, and needs no chars-per-token constant (Korean and Latin
        text differ by ~3x, so any such constant would be wrong for one of
        them).

        The cut is pulled back to a whitespace boundary, and a `[C:` left
        dangling by the cut is removed: a half-written marker matches neither
        `_RAW_MARKER` nor the renderer's lookup, so it would survive into the
        report as literal text where a citation belongs.
        """

        synth_model = resolve_harness_model("synth").model
        ceiling = self.synthesis_max_tokens
        text = answer
        while text and prompt_input_bound(synth_model, text) > ceiling:
            text = text[: len(text) // 2]
        if len(text) == len(answer):
            return answer
        cut = text.rsplit(" ", 1)[0] if " " in text else text
        return _DANGLING_MARKER.sub("", cut).rstrip()

    async def _degraded_summary(
        self,
        question,
        child_summaries: list[NodeSummary],
        reason: str,
        pairs: list | None = None,
    ) -> NodeSummary:
        """Fall back to joining the children's answers, and say so.

        This degradation predates the ledger entry and left no trace, so a
        run whose reductions all degraded was byte-identical to one where
        they all succeeded. That distinction is exactly what tells whether
        isolating the report tier worked: reductions are allowed to degrade,
        the assembly is not.

        `pairs` is the node's own verified claims, and it exists because
        joining children is not a fallback for a **leaf**: a leaf has no
        children, so the join produced `""` and the leaf's verified claims
        vanished. Measured 2026-08-07: most degraded reductions were leaves
        (8 of 10, 11 of 14, 8 of 11 ...), the runs that degraded 67-79% of
        their reductions shipped 0-8 citation markers, and the one that
        degraded 18% shipped 60. With nothing to cite the report gate
        rejected all 18 attempts.

        The deterministic answer keeps `[C:...]` markers so CitationRenderer
        can still resolve them -- these are verified claims by construction,
        so they cannot orphan. It deliberately drops the prompt scaffolding
        (evidence excerpts, confidence) that `reduce_node` builds for the
        model: that is input for an LLM, not prose for a reader.

        **The join is bounded** (D54). It stands in for an answer an LLM
        would have written under a `synthesis_max_tokens` output ceiling, and
        it was the one path in the tree that respected no ceiling at all: a
        degraded parent joins its children's answers, and a degraded child's
        answer is itself such a join, so the text accumulates up the tree.
        Sample #11's `7aa21c7f` degraded 12 reductions and **the last was the
        root** -- its answer became most of the subtree, ~5,800-12,200 input
        tokens against an assembly allowance of 6,000. `shrink_once` refuses
        to drop the root answer, so the assembly clamp dropped every child
        block and every caveat and still did not fit (12 of 12 clamps
        `exhausted`), which starved the report of the very claims it had to
        cite and made attempt 1 fail its reservation outright. The retry loop
        had never run.
        """
        answer = " ".join(
            c.answer for c in child_summaries if c.answer.strip()
        )
        claim_ids: list[str] = []
        # Which branch ran is not recoverable after the fact, and that cost a
        # measurement (CITE1). `answer_chars` is logged *below* this
        # reassignment, so a non-zero value says nothing about which text it
        # counted -- backtesting #21/#22 could only bound the own-claims drop,
        # never measure it, and the bound was loose enough to be useless (one
        # run's "at risk" set was its entire claim inventory while 14 of 17
        # markers demonstrably reached the assembly).
        answer_source = "children_join" if answer else "empty"
        if not answer and pairs:
            answer = " ".join(
                f"[C:{claim.id}] {claim.text}" for claim, _evidence in pairs
            )
            claim_ids = [claim.id for claim, _evidence in pairs]
            answer_source = "own_claims"
        bounded = self._bound_degraded_answer(answer)
        await self.ledger.log(
            "node_reduction_degraded",
            question.id,
            {
                "question_id": question.id,
                "child_count": len(child_summaries),
                "reason": reason,
                # The cascade is invisible without these: a degraded root is
                # byte-identical in the ledger whether its join was 400 chars
                # or 40,000, and the latter is what breaks the assembly.
                "answer_chars": len(answer),
                "answer_truncated": len(bounded) < len(answer),
                "answer_source": answer_source,
                # `children_join` with own claims present is the silent drop:
                # this node had verified claims and joined its children
                # instead, so those markers end here. Recording what was
                # available -- not just what was used -- is what makes the
                # drop countable rather than inferable.
                "own_claims_available": len(pairs or []),
                # Bounding halves until it fits, and halving takes markers
                # with it. Separated from the join so a truncation loss is
                # not read as a join loss: they need different fixes.
                "distinct_claims_before_bound": len(_distinct_claims(answer)),
                "distinct_claims_after_bound": len(_distinct_claims(bounded)),
            },
        )
        answer = bounded
        return NodeSummary(
            question_id=question.id,
            answer=answer,
            key_claim_ids=claim_ids,
            confidence=0.0,
            caveats=[reason],
            conflicts=[],
        )

    async def reduce_tree(self, root_id: str) -> dict[str, NodeSummary]:
        """Post-order reduce over the question tree rooted at `root_id`.

        Leaves are reduced first, then parents using only their direct
        children's `NodeSummary` (never grandchild raw claims) -- this
        keeps each node's LLM context bounded regardless of subtree size
        (AC-a). `abandoned` questions are excluded entirely (no summary
        is produced for them, nor are they passed to their parent).
        """
        summaries: dict[str, NodeSummary] = {}
        visited: set[str] = set()

        async def visit(qid: str) -> None:
            if qid in visited:
                # cycle / diamond re-encounter -- already reduced (or in
                # progress); skip to avoid unbounded recursion.
                return
            visited.add(qid)
            children = [
                child
                for child in await self.ledger.children(qid)
                if child.status != "abandoned"
            ]
            child_summaries: list[NodeSummary] = []
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
