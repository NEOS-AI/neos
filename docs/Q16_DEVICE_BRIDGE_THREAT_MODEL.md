# Q16 사용자 기기 브리지 — 위협 모델 (지속적 개선)

> **지위:** 살아 있는 문서다. dots 분석 §4 결정 7(2026-09-30): 위협 모델은 **착수 조건이 아니라 지속적 개선**이다.
> 브리지는 READ_ONLY 로 시작했고, **도구 위험 등급을 한 단계 넓히는 커밋은 §3 표에 한 줄을 먼저 더한다.**
> 설계: [Q16_DEVICE_BRIDGE_DESIGN_261001.md](Q16_DEVICE_BRIDGE_DESIGN_261001.md)(결정 B1~B13 · Q16b BW1~BW11 · Q16c BC1~BC12).

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
| 브리지가 등급을 부풀림 | 선언에 READ_ONLY 밖이 하나라도 있으면 전체 거절, 받는 집합은 코드 상수 | `test_anything_but_read_only_refuses_the_whole_registration` · `test_the_opened_risks_are_read_only_and_one_write_tool` · `test_a_write_declaration_is_refused_whole` |
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
| Q16b | 2026-10-02 | `WORKSPACE_WRITE` — `write_file` 하나(파일 전체 쓰기), 명시한 폴더 안. 자격증명의 `allow_writes`(기본 off)와 클라이언트의 `--allow-writes` **두 열쇠**가 다 있어야 선언이 받아진다 | 주입에 넘어간 모델이 사용자의 파일을 **덮어쓴다**(되돌릴 수 없다) · 실행되는 파일(스크립트·자동 실행 위치·셸 설정 dotfile·`.git/hooks`)을 심는다 · 링크·경쟁으로 루트 밖이나 비밀 파일에 쓴다 · 반쯤 쓴 파일을 남긴다 · 디스크를 채운다 · 사람 없는 런이 기기를 바꾼다 · 같은 쓰기가 두 번 돈다 | §4 의 표 — 요약: 매 쓰기 사람 승인(소유자의 allow 규칙만 넘는다; 운영자 allow·auto·"항상 허용"은 못 넘는다) · 무인·background·자식은 **어떤 허락으로도** 거절 · read-before-write 다이제스트(`base_sha256`, 다르면 stale) · 링크 없는 경로만(성분마다 `O_NOFOLLOW` 디렉터리 fd) · dot 성분·자동 실행 확장자·비밀 경로 거절 · 실행 비트를 세우지 않고 실행 파일은 덮지 않는다 · 같은 폴더 임시 파일 + rename(덮기)/link(새로 만들기) · 크기 상한 | §4 의 표 |
| Q16c | 2026-10-02 | `COMMAND` — `run_command` 하나(argv 하나를 기기에서 실행), 명시한 폴더 안을 cwd 로. 자격증명의 `allow_commands`(090, 기본 off)와 클라이언트의 `--allow-commands EXE,…` **두 열쇠**, 그리고 운영자의 서버 상한 `device_bridge.command_allowlist`(기본 **비어 있음**)가 다 있어야 선언이 받아진다 | 주입에 넘어간 모델이 사용자의 기기에서 **임의 코드**를 사용자 권한으로 돌린다(허용한 실행 파일이 저장소 코드를 돌리면 — `pytest`·`make` — 그 코드가 무엇이든 돈다) · 쓰기(Q16b)로 심은 파일을 명령으로 실행한다 · 셸 문자열·래퍼(`env`·`xargs`·`timeout`)·인라인 인터프리터로 허용 목록을 넘는다 · 로그인·토큰 명령(`gh auth`·`npm token`)을 돌린다 · 브리지 토큰·셸 환경의 비밀이 자식 프로세스로 샌다 · 루트 밖을 cwd·피연산자로 삼는다 · 끝나지 않는 프로세스·백그라운드 자식이 남는다 · 거대한 출력·출력에 실린 지시 · 사람 없는 런이 명령을 돌린다 · 같은 명령이 두 번 돈다 | §5 의 표 — 요약: 매 호출 사람 승인(소유자의 **argv 접두가 있는** allow 규칙만 넘는다; 도구 전체 allow·운영자 allow·auto·"항상 허용"은 못 넘는다) · 무인·background·자식은 **어떤 허락으로도** 거절 · argv 만(셸 문자열 없음), 실행 파일은 클라이언트 선언 ∩ 서버 상한, 셸·래퍼·권한 상승·런처는 늘 거절 · 샌드박스 `execute.v1` 의 argv 규칙을 **같은 함수**로 · USER_ONLY 그대로 · `secret://` 거절 · cwd·피연산자는 루트 안 · 실행 파일 경로는 시작할 때 고정(루트 안의 실행 파일은 거절) · 환경은 허용한 몇 개만(토큰 없음) · stdin 없음 · 시간 제한 후 프로세스 그룹째 종료 · 출력 상한·제어 문자 제거·untrusted 감싸기, 종료 코드는 서버가 만든 줄 · 다시 돌지 않는다(claim 재획득은 `tool_outcome_unknown`) | §5 의 표 |

