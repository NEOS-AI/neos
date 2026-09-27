"""In-process GEPA search. No database, Celery, or model SDK."""

from __future__ import annotations

import inspect
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from neos.gepa_opt.acceptance import accept_strict_minibatch_sum
from neos.gepa_opt.pareto import select_parent
from neos.gepa_opt.reflect import ParseSkip, cap_side_info, parse_proposal, render_reflection
from neos.gepa_opt.types import Candidate, EngineConfig, validate_candidate

_MINIBATCH = 3


@dataclass
class SearchResult:
    """One search. overlay is set only when status is succeeded."""

    status: str
    error_code: str | None
    candidates: list[dict[str, Any]]
    overlay: dict[str, Any] | None
    component_cursor: int
    iteration: int
    evals_used: int
    reflector_tokens_used: int
    score_rows: list[dict[str, Any]] = field(default_factory=list)


async def run_search(
    *,
    config: EngineConfig,
    seed: Mapping[str, str],
    train: Sequence[Mapping[str, Any]],
    val: Sequence[Mapping[str, Any]],
    test: Sequence[Mapping[str, Any]],
    max_evals: int,
    max_token_cost: int,
    evaluator: Any,
    reflector: Any,
    prior_candidates: Sequence[Mapping[str, Any]] | None = None,
    start_iteration: int = 0,
    evals_used: int = 0,
    tokens_used: int = 0,
) -> SearchResult:
    """Run one GEPA or not-gepa search. The reflector may be sync or async.

    ``prior_candidates`` is the committed frontier. Resume starts at
    ``start_iteration`` and does not score the seed again.
    """
    cursor = config.component_cursor
    candidates: list[dict[str, Any]] = []
    score_rows: list[dict[str, Any]] = []
    seed_components = validate_candidate(seed)
    if prior_candidates is not None:
        candidates = [dict(item) for item in prior_candidates]
        if len(train) == 0:
            return _failed(
                "empty_train", candidates, cursor, start_iteration, evals_used, tokens_used, score_rows
            )
        if config.pareto:
            return await _pareto_loop(
                config=config,
                train=train,
                val=val,
                test=test,
                max_evals=max_evals,
                max_token_cost=max_token_cost,
                evaluator=evaluator,
                reflector=reflector,
                candidates=candidates,
                score_rows=score_rows,
                cursor=cursor,
                evals_used=evals_used,
                tokens_used=tokens_used,
                iteration=start_iteration,
            )
        return _failed(
            "resume_requires_gepa",
            candidates,
            cursor,
            start_iteration,
            evals_used,
            tokens_used,
            score_rows,
        )

    val_scores, val_infos, evals_used = _score_examples(
        evaluator, seed_components, val, evals_used, score_rows, phase="full_val"
    )
    if val and _all_errors(val_infos):
        return _failed(
            _error_name(val_infos),
            candidates,
            cursor,
            0,
            evals_used,
            tokens_used,
            score_rows,
        )

    candidates.append(
        _candidate(
            "seed",
            seed_components,
            accepted=True,
            reject_reason=None,
            val_mean=_mean(val_scores),
            val_subscores=val_scores,
            iteration=0,
        )
    )
    if len(train) == 0:
        return _failed("empty_train", candidates, cursor, 0, evals_used, tokens_used, score_rows)

    if config.pareto:
        return await _pareto_loop(
            config=config,
            train=train,
            val=val,
            test=test,
            max_evals=max_evals,
            max_token_cost=max_token_cost,
            evaluator=evaluator,
            reflector=reflector,
            candidates=candidates,
            score_rows=score_rows,
            cursor=cursor,
            evals_used=evals_used,
            tokens_used=tokens_used,
        )
    return await _oneshot(
        config=config,
        train=train,
        val=val,
        test=test,
        max_token_cost=max_token_cost,
        evaluator=evaluator,
        reflector=reflector,
        candidates=candidates,
        score_rows=score_rows,
        cursor=cursor,
        evals_used=evals_used,
        tokens_used=tokens_used,
    )


