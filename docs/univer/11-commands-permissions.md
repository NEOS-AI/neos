# 커맨드 하네스 · 인터셉터 · 권한 · 라이프사이클

조사 기준: `/Users/yeonwoosung/Desktop/univer` v1.0.2. 1차 문서(`01-architecture-harness.md`)가 얇게 둔 실행 경로를 소스에서 다시 집계한다. ID 전수는 [11-command-ids.md](./11-command-ids.md).

---

## 1. 한 줄

에이전트가 Facade로 쓰는 모든 쓰기는 `ICommandService`를 탄다. COMMAND가 MUTATION 묶음을 만들고 undo 스택에 넣는다. OPERATION은 스냅샷에 안 남는다. Sheets는 `SheetInterceptorService`가 커맨드 전후에 부가 MUTATION을 붙인다. 권한은 인메모리 포인트 3층(workbook / worksheet / range). 플러그인은 `LifecycleStages` 네 단계에 맞춰 깨어난다.

---

## 2. CommandType 계약

`packages/core/src/services/command/command.service.ts:37-55`.

| 값 | 이름 | 스냅샷 | 협업 단위 | 역할 |
| --- | --- | --- | --- | --- |
| 0 | `COMMAND` | 직접 쓰지 않음 | MUTATION을 통해 | 비즈니스 오케스트레이션. undo MUTATION을 만들고 `pushUndoRedo` |
| 1 | `OPERATION` | 저장하지 않음 | 충돌 해결 없음 | 스크롤, 사이드바, 활성 시트, 팝업 |
| 2 | `MUTATION` | 저장 | 충돌 해결의 최소 단위 | 셀 값, 행/열, 필터, 수식 결과 |

ID 패턴 (`command.service.ts:67-71`): `<namespace>.<type>.<command-name>`. 예: `sheet.command.set-range-values`.

`ICommand.handler(accessor, params?, options?)`는 파라미터를 **직렬화 가능**하게 받도록 적혀 있다 (`command.service.ts:80-85`). `IMultiCommand`는 같은 id에 여러 구현을 `priority`/`preconditions`로 고른다 (`command.service.ts:92-105`).

### 2.1 실행 옵션

`IExecutionOptions` (`command.service.ts:186-199`):

| 필드 | 의미 |
| --- | --- |
| `onlyLocal` | 주석: 로컬만, replica에 동기화하지 말 것. **DataSync는 이 플래그를 보지 않는다** |
| `fromCollab` | 협업 피어에서 온 커맨드 |
| `fromChangeset` | 스냅샷/changeset 로드 |
| `syncOnly` | changeset만 보내고 로컬 실행은 나중에 `onlyLocal`로 |
| 인덱스 시그니처 | RPC가 `fromSync`를 여기에 실어 bounce를 막는다 |

`onMutationExecutedForCollab`은 **리스너 배열**이다. 같은 함수 참조를 두 번 넣으면 throw (`command.service.ts:403-414`). `syncOnly`면 collab 리스너만, 그 외 MUTATION은 일반 `onCommandExecuted`와 collab 리스너를 둘 다 부른다. 이 클론의 프로덕션 플러그인은 collab 리스너를 등록하지 않는다.

### 2.2 에이전트가 실제로 부르는 경로

Facade `univerAPI.executeCommand(id, params)` → `ICommandService.syncExecuteCommand` (`packages/core/src/facade/f-univer.ts:547-553`). `FRange.setValue` 같은 고수준 API도 내부에서 `sheet.command.set-range-values`를 실행한다.

에이전트가 자주 쓰는 COMMAND:

| ID | 하는 일 |
| --- | --- |
| `sheet.command.set-range-values` | 셀 값/수식/스타일 |
| `sheet.command.insert-row` / `insert-col` | 행·열 삽입 |
| `sheet.command.remove-row` / `remove-col` | 삭제 |
| `sheet.command.add-worksheet-merge` | 병합 |
| `sheet.command.sort-range` | 정렬 |
| `sheet.command.addDataValidation` | 데이터 유효성 |
| `sheet.command.add-conditional-rule` | 조건부 서식 |
| `sheet.command.add-table` | 구조화 테이블 |
| `doc.command.insert-text` / `update-text` | 문서 텍스트 |
| `doc.command.insert-doc-image` | 문서 이미지 |
| `formula.command.insert-function` | 수식 삽입 UI/커맨드 |
| `thread-comment.command.add-comment` | 댓글 |

