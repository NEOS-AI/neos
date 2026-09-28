"""Postgres JSON store for GEPA opt. Raw SQL, same session shape as lessons."""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from sqlalchemy import text

SessionFactory = Callable[[], Awaitable[Any]]


def _with_subscores(
    candidate_rows: Sequence[Mapping[str, Any]],
    score_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, str], list[float]] = {}
    for row in score_rows:
        key = (int(row["iteration"]), str(row["proposal_kind"]))
        grouped.setdefault(key, []).append(float(row["score"]))
    built = [_candidate_row(row) for row in candidate_rows]
    for candidate in built:
        candidate["val_subscores"] = grouped.get(
            (int(candidate["iteration"]), str(candidate["proposal_kind"]))
        )
    return built


def _candidate_row(row: Mapping[str, Any]) -> dict[str, Any]:
    components = row["components"]
    if isinstance(components, str):
        components = json.loads(components)
    return {
        "proposal_kind": row["proposal_kind"],
        "components": {str(key): str(value) for key, value in dict(components).items()},
        "accepted": bool(row["accepted"]),
        "reject_reason": row["reject_reason"],
        "val_mean": row["val_mean"],
        "test_mean": row["test_mean"],
        "val_subscores": None,
        "iteration": int(row["iteration"]),
    }


def _example_item(row: Mapping[str, Any]) -> dict[str, Any]:
    """Copy the JSON payload and attach the example id column the scorer needs."""
    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    item = dict(payload)
    item["example_id"] = str(row["example_id"])
    item["split"] = str(row["split"])
    return item


def _mapping(row: Any) -> dict[str, Any]:
    if row is None:
        raise LookupError("gepa opt row is missing for this owner")
    if isinstance(row, Mapping):
        return dict(row)
    return dict(row._mapping)


