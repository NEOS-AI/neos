# Coding Workspace Gateway 설계

## 1. 목적과 범위

이 변경은 이미 구현된 sandbox file API, filesystem watcher, replayable PTY와
durable coding loop를 실제 Code workspace UI에 연결한다.

이번 범위는 다음을 포함한다.

- task-scoped file tree와 read-only file viewer
- 별도 Edit 모드의 사용자 파일 편집·저장
- workspace 또는 선택 파일 diff review
- reconnect 가능한 interactive PTY
- 사용자 편집을 다음 agent safe point에 정확히 한 번 반영
- desktop resizable dock와 mobile bottom sheet

이번 범위는 multi-file editor tabs, collaborative editing, automatic merge,
language server, arbitrary terminal sharing, managed sandbox provider 선택을
포함하지 않는다.

## 2. 핵심 결정

### 2.1 전용 Workspace Gateway

파일과 terminal 트래픽을 기존 durable coding event WebSocket에 섞지 않는다.
전용 gateway가 세 경계를 제공한다.

- file tree/read/save/diff: task-scoped REST
- filesystem watcher: replay cursor가 있는 task-scoped WebSocket
- PTY input/output/resize: 별도 replay cursor가 있는 task-scoped WebSocket

각 요청은 coding task 소유권을 확인하고 현재 canonical sandbox binding을
resolve한다. 브라우저는 backend가 발급한 짧은 수명의 one-time ticket으로
watcher와 PTY WebSocket에 접속한다. ticket은 task, owner, stream kind에
결속하며 다른 task나 다른 stream에 재사용할 수 없다.

### 2.2 사용자 terminal은 직접 행위

인증된 사용자가 PTY에 입력한 명령은 agent tool call이 아니므로 기존 agent
approval을 통과하지 않는다. 대신 다음 경계를 적용한다.

- task 소유권과 단기 ticket
- sandbox 내부 non-root PTY
- provider resource/network/path 제한
- bounded audit metadata
- idle TTL, 명시적 종료, task terminal/sandbox suspend cleanup

audit에는 operation, outcome, byte bucket과 내부 action reference만 기록한다.
명령, 입력, 출력, path, environment 값은 metric label이나 일반 log에 넣지
않는다.

### 2.3 기본 read-only, 명시적 Edit 모드

Files 탭은 기본적으로 tree와 read-only viewer를 제공한다. 사용자는 명시적
`Edit` 동작으로만 편집기에 들어간다. 편집 요청은 단일 파일에 한정하며 다음
값을 포함한다.

- client-generated `edit_id`
- normalized relative path
- `base_revision`
- 새 file content

저장은 현재 revision과 `base_revision`이 같을 때만 수행한다. 불일치는
`409 workspace_revision_conflict`와 현재 revision을 반환한다. 서버는 자동
merge나 overwrite를 하지 않으며 브라우저 draft를 유지한다.

## 3. Backend 구성요소

### 3.1 `CodingWorkspaceService`

REST handler가 직접 sandbox session을 다루지 않도록 application service를
둔다. 책임은 다음과 같다.

- task owner 검증
- canonical sandbox binding resolve
- tree/read/diff request validation과 bounded response
- user edit intent 생성 및 저장 orchestration
- stable public error로 sandbox 예외 정규화

tree와 diff 응답은 크기, entry 수, depth를 제한한다. file read는 UTF-8 text와
binary metadata를 구분하며 binary content를 inline 반환하지 않는다.

### 3.2 `CodingWorkspaceMutationRepository`

사용자 편집의 durable identity와 agent 반영 상태를 저장한다.

```text
coding_workspace_edits
  edit_id
  task_id
  run_id
  path
  base_revision
  resulting_revision
  status
  content_digest
  content_bytes
  created_at
  committed_at
  applied_checkpoint_id
```

`status`는 `prepared`, `committed`, `reconcile_required`, `applied`로 제한한다.
동일 task의 `edit_id`는 unique하며 duplicate request는 동일 결과를 반환한다.
DB에는 본문을 저장하지 않고 digest와 byte 수만 저장한다.

### 3.3 저장과 reconciliation

sandbox filesystem과 PostgreSQL은 하나의 분산 transaction을 제공하지 않으므로
intent 기반 protocol을 사용한다.

1. owner, path, size, base revision을 검증한다.
2. `prepared` edit intent를 durable commit한다.
3. sandbox에 conditional write를 수행한다.
4. resulting revision을 `committed`로 기록하고
   `workspace.user_edit.applied` event와 outbox를 commit한다.
5. 3 이후 4 이전에 결과가 모호하면 `reconcile_required`로 남긴다.

