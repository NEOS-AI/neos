# 15. Neos 병합 상태 — Univer

조사 기준: 2026-09-25. Neos HEAD `2e621684` (`dev`). 원본 `/Users/yeonwoosung/Desktop/univer` v1.0.2 HEAD `1defaf4` (읽기 전용). 최종 부착 웨이브 부록: 같은 날, 커널·완결성 위에 Tasks 1–13이 `2e621684`까지 착륙했다.

이 문서는 원본 인벤토리(`00`–`14`)와 구현 계약(`spec/`)을 **대체하지 않는다**. 커널·완결성·최종 부착 웨이브 착륙 뒤, OSS Office 기능이 Neos에 있는지를 재감사한 기록이다. 방법: 도메인 서브에이전트 16 + 후속 5, 이후 `2026-09-25-fsi-univer-final.md`.

분류 라벨은 [FSI 10-merge-status](../financial-services/10-merge-status.md)와 같다: MERGED / PARTIAL / DEFERRED / GAP / OUT OF SCOPE.

판정 막대:

1. **커널 + 최종 부착 웨이브** — `docs/superpowers/plans/2026-09-25-univer-kernel.md` + completeness + `2026-09-25-fsi-univer-final.md`. 하네스 부착 + in-memory 더블. SKILL.md·glob·SessionPort flags·office-session 드라이버가 붙었다. 이 막대는 대체로 맞다.
2. **Office SDK 제품** — `@univerjs` Node preset, 수식 516, Facade `save()` 스냅샷, Docs OT. 이 막대는 더블이다. Node pin은 이후.

완결성 플랜 잠금: 이 웨이브는 **더블을 개선**한다. Node pin은 이후다 (`2026-09-25-univer-kernel-completeness.md:7,40`). spec `01`이 Node sidecar를 v0로 적은 문장은 이 잠금에 진다.

---

## 1. 한 줄

Univer는 에이전트 루프가 아니라 Office SDK다. Neos v0는 `ParentKind.UNIVER`와 kebab 네 개로 **딥 하네스에 붙인 런타임 능력**이다. 라이브 엔진은 Python `InMemorySidecar`다. `SidecarClient`는 Node를 띄우지 않는다. 네 SKILL.md는 더블 계약을 가르친다. `run_parent_spawn`이 office-session 리프를 스폰한다. HTTP `/api/v1/univer`와 부모 LLM 내구 턴 루프는 없다.

---

## 2. 커널에 있는 것

| 능력 | 상태 | 위치 |
|---|---|---|
| `ParentKind.UNIVER` + 마이그레이션 `065` (064는 역사적 4종) | MERGED | `types.py`; `db/migrations/065_allow_univer_subagent_parent.sql` |
| kebab `univer-reader\|writer\|critic\|formula` | MERGED | `neos/subagent/catalog.py:262-353` |
| 전부 `SandboxMode.NONE`, `can_spawn=False`, 작성자 하나 | MERGED | catalog + `profile.py` |
| `UniverConfig` 기본 off; formula는 sheets 필요 | MERGED | `neos/config/schema.py:2029-2045` |
| office-session YAML + 5블록 프롬프트 | MERGED | `skills/univer/profiles/office-session.yaml`, `agents/office-session.md` |
| 스킬 4개, `univer_catalog()`, 코딩 루트와 분리 | MERGED | `skills/univer/*/SKILL.md` (InMemorySidecar 계약); `markdown_catalog.py:54-63` |
| 리더 스키마 00 (`unit_id`,`kind`,`sheets`) | MERGED | `neos/univer/schemas.py:33-55` |
| 수식 스키마 02 (`wait_status`,`error_count`, ErrorType 12) | MERGED | `schemas.py:57-107` |
| fold 게이트 completed + `full_summary` | MERGED | `neos/univer/loop.py:95-97` |
| COMMAND 12 허용, MUTATION/OPERATION → `mutation_forbidden` | MERGED | `allowlist.py`; `ports.py:370-378` |
| `save()` `_confine` + draft_root + 심링크 거부 | MERGED | `sidecar.py:314-340`; `tests/univer/test_sidecar_tools.py:336-378` |
| 리프 `univer.merge.v1` → `policy_binding_denied` | MERGED | `ports.py:363-367` |
| 부모 헬퍼 `merge_draft_to_trunk` | MERGED (호출은 테스트) | `ports.py:310-326` |
| Node 없음 → `node_missing`; 바이너리만 있으면 `sidecar_unavailable` | MERGED | `sidecar.py:74-85`; `ports.py:290-301` |
| `cancel_univer_children` / `artifact_status_for` | MERGED (헬퍼) | `loop.py:101-114` |
| binding execute 경로 | MERGED | `UniverSessionPort` / `UniverToolPort` `_binding_denied` |
| glob `*` 한 세그먼트 (`draft/*.json` ≠ nested) | MERGED | `ports.py:398-413`; `tests/univer/test_ports.py` |
| `UniverSessionPort(flags=)` | MERGED | `ports.py:182-193` |
| `run_parent_spawn` + `overlay_catalog` + `FlagDisabled` | MERGED | `neos/univer/loop.py:25-69` |
| 코딩 `spawn_agent.v1` `univer-*` → `policy_unknown_spec` | MERGED | `neos/coding/loop/_durable/spawn.py:794-795` |
| `univer.facade_js.v1` / 자유 JS / hosted MCP | OUT OF SCOPE (거부) | `ports.py:264-265` |
| Slides / Bases / Boards / PDF / Pro / CLI | OUT OF SCOPE | KD11 |
| HTTP `/api/v1/univer` | DEFERRED | 라우트 없음 |
| Node `@univerjs` sidecar pin | DEFERRED | `SidecarClient`는 띄우지 않음 |

