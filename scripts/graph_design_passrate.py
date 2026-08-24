"""설계자 통과율 표본 — `LlmGraphDesigner`가 실제 모델로 성립하는 토폴로지를 내는가.

사전 등록: `docs/graph_design_passrate_preregistration.md` (커밋 984ceced).
**표본은 정확히 1회 돈다** (§10.2). 실패한 호출도 관측이므로 재시도하지 않는다.

프로덕션 경로와 같은 재료를 쓴다 -- 같은 프롬프트 파일, 같은 카탈로그
(`NODE_CONTRACTS` 전량), 같은 `mandatory`, `budget`/`node_costs` 둘 다 `None`.
다른 것은 하나뿐이다: 여기서는 `validate_topology` 를 직접 불러 위반 목록을
**보존**한다(프로덕션은 위반이 있으면 버리고 정적으로 폴백한다). L-2(거부 사유
분포)가 그 목록을 필요로 한다.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from neos.config.model_routing import resolve_model  # noqa: E402
from neos.config.settings import settings  # noqa: E402
from neos.utils.llm_factory import LLMFactory  # noqa: E402

# 🔴 이 import 가 카탈로그를 채운다. `NODE_CONTRACTS` 는 `@node_contract` 데코레이터가
# 클래스 정의 시점에 등록하는 dict 라, `neos.workflow.graph` 를 import 하지 않으면
# **비어 있다**. 없이 돌리면 모델에게 "빈 목록에서 노드를 고르라"고 요구하는 셈이고,
# 그 결과 나오는 통과율 0% 를 "모델이 못 한다" 로 오독하게 된다. dry-run 이
# 잡았다 -- 표본은 1회뿐이라 이 한 줄이 표본 전체를 좌우한다.
import neos.workflow.graph  # noqa: E402,F401 -- 부수효과로 NODE_CONTRACTS 를 채운다
from neos.workflow.contracts import NODE_CONTRACTS  # noqa: E402
from neos.workflow.enums import WorkflowNode  # noqa: E402
from neos.workflow.graph_designer import DesignRequest, InvalidDesignPayload  # noqa: E402
from neos.workflow.graph_designer_llm import LlmGraphDesigner  # noqa: E402
from neos.workflow.topology import validate_topology  # noqa: E402

# 사전 등록 §3: 유형 넷 × 5개. 내가 만든 질의라 대표성은 없다 -- 그 편향은
# 사전 등록 §3에 적혀 있고 판정과 함께 인용해야 한다.
QUERIES: tuple[tuple[str, str], ...] = (
    # 대화형 -- 검색도 분석도 필요 없는 것
    ("conversational", "안녕하세요, 오늘 기분이 어때요?"),
    ("conversational", "당신은 무엇을 할 수 있나요?"),
    ("conversational", "고마워요, 도움이 됐어요."),
    ("conversational", "방금 한 말을 더 짧게 요약해 줄래요?"),
    ("conversational", "당신의 이름은 무엇인가요?"),
    # 검색형 -- 외부 사실을 가져와야 하는 것
    ("search", "2026년 한국의 최저임금은 얼마인가요?"),
    ("search", "최근 발표된 pgvector 최신 버전과 주요 변경점을 알려줘"),
    ("search", "OpenAI 와 Anthropic 의 최신 모델 가격을 비교해줘"),
    ("search", "서울시 전기차 보조금 신청 방법을 알려줘"),
    ("search", "LangGraph 1.0 의 체크포인터 API 가 어떻게 바뀌었나요?"),
    # 분석형 -- 가져온 것을 판단해야 하는 것
    ("analysis", "우리 회사가 Kubernetes 로 옮기는 게 타당한지 분석해줘"),
    ("analysis", "이 주장이 사실인가: 재택근무가 생산성을 20% 높인다"),
    ("analysis", "Rust 와 Go 중 어느 쪽이 우리 백엔드에 맞는지 판단해줘"),
    ("analysis", "전기차 배터리 가격 하락 추세가 2030년까지 이어질까?"),
    ("analysis", "이 코드베이스의 순환 의존성 문제를 어떻게 봐야 하나?"),
    # 복합 -- 검색·분석·생성이 모두 필요한 것
    ("composite", "경쟁사 세 곳의 가격 정책을 조사하고 우리 전략을 제안해줘"),
    ("composite", "AI 규제 동향을 조사해서 우리 제품 로드맵에 미칠 영향을 보고서로 써줘"),
    ("composite", "최근 벡터 DB 벤치마크를 찾아보고 우리 스택 교체 여부를 판단해 문서로 정리해줘"),
    ("composite", "국내 핀테크 규제를 조사하고 리스크를 정리한 뒤 대응 계획을 세워줘"),
    ("composite", "기후 정책 논문 몇 편을 찾아 요약하고 상충하는 주장을 정리해줘"),
)


def _fingerprint(model_name: str, provider: str, prompt_path: Path) -> dict:
    """§10.2 가 요구하는 구성 지문. 이 표본이 무엇으로 돌았는지 복원 가능해야 한다."""

    return {
        "model": model_name,
        "provider": provider,
        "catalog_size": len(NODE_CONTRACTS),
        "timeout_sec": settings.config.workflow.graph_design_timeout_sec,
        "budget_hint": settings.config.workflow.graph_design_budget_hint,
        "mandatory": [WorkflowNode.RESP_GENERATOR.value],
        "prompt_sha256": hashlib.sha256(prompt_path.read_bytes()).hexdigest()[:16],
        "validate_budget": None,
        "validate_node_costs": None,
    }


async def main() -> int:
    started = datetime.now(timezone.utc)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    out = Path("artifacts/graph-design-passrate") / stamp
    (out / "responses").mkdir(parents=True, exist_ok=True)

    provider = settings.LLM_PROVIDER
    model_name = resolve_model(
        config=settings.config.model_routing,
        provider=provider,
        role="everyday",
        feature_override=settings.config.workflow.graph_design_model,
    ).model
    prompt_path = Path("neos/workflow/prompts/graph_design.md")

    llm = LLMFactory.create_llm(provider=provider, model=model_name)
    designer = LlmGraphDesigner(model=llm, prompt_path=prompt_path)
    catalog = tuple(NODE_CONTRACTS.values())
    mandatory = (WorkflowNode.RESP_GENERATOR.value,)

    print(f"model={model_name} provider={provider} catalog={len(catalog)}")
    print(f"artifacts -> {out}\n")

    verdicts = []
    for i, (kind, query) in enumerate(QUERIES, 1):
        record: dict = {"n": i, "kind": kind, "query": query}
        try:
            topology = await designer.design(
                DesignRequest(
                    query=query,
                    catalog=catalog,
                    budget=settings.config.workflow.graph_design_budget_hint,
                )
            )
        except InvalidDesignPayload as exc:
            record |= {"outcome": "parse_failed", "detail": str(exc)[:400]}
        except TimeoutError:
            record |= {"outcome": "timeout"}
        except Exception as exc:  # noqa: BLE001 -- 관측 대상이다. 삼키지 않고 적는다.
            record |= {"outcome": "error", "detail": f"{type(exc).__name__}: {exc}"[:400]}
        else:
            violations = validate_topology(
                topology, contracts=NODE_CONTRACTS, mandatory=mandatory,
                budget=None, node_costs=None,
            )
            record |= {
                "outcome": "approved" if not violations else "rejected",
                "nodes": list(topology.nodes),
                "node_count": len(topology.nodes),
                "edge_count": len(topology.edges),
                "violations": [
                    {"rule": v.rule, "node": v.node, "detail": v.detail[:200]}
                    for v in violations
                ],
            }
            (out / "responses" / f"{i:02d}-{kind}.json").write_text(
                json.dumps(
                    {"nodes": list(topology.nodes), "edges": [list(e) for e in topology.edges]},
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )

        verdicts.append(record)
        mark = {"approved": "OK  ", "rejected": "REJ ", "parse_failed": "PARSE",
                "timeout": "TIME", "error": "ERR "}[record["outcome"]]
        extra = ""
        if record["outcome"] == "rejected":
            extra = f" ({len(record['violations'])}건: " + ",".join(
                sorted({v["rule"] for v in record["violations"]})
            ) + ")"
        elif record["outcome"] == "approved":
            extra = f" ({record['node_count']} nodes)"
        print(f"  {mark} {i:2d}/{len(QUERIES)} [{kind}]{extra}")

    ended = datetime.now(timezone.utc)
    approved = sum(1 for v in verdicts if v["outcome"] == "approved")

    (out / "queries.json").write_text(
        json.dumps([{"kind": k, "query": q} for k, q in QUERIES], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out / "verdicts.json").write_text(
        json.dumps(verdicts, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "preregistration_commit": "984ceced",
                "preregistration": "docs/graph_design_passrate_preregistration.md",
                "pid": os.getpid(),
                "utc_start": started.isoformat(),
                "utc_end": ended.isoformat(),
                "exit_status": 0,
                "sample_size": len(QUERIES),
                "approved": approved,
                "pass_rate": round(approved / len(QUERIES), 4),
                "config_fingerprint": _fingerprint(model_name, provider, prompt_path),
            },
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )

    print(f"\nL-1 통과율: {approved}/{len(QUERIES)} = {approved / len(QUERIES):.1%}")
    print(f"기대 <30% / 반증 >=50% (사전 등록 984ceced)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