MUTATION(`sheet.mutation.set-range-values` 등)을 에이전트가 직접 부르면 undo/인터셉터/권한 훅을 건너뛴다. 커스텀 플러그인이 아니면 COMMAND를 쓴다.

---

## 3. 집계 — 609 ID

`__tests__`를 뺀 `packages/**/*.ts(x)`에서 `*.command.*` / `*.mutation.*` / `*.operation.*` 문자열을 모으면 **609**.

| 종류 | 개수 |
| ---: | ---: |
| command | 367 |
| mutation | 120 |
| operation | 122 |

상위 prefix:

| prefix | 개수 |
| --- | ---: |
| `sheet.command` | 239 |
| `doc.command` | 91 |
| `sheet.mutation` | 71 |
| `sheet.operation` | 52 |
| `formula.mutation` | 28 |
| `doc.operation` | 14 |
| `ui.operation` | 10 |
| `slide.operation` | 9 |
| `sheets.command` | 9 |
| `drawing.operation` | 8 |

`base-ui.operation` 2개가 OSS에 있다 (`toggle-fullscreen`, `toggle-shortcut-panel`). `packages/bases*` 플러그인은 없고, UI 슬롯 이름만 공유 워크벤치에 남아 있다. Slides COMMAND는 **4개** (`add-text`, `insert-float-image`, ellipse/rectangle shape).

전수 목록: [11-command-ids.md](./11-command-ids.md).

---

## 4. `SheetInterceptorService`

`packages/sheets/src/services/sheet-interceptor/sheet-interceptor.service.ts`. Sheets 기능 플러그인이 커널 커맨드에 부가 MUTATION을 꽂는 구멍이다.

### 4.1 커맨드 훅

| 메서드 | 쌍 | 하는 일 |
| --- | --- | --- |
| `interceptBeforeCommand` / `beforeCommandExecute` | 실행 허가 | `performCheck`가 모두 true여야 COMMAND가 진행 (`:259-278`) |
| `interceptCommand` / `onCommandExecute` | 실행 중 | 부가 undo/redo MUTATION. `preUndos`/`preRedos`로 순서 고정 (`:181-206`) |
| `interceptAfterCommand` / `afterCommandExecute` | 실행 후 | 사후 MUTATION (`:208-226`) |
| `interceptAutoHeight` / `generateMutationsOfAutoHeight` | 행 높이 | 자동 높이 부가 MUTATION (`:228-248`) |
| `interceptRanges` | 범위 | 피벗 등, 영역 지울 때 플러그인 데이터 정리 (`:282-288`) |

priority는 **큰 숫자가 앞** (`sort (b - a)`). HTTP interceptor와 반대다.

### 4.2 셀/행 뷰 훅

`INTERCEPTOR_POINT` (`interceptor-const.ts:24-27`):

- `CELL_CONTENT` — 렌더/읽기 시 셀 값을 합성. 기본 핸들러 priority -1.
- `ROW_FILTERED` — 필터가 행을 숨기는지.

`writeCellInterceptor` 키: `BEFORE_CELL_EDIT`, `AFTER_CELL_EDIT`, `VALIDATE_CELL`.

셀 콘텐츠 우선순위 상수 (`interceptor-const.ts:29-33`):

| 이름 | 값 |
| --- | ---: |
| DATA_VALIDATION | 9 |
| NUMFMT | 10 |
| CELL_IMAGE | 11 |

필터·numfmt·DV·노트·테이블이 이 파이프에 붙는다. 에이전트가 `getValue`로 읽는 표시값은 원본 `ICellData.v`가 아니라 인터셉터 합성값일 수 있다.

---

## 5. 권한 3층

인메모리 `IPermissionService` (`packages/core/src/services/permission`). 실시간 ACL 서버는 없다. `AuthzIoLocalService`가 로컬 스텁이다.

### 5.1 Workbook 포인트