async def _pareto_loop(
    *,
    config: EngineConfig,
    train: Sequence[Mapping[str, Any]],
    val: Sequence[Mapping[str, Any]],
    test: Sequence[Mapping[str, Any]],
    max_evals: int,
    max_token_cost: int,
    evaluator: Any,
    reflector: Any,
    candidates: list[dict[str, Any]],
    score_rows: list[dict[str, Any]],
    cursor: int,
    evals_used: int,
    tokens_used: int,
    iteration: int = 0,
) -> SearchResult:
    while evals_used < max_evals and tokens_used < max_token_cost:
        try:
            parent_index = select_parent(*_fronts(candidates, len(val)), random.Random(0))
        except RuntimeError:
            return _failed(
                "empty_front", candidates, cursor, iteration, evals_used, tokens_used, score_rows
            )
        parent = candidates[parent_index]["components"]
        batch = _minibatch_indexes(len(train), iteration)
        parent_scores, parent_infos, evals_used = _score_examples(
            evaluator,
            parent,
            [train[i] for i in batch],
            evals_used,
            score_rows,
            phase="minibatch",
        )
        if parent_scores and min(parent_scores) >= 1.0:
            continue
        if _all_empty(parent_infos):
            continue
        if _all_errors(parent_infos):
            return _failed(
                _error_name(parent_infos),
                candidates,
                cursor,
                iteration,
                evals_used,
                tokens_used,
                score_rows,
            )
        names = sorted(parent)
        component_name = names[cursor % len(names)]
        rendered = render_reflection(parent[component_name], {"examples": parent_infos})
        try:
            reflected = await _call_reflector(
                reflector, component_name, parent[component_name], rendered
            )
        except Exception as exc:
            return _failed(
                type(exc).__name__,
                candidates,
                cursor,
                iteration,
                evals_used,
                tokens_used,
                score_rows,
            )
        usage = reflected.usage
        tokens_used += int(usage.input_tokens) + int(usage.output_tokens)
        parsed = parse_proposal(reflected.text, _finish_reason(reflected))
        if isinstance(parsed, ParseSkip):
            cursor += 1
            continue
        if reflected.delta != {component_name: parsed}:
            return _failed(
                "bad_delta", candidates, cursor, iteration, evals_used, tokens_used, score_rows
            )
        child = dict(parent)
        child[component_name] = parsed
        child_scores, _, evals_used = _score_examples(
            evaluator,
            child,
            [train[i] for i in batch],
            evals_used,
            score_rows,
            phase="minibatch",
        )
        iteration += 1
        cursor += 1
        if accept_strict_minibatch_sum(parent_scores, child_scores):
            full_scores, _, evals_used = _score_examples(
                evaluator, child, val, evals_used, score_rows, phase="full_val"
            )
            candidates.append(
                _candidate(
                    "reflective",
                    child,
                    accepted=True,
                    reject_reason=None,
                    val_mean=_mean(full_scores),
                    val_subscores=full_scores,
                    iteration=iteration,
                )
            )
        else:
            reason = "length_mismatch" if len(parent_scores) != len(child_scores) else "not_strict"
            candidates.append(
                _candidate(
                    "reflective",
                    child,
                    accepted=False,
                    reject_reason=reason,
                    val_mean=None,
                    val_subscores=None,
                    iteration=iteration,
                )
            )
    return _succeed(
        candidates, test, evaluator, cursor, iteration, evals_used, tokens_used, score_rows
    )