## 4. Q16b — `WORKSPACE_WRITE` (2026-10-02)

**열린 것:** `write_file` 하나 — 명시한 폴더 안의 텍스트 파일 하나를 통째로 쓴다(새로 만들기 또는 덮어쓰기).
`mkdir`·`rm`·`mv`·`chmod`·부분 편집은 열지 않았다. 실행은 여전히 없다.
설계: [Q16b 결정 BW1~BW11](Q16_DEVICE_BRIDGE_DESIGN_261001.md#6-q16b--쓰기-등급-2026-10-02).

| 위협(새로 가능해진 것) | 막는 것 | 고정한 테스트 |
|---|---|---|
| 사용자가 모르게 쓰기가 열린다 | 두 열쇠: 자격증명 `allow_writes`(기본 false, 080 에 083 이 더한 열) **와** 클라이언트 `--allow-writes`. 쓰기를 선언했는데 자격증명이 꺼져 있으면 등록 **전체** 거절(`device_writes_not_enabled`, 4403). 켜고 끄면 붙은 연결을 끊는다 · 소켓은 쓰기마다 **지금의** 자격증명을 다시 읽는다 | `test_a_write_declaration_needs_the_credential_to_allow_writes` · `test_the_socket_rechecks_writes_with_the_live_credential` · `test_flipping_writes_kicks_the_live_connection` |
| 주입에 넘어간 모델이 파일을 덮어쓴다 | 쓰기마다 사람 승인(REQUIRE_APPROVAL). 운영자 allow 목록·auto 모드·"항상 허용" 기억은 넘지 못하고 **소유자의 allow 규칙만** 넘는다(Q6 S7 과 같은 자리). 승인 화면에 경로·본문 미리보기가 실린다 | `test_device_writes_ask_a_person_and_only_the_owner_can_waive_it` · `test_the_approver_sees_what_will_be_written` |
| 사람 없는 런이 기기를 바꾼다 | 무인(autonomous·background·운영자 unattended) 쓰기는 브리지의 `allow_unattended` 와 **어떤 allow 로도** 거절(`policy_device_write_unattended`) — 노출·게이트·소켓이 한 함수(`device_unattended_refusal`). background 는 Q1 천장이 먼저 막는다. 무인 런에는 쓰기 도구가 보이지도 않는다 | `test_unattended_device_writes_are_refused_whatever_allows_them` · `test_an_unattended_run_never_sees_the_write_tool` · `test_unattended_writes_are_refused_at_the_socket` |
| 자식이 기기에 쓴다 | B11 그대로(`policy_device_child`) — 이름 판정이 등급과 상관없다 | `test_a_child_cannot_write_to_the_device` |
| 읽지 않은 파일을 덮는다 · 읽은 뒤 바뀐 파일을 덮는다 · 같은 쓰기가 두 번 돈다 | `base_sha256`: 있는 파일은 **온전히 읽은** 내용의 다이제스트를 내야 덮인다(잘린 읽기에는 다이제스트가 없다), 없는 파일은 `null` 이어야 만들어진다. 기기가 rename 직전에 다시 해시해서 다르면 `precondition_stale_read`. 다시 돈 쓰기는 다이제스트가 이미 바뀌어 거절된다 | `test_overwrite_needs_the_digest_of_a_full_read` · `test_a_stale_digest_is_refused_and_nothing_changes` · `test_create_only_never_clobbers` · `test_a_replayed_write_is_stale` |
| 링크·`..` 로 루트 밖이나 비밀 파일에 쓴다 | 읽기의 경계(B10) + 쓰기는 **링크가 하나도 없는 경로**만: 루트부터 성분마다 `O_NOFOLLOW|O_DIRECTORY` 로 디렉터리 fd 를 잡고 그 fd 안에서 만든다(중간 디렉터리 바꿔치기 경쟁이 닫힌다). 마지막 성분이 링크면 거절. 비밀 경로는 서버·클라이언트가 같은 함수 | `test_writes_never_follow_a_symlink_anywhere_in_the_path` · `test_write_paths_outside_the_root_are_refused` · `test_a_swapped_parent_directory_is_not_followed` |
| 실행되는 파일을 심는다 | dot 성분(`.git/`·`.github/`·`.vscode/`·`.bashrc`·`.envrc`…) 전부 거절 · OS 가 열면 실행하는 확장자(`.command`·`.desktop`·`.lnk`·`.bat`·`.ps1`·`.plist`…) 거절 — 서버 검증기와 클라이언트가 **같은 함수**(`device_write_refusal`) · 새 파일은 `0644 & ~umask`(실행 비트 없음) · 실행 비트가 선 파일은 덮지 않는다 · 지시 파일(`AGENTS.md` 등)은 소유자 allow 가 있어도 승인 | `test_write_policy_is_one_function_on_both_sides` · `test_executable_files_are_never_written_and_new_files_are_not_executable` · `test_instruction_files_on_the_device_always_ask` |
| 반쯤 쓴 파일 · 하드 링크를 통한 쓰기 | 같은 디렉터리 임시 파일(`O_CREAT|O_EXCL|O_NOFOLLOW`) → fsync → 덮기는 `rename`, 새로 만들기는 `link`(있으면 실패) · 어떤 실패든 임시 파일을 지운다 · rename 은 디렉터리 항목을 바꾸므로 다른 하드 링크의 내용은 바뀌지 않는다 | `test_a_failed_write_leaves_neither_a_partial_file_nor_a_temp_file` · `test_a_hard_link_elsewhere_is_not_written_through` |
| 디스크를 채운다 · 거대한 쓰기 | 한 쓰기의 상한(`max_write_bytes`, 기본 256 KiB — 서버와 클라이언트가 다 본다) · 텍스트만(NUL·UTF-8 아님 거절) · 쓰기마다 사람 승인이 곧 속도 제한 · 공간이 없으면 `device_no_space` 로 임시 파일을 지우고 끝 | `test_write_size_and_text_are_capped_on_both_sides` |
| 결과로 주입 | 쓰기 결과는 서버가 만든 한 줄(바이트 수 · 새로/덮음 · 검증한 16진 다이제스트)뿐이다 — 기기 문자열이 없다 | `test_a_write_result_carries_no_device_text` |

**남는 위험(알고 받아들인 것):**

- 사람이 승인 화면을 읽지 않고 누르면 막지 못한다. 소유자가 `device_write_file.v1` 에 allow 규칙을 두면 사람이 있는 런에서 묻지 않는다 — 그것은 소유자의 선택이다(무인에는 여전히 닫혀 있다)
- 다이제스트 검사와 rename 사이(마이크로초)에 같은 기기의 다른 프로세스가 파일을 바꾸면 그 변경을 덮는다. 같은 기기의 프로세스는 이미 그 파일을 마음대로 바꿀 수 있다
- 루트 **안**의 dot 이 아닌 스크립트(`build.sh`·`Makefile`·`package.json` 의 scripts)는 쓸 수 있고, 사람이 나중에 그것을 실행할 수 있다. 실행 비트를 세우지 않고 실행 파일을 덮지 않는 것까지가 브리지의 몫이고, 그 내용은 승인 화면에서 사람이 본다
- 루트 폴더 자체가 자동 실행 위치(예: `~/Library/LaunchAgents`)면 확장자 목록이 일부만 막는다. 루트를 고르는 것은 사람이다(홈·`/` 는 거절)

## 5. Q16c — `COMMAND` (2026-10-02)

**열린 것:** `run_command` 하나 — 사용자가 클라이언트에서 이름을 댄 실행 파일 중 하나를 argv 로, 명시한 폴더 안을 cwd 로 돌린다.
셸은 없다. 출력과 종료 코드가 돌아온다. 쓰기(Q16b)와는 따로 열고 닫는다.
설계: [Q16c 결정 BC1~BC12](Q16_DEVICE_BRIDGE_DESIGN_261001.md#7-q16c--명령-등급-2026-10-02).

| 위협(새로 가능해진 것) | 막는 것 | 고정한 테스트 |
|---|---|---|
| 사용자·운영자가 모르게 실행이 열린다 | 세 자리가 다 열어야 한다: 자격증명 `allow_commands`(기본 false, 090) · 클라이언트 `--allow-commands EXE,…` · 서버 상한 `command_allowlist`(기본 비어 있음). 명령을 선언했는데 자격증명이 꺼져 있으면 `device_commands_not_enabled`, 선언한 실행 파일이 상한 밖이면 `device_command_not_allowed` — 둘 다 등록 **전체** 거절(4403). 켜고 끄면 붙은 연결을 끊는다 · 소켓은 명령마다 **지금의** 자격증명을 다시 읽는다 | `test_a_command_declaration_needs_the_credential_to_allow_commands` · `test_declared_executables_must_sit_inside_the_server_bound` · `test_the_socket_rechecks_commands_with_the_live_credential` · `test_flipping_commands_kicks_the_live_connection` |
| 주입에 넘어간 모델이 명령을 돌린다 | 매 호출 사람 승인. 운영자 allow 목록·auto 모드·"항상 허용" 기억·**도구 전체에 건** 소유자 allow 는 넘지 못하고, 소유자의 **argv 접두가 맞는** allow 규칙만 넘는다(`device_run_command.v1 pytest`). 지시 파일을 피연산자로 삼으면 그 규칙도 넘지 못한다. 승인 화면에 argv 전체와 cwd 가 실린다(이벤트에는 실행 파일·cwd 만) | `test_device_commands_ask_a_person_and_only_an_owner_argv_rule_waives_it` · `test_the_approver_sees_the_whole_argv` |
| 사람 없는 런이 기기에서 명령을 돌린다 | 무인(autonomous·background·운영자 unattended) 명령은 브리지의 `allow_unattended` 와 **어떤 allow 로도** 거절(`policy_device_command_unattended`) — 노출·게이트·소켓·서비스가 한 함수(`device_unattended_refusal`). background 는 Q1 천장이 먼저 막는다. 무인 런에는 보이지도 않는다 | `test_unattended_device_commands_are_refused_whatever_allows_them` · `test_an_unattended_run_never_sees_the_command_tool` · `test_unattended_commands_are_refused_at_the_socket` |
| 자식이 기기에서 명령을 돌린다 | B11 그대로(`policy_device_child`) | `test_a_child_cannot_run_a_command_on_the_device` |
| 허용 목록을 셸·래퍼·인라인 코드로 넘는다 | argv 만(문자열 명령 없음) · `argv[0]` 은 맨 이름이고 클라이언트 선언 ∩ 서버 상한 안 · 셸·래퍼·권한 상승·런처·네트워크 클라이언트는 상한에도 들 수 없다(설정 검증·클라이언트 시작·검증기가 같은 목록) · 샌드박스 `execute.v1` 의 argv 규칙(인라인 `-c`/`-e`, 패키지 설치, `git` 은 status/diff/log, 위험한 `rm`, 전용 도구가 있는 명령)을 **같은 함수**(`validate_argv`)로 · 기기 규칙은 서버 검증기와 클라이언트가 **같은 함수**(`device_command_refusal`) | `test_a_shell_string_or_a_wrapper_is_never_a_device_command` · `test_sandbox_argv_rules_apply_to_device_commands` · `test_command_policy_is_one_function_on_both_sides` · `test_the_client_runs_only_its_pinned_executables` |
| 로그인·토큰·권한 명령 | USER_ONLY 바닥(`gh auth`·`npm token`·`passwd` …, 운영자 `approval_user_only_extra` 포함)이 기기 명령에도 그대로 — 승인으로도 위임할 수 없다 | `test_user_only_commands_stay_with_the_user_on_the_device` |
| 비밀이 명령으로·명령에서 샌다 | `secret://` 가 argv·cwd 어디에든 있으면 거절(B8) · 비밀 경로 피연산자 거절 · 자식 프로세스의 환경은 허용한 몇 개(`PATH`·`HOME`·`LANG`·`TMPDIR` …)뿐 — 브리지 토큰도 셸의 다른 비밀도 넘어가지 않는다 · stdin 은 비어 있다 | `test_a_secret_reference_in_argv_never_leaves` · `test_the_child_process_gets_a_scrubbed_environment` |
| 루트 밖에서·루트 밖을 대상으로 돈다 | cwd 는 상대 경로(정규화 · `..` 거절)이고 클라이언트가 실경로로 다시 봐서 루트 안의 디렉터리여야 한다 · 절대·`~`·`..` 피연산자 거절(`--opt=값` 의 값도) · 실행 파일 경로는 시작할 때 `PATH` 에서 찾아 고정하고, 루트 안에 있으면 거절(쓰기로 바꿔치기할 수 없게) | `test_cwd_and_operands_stay_inside_the_shared_folder` · `test_the_client_confines_cwd_to_the_root` |
| 끝나지 않는 프로세스 · 남는 백그라운드 자식 · 거대한 출력 | 시간 제한(서버 상한 · 클라이언트 상한 중 작은 쪽) 뒤 **프로세스 그룹째** SIGKILL, 끝난 뒤에도 그룹을 한 번 더 정리 · stdout·stderr 각각 상한(넘는 것은 읽어 버린다 — 파이프가 막히지 않게) · 브리지당 동시 호출 상한 | `test_a_command_that_overruns_is_killed_with_its_process_group` · `test_command_output_is_capped_scrubbed_and_wrapped` |
| 출력으로 주입 · 결과 위조 | 출력은 자른 뒤 제어 문자(ANSI 이스케이프 포함)를 지우고 untrusted 경계로 감싼다 · 종료 코드·시간 초과 줄은 서버가 검사한 정수·불리언으로 경계 **밖**에 만든다 · 상태와 이유 코드는 서버 목록에서만 | `test_command_output_is_capped_scrubbed_and_wrapped` · `test_a_command_result_never_names_its_own_status` |
| 같은 명령이 두 번 돈다 | 기기 호출은 투기적으로 돌지 않는다(B13) · READ_ONLY 아닌 재획득 claim 은 `tool_outcome_unknown` 으로 끝난다(다시 보내지 않는다) · 명령의 claim 은 명령 시간 상한 + 호출 대기 + 30초만큼 쥔다(일반 도구 TTL 이 먼저 끝나지 않게) | `test_device_commands_are_never_speculative` · `test_a_device_command_holds_its_claim_for_its_whole_time_limit` |
| 플래그를 켜지 않은 배포가 바뀐다 | 명령을 내놓지 않은 브리지(그리고 플래그 off)는 도구 목록·시스템 프롬프트·이벤트 어휘가 Q16b 와 바이트가 같다 | `test_flag_off_and_a_bridge_without_commands_stay_byte_identical` |

**남는 위험(알고 받아들인 것):**

- **허용한 실행 파일은 무엇이든 돌릴 수 있다.** `pytest`·`make`·`npm` 은 루트 안의 코드를 실행한다 — 그 코드를 모델이 Q16b 쓰기로 바꿨거나 원래 악성이면 사용자 권한으로 돈다. 기기 쪽 OS 샌드박스(seatbelt·bubblewrap)는 이 슬라이스에 없다(이식성). 막는 것은 매 호출 사람 승인(같은 런의 쓰기도 각각 승인 화면에 보인다)과, 무엇을 허용할지 사람(클라이언트)·운영자(상한)가 이름으로 고르는 것이다
- 승인 화면을 읽지 않고 누르면 막지 못한다. 소유자가 argv 접두 규칙을 두면 사람이 있는 런에서 그 접두는 묻지 않는다 — 소유자의 선택이다(무인에는 여전히 닫혀 있다)
- 명령이 스스로 네트워크·루트 밖 파일에 닿는 것은 막지 않는다(피연산자 검사는 argv 만 본다). 시간 제한과 프로세스 그룹 종료가 수명을 묶을 뿐이다
- cwd 검사와 프로세스 시작 사이에 중간 디렉터리를 링크로 바꾸는 경쟁은 막지 않는다(B10 의 읽기와 같은 위험 — 같은 기기의 악의적 프로세스는 이미 그 디렉터리를 마음대로 쓴다)
- 새 세션으로 그룹을 벗어난 손자 프로세스는 그룹 종료로 잡히지 않는다