`loop.py`는 `run_leaf` + `run_parent_spawn` 드라이버 + 위 두 헬퍼다. 라이브 부모 LLM이 `spawn_agent`를 해석하는 내구 턴 루프는 없다.

---

## 3. 패키지 · preset vs 사이드카

클론 공개 패키지 60, preset 17. Node/headless는 **둘**: `preset-sheets-node-core`, `preset-docs-node-core`. Slides Node preset/Facade 없음.

`InMemorySidecar` RPC: `health`, `create`, `dispose`, `load`, `inspect`, `range_get`/`range_set`, `execute_command`, `formula_wait`, `save`. 리프 도구는 inspect / range_get / range_set / execute_command / formula_wait / save 여섯이다. health/load/dispose/create는 부모 RPC다.

빈 시트 기본값 1000×20, 행 높이 24, 열 너비 88, `appVersion` `1.0.2`는 SDK와 같다 (`sidecar.py:25-29` vs `sheet-snapshot-utils.ts:22-32`). ErrorType 12 리터럴 동일.

stock node-core가 가진 filter / hyperlink / drawing / thread-comment / numfmt는 더블에 없다. CF/table은 OSS 패키지이고 허용 목록에 있으나, 더블은 `resources[]`에 커맨드 params JSON만 붙인다.

`create` RPC는 spec 01 §4 표에 없다. completeness 테스트가 `one_unit_limit`에 쓴다. 암시적 부트가 한 유닛이다.

---

## 4. COMMAND 12

허용 ID (`neos/univer/allowlist.py:3-18`):

`sheet.command.set-range-values`, `insert-row`, `insert-col`, `remove-row`, `remove-col`, `add-worksheet-merge`, `sort-range`, `addDataValidation`, `add-conditional-rule`, `add-table`, `doc.command.insert-text`, `doc.command.update-text`.

12개 모두 상태를 바꾼다. silent `ok: true` no-op는 없다. 인벤토리 `11-command-ids.md` 609개 dump는 상수 ID `insert-row` 등을 빠뜨렸다 (소스 `InsertRowCommandId`).

| ID | 더블 동작 | vs Univer | 분류 |
|---|---|---|---|
| set-range-values | `cellData` + dirty | interceptor extra MUTATION 없음 | MERGED / PARTIAL |
| insert/remove row/col | 셀·카운트·머지 시프트, floor 1 | `*-by-range` + interceptor 없음 | MERGED / PARTIAL |
| add-worksheet-merge | `mergeData[]` append | overlap/clear 없음 | MERGED / PARTIAL |
| sort-range | 첫 열 numeric then string | `orderRules` / filter 없음 | MERGED / PARTIAL |
| DV / CF / table | `resources[].data = json.dumps(params)` | 플러그인 `toJson` 모델 아님 | PARTIAL |
| insert-text | `{text}`를 `\r\n` 앞에 splice | TextX `{body, range, unitId}` 아님 | MERGED (완결성 `{text}`) |
| update-text | 본문 전체 `text + "\r\n"` | OSS는 범위 RETAIN | LOCKED→code (완결성 교체) |