`packages/sheets/src/services/permission/workbook-permission/util.ts:21-44`.

Edit, Print, Comment, View, Copy, Export, ManageCollaborator, CreateSheet, DeleteSheet, RenameSheet, HideSheet, Duplicate, Share, MoveSheet, CopySheet, ViewHistory, RecoverHistory, CreateProtect, InsertRow, InsertColumn, DeleteRow, DeleteColumn.

기본 `UnitAction` 목록이 같다 (`defaultWorkbookPermissionPoints`, `:46-69`). History/Share/Export는 OSS UI에 자리가 있고 구현은 Pro다.

### 5.2 Worksheet 포인트

코어 4개 (`worksheet-permission/utils.ts:20-25`): Edit, View, ManageCollaborator, DeleteProtection.

패널 확장 (`:28-43`): Copy, DeleteColumn/Row, EditExtraObject, Filter, InsertColumn/Row, InsertHyperlink, PivotTable, SetCellStyle/Value, SetColumnStyle/RowStyle, Sort.

### 5.3 Range 보호

`getAllRangePermissionPoint` (`range-permission/util.ts:25`): View, Edit, ManageColla, DeleteProtection.

`RangeProtectionService`가 규칙이 생기면 포인트를 만들고, 규칙이 바뀌면 포인트를 갈아끼운다.

권한 포인트 **id는 이름 문자열이 아니라 숫자 enum**이다 (`packages/protocol/src/ts/univer/permission.ts`).

| 층 | 템플릿 | 예 |
| --- | --- | --- |
| Workbook | `${UnitObject.Workbook}.${UnitAction}_${unitId}` | Edit = `1.1_${unitId}` |
| Worksheet | `${UnitObject.Worksheet}.${UnitAction}_${unitId}_${subUnitId}` | View = `2.0_${unitId}_${sheetId}` |
| Range | `${UnitObject.SelectRange}.${UnitAction}.${permissionId}` | Edit = `3.1.${permissionId}` |

시트 권한 거부는 `interceptBeforeCommand`가 아니라 `ICommandService.beforeCommandExecuted`에서 `CustomCommandExecutionError`를 던진다 (`sheet-permission-check.controller.ts:181-209`). `interceptBeforeCommand`의 프로덕션 호출자는 이 클론에 없다 (테스트만).

Undo/Redo 커맨드 id: `univer.command.undo` / `univer.command.redo` (`undoredo.service.ts:124-174`). `NilCommand` id는 `'nil'`.

Docs 쪽 `DocInterceptorService`는 커맨드 부가 MUTATION이 아니라 custom-range/decoration **뷰 합성**이다.

### 5.4 Authz 로컬 스텁

`AuthzIoLocalService` (`packages/core/src/services/authz-io/authz-io-local.service.ts`):

- `create()` 기본 strategy는 **Owner 액션만**.
- `allowed()` 폴백(objectID/strategy 없음)은 Owner **또는** Editor.
- collaborator list/role/update는 빈 구현.
- 주석: 프로덕션에서 mock을 쓰지 말 것 (`:41-54`).
- `createUniver({ collaboration: true })`는 이 바인딩을 `null`로 빼서 Pro가 원격 IO를 넣게 한다 (`presets/src/preset.ts:51-55`).

---

## 6. 플러그인 라이프사이클

`LifecycleStages` (`packages/core/src/services/lifecycle/lifecycle.ts:20-40`):

| 단계 | 의미 |
| --- | --- |
| `Starting` | 플러그인 등록 |
| `Ready` | 유닛이 생기고 서비스/컨트롤러가 초기화됨. 첫 렌더 준비 |
| `Rendered` | 첫 렌더 완료 |
| `Steady` | lazy 작업까지 끝. 사용자 기능 제공 |

`Plugin` 훅: `onStarting` / `onReady` / `onRendered` / `onSteady` (`plugin.service.ts:51-65`). 로드 시점에 이미 지나간 단계를 재생한다.

타입 플러그인(`UNIVER_SHEET` 등)은 **그 타입의 첫 `createUnit`** 에서만 `startPluginsForType`이 돈다. `UNIVER_UNKNOWN`(UI, render, formula engine, network)만 등록 즉시 로드.