async def _oneshot(
    *,
    config: EngineConfig,
    train: Sequence[Mapping[str, Any]],
    val: Sequence[Mapping[str, Any]],
    test: Sequence[Mapping[str, Any]],
    max_token_cost: int,
    evaluator: Any,
    reflector: Any,
    candidates: list[dict[str, Any]],
    score_rows: list[dict[str, Any]],
    cursor: int,
    evals_used: int,
    tokens_used: int,
) -> SearchResult:
    parent = candidates[0]["components"]
    batch = _minibatch_indexes(len(train), 0)
    parent_scores, parent_infos, evals_used = _score_examples(
        evaluator,
        parent,
        [train[i] for i in batch],
        evals_used,
        score_rows,
        phase="minibatch",
    )
    if _all_errors(parent_infos):
        return _failed(
            _error_name(parent_infos), candidates, cursor, 0, evals_used, tokens_used, score_rows
        )
    if _all_empty(parent_infos):
        return _succeed(
            candidates, test, evaluator, cursor, 0, evals_used, tokens_used, score_rows
        )
    names = sorted(parent)
    component_name = names[cursor % len(names)]
    rendered = render_reflection(parent[component_name], {"examples": parent_infos})
    try:
        reflected = await _call_reflector(
            reflector, component_name, parent[component_name], rendered
        )
    except Exception as exc:
        return _failed(
            type(exc).__name__, candidates, cursor, 0, evals_used, tokens_used, score_rows
        )
    usage = reflected.usage
    tokens_used += int(usage.input_tokens) + int(usage.output_tokens)
    if tokens_used > max_token_cost:
        tokens_used = tokens_used
    parsed = parse_proposal(reflected.text, _finish_reason(reflected))
    if isinstance(parsed, ParseSkip) or reflected.delta != {component_name: parsed}:
        code = "bad_delta" if not isinstance(parsed, ParseSkip) else None
        if code == "bad_delta":
            return _failed(
                "bad_delta", candidates, cursor, 0, evals_used, tokens_used, score_rows
            )
        cursor += 1
        return _succeed(
            candidates, test, evaluator, cursor, 0, evals_used, tokens_used, score_rows
        )
    child = dict(parent)
    child[component_name] = parsed
    child_scores, _, evals_used = _score_examples(
        evaluator, child, [train[i] for i in batch], evals_used, score_rows, phase="minibatch"
    )
    if accept_strict_minibatch_sum(parent_scores, child_scores):
        full_scores, _, evals_used = _score_examples(
            evaluator, child, val, evals_used, score_rows, phase="full_val"
        )
        candidates.append(
            _candidate(
                "oneshot",
                child,
                accepted=True,
                reject_reason=None,
                val_mean=_mean(full_scores),
                val_subscores=full_scores,
                iteration=1,
            )
        )
    else:
        reason = "length_mismatch" if len(parent_scores) != len(child_scores) else "not_strict"
        candidates.append(
            _candidate(
                "oneshot",
                child,
                accepted=False,
                reject_reason=reason,
                val_mean=None,
                val_subscores=None,
                iteration=1,
            )
        )
    cursor += 1
    return _succeed(candidates, test, evaluator, cursor, 1, evals_used, tokens_used, score_rows)


def _succeed(
    candidates: list[dict[str, Any]],
    test: Sequence[Mapping[str, Any]],
    evaluator: Any,
    cursor: int,
    iteration: int,
    evals_used: int,
    tokens_used: int,
    score_rows: list[dict[str, Any]],
) -> SearchResult:
    best = _best(candidates)
    if test:
        test_scores, _, _ = _score_examples(
            evaluator, best["components"], test, 0, score_rows, phase="held_out_test"
        )
        best["test_mean"] = _mean(test_scores)
    return SearchResult(
        status="succeeded",
        error_code=None,
        candidates=candidates,
        overlay={"status": "staged", "components": dict(best["components"])},
        component_cursor=cursor,
        iteration=iteration,
        evals_used=evals_used,
        reflector_tokens_used=tokens_used,
        score_rows=score_rows,
    )


def _failed(
    code: str,
    candidates: list[dict[str, Any]],
    cursor: int,
    iteration: int,
    evals_used: int,
    tokens_used: int,
    score_rows: list[dict[str, Any]],
) -> SearchResult:
    return SearchResult(
        status="failed",
        error_code=code,
        candidates=candidates,
        overlay=None,
        component_cursor=cursor,
        iteration=iteration,
        evals_used=evals_used,
        reflector_tokens_used=tokens_used,
        score_rows=score_rows,
    )