reconciler는 sandbox revision과 content digest를 비교한다. 정확히 일치할 때만
commit을 완성하고, 불일치하면 stable conflict로 닫아 사용자의 재검토를
요구한다. 같은 `edit_id`로 재요청하면 현재 intent 상태를 조회해 mutation을
중복 실행하지 않는다.

저장 완료는 `workspace.user_edit.applied`, safe-point 반영 완료는
`workspace.user_edit.synced` event로 공개한다. payload는 다음 값만 포함한다.

```json
{
  "edit_id": "cwe_...",
  "path": "src/app.py",
  "base_revision": "12",
  "resulting_revision": "13",
  "status": "pending_agent_sync"
}
```

file content, digest, actor, terminal 내용은 공개 event에 포함하지 않는다.
synced event는 같은 identity와 `applied_checkpoint_id`를 포함한다.

### 3.4 Agent safe-point 반영

coding loop가 임의 시점에 workspace edit를 읽지 않는다. 기존 safe-point
전이에서 canonical run과 fencing token으로 미적용 committed edit를 claim한다.

- edit는 resulting revision, created sequence 순서로 정렬한다.
- 한 safe point에서 여러 edit를 bounded batch로 합칠 수 있다.
- model context에는 path, resulting revision, “사용자가 직접 수정했다”는
  구조화 instruction만 추가한다.
- file content는 다음 model turn이 기존 read tool로 필요할 때 읽는다.
- checkpoint commit과 edit의 `applied_checkpoint_id` 갱신을 같은 fenced DB
  transaction에 넣는다.

따라서 재전달이나 replacement worker가 동일 edit context를 두 번 transcript에
추가하지 못한다. 저장은 진행 중인 model/tool call을 중단하지 않으며 다음
safe point부터 적용된다.

### 3.5 `CodingWorkspaceStreamService`

filesystem watcher와 PTY transport의 공통 책임은 authentication, cursor
validation, heartbeat, bounded replay, cleanup이다. 실제 cursor와 payload
contract는 서로 분리한다.

- watcher cursor gap: `workspace_resync_required`
- PTY cursor gap: `terminal_resync_required`
- coding event cursor에는 영향 없음

socket disconnect는 PTY process를 종료하지 않는다. 재연결은 동일 `pty_id`와
새 ticket을 사용한다. 명시적 kill, idle TTL, task terminal 전이, sandbox
suspend/destroy에서 PTY를 종료한다.

## 4. REST와 WebSocket 계약

권장 REST surface는 다음과 같다.

```text
GET  /api/v1/coding/tasks/{task_id}/workspace/tree
GET  /api/v1/coding/tasks/{task_id}/workspace/files?path=...
GET  /api/v1/coding/tasks/{task_id}/workspace/diff?path=...
PUT  /api/v1/coding/tasks/{task_id}/workspace/files
POST /api/v1/coding/tasks/{task_id}/workspace/ws-ticket
POST /api/v1/coding/tasks/{task_id}/workspace/ptys
DELETE /api/v1/coding/tasks/{task_id}/workspace/ptys/{pty_id}
```

save request는 `edit_id`, `path`, `base_revision`, `content`를 받는다. 성공
response는 resulting revision과 agent sync 상태를 반환한다. owner가 아닌
task와 존재하지 않는 task는 모두 `404`다.

기존 owner-scoped coding snapshot의 workspace projection에는 bounded
`user_edits` 목록을 추가한다. 각 항목은 edit identity, path, base/result
revision, `pending_agent_sync|agent_synced` 상태와 optional
`applied_checkpoint_id`만 포함한다. content와 digest는 snapshot에 포함하지
않는다. 따라서 reconnect한 브라우저도 REST 저장 응답에 의존하지 않고 durable
상태를 복원한다.

WebSocket subprotocol은 watcher와 PTY를 분리한다.

```text
neos.coding.workspace.v1
neos.coding.pty.v1
```

Watcher frame은 cursor, workspace revision, changed path 목록과 change kind만
포함한다. PTY frame은 cursor, stream kind, bounded base64 bytes, terminal
state를 포함한다. input과 resize는 client-to-server command frame이다.

## 5. Frontend 설계

### 5.1 B안: Resizable workspace dock

기존 execution ledger를 왼쪽 주 작업면으로 유지한다. 오른쪽은 최소·최대 폭이
제한된 resizable dock이며 `Files`, `Diff`, `Terminal` 탭을 제공한다. 모바일은
같은 내용을 full-height bottom sheet로 전환한다.

상태 소유권을 분리한다.

- agent ledger: 기존 durable coding projection store
- Files/Diff: revision-keyed query cache와 local edit draft
- Terminal: PTY session/replay store
- watcher: cache invalidation과 revision conflict signal

파일/terminal payload는 coding projection store에 넣지 않는다. 따라서 agent
event burst가 editor나 terminal을 불필요하게 rerender하지 않는다.

