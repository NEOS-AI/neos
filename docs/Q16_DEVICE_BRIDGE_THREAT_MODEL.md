# Q16 사용자 기기 브리지 — 위협 모델 (지속적 개선)

> **지위:** 살아 있는 문서다. dots 분석 §4 결정 7(2026-09-30): 위협 모델은 **착수 조건이 아니라 지속적 개선**이다.
> 브리지는 READ_ONLY 로 시작했고, **도구 위험 등급을 한 단계 넓히는 커밋은 §3 표에 한 줄을 먼저 더한다.**
> 설계: [Q16_DEVICE_BRIDGE_DESIGN_261001.md](Q16_DEVICE_BRIDGE_DESIGN_261001.md)(결정 B1~B13).

## 1. 지키는 것과 상대

| 지키는 것 | 왜 |
|---|---|
| 사용자 기기의 파일(특히 루트 밖 · 비밀 파일) | 샌드박스와 달리 되돌릴 수 없고, 사람의 사생활이다 |
| 다른 사용자의 기기 | 다중 사용자 서버에서 소유자 경계가 무너지면 사고의 크기가 사용자 수만큼 커진다 |
| 금고의 비밀(Q6) | 풀린 값이 기기로 가는 길이 생기면 금고의 봉인이 의미를 잃는다 |
| 모델의 판단 | 기기에서 온 글은 지시가 아니라 데이터다 |

| 상대 | 할 수 있는 것 |
|---|---|
| 기기 파일에 주입된 글(README·메모·메일 사본) | 모델이 읽는 결과에 지시처럼 보이는 문장을 싣는다 |
| 프롬프트 주입에 넘어간 모델 | 허용된 도구를 엉뚱한 경로·엉뚱한 시점에 부른다 |
| 토큰을 훔친 사람 | 그 사용자의 브리지인 척 붙는다 |
| 다른 NEOS 사용자 | 자기 태스크가 남의 기기에 닿게 하려 한다 |
| 망가진·변조된 브리지 | 선언을 부풀리거나, 답의 모양·크기·이유 코드를 속인다 |

## 2. 시작 상태 — READ_ONLY (Q16a, 2026-10-01)

**열린 것:** 사용자가 명시한 폴더 하나에 대한 `list_dir` · `stat` · `read_file`. 쓰기 · 실행 · 네트워크 없음.

| 위협 | 막는 것 | 고정한 테스트 |
|---|---|---|
| 루트 밖 읽기(`..` · 절대 경로 · 링크 탈출) | 서버 검증기(상대 경로만) + 클라이언트가 실경로를 다시 본다 · `O_NOFOLLOW` | `test_paths_outside_the_root_are_refused` · `test_a_symlink_out_of_the_root_is_refused` |
| 비밀 파일 읽기(`.env` · `.ssh` · 자격증명) | 서버 검증기 · 게이트 · 클라이언트가 **같은 함수** `is_denied_secret_path` 를 쓴다 · 목록에서도 숨긴다 · 링크를 따라간 실경로도 본다 | `test_secret_paths_are_refused_*` · `test_a_symlink_to_a_secret_inside_the_root_is_refused` |
| 기기 글의 프롬프트 주입 | 결과는 자른 뒤 untrusted 경계로 감싼다 · 파일 이름의 제어 문자 제거 · 이유 코드는 서버 목록에서만 · 도구 설명은 서버가 정한다(B2) | `test_file_text_is_capped_then_wrapped_as_untrusted` · `test_listing_names_cannot_forge_lines_and_are_capped` · `test_reason_codes_come_from_our_list_never_from_the_device` |
| 다른 사용자의 기기에 닿기 | 연결 표시 키가 소유자 · 소켓이 요청의 사용자를 확인 · 루프가 답의 사용자·id 를 확인 | `test_another_users_bridge_never_answers` · `test_the_socket_refuses_a_request_for_another_user` · `test_a_reply_must_name_the_request_and_the_owner` · `test_another_users_task_never_reaches_this_bridge` |
| 사람 없는 런의 기기 읽기 | 브리지별 `allow_unattended`(기본 false) — 노출 · 게이트 · 소켓이 한 함수로 | `test_unattended_device_reads_need_the_bridge_to_opt_in` · `test_unattended_is_rechecked_at_the_socket_with_the_live_setting` · `test_an_unattended_run_does_not_see_a_bridge_that_did_not_opt_in` |
| 비밀이 기기로 가기 | `secret://` 를 실은 호출은 검증에서 거절, 금고를 읽지 않는다 | `test_a_secret_reference_never_reaches_a_device` · `test_a_secret_reference_is_refused_before_anything_leaves` |
| 브리지가 등급을 부풀림 | 선언에 READ_ONLY 밖이 하나라도 있으면 전체 거절, 받는 집합은 코드 상수 | `test_anything_but_read_only_refuses_the_whole_registration` · `test_q16a_opens_read_only_and_nothing_else` · `test_a_write_declaration_is_refused_whole` |
| 자식(서브에이전트)이 기기에 닿기 | 정의에 없음 · 스펙에 없음 · 자식 게이트 거절 | `test_a_child_cannot_reach_the_device_even_with_an_opted_in_bridge` |
| 토큰 도난 | 토큰은 한 번만 보이고 해시만 저장 · 헤더로만(쿼리 문자열 금지) · 폐기 즉시 끊김 + 갱신마다 재확인 · 사용자당 연결 하나 | `test_the_token_is_shown_once_and_only_its_hash_is_kept` · `test_revocation_and_setting_changes_close_the_live_socket` · `test_changing_or_revoking_kicks_the_live_connection` |
| 거대한 답 · 느린 답 · 몰아치는 호출 | 메시지 상한(넘으면 1009) · 호출 시간 제한 · 브리지당 동시 호출 상한 | `test_an_oversized_message_closes_the_socket_and_fails_what_was_waiting` · `test_inflight_cap_timeout_and_disconnect_are_named` |
| 클라이언트가 무언가를 실행 | 클라이언트 소스에 프로세스·셸·exec·eval 이 없다 | `test_the_client_never_executes_anything` |

