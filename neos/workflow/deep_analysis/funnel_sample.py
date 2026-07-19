import statistics
from dataclasses import dataclass


QUESTION_SET_VERSION = "mixed-v1"


@dataclass(frozen=True)
class QuestionCase:
    case_id: str
    category: str
    question: str


QUESTION_CASES = (
    QuestionCase("fact-eu-ai-act", "fact", "As of 2026-07-19, which EU AI Act obligations for providers of general-purpose AI models are already applicable, and on what dates did they begin to apply? Use official EU sources."),
    QuestionCase("fact-aspartame", "fact", "Did WHO or IARC classify aspartame as carcinogenic in 2023, and how does that hazard classification differ from JECFA's risk assessment? Use primary institutional sources."),
    QuestionCase("tech-hybrid-search", "technical", "Compare PostgreSQL 17 and Elasticsearch 8.x for hybrid lexical and vector search, including native capabilities, consistency, ranking controls, and operational trade-offs. Prefer official documentation and primary sources."),
    QuestionCase("tech-free-threading", "technical", "Compare free-threaded CPython 3.13 with the standard GIL build for CPU-bound multithreaded workloads, extension compatibility, and production readiness. Use Python project documentation and primary benchmarks."),
    QuestionCase("policy-london-ulez", "causal_policy", "What measured effects did London's 2023 ULEZ expansion have on roadside air pollution and traffic by July 2026, and which findings support causal attribution rather than simple association? Use official evaluations and peer-reviewed research."),
)

_COUNTER_FIELDS = (
    "proposed",
    "graded",
    "deterministic_passed",
    "deterministic_rejected",
    "agentic_attempted",
    "agentic_passed",
    "agentic_rejected",
    "agentic_skipped",
    "agentic_exhausted",
    "verified",
    "rejected",
    "unverified",
)
_RATE_FIELDS = ("evidence_missing_rate", "source_dead_rate")
_AVERAGE_FIELDS = (
    "avg_evidence_count",
    "avg_source_count",
    "avg_excerpt_chars",
)
_QUOTE_BUCKETS = ("exact", "above_threshold", "near_miss", "low", "unavailable")


def _metric(count: int, denominator: int) -> dict[str, int | float]:
    return {
        "count": max(0, int(count)),
        "denominator": max(0, int(denominator)),
        "rate": max(0, int(count)) / denominator if denominator > 0 else 0.0,
    }


def stage_metrics(funnel: dict) -> dict[str, dict[str, int | float]]:
    proposed = int(funnel.get("proposed", 0))
    graded = int(funnel.get("graded", 0))
    return {
        "proposal_to_grade": _metric(proposed - graded, proposed),
        "deterministic_rejection": _metric(funnel.get("deterministic_rejected", 0), graded),
        "agentic_loss": _metric(funnel.get("agentic_rejected", 0) + funnel.get("agentic_exhausted", 0), graded),
        "final_unresolved": _metric(funnel.get("rejected", 0) + funnel.get("unverified", 0), graded),
    }


def aggregate_funnels(funnels: list[dict]) -> dict:
    combined = {field: sum(int(funnel.get(field, 0)) for funnel in funnels) for field in _COUNTER_FIELDS}
    combined["quote_score_buckets"] = {
        bucket: sum(int(funnel.get("quote_score_buckets", {}).get(bucket, 0)) for funnel in funnels)
        for bucket in _QUOTE_BUCKETS
    }
    graded = combined["graded"]
    for field in (*_RATE_FIELDS, *_AVERAGE_FIELDS):
        weighted_total = sum(float(funnel.get(field, 0.0)) * int(funnel.get("graded", 0)) for funnel in funnels)
        combined[field] = weighted_total / graded if graded else 0.0
    return combined


def dominant_stage(funnel: dict) -> str:
    metrics = stage_metrics(funnel)
    return max(metrics, key=lambda stage: (metrics[stage]["count"], metrics[stage]["rate"]))


def select_representative(observations: list[dict]) -> dict | None:
    completed = [item for item in observations if item["status"] == "completed"]
    if not completed:
        return None
    aggregate = aggregate_funnels([item["signals"]["claim_funnel"] for item in completed])
    stage = dominant_stage(aggregate)
    candidates = [item for item in completed if stage_metrics(item["signals"]["claim_funnel"])[stage]["count"] > 0]
    if not candidates:
        return min(completed, key=lambda item: item["order"])
    median_graded = statistics.median(item["signals"]["claim_funnel"]["graded"] for item in completed)
    selected = min(candidates, key=lambda item: (abs(item["signals"]["claim_funnel"]["graded"] - median_graded), item["order"]))
    return {**selected, "dominant_stage": stage}
