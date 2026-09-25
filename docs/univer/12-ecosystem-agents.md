# 에이전트 에코시스템 — Skills · MCP · CLI · Workspace · 호스트 플러그인

조사 기준일: 2026-09-25. Univer OSS 클론(`/Users/yeonwoosung/Desktop/univer` v1.0.2)에는 에이전트 루프가 없다. 이 문서는 README가 가리키는 **형제 GitHub 레포의 공개 README / SKILL.md**를 읽어, 에이전트가 Univer에 붙는 실제 표면을 고정한다. 형제 레포는 이 머신에 클론되어 있지 않다.

사실(fetched page)과 추론을 가른다.

---

## 1. 한 줄

에이전트 표면은 **두 갈래**다.

1. **셀 도구 MCP** — 살아 있는 Univer 인스턴스에 `set_range_data` 같은 도구를 보낸다 (`univer-mcp` + start-kit).
2. **Worktree + Facade execute** — `.univer` 파일의 격리 초안에서 신뢰된 Facade JS를 실행하고, 사람이 merge/discard 한다 (`univer-cli`, Workspace, DSH, WorkBuddy, OpenClaw).

둘 다 밑바닥은 이 OSS 클론의 Facade/Command다. 루프·스킬·MCP 서버·Worktree 저장소는 여기 없다.

```text
에이전트 호스트 (Claude / Codex / Cursor / DSH / WorkBuddy / OpenClaw)
        │
        ├─ SDK Skills (dream-num/skills)  → 앱 코드에 Facade를 짜라고 가르침
        ├─ Hosted MCP (mcp.univer.ai)     → mcp-bridge 플러그인 → window.univerAPI
        └─ CLI / Workspace / DSH 도구     → univer execute (Facade JS) + worktree
                 │
                 ▼
        FUniver / ICommandService   ← 이 클론
```

---

## 2. 스킬 팩

### 2.1 `dream-num/univer-sdk-skills` (구 팩)

- 목적: 에이전트에게 Univer 임베드/플러그인/Node/Pro 통합을 가르친다.
- 라이선스: Apache-2.0.
- 설치: `npx skills add dream-num/univer-sdk-skills`.
- 본문 호환 표기는 Univer `v0.21.x` / Pro `v0.20.x` (소스 1.0.2보다 오래됨).

| Skill | 범위 |
| --- | --- |
| `univer-integrate` | React/Vue/HTML/Node 임베드, Facade, 20+ recipe, 권한, 멀티 유닛, network, watermark/recorder/telemetry |
| `univer-pro-integrate` | 라이선스 우선 등록, 협업, XLSX/DOCX exchange, print, pivot, charts |
| `univer-node-backend` | UI 없는 Node, `rpc-node` fork 워커, 배치 리포트 |
| `univer-plugin-dev` | COMMAND/MUTATION/OPERATION, Facade 확장, 메뉴/단축키 |

### 2.2 `dream-num/skills` (현재 우산)

- 목적: SDK + 테마 + **CLI 디스커버리**.
- 설치: `npx skills add dream-num/skills`. CLI README가 이 명령을 가리킨다.
- SDK 스킬 베이스라인 문구: Univer / Pro `1.0.0-beta.0`.

| Skill | 용도 |
| --- | --- |
| `univer-integrate` | OSS Sheets/Docs/Slides + 현재 Facade |
| `univer-pro-integrate` | 라이선스 Sheets/Docs/Slides/Bases/Boards/PDFs, 협업, exchange |
| `univer-node-backend` | 헤드리스 모델/수식 |
| `univer-plugin-dev` | 플러그인·커맨드·UI·이벤트·Facade |
| `univer-customize-theme` | 팔레트, 다크모드, Pro 차트 테마 |
| `univer-cli` | 로컬 `.univer` (discovery, `hidden: true`) |
| `univer-workspace-cli` | 원격 Workspace (discovery, `hidden: true`) |

CLI 운영 스킬(`core` / `sheet` / `doc` / `slide` / `base` / `board` / `embed` / `cross-unit-formula`)은 **GitHub skills 레포가 아니라 설치된 CLI 바이너리**에 있다.

```bash
univer skills get core
univer skills get sheet
```

`docs.univer.ai/guides/skills` 는 2026-09-25 fetch에서 본문이 없었다. `univer-sdk-skills` README는 아직 그 URL을 가리킨다.

---

## 3. Hosted MCP

