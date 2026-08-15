import re

from neos.workflow.contracts import NODE_CONTRACTS
from neos.workflow.topology import validate_topology
from neos.workflow.topology_export import static_topology

# ============================================================================
# 알려진 위반 7개 -- "이렇게 생겨야 하는 그래프"가 아니라 "아직 안 고친 실제
# 프로덕션 버그 목록"이다. 이 세트가 줄어들면(누군가 고쳤다는 뜻) 이 파일을
# 의도적으로 편집해야 하고, 늘어나면(새 배선이 새 위반을 만들었다는 뜻) 그
# 자체로 실패해야 한다 -- 그래서 정확히 이 집합과만 같은지 비교한다(부분집합
# 검사가 아니다).
#
# 두 개의 독립된 근본 원인:
#
# 1. `response_generator` 3개 -- `skill_tool_selector`의 `skip_orchestrators`
#    빠른 경로(검색/분석/생성 에이전트가 전혀 필요 없는 단순 대화, 예:
#    "안녕하세요")가 `search_results`/`analysis_results`/`generation_results`
#    가 전부 빈 채로 `response_generator`에 곧장 들어간다. 이 경로는
#    `final_response`를 미리 채워 두지 않으므로 `_preserve_existing_response`
#    분기로 빠지지 않고 정상 생성 분기를 타는데,
#    `_construct_final_response([], ...)`(response_generator.py:193)는
#    `response_parts`가 비면 "죄송합니다 ... 관련 정보를 찾지 못했습니다"
#    사과 메시지를 반환한다 -- 검색이 애초에 필요 없었던 질의에도 "못 찾음"
#    응답이 나간다. 사용자에게 그대로 노출되는 프로덕션 버그다.
#
# 2. `result_integrator` 1개 + `quality_validator` 3개 -- `RECURSIVE_ORCHESTRATOR`
#    / `HYPER_DEEP_ORCHESTRATOR` → `RESULT_INTEGRATOR` 엣지가, ROMA/HyperDeep
#    이 절대 쓰지 않는 레거시 필드(`search_results`/`analysis_results`/
#    `generation_results`)에 의존하는 `result_integrator`/`quality_validator`
#    로 그대로 흘러 들어간다. 두 처리기 모두 `final_response`가 이미 있는지
#    확인하는 분기가 없어(result_processor.py:15,
#    quality_validator.py:16) 빈 데이터로 `integrated_results`/`quality_score`
#    를 다시 계산하고, 점수가 낮으면 ROMA/HyperDeep이 이미 끝낸 뒤에도
#    레거시 검색→분석→생성 파이프라인 전체를 불필요하게 재실행할 수 있다.
#
# 두 원인 다 그래프 배선(엣지) 또는 처리기 로직을 바꿔야 하는 프로덕션 동작
# 변경이라 이 태스크 범위 밖에 남겨 뒀다. 전체 근거·추적은
# `.superpowers/sdd/2026-08-15-subagent-graph-engineering-loop/task-5-report.md`
# "Fix round 1" 절 참고.
_KNOWN_VIOLATIONS: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("unsatisfied_requires", "response_generator", "analysis_results"),
        ("unsatisfied_requires", "response_generator", "generation_results"),
        ("unsatisfied_requires", "response_generator", "search_results"),
        ("unsatisfied_requires", "result_integrator", "search_results"),
        ("unsatisfied_requires", "quality_validator", "analysis_results"),
        ("unsatisfied_requires", "quality_validator", "generation_results"),
        ("unsatisfied_requires", "quality_validator", "search_results"),
    }
)

# `unsatisfied_requires` 의 `detail` 은 topology.py 에서
# f"...키 '{key}' 가 START 에서..." 형태로 고정돼 있다 -- 그 리터럴 키를
# 뽑아내 (rule, node, key) 3튜플로 정규화한다. `TopologyViolation` 이 key를
# 별도 필드로 노출하지 않으므로 이 파싱이 유일한 추출 경로다.
_REQUIRES_KEY_PATTERN = re.compile(r"키 '([^']+)'")


def _violation_signature(violation) -> tuple[str, str, str]:
    if violation.rule != "unsatisfied_requires":
        # 이 목록은 unsatisfied_requires 전용이다 -- 다른 규칙(unreachable_node
        # 등)이 새로 뜨면 키 추출 없이도 곧바로 눈에 띄어야 한다.
        return (violation.rule, violation.node or "", violation.detail)
    match = _REQUIRES_KEY_PATTERN.search(violation.detail)
    key = match.group(1) if match else violation.detail
    return (violation.rule, violation.node or "", key)


def test_the_static_graph_matches_the_known_violation_set() -> None:
    """정적 그래프는 알려진 위반 7개와 **정확히** 같은 집합을 낸다.

    실패하면 세 갈래다: (1) 새 위반이 나타났다 -- 새 배선이나 계약 변경이
    또 다른 순서 버그를 만들었으니 조사해야 한다. (2) 알려진 위반이
    사라졌다 -- 누군가 위 두 원인 중 하나를 고쳤다는 뜻이니, 이 목록에서
    지워야 할 항목을 고른 의도적 편집이 필요하다(자동으로 초록불이 되면 안
    된다). (3) 둘 다 -- 위반의 성격 자체가 바뀐 것이다.

    이 테스트가 초록불이라고 해서 그래프가 "옳다"는 뜻이 아니다 -- 알려진
    버그 7개가 **여전히, 정확히 이만큼만** 있다는 뜻이다.
    """
    violations = validate_topology(static_topology(), contracts=NODE_CONTRACTS)
    actual = {_violation_signature(v) for v in violations}

    new_violations = actual - _KNOWN_VIOLATIONS
    resolved_violations = _KNOWN_VIOLATIONS - actual

    if not new_violations and not resolved_violations:
        return

    lines = []
    if new_violations:
        lines.append("새로 나타난 위반 (알려진 7개에 없음):")
        lines.extend(
            f"  + {rule} @ {node}: {key}" for rule, node, key in sorted(new_violations)
        )
    if resolved_violations:
        lines.append(
            "알려진 위반 목록에는 있지만 더는 재현되지 않음 "
            "(고쳤다면 _KNOWN_VIOLATIONS 에서 지워야 한다):"
        )
        lines.extend(
            f"  - {rule} @ {node}: {key}"
            for rule, node, key in sorted(resolved_violations)
        )
    raise AssertionError("\n".join(lines))
