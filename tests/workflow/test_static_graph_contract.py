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
# 2026-08-16 갱신 -- 둘 다 고쳤고, 결과가 대칭이 아니다.
#
# 원인 2(G1-b)는 해소됐다: 두 재귀 경로를 RESULT_INTEGRATOR 가 아니라
# RESP_GENERATOR 로 직행시켰다(둘 다 이미 `final_response` 를 쓴다). 이제
# result_integrator 의 유일한 진입은 generation_orchestrator 뿐이고 그 경로는
# 세 결과를 전부 채우므로, 위반 4건이 아래 목록에서 사라졌다.
#
# 원인 1(G1-a)은 **버그는 고쳤지만 위반은 남는다.** skip 경로에
# `direct_response` 노드를 놓아 사과문 대신 실제 답을 만든다. 그러나
# response_generator 로 들어오는 7개 경로 중 여섯도 같은 세 키를 쓰지 않는데,
# 그것들은 스스로 `final_response` 를 채워 `_preserve_existing_response` 로
# 빠지므로 실제로는 멀쩡하다 -- 계약이 "final_response 가 없을 때만 필요" 라는
# 조건을 표현하지 못해 **진짜 버그와 무해한 경로가 같은 서명**을 낸다. 그래서
# 이 세 건은 지우지 않는다. G1-a 의 수정은
# `tests/workflow/test_direct_response_path.py` 가 행동으로 고정한다.
#
# (아래는 발견 당시 서술이다.) 두 원인 다 그래프 배선(엣지) 또는 처리기
# 로직을 바꿔야 하는 프로덕션 동작 변경이라 그 태스크 범위 밖에 남겨 뒀었다. 전체 근거·추적은
# `.superpowers/sdd/2026-08-15-subagent-graph-engineering-loop/task-5-report.md`
# "Fix round 1" 절 참고.
_KNOWN_VIOLATIONS: frozenset[tuple[str, str, str]] = frozenset(
    {
        # 2026-08-16: G1-b 를 고치면서 4건이 사라졌다 -- result_integrator 1건과
        # quality_validator 3건. 재귀 경로(RECURSIVE/HYPER_DEEP)가 스스로 만든
        # `final_response` 를 두고 레거시 체인에 합류하던 것을 응답 생성기로
        # 직행시켰다. 이제 result_integrator 의 유일한 진입은
        # generation_orchestrator 뿐이고, 그 경로는 세 결과를 전부 채운다.
        #
        # 남은 3건(response_generator)은 **G1-a 를 고쳐도 사라지지 않는다.**
        # 이 노드로 들어오는 7개 경로 중 여섯(task_scheduling, mission_*,
        # execution_approval, self_reflection, direct_response 를 제외한 나머지)
        # 이 같은 세 키를 쓰지 않는데, 그것들은 스스로 `final_response` 를 채워
        # `_preserve_existing_response` 로 빠지므로 실제로는 멀쩡하다. 계약이
        # "final_response 가 없을 때만 필요" 라는 조건을 표현하지 못해서 진짜
        # 버그와 무해한 경로가 같은 서명을 낸다 -- G1-a 의 실제 수정은
        # `tests/workflow/test_direct_response_path.py` 가 행동으로 고정한다.
        # 2026-09-05: 셋을 지웠다. 면제가 아니라 **해소**다 -- 계약이
        # `requires_unless` 로 조건을 표현하게 됐고, 검증기가 진입 경로마다
        # "면제 키 또는 요구 키" 를 검사한다. 실측으로 확인한 것: 진입 간선은
        # 주석이 적던 7개가 아니라 **9개**이고, 그중 여덟이 `final_response` 를
        # 보장하며 나머지 하나(`self_reflection`)는 결과 셋 전부를 보장한다.
        # 즉 아홉 경로 전부가 둘 중 하나를 준다 -- "무해하다" 는 판정은 옳았고
        # 세는 수가 틀렸다.
    }
)

# `TopologyViolation.key` 가 구조화된 필드로 노출하는 값을 그대로 쓴다 --
# 예전에는 `detail` 한국어 문장에서 정규식으로 키를 뽑아냈는데, 그러면 문구를
# 다듬기만 해도 이 핀이 깨질 수 있었다.


def _violation_signature(violation) -> tuple[str, str, str]:
    if violation.rule != "unsatisfied_requires":
        # 이 목록은 unsatisfied_requires 전용이다 -- 다른 규칙(unreachable_node
        # 등)이 새로 뜨면 키 추출 없이도 곧바로 눈에 띄어야 한다.
        return (violation.rule, violation.node or "", violation.detail)
    key = violation.key if violation.key is not None else violation.detail
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