def _score_examples(
    evaluator: Any,
    candidate: Candidate,
    examples: Sequence[Mapping[str, Any]],
    evals_used: int,
    score_rows: list[dict[str, Any]],
    *,
    phase: str,
) -> tuple[list[float], list[dict[str, Any]], int]:
    scores: list[float] = []
    infos: list[dict[str, Any]] = []
    for example in examples:
        if phase != "held_out_test":
            evals_used += 1
        try:
            score, info = evaluator(candidate, example)
            payload = dict(info)
        except Exception as exc:
            score = 0.0
            payload = {"error_type": type(exc).__name__}
        payload = cap_side_info(payload)
        scores.append(float(score))
        infos.append(payload)
        score_rows.append(
            {
                "phase": phase,
                "score": float(score),
                "side_info": payload,
                "example": example,
                "components": dict(candidate),
            }
        )
    return scores, infos, evals_used


def _minibatch_indexes(n: int, iteration: int) -> list[int]:
    ids = list(range(n))
    random.Random(0).shuffle(ids)
    if n % _MINIBATCH != 0:
        source = list(ids)
        pad_at = 0
        while len(ids) % _MINIBATCH != 0:
            ids.append(source[pad_at % len(source)])
            pad_at += 1
    start = (iteration * _MINIBATCH) % len(ids)
    return [ids[(start + offset) % len(ids)] for offset in range(_MINIBATCH)]


def _fronts(
    candidates: list[dict[str, Any]], scores_width: int
) -> tuple[dict[int, set[int]], list[float]]:
    means: list[float] = []
    fronts: dict[int, set[int]] = {index: set() for index in range(scores_width)}
    eligible: list[tuple[int, list[float]]] = []
    for index, candidate in enumerate(candidates):
        subs = candidate.get("val_subscores")
        if candidate["accepted"] and subs:
            means.append(sum(subs) / len(subs))
            eligible.append((index, subs))
        else:
            means.append(float("-inf"))
    for val_index in range(scores_width):
        best: float | None = None
        for index, subs in eligible:
            if val_index >= len(subs):
                continue
            score = subs[val_index]
            if best is None or score > best:
                best = score
                fronts[val_index] = {index}
            elif score == best:
                fronts[val_index].add(index)
    return {key: value for key, value in fronts.items() if value}, means


def _candidate(
    kind: str,
    components: Candidate,
    *,
    accepted: bool,
    reject_reason: str | None,
    val_mean: float | None,
    val_subscores: list[float] | None,
    iteration: int,
) -> dict[str, Any]:
    return {
        "proposal_kind": kind,
        "components": dict(components),
        "accepted": accepted,
        "reject_reason": reject_reason,
        "val_mean": val_mean,
        "test_mean": None,
        "val_subscores": val_subscores,
        "iteration": iteration,
    }


def _best(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    ranked = [item for item in candidates if item["val_mean"] is not None]
    return max(ranked, key=lambda item: item["val_mean"])


def _mean(scores: list[float]) -> float | None:
    if not scores:
        return None
    return sum(scores) / len(scores)


def _all_errors(infos: list[dict[str, Any]]) -> bool:
    return bool(infos) and all("error_type" in info for info in infos)


def _all_empty(infos: list[dict[str, Any]]) -> bool:
    return bool(infos) and all(info == {} for info in infos)


def _error_name(infos: list[dict[str, Any]]) -> str:
    for info in infos:
        if "error_type" in info:
            return str(info["error_type"])
    return "error_type"


def _finish_reason(reflected: Any) -> str | None:
    reason = getattr(reflected, "finish_reason", None)
    if reason is None:
        reason = getattr(reflected.usage, "finish_reason", None)
    return reason


async def _call_reflector(
    reflector: Any, component_name: str, curr_param: str, side_info_text: str
) -> Any:
    result = reflector(component_name, curr_param, side_info_text)
    if inspect.isawaitable(result):
        result = await result
    return result