### 5.2 Files 상태 전이

```text
read_only
  -> editing
  -> saving
  -> saved_pending_agent
  -> agent_synced

editing/saving
  -> revision_conflict
  -> reload_latest | compare_changes
```

저장 성공 후 `Saved · agent sync pending`을 표시한다. snapshot의
`user_edits` 또는 `workspace.user_edit.synced` event에서
`applied_checkpoint_id`를 관찰하면
`Agent synced at checkpoint …`로 바꾼다.

watcher가 편집 중인 path의 더 높은 revision을 알리면 draft를 폐기하지 않고
conflict 상태로 전환한다. `Reload latest`는 명시적 확인 후 draft를 교체하고,
`Compare changes`는 Diff 탭에서 draft와 최신 파일을 비교한다.

### 5.3 Diff와 Terminal

Diff 탭은 선택 파일과 전체 workspace 범위를 전환한다. 변경 출처를 user edit,
agent edit, terminal/direct mutation으로 구분하되, 출처를 확정할 수 없으면
일반 workspace change로 표시한다.

Terminal 탭은 create/connect/reconnecting/closed/failed 상태를 표시한다.
output은 bounded virtualized buffer로 렌더링하며 input, resize, reconnect가
같은 PTY session을 사용한다. terminal 오류가 coding event connection을
종료시키지 않는다.

### 5.4 접근성·반응형

- dock splitter는 keyboard 조절과 ARIA separator를 제공한다.
- tablist/tab/tabpanel semantics를 사용한다.
- save/conflict/agent-sync 상태는 non-intrusive status live region으로 알린다.
- keyboard shortcut은 Files `Cmd/Ctrl+Shift+E`, Diff
  `Cmd/Ctrl+Shift+D`, Terminal ``Cmd/Ctrl+Shift+` ``로 제한한다.
- 모바일 sheet가 열려도 execution ledger scroll position을 보존한다.

## 6. 오류와 보안 정책

Stable public errors:

- `workspace_revision_conflict`
- `workspace_edit_exists`
- `workspace_edit_reconcile_required`
- `workspace_path_invalid`
- `workspace_file_too_large`
- `workspace_binary_not_editable`
- `workspace_stream_cursor_expired`
- `terminal_session_not_found`
- `terminal_stream_cursor_expired`
- `terminal_session_limit_exceeded`

path traversal, absolute path, NUL, symlink escape는 기존 sandbox path policy로
거절한다. file/terminal 본문을 metrics, audit, exception message에 넣지 않는다.
REST와 WS 모두 response/frame size를 제한하고 slow consumer는 해당 workspace
stream만 종료한다.

## 7. 테스트 전략

### 7.1 Backend

- owner/foreign task와 ticket binding
- path traversal, symlink escape, binary/UTF-8/size limit
- tree/read/diff bounded contract
- stale revision과 duplicate `edit_id`
- sandbox write 이후 crash reconciliation
- safe point batch와 exactly-once checkpoint binding
- stale/replacement worker fencing
- watcher replay, coalescing, eviction resync
- PTY input/output/resize/reconnect/idle cleanup
- coding cursor와 workspace cursor 독립성

### 7.2 Frontend

- 기본 read-only와 명시적 Edit 진입
- draft 보존, save, conflict, reload/compare
- pending-agent에서 checkpoint sync로의 전이
- dock resize와 persisted bounded width
- tab keyboard/accessibility contract
- watcher invalidation과 stale query suppression
- terminal reconnect/replay와 coding connection 격리
- mobile sheet와 ledger scroll 유지

### 7.3 Vertical slice

Docker opt-in fixture에서 다음을 검증한다.

1. file tree와 파일을 읽는다.
2. 사용자가 base revision으로 파일을 저장한다.
3. watcher가 resulting revision을 전달한다.
4. durable edit event가 replay된다.
5. 다음 safe point가 edit를 한 번만 model context에 반영한다.
6. agent가 새 revision에서 테스트를 실행한다.
7. 브라우저 reconnect 후 snapshot과 watcher/event tail이 동일 상태로 수렴한다.

## 8. Rollout과 rollback

배포 순서는 migration과 mutation repository, backend REST/WS gateway, edit
reconciler, agent safe-point consumption, frontend dock 순서다. Edit UI는
backend capability가 확인될 때만 활성화한다.

rollback 시 frontend Edit와 terminal create를 먼저 비활성화하고 watcher는
read-only invalidation 용도로 유지할 수 있다. worker의 edit consumption을
중단해도 committed edit와 event는 보존한다. migration row를 삭제하거나
pending edit를 자동 적용 처리하지 않는다. 재활성화 시 reconciler와 safe-point
claim이 durable 상태에서 이어간다.