`@DependentOn(...)`은 미등록 의존성을 **빈 config로 자동 등록**한다 (`plugin.service.ts:115-119`, `274-280`).

이 클론의 `pluginName` 예:

| 플러그인 | pluginName |
| --- | --- |
| `UniverSheetsPlugin` | `SHEET_PLUGIN` |
| `UniverSheetsUIPlugin` | `SHEET_UI_PLUGIN` |
| `UniverDocsPlugin` | `DOCS_PLUGIN` |
| `UniverFormulaEnginePlugin` | `UNIVER_ENGINE_FORMULA_PLUGIN` |
| `UniverRPCMainThreadPlugin` | `UNIVER_RPC_MAIN_THREAD_PLUGIN` |
| `UniverActionRecorderPlugin` | `UNIVER_ACTION_RECORDER_PLUGIN` |
| `UniverWatermarkPlugin` | `UNIVER_WATERMARK_PLUGIN` |

버전이 `@univerjs/core`와 다르면 에러 로그 후 계속한다 (`plugin.service.ts:200-212`).

---

## 7. 리소스 훅 — 스냅샷에 플러그인 데이터 싣기

`IResources = Array<{ id?, name, data: string }>` (`packages/core/src/services/resource-manager/type.ts:22`). `IWorkbookData.resources` / `IDocumentData.resources`가 이 배열이다.

`IResourceHook.pluginName`은 `` `${SHEET\|DOC\|SLIDE\|BOARD\|BASE\|UNIVER}_${string}_PLUGIN` `` 형식 (`type.ts:24-27`). `registerPluginResource`가 `toJson`/`parseJson`/`onLoad`/`onUnLoad`를 묶는다.

이 클론에서 등록이 확인된 훅:

| 상수/이름 | 패키지 |
| --- | --- |
| `SHEET_DATA_VALIDATION_PLUGIN` | data-validation |
| `DOCS_DRAWING_PLUGIN` | docs-drawing |
| `DOC_HYPER_LINK_PLUGIN` | docs-hyper-link |
| `SHEET_CONDITIONAL_FORMATTING_PLUGIN` | sheets-conditional-formatting |
| `SHEET_DEFINED_NAME_PLUGIN` | sheets (defined names) |
| `SHEET_DRAWING_PLUGIN` | sheets-drawing |
| `SHEET_FILTER_SNAPSHOT_ID` | sheets-filter |
| 노트 `PLUGIN_NAME` | sheets-note |
| range protection `PLUGIN_NAME` | sheets permission |
| worksheet POINT/RULE model | sheets permission |

`FWorkbook.save()`는 모델 스냅샷 + 이 리소스 배열을 합친다. 에이전트가 필터/DV/CF를 검증하려면 `save()` 결과를 봐야 한다.

---

## 8. Undo

`LocalUndoRedoService` (`packages/core/src/services/undoredo/undoredo.service.ts`).

- 아이템: `{ unitID, undoMutations, redoMutations, id? }` (`:31-42`).
- `undoRedo.historyLimit` 기본 50. `0`이면 히스토리 없음 (`Univer` 생성자).
- `beginUndoRedoGroup`으로 연속 푸시를 한 아이템으로 묶는다.
- 에디터 유닛 id(`DOCS_NORMAL_EDITOR_UNIT_ID_KEY` 등)는 시트 포커스와 분리한다.

`collaboration: true`면 `IUndoRedoService` 바인딩을 제거한다. Pro collab이 원격 undo를 넣기 위한 슬롯이다.

---

## 9. Action recorder · Telemetry · Watermark

| 패키지 | 역할 | Facade |
| --- | --- | --- |
| `@univerjs/action-recorder` | 사용자 액션 기록/리플레이. 커맨드 `start/stop/complete-recording`, `replay-local-records*` | 없음 |
| `@univerjs/telemetry` | `ITelemetryService` 인터페이스만. 기본 구현·전송 없음 | 없음 |
| `@univerjs/watermark` | 렌더 엔진 위에 워터마크 | 있음 |

레코더는 디버그/데모용이지 에이전트 루프가 아니다. 리플레이는 같은 COMMAND ID를 다시 실행한다.