### 3.1 `dream-num/univer-mcp`

- 라이선스: MIT. 트리: `LICENSE` + `README.md`만 (도구 소스 없음). Early stage.
- 흐름: MCP host → `https://mcp.univer.ai/mcp/?univer_session_id=…` → mcp-bridge 플러그인 → Univer 인스턴스.
- 인증: `console.univer.ai/apikeys` Bearer. `univer_session_id`는 인스턴스와 같아야 한다 (기본 `default`).
- 멀티모달 모델 권장. plain text 모드는 “NOT supported yet”.

### 3.2 `dream-num/univer-mcp-start-kit`

Vite 앱이 Pro MCP 플러그인을 등록하고 `window.univerAPI`를 노출한다.

```ts
univer.registerPlugin(UniverMCPPlugin)
univer.registerPlugin(UniverMCPUIPlugin, { showDeveloperTools: true })
univer.registerPlugin(UniverSheetMCPPlugin)
window.univerAPI = univerAPI
```

패키지: `@univerjs-pro/mcp`, `@univerjs-pro/mcp-ui`, `@univerjs-pro/sheets-mcp`. FAQ는 OSS로 킷을 돌릴 수 있다고 하고, 고급 기능은 `UNIVER_CLIENT_LICENSE`다.

start-kit README에 이름이 적힌 도구 **30개** (차트/피벗 WIP):

| 군 | 도구 |
| --- | --- |
| 데이터 | `set_range_data`, `get_range_data`, `search_cells`, `auto_fill`, `format_brush` |
| 시트 | `create_sheet`, `delete_sheet`, `rename_sheet`, `activate_sheet`, `move_sheet`, `set_sheet_display_status`, `get_sheets`, `get_active_unit_id` |
| 구조 | `insert_rows`, `insert_columns`, `delete_rows`, `delete_columns`, `set_cell_dimensions`, `set_merge` |
| 서식 | `set_range_style`, CF add/set/delete/get |
| DV | add/set/delete/get data validation |
| 유틸 | `get_activity_status`, `scroll_and_screenshot` |

이 이름들은 **start-kit README**에만 있다. `univer-mcp` 레포에는 목록이 없다.

---

## 4. Univer CLI — 로컬 Worktree

`dream-num/univer-cli`. Apache-2.0. Node ≥ 24. `univer` 바이너리 하나.

흐름:

1. discovery skill이 CLI 설치를 확인.
2. `univer skills get core` + unit skill.
3. `.univer` 생성/import, 격리 Worktree.
4. `inspect` → `execute`(신뢰된 Facade JS) → 모델 읽기.
5. screenshot / layout lint.
6. Worktree `ready` + 로컬 Viewer URL.
7. 사람이 merge / reopen / discard.

명령 군: `new`, `import`, `status`, `unit`, `worktree`, `inspect`, `execute`, `screenshot`, `print-pdf`, `lint`, `compile-svg`, `compile-typst`, `export`, `open`, `api`, `resources`, `skills`, `config`, `doctor`, `update`, `daemon`, `optimize`.

`.univer`는 SQLite (Units, revisions, Worktrees, History). `execute`는 비신뢰 코드 샌드박스가 아니다.

Pro History가 semantic diff를 계산한다. 번들 localhost 런타임 라이선스가 90일마다 돈다. `@univerjs` / `@univerjs-pro` / `@univer-cli`를 같은 버전으로 올린다.

---

## 5. Univer Workspace

`dream-num/univer-workspace`. 사람+에이전트가 같은 Space에서 문서를 만들고 리뷰하는 배포 가능 워크스페이스.

```
Browser ──┐
Agent ────┼── Workspace Server ── Product / Collaboration / Blobs
CLI ──────┘
```

Workspace Agent는 **DSH 기반 로컬 웹앱**. Worktree: create → 에이전트 초안 → Ready → 사람 Merge/Reopen.

소유 분할 (README):

| 층 | 책임 |
| --- | --- |
| Univer Runtime | 유닛 모델, 렌더, Facade |
| Collaboration SDK | 스냅샷, OT, realtime, Worktree 프로토콜 |
| CLI SDK | 헤드리스, execute, inspect, render |
| Workspace | identity, Spaces, ACL, Blob, HTTP |

`univer-workspace-cli skills get`은 Core/Sheet/Doc/Slide/Base/Board/**Blob/HTML Views**/embed/cross-unit-formula.