비허용 COMMAND → `command_not_allowlisted`. `*.mutation.*` / `*.operation.*` → `mutation_forbidden` (allowlist보다 mutation 먼저). `unit_kind_mismatch`는 `test_sheet_command_on_doc_is_unit_kind_mismatch`가 잠근다.

인터셉터 extra MUTATION은 v0 더블 범위 밖 (DEFERRED).

---

## 5. 수식

소스 재집계: map **516** / `index.ts` 구현 **502**. 인벤토리 `02` · `14`와 일치.

Neos가 계산하는 것 (`sidecar.py`): `+ - * /`, 비교, A1, 범위, `SUM`, `IF`. 그 외 호출은 `#NAME?`. `/0` → `#DIV/0!`.

알려진 더블 한계 (엔진 PARTIAL, 하네스 버그 아님):

- `SUM`이 ErrorType을 전파하지 않음 (비수치를 0/skip)
- `IF`가 eager (`1/0` 분기도 먼저 평가)
- 소문자 `if`는 Python keyword → `#NAME?`
- insert/remove가 수식 A1 텍스트를 다시 쓰지 않음

`univer.formula_wait.v1`는 writer와 formula 리프에 있다. 도구 응답은 `{ok, formula_dirty}` / `formula_timeout` / `unit_busy`. `wait_status` / `error_count`는 **fold 스키마**다.

커스텀 함수 RPC는 OSS가 throw한다. v0 비목표.

---

## 6. Facade → 도구

| Facade | Neos | 분류 |
|---|---|---|
| `FUniver.newAPI` / createUniver | 부모 사이드카 부트 | MERGED (부모) |
| `FRange` get/set A1 | `range_get` / `range_set` (set는 top-left) | PARTIAL |
| `FFormula.onCalculationResultApplied` | `formula_wait` | MERGED |
| `FUniver.executeCommand` | 12 COMMAND | PARTIAL |
| `FWorkbook.save` / `FDocument.save` | `univer.save.v1` → `draft/workbook.json` 또는 `draft/document.json` | MERGED (경로) / PARTIAL (JSON 모양) |
| `insertSheet` / undo / UI / screenshot | 없음 | DEFERRED / OUT OF SCOPE |

권한 매트릭스 (catalog ∩ stepper): writer만 range_set / execute_command / save / write_file / formula_wait. critic 쓰기 없음. glob는 오케스트레이터만. writer glob → `tool_not_allowed`.

`UniverToolPort.definitions()`는 사이드카 도구 여섯을 항상 돌려준다. 리프 거부는 카탈로그 멤버십이다.

---

## 7. draft / trunk 감옥

두 감옥이 둘 다 필요하다.

| | `write_file.v1` | `univer.save.v1` |
|---|---|---|
| 파일 | draft 직속 `*.json` | 정확히 `draft/workbook.json` 또는 `draft/document.json` |
| 심링크 | 논리 동일, 테스트는 save만 | 테스트 3개 (시트/세션 밖/문서) |

`merge_draft_to_trunk`는 두 스냅샷만 `trunk/`로 복사하고 `staged_for_signoff`를 돌려준다. 리프 merge는 거부.

glob `*`는 한 경로 세그먼트다 (`_glob_match` / `_glob_parts`, `ports.py:398-413`). `draft/*.json`은 `draft/workbook.json`에 맞고 `draft/nested/foo.json`에는 안 맞는다. MERGED.

`_shift_merges`는 insert/remove에서 호출된다. 행 삽입 후 머지 start/end 이동은 `test_insert_row_shifts_merge_start_row`가 잠근다 (MERGED).

권한 point ID (`1.action_unitId` …)는 `neos/univer/`에 없다. DEFERRED / OUT OF SCOPE.

---

## 8. 스냅샷 JSON

### 시트 — `Partial<IWorkbookData>`로 로드 가능, 라운드트립은 손실