**남는 위험(알고 받아들인 것):**

- 루트 폴더 **안**의 사적인 파일은 읽힌다. 무엇을 나눌지는 루트를 고르는 사람의 몫이다(홈 폴더 자체와 `/` 는 거절한다)
- 클라이언트 경로 검사와 열기 사이에 **중간 디렉터리**가 링크로 바뀌는 경쟁은 막지 않는다(마지막 성분만 `O_NOFOLLOW`). 같은 기기에 악의적 프로세스가 있으면 이미 그 프로세스가 파일을 읽을 수 있다
- 감싼 결과도 모델을 100% 지키지 못한다 — READ_ONLY 라서 주입이 성공해도 할 수 있는 것은 다른 READ_ONLY 호출뿐이다(그래서 등급을 넓힐 때 이 줄을 다시 본다)
- Redis 에 쓰기 권한이 있는 자는 연결 표시를 위조할 수 있다 — 그 위치는 이미 코딩 소켓 티켓을 위조할 수 있는 위치다

## 3. 증분 — 등급을 넓힐 때마다 한 줄

등급을 넓히는 커밋은 **같은 커밋에서** 여기에 한 줄을 더한다. `ALLOWED_DEVICE_RISKS` 를 바꾸면서 이 표를 바꾸지 않은 커밋은 리뷰에서 돌려보낸다.

| 증분 | 날짜 | 무엇을 열었나 | 무엇이 새로 가능해졌나 | 무엇으로 막나 | 고정한 테스트 |
|---|---|---|---|---|---|
| Q16a | 2026-10-01 | `READ_ONLY` — `list_dir` · `stat` · `read_file`, 명시한 폴더 하나 | 에이전트가 사용자 기기의 그 폴더 안 텍스트를 읽는다(사람이 있을 때 · 브리지가 허락하면 사람 없이도) | §2 의 표 전부 — 요약: 루트 감금 · 비밀 경로 · untrusted 감싸기 · 소유자 격리 3겹 · 무인 허락 · 비밀 참조 거절 · 자식 거절 | §2 의 표 |
| _Q16b (예정)_ | — | _`WORKSPACE_WRITE` — 루트 안 쓰기_ | _기기의 파일이 바뀐다 — 되돌릴 수 없을 수 있다_ | _(이 칸을 채우기 전에 열지 않는다)_ | — |