class GepaOptStore:
    """Every method filters on owner_namespace. A read by id alone is not offered."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def insert_run_with_seed(
        self,
        *,
        run_id: str,
        owner_namespace: str,
        surface: str,
        engine_label: str,
        pareto_enabled: bool,
        max_evals: int,
        max_token_cost: int,
        seed_components: Mapping[str, str],
        examples: Sequence[Mapping[str, Any]],
    ) -> str:
        """Insert the run, the seed candidate, then point seed_candidate_id at it."""
        candidate_id = str(uuid.uuid4())
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        INSERT INTO gepa_opt_runs (
                            run_id, owner_namespace, surface, engine_label,
                            pareto_enabled, merge_enabled, status, max_evals, max_token_cost
                        ) VALUES (
                            :run_id, :owner_namespace, :surface, :engine_label,
                            :pareto_enabled, false, 'queued', :max_evals, :max_token_cost
                        )
                        """
                    ),
                    {
                        "run_id": run_id,
                        "owner_namespace": owner_namespace,
                        "surface": surface,
                        "engine_label": engine_label,
                        "pareto_enabled": pareto_enabled,
                        "max_evals": max_evals,
                        "max_token_cost": max_token_cost,
                    },
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO gepa_opt_candidates (
                            candidate_id, run_id, owner_namespace, iteration,
                            proposal_kind, components, accepted
                        ) VALUES (
                            :candidate_id, :run_id, :owner_namespace, 0,
                            'seed', CAST(:components AS jsonb), true
                        )
                        """
                    ),
                    {
                        "candidate_id": candidate_id,
                        "run_id": run_id,
                        "owner_namespace": owner_namespace,
                        "components": json.dumps(dict(seed_components)),
                    },
                )
                await session.execute(
                    text(
                        """
                        UPDATE gepa_opt_runs
                        SET seed_candidate_id = :candidate_id, updated_at = now()
                        WHERE run_id = :run_id AND owner_namespace = :owner_namespace
                        """
                    ),
                    {
                        "candidate_id": candidate_id,
                        "run_id": run_id,
                        "owner_namespace": owner_namespace,
                    },
                )
                for ordinal, example in enumerate(examples):
                    await session.execute(
                        text(
                            """
                            INSERT INTO gepa_opt_examples (
                                example_id, run_id, owner_namespace, split, ordinal, payload
                            ) VALUES (
                                :example_id, :run_id, :owner_namespace, :split, :ordinal,
                                CAST(:payload AS jsonb)
                            )
                            """
                        ),
                        {
                            "example_id": str(example.get("example_id") or uuid.uuid4()),
                            "run_id": run_id,
                            "owner_namespace": owner_namespace,
                            "split": example["split"],
                            "ordinal": ordinal,
                            "payload": json.dumps(dict(example["payload"])),
                        },
                    )
        return candidate_id

    async def claim(self, run_id: str, owner_namespace: str, celery_task_id: str) -> str:
        """Move queued -> running. Same task id on a running row resumes. Else lost."""
        async with await self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text(
                        """
                        UPDATE gepa_opt_runs
                        SET status = 'running', celery_task_id = :celery_task_id, updated_at = now()
                        WHERE run_id = :run_id
                          AND owner_namespace = :owner_namespace
                          AND status = 'queued'
                          AND celery_task_id IS NULL
                        """
                    ),
                    {
                        "run_id": run_id,
                        "owner_namespace": owner_namespace,
                        "celery_task_id": celery_task_id,
                    },
                )
                if int(getattr(result, "rowcount", 0) or 0) > 0:
                    return "claimed"
                found = await session.execute(
                    text(
                        """
                        SELECT status, celery_task_id
                        FROM gepa_opt_runs
                        WHERE run_id = :run_id AND owner_namespace = :owner_namespace
                        """
                    ),
                    {"run_id": run_id, "owner_namespace": owner_namespace},
                )
        row = found.mappings().first() if hasattr(found, "mappings") else None
        if (
            row is not None
            and row["status"] == "running"
            and row["celery_task_id"] == celery_task_id
        ):
            return "resume"
        return "lost"

    async def commit_iteration(
        self,
        *,
        run_id: str,
        owner_namespace: str,
        candidate: Mapping[str, Any],
        scores: Sequence[Mapping[str, Any]],
        advance_cursor: bool,
        best_candidate_id: str | None,
        evals_used: int | None = None,
        tokens_used: int | None = None,
        wins_best: bool = False,
    ) -> str:
        """Insert one proposal and its scores, then bump iteration, in one transaction."""
        candidate_id = str(candidate.get("candidate_id") or uuid.uuid4())
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        INSERT INTO gepa_opt_candidates (
                            candidate_id, run_id, owner_namespace, parent_id, iteration,
                            proposal_kind, components, accepted, reject_reason, val_mean, test_mean
                        ) VALUES (
                            :candidate_id, :run_id, :owner_namespace, :parent_id, :iteration,
                            :proposal_kind, CAST(:components AS jsonb), :accepted, :reject_reason,
                            :val_mean, :test_mean
                        )
                        """
                    ),
                    {
                        "candidate_id": candidate_id,
                        "run_id": run_id,
                        "owner_namespace": owner_namespace,
                        "parent_id": candidate.get("parent_id"),
                        "iteration": candidate["iteration"],
                        "proposal_kind": candidate["proposal_kind"],
                        "components": json.dumps(dict(candidate["components"])),
                        "accepted": candidate["accepted"],
                        "reject_reason": candidate.get("reject_reason"),
                        "val_mean": candidate.get("val_mean"),
                        "test_mean": candidate.get("test_mean"),
                    },
                )
                await self._insert_scores(session, candidate_id, owner_namespace, scores)
                await session.execute(
                    text(
                        """
                        UPDATE gepa_opt_runs
                        SET iteration = iteration + 1,
                            component_cursor = component_cursor + CASE WHEN :advance THEN 1 ELSE 0 END,
                            evals_used = COALESCE(:evals_used, evals_used),
                            reflector_tokens_used = COALESCE(:tokens_used, reflector_tokens_used),
                            best_candidate_id = CASE
                                WHEN :wins_best THEN :candidate_id
                                ELSE COALESCE(:best_candidate_id, best_candidate_id)
                            END,
                            updated_at = now()
                        WHERE run_id = :run_id AND owner_namespace = :owner_namespace
                        """
                    ),
                    {
                        "advance": advance_cursor,
                        "best_candidate_id": best_candidate_id,
                        "evals_used": evals_used,
                        "tokens_used": tokens_used,
                        "wins_best": wins_best,
                        "candidate_id": candidate_id,
                        "run_id": run_id,
                        "owner_namespace": owner_namespace,
                    },
                )
        return candidate_id

    async def record_seed_evaluation(
        self,
        *,
        run_id: str,
        owner_namespace: str,
        candidate_id: str,
        val_mean: float | None,
        scores: Sequence[Mapping[str, Any]],
        evals_used: int,
        tokens_used: int,
    ) -> None:
        """Store the seed val scores and mark that candidate best when none is set."""
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        UPDATE gepa_opt_candidates
                        SET val_mean = :val_mean
                        WHERE candidate_id = :candidate_id AND owner_namespace = :owner_namespace
                        """
                    ),
                    {
                        "val_mean": val_mean,
                        "candidate_id": candidate_id,
                        "owner_namespace": owner_namespace,
                    },
                )
                await self._insert_scores(session, candidate_id, owner_namespace, scores)
                await session.execute(
                    text(
                        """
                        UPDATE gepa_opt_runs
                        SET evals_used = :evals_used,
                            reflector_tokens_used = :tokens_used,
                            best_candidate_id = COALESCE(best_candidate_id, :candidate_id),
                            updated_at = now()
                        WHERE run_id = :run_id AND owner_namespace = :owner_namespace
                        """
                    ),
                    {
                        "evals_used": evals_used,
                        "tokens_used": tokens_used,
                        "candidate_id": candidate_id,
                        "run_id": run_id,
                        "owner_namespace": owner_namespace,
                    },
                )

    async def advance_cursor(
        self,
        *,
        run_id: str,
        owner_namespace: str,
        evals_used: int,
        tokens_used: int,
    ) -> None:
        """Bump the component cursor with no candidate row."""
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        UPDATE gepa_opt_runs
                        SET component_cursor = component_cursor + 1,
                            evals_used = :evals_used,
                            reflector_tokens_used = :tokens_used,
                            updated_at = now()
                        WHERE run_id = :run_id AND owner_namespace = :owner_namespace
                        """
                    ),
                    {
                        "evals_used": evals_used,
                        "tokens_used": tokens_used,
                        "run_id": run_id,
                        "owner_namespace": owner_namespace,
                    },
                )

    async def record_test_scores(
        self,
        *,
        owner_namespace: str,
        candidate_id: str,
        test_mean: float | None,
        scores: Sequence[Mapping[str, Any]],
    ) -> None:
        """Store held-out test scores for one committed candidate."""
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        UPDATE gepa_opt_candidates
                        SET test_mean = :test_mean
                        WHERE candidate_id = :candidate_id AND owner_namespace = :owner_namespace
                        """
                    ),
                    {
                        "test_mean": test_mean,
                        "candidate_id": candidate_id,
                        "owner_namespace": owner_namespace,
                    },
                )
                await self._insert_scores(session, candidate_id, owner_namespace, scores)

    async def _insert_scores(
        self,
        session: Any,
        candidate_id: str,
        owner_namespace: str,
        scores: Sequence[Mapping[str, Any]],
    ) -> None:
        for score in scores:
            await session.execute(
                text(
                    """
                    INSERT INTO gepa_opt_example_scores (
                        score_id, candidate_id, example_id, owner_namespace,
                        split, phase, score, side_info
                    ) VALUES (
                        :score_id, :candidate_id, :example_id, :owner_namespace,
                        :split, :phase, :score, CAST(:side_info AS jsonb)
                    )
                    """
                ),
                {
                    "score_id": str(uuid.uuid4()),
                    "candidate_id": candidate_id,
                    "example_id": score["example_id"],
                    "owner_namespace": owner_namespace,
                    "split": score["split"],
                    "phase": score["phase"],
                    "score": score["score"],
                    "side_info": json.dumps(dict(score["side_info"])),
                },
            )

    async def load_bundle(self, run_id: str, owner_namespace: str) -> dict[str, Any]:
        """Seed, splits, and budgets for one owner-scoped run."""
        async with await self._session_factory() as session:
            run_result = await session.execute(
                text(
                    """
                    SELECT engine_label, pareto_enabled, max_evals, max_token_cost,
                           component_cursor, seed_candidate_id, surface,
                           iteration, evals_used, reflector_tokens_used
                    FROM gepa_opt_runs
                    WHERE run_id = :run_id AND owner_namespace = :owner_namespace
                    """
                ),
                {"run_id": run_id, "owner_namespace": owner_namespace},
            )
            example_result = await session.execute(
                text(
                    """
                    SELECT example_id, split, payload
                    FROM gepa_opt_examples
                    WHERE run_id = :run_id AND owner_namespace = :owner_namespace
                    ORDER BY split, ordinal
                    """
                ),
                {"run_id": run_id, "owner_namespace": owner_namespace},
            )
            run = _mapping(run_result.mappings().first())
            seed_result = await session.execute(
                text(
                    """
                    SELECT components
                    FROM gepa_opt_candidates
                    WHERE candidate_id = :candidate_id AND owner_namespace = :owner_namespace
                    """
                ),
                {
                    "candidate_id": run["seed_candidate_id"],
                    "owner_namespace": owner_namespace,
                },
            )
            seed_row = _mapping(seed_result.mappings().first())
            example_rows = list(example_result.mappings().all())
            candidate_result = await session.execute(
                text(
                    """
                    SELECT iteration, proposal_kind, components, accepted,
                           reject_reason, val_mean, test_mean
                    FROM gepa_opt_candidates
                    WHERE run_id = :run_id AND owner_namespace = :owner_namespace
                    ORDER BY iteration
                    """
                ),
                {"run_id": run_id, "owner_namespace": owner_namespace},
            )
            candidate_rows = list(candidate_result.mappings().all())
            score_result = await session.execute(
                text(
                    """
                    SELECT c.iteration, c.proposal_kind, s.score
                    FROM gepa_opt_example_scores s
                    JOIN gepa_opt_candidates c ON c.candidate_id = s.candidate_id
                    JOIN gepa_opt_examples e ON e.example_id = s.example_id
                    WHERE s.owner_namespace = :owner_namespace
                      AND c.run_id = :run_id
                      AND s.phase = 'full_val'
                    ORDER BY c.iteration, e.ordinal
                    """
                ),
                {"run_id": run_id, "owner_namespace": owner_namespace},
            )
            score_rows_db = list(score_result.mappings().all())
        seed = seed_row["components"]
        if isinstance(seed, str):
            seed = json.loads(seed)
        grouped: dict[str, list[dict[str, Any]]] = {"train": [], "val": [], "test": []}
        for row in example_rows:
            grouped[str(row["split"])].append(_example_item(row))
        return {
            "seed": {str(key): str(value) for key, value in dict(seed).items()},
            "train": grouped["train"],
            "val": grouped["val"],
            "test": grouped["test"],
            "engine_label": run["engine_label"],
            "pareto_enabled": run["pareto_enabled"],
            "max_evals": run["max_evals"],
            "max_token_cost": run["max_token_cost"],
            "component_cursor": run["component_cursor"],
            "seed_candidate_id": run["seed_candidate_id"],
            "surface": run["surface"],
            "iteration": int(run.get("iteration") or 0),
            "evals_used": int(run.get("evals_used") or 0),
            "reflector_tokens_used": int(run.get("reflector_tokens_used") or 0),
            "candidates": _with_subscores(candidate_rows, score_rows_db),
        }

    async def mark_succeeded(self, run_id: str, owner_namespace: str) -> None:
        """Close a run that staged an overlay."""
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        UPDATE gepa_opt_runs
                        SET status = 'succeeded', finished_at = now(), updated_at = now()
                        WHERE run_id = :run_id AND owner_namespace = :owner_namespace
                        """
                    ),
                    {"run_id": run_id, "owner_namespace": owner_namespace},
                )

    async def fail_run(self, run_id: str, owner_namespace: str, error_code: str) -> None:
        """Mark the run failed. Does not insert an overlay."""
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        UPDATE gepa_opt_runs
                        SET status = 'failed', error_code = :error_code,
                            finished_at = now(), updated_at = now()
                        WHERE run_id = :run_id AND owner_namespace = :owner_namespace
                        """
                    ),
                    {
                        "run_id": run_id,
                        "owner_namespace": owner_namespace,
                        "error_code": error_code,
                    },
                )

    async def stage_overlay(
        self,
        *,
        overlay_id: str,
        owner_namespace: str,
        surface: str,
        candidate_id: str,
        run_id: str,
    ) -> None:
        """Insert a staged overlay. Does not demote an approved row."""
        async with await self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        INSERT INTO gepa_opt_overlays (
                            overlay_id, owner_namespace, surface, status, candidate_id, run_id
                        ) VALUES (
                            :overlay_id, :owner_namespace, :surface, 'staged', :candidate_id, :run_id
                        )
                        """
                    ),
                    {
                        "overlay_id": overlay_id,
                        "owner_namespace": owner_namespace,
                        "surface": surface,
                        "candidate_id": candidate_id,
                        "run_id": run_id,
                    },
                )

    async def approved_components(
        self, owner_namespace: str, surface: str
    ) -> dict[str, str] | None:
        """The one approved overlay for this owner and surface, or None."""
        async with await self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT c.components
                    FROM gepa_opt_overlays o
                    JOIN gepa_opt_candidates c ON c.candidate_id = o.candidate_id
                    WHERE o.owner_namespace = :owner_namespace
                      AND o.surface = :surface
                      AND o.status = 'approved'
                    """
                ),
                {"owner_namespace": owner_namespace, "surface": surface},
            )
        row = result.first() if hasattr(result, "first") else None
        if row is None:
            return None
        components = row[0]
        if isinstance(components, str):
            components = json.loads(components)
        return {str(key): str(value) for key, value in dict(components).items()}

    async def approve(self, overlay_id: str, actor: str, owner_namespace: str) -> None:
        """Archive the current approved row, then approve the staged row."""
        if not actor:
            raise ValueError("approve requires an actor")
        async with await self._session_factory() as session:
            async with session.begin():
                locked = await session.execute(
                    text(
                        """
                        SELECT overlay_id, status
                        FROM gepa_opt_overlays
                        WHERE owner_namespace = :owner_namespace
                          AND (
                            (overlay_id = :overlay_id AND status = 'staged')
                            OR status = 'approved'
                          )
                        ORDER BY overlay_id
                        FOR UPDATE
                        """
                    ),
                    {"owner_namespace": owner_namespace, "overlay_id": overlay_id},
                )
                rows = locked.mappings().all() if hasattr(locked, "mappings") else []
                staged = any(
                    str(row["overlay_id"]) == overlay_id and row["status"] == "staged"
                    for row in rows
                )
                if not staged:
                    raise ValueError("approve requires a staged overlay")
                await session.execute(
                    text(
                        """
                        UPDATE gepa_opt_overlays
                        SET status = 'archived', archived_at = now()
                        WHERE owner_namespace = :owner_namespace
                          AND status = 'approved'
                          AND overlay_id <> :overlay_id
                        """
                    ),
                    {"owner_namespace": owner_namespace, "overlay_id": overlay_id},
                )
                await session.execute(
                    text(
                        """
                        UPDATE gepa_opt_overlays
                        SET status = 'approved', approved_by = :actor, approved_at = now()
                        WHERE overlay_id = :overlay_id
                          AND owner_namespace = :owner_namespace
                          AND status = 'staged'
                        """
                    ),
                    {
                        "actor": actor,
                        "overlay_id": overlay_id,
                        "owner_namespace": owner_namespace,
                    },
                )