`IWorkbookData.sheets` 값 타입이 `Partial<IWorksheetData>`다 (`typedef.ts:72`). Univer는 `mergeWorksheetSnapshotWithDefault`로 채운다. Neos는 그 merge를 하지 않는다.

Neos emit: `id`, `name`, `appVersion`, `sheetOrder`(한 시트), `sheets[id].{id,name,rowCount,columnCount,defaultRowHeight,defaultColumnWidth,mergeData,cellData}`, `resources`.

로드 후 다시 저장하면 사라지거나 덮이는 것: `locale`, `styles`, `dateSystem`, `rev`, `freeze`, `hidden`, `rowData`/`columnData`, 다른 시트, `resources[].id`. `appVersion`은 항상 `1.0.2`. 셀 `v`/`t`/`f`/`p`/`s`는 dict 통째 보관으로 살아남을 수 있다. `range_get`은 `v`/`t`/`f`만 보여 준다. `t` enum 1/2/3은 일치. `FORCE_STRING=4`는 Neos가 만들지 않는다.

실 `FWorkbook.save()` JSON을 넣었다가 다시 저장하면 스타일 테이블이 사라지고 셀 `s` id만 남는다.

테스트는 Neos-native JSON만 로드한다. 실 Facade 픽스처 없음.

### 문서 — Facade `IDocumentData`와 라운드트립 불가

emit (`sidecar.py:746-762`): `id`, `title`, `appVersion`, `documentStyle: {}`, `body.{dataStream, paragraphs[{startIndex}], sectionBreaks}`, `resources: []` 항상.

빠진 것: `paragraphId` (필수), `sectionId` (필수), 실 `documentStyle`, `locale`, `drawings`, `headers`/`footers`, `customRanges`, `textRuns`, plugin resources.

load는 `id` / `title` / `body.dataStream`만 복구한다. Univer `createDocument`는 body를 통째 교체하므로 기본 스냅샷이 구멍을 메우지 않는다.

스킬 `univer-docs-headless`는 Python `InMemorySidecar`와 `doc.command.insert-text` `{text}` splice, `univer.save.v1` → `draft/document.json`을 가르친다. Node preset / `FDocument.save()`는 라이브 경로가 아니다 (UNI-5 LOCKED→code).

---

## 9. 스킬 · 에코시스템

MERGED: 네 SKILL.md (InMemorySidecar · `univer.*.v1`, Facade/Node를 라이브로 가르치지 않음), office-session 컴파일, `output_schema_ref`, 빈 `mcp_allowlist` 강제, `univer_catalog()` ∩ allowlist, 코딩 `default_catalog().get("univer-sheets-headless") is None`.

`## When to Use` / `## Boundaries` 없음 — 코딩 카탈로그에서 빠지도록 의도.

형제 레포 (univer-mcp, univer-cli, Pro, Workspace, DSH)는 이 머신에 클론되어 있지 않다. README 언급만. copytree `dream-num/skills` 없음. OUT OF SCOPE.

리프 `skill_allowlist: []`. 부모만 네 이름을 가진다. writer 카탈로그에 `load_skill.v1`이 있어도 빈 YAML이면 로드 불가.

---

## 10. Docs / Slides / UI

| 표면 | 분류 |
|---|---|
| `docs_enabled`, 빈 `"\r\n"`, insert `{text:"Hello"}` | MERGED / PARTIAL |
| `update-text` 의미 (OSS RETAIN vs 더블 replace) | LOCKED→code |
| delete-text, 헤더, 리스트, 테이블, OT | DEFERRED |
| drawing / hyperlink / comment 모델 (node-core에 일부 있음) | DEFERRED, allowlist 밖 |
| TOC / find-replace (render 의존) | OUT OF SCOPE |
| Slides (Facade·preset 없음, instance type 3 금지) | OUT OF SCOPE |
| Canvas Engine→Scene→Viewport | OUT OF SCOPE. `neos/univer/`에 render 경로 없음 |

---

## 11. 테스트 구멍

symlink-jail 테스트는 실제 심링크를 심고 trunk 바이트를 본다. 실패할 수 있다.

실패하기 어려운 테스트:

- `health.in_flight` 하드코드 `False` + idle 사이드카 assert
- `sidecar._in_flight = True`를 찔러 `unit_busy`
- `cancel_univer_children` 빈 스토어 → 양쪽 `[]`
- `quoted_json_is_handoff` 항진