호스티드 origin 문구가 페이지마다 갈린다: `https://space.univer.ai/` vs `https://workspace.univer.plus/`.

---

## 6. 호스트 플러그인

### 6.1 `dsh-univer-office` (DeepSeek Harness)

npm `dsh-univer-office@0.3.5`. MCP가 아니라 **DSH host tools**. 스킬: `univer`, `univer-sheet|doc|slide|base|board`, `univer-embed`, `univer-cross-unit-formula`.

| Tool | 역할 |
| --- | --- |
| `univer_new` | 빈 `.univer`, 덮어쓰지 않음 |
| `univer_worktree` | create / ready / reopen / merge / discard |
| `univer_execute` | Facade JS (`workbook`/`doc`/`presentation`/`base`/`board` + `api`) |
| `univer_inspect` / `univer_export` / `univer_screenshot` / `univer_print_pdf` | 검증·전달 |
| `univer_lint` / `univer_compile_svg` | 슬라이드 |
| `univer_api` / `univer_resources` | 오프라인 Facade·에셋 |

`package.json`이 `@univerjs/*`와 큰 `@univerjs-pro/*` 세트를 **1.0.2**로 고정한다.

### 6.2 `workbuddy-univer-office`

개발 프리뷰. 스킬 하나 `univer-office`. 로컬 MCP (`stdio` 또는 `127.0.0.1:9080`). DSH 패키지에 의존하지 않는다. 도구 군은 DSH와 같고 `univer_preview`가 추가된다. 일부 기능은 `UNIVER_LICENSE`.

### 6.3 `openclaw-univer-office`

OpenClaw 플러그인. `univer-workspace-cli`를 argv로 감싼다. 도구: `univer_office_connect|files|worktree|content|handoff`. `ready`는 trunk를 바꾸지 않는다. merge/discard는 사람 승인.

---

## 7. AI SDK 문서 (`docs.univer.ai/ai`)

`dream-num/documentation`의 `content/ai/`. **제품 CLI가 아니라 Office CLI를 만드는 TypeScript SDK** (`@univer-cli/*`, 문서상 25 패키지).

권장 형태:

```
AI Agent / CLI user → AI SDK (비즈니스 CLI)
Human               → Web SDK
both                → Server SDK (협업 · 파일 교환) → Storage
```

Worktree는 Git worktree가 아니다. 문서 콘텐츠의 협업 초안이다.

| 연산 | 의미 |
| --- | --- |
| `runtime.commit()` | 초안에 mutation 제출 |
| `markReady()` | 초안 동결, 리뷰 |
| `reopenWorktree()` | ready → draft |
| `mergeWorktree()` | draft Units → trunk |

문서 버전 콜아웃은 `1.0.0-rc.0`으로, skills의 `1.0.0-beta.0`·DSH의 `1.0.2`와 다르다.

문서 사이트의 `/mcp/icons`는 아이콘 검색 MCP (`search_icons`, `get_icon`)이지 스프레드시트 MCP가 아니다.

---

## 8. Pro / 라이선스

| 레포 | Pro? |
| --- | --- |
| univer-sdk-skills / skills (integrate, plugin-dev) | OSS. Bases/Boards/PDFs/licensed Slides는 pro-integrate |
| univer-mcp / start-kit | 호스티드 + `@univerjs-pro/mcp*` |
| univer-cli / workspace | 번들 localhost 라이선스 + `@univerjs-pro/*` 동버전 |
| dsh-univer-office | Pro + CLI SDK 1.0.2 고정 |
| workbuddy / openclaw | 배포/기능에 `UNIVER_LICENSE` |

OSS 클론만으로 에이전트를 붙이는 정본 경로는 **Node preset + Facade + `executeCommand` + `save()`** 다. Worktree·xlsx 왕복·스크린샷·차트는 형제 레포/Pro다.

---

## 9. 출처

공개 README / SKILL.md fetch, 2026-09-25:

- https://github.com/dream-num/univer-sdk-skills
- https://github.com/dream-num/skills
- https://github.com/dream-num/univer-mcp
- https://github.com/dream-num/univer-mcp-start-kit
- https://github.com/dream-num/univer-cli
- https://github.com/dream-num/univer-workspace
- https://github.com/dream-num/dsh-univer-office
- https://github.com/dream-num/workbuddy-univer-office
- https://github.com/dream-num/openclaw-univer-office
- https://docs.univer.ai/ai
- https://github.com/dream-num/documentation (`content/ai`)