더블 한계 핀 (엔진 PARTIAL, 하네스 버그 아님): SUM-of-`#DIV/0!` skip/zero, 소문자 `if` → `#NAME?`, `unit_kind_mismatch`, merge shift, glob 한 세그먼트, SessionPort `flags=` (`tests/univer/test_sidecar_tools.py`, `test_ports.py`).

테스트 없는 KD: KD4 Node pin, KD12 FSI는 openpyxl, KD14 HTTP 부재 assert, `test_no_pro_license_shipped`.

`lookup_spec("univer_reader")` → `UnknownSpec`은 테스트됨.

---

## 12. 스펙 vs 코드 (Univer)

| ID | 스펙 문장 | 코드 | 상태 |
|---|---|---|---|
| UNI-1 | v0 = Node sidecar | `InMemorySidecar` | LOCKED→code |
| UNI-2 | 00 수식 스키마 `status`/`cells` | 02 `wait_status`/`error_count` | LOCKED→code |
| UNI-3 | 01 “writer에게 write_file 주지 않는다” | writer가 가짐 | LOCKED→code |
| UNI-4 | 01 critic가 `out/_spec` 씀 | critic 쓰기 없음 | LOCKED→code |
| UNI-5 | SKILL.md가 Facade/Node를 가르침 | 네 SKILL.md가 InMemorySidecar/`univer.*.v1` | LOCKED→code |
| UNI-6 | persist Facade `IDocumentData` | subset + `resources: []` | LOCKED→code (더블) |
| UNI-7 | update-text = 속성/백스페이스 | replace paragraph | LOCKED→code |
| UNI-8 | 00 orch tokens에서 glob 제외 스니펫 | glob 포함 | LOCKED→code |
| UNI-9 | 00 writer에 formula_wait 없음 | writer가 가짐 | LOCKED→code |
| UNI-10 | 00 writer WORKTREE 잔여 | 전부 NONE | LOCKED→code |
| UNI-11 | 02 reader `[unit_kind, status]` | 00 `[unit_id, kind, sheets]` | LOCKED→code |
| 마스터 Goal 7 | truncated fold는 스키마 안 함 | KD10: `full_summary`로 함 | 코드는 KD10 |

“병합됐는가”에 답할 때 Node sidecar를 스펙 문장만 보고 MERGED로 쓰지 않는다. office-session `run_parent_spawn`은 드라이버다. 라이브 부모 LLM 루프가 아니다.

---

## 13. 코딩 부모 스폰 (공통 — kebab는 MERGED)

`neos/coding/loop/_durable/spawn.py:794-795`는 `lookup_spec` **전에** `fsi-` / `univer-` prefix를 거부한다. `spec=univer-writer` 등 네 kebab는 `policy_unknown_spec`, 자식 런 0. 플래그는 이 경로를 열지 않는다.

세션 overlay 별칭을 `univer-` prefix 없이 스폰하는 경로는 이 게이트 밖이다 (**GAP**, 이 웨이브 비목표). Univer 모듈 kebab는 prefix와 같다.

상세: [FSI 10 §11](../financial-services/10-merge-status.md#11-코딩-부모-스폰-공통--kebab는-merged).

---

## 14. 다음 웨이브 (우선)

1. 실 Node `@univerjs` 1.0.2 sidecar pin — 그 전에 더블 JSON을 `FWorkbook.save()` / `FDocument.save()`로 부르지 않는다. 커맨드 params도 `{text}` / `{startRow,count}` → Univer `{body,range,unitId}` 번역이 필요하다
2. HTTP `/api/v1/univer` — 사용자가 요청하기 전까지 시작하지 않는다
3. 코딩 overlay 별칭을 `fsi-`/`univer-` prefix 없이 거부
4. 부모 LLM이 `spawn_agent`를 해석하는 내구 턴 루프 (`run_parent_spawn`은 드라이버일 뿐)
5. 더블 JSON 라운드트립 (`locale`/`styles`/`IDocumentData`) — 엔진 한계이지 하네스 GAP이 아님

HTTP/UI와 Pro/MCP/CLI는 사용자가 요청하기 전까지 시작하지 않는다.
