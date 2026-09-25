# Univer Sheets + Formula Engine

조사 기준: Univer `1.0.2` (`/Users/yeonwoosung/Desktop/univer`). OSS 범위는 README가 말하는 것만 적는다. Pro 소스(차트, 피벗, 실시간 협업 등)는 이 저장소에 없고, 여기서 발명하지 않는다.

계층은 대략 다음이다.

```text
packages/core/src/sheets     스냅샷·Workbook/Worksheet/Range 모델
packages/sheets              커맨드/뮤테이션, 선택, 인터셉터, 권한
packages/sheets-ui           캔버스 UI, 셀/수식 편집기, 렌더 컨트롤러
packages/engine-formula      Lexer → AST → Interpreter + 함수 레지스트리
                             (파이프라인 상세: [14-formula-engine-internals.md](./14-formula-engine-internals.md))
packages/sheets-formula      시트 dirty 트리거, 워커 위임, 결과 적용
packages/sheets-formula-ui   수식 바, 프롬프트, 범위 선택기
기능 플러그인                numfmt / filter / sort / DV / CF / …
```

---

## 1. 패키지 목록

각 행의 Facade는 `package.json`의 `"./facade"` export 여부다. Sheets UI 쌍 중 Facade가 없는 패키지는 `numfmt-ui`만이 아니다. `conditional-formatting-ui`, `data-validation-ui`, `filter-ui`, `sort-ui`, `thread-comment-ui`도 없다. `sheets-note-ui` / `sheets-table-ui`는 export만 있고 `src/facade/`가 없다. 전수는 [10-cross-check.md](./10-cross-check.md) §1.2.

| 패키지 | 역할 | 플러그인 | Facade | 핵심 커맨드 / 서비스 |
| --- | --- | --- | :---: | --- |
| `@univerjs/sheets` | 시트 데이터 모델·비즈니스 로직. UI 독립. | `UniverSheetsPlugin` (`SHEET_PLUGIN`) | 있음 `FWorkbook`/`FWorksheet`/`FRange`/`FSelection` | 커맨드 `sheet.command.set-range-values`, Insert/Remove row-col, merge, freeze, protection. 서비스 `SheetsSelectionsService`, `RefRangeService`, `SheetInterceptorService`, `NumfmtService`, `WorkbookPermissionService` |
| `@univerjs/sheets-ui` | 스프레드시트 UI. 캔버스 렌더, 셀 편집, 클립보드, 권한 UI. | `UniverSheetsUIPlugin` (`SHEET_UI_PLUGIN`); 모바일 `UniverSheetsMobileUIPlugin` | 있음. `FWorkbook`에 스크롤/편집 브리지 mixin | 서비스 `IEditorBridgeService`, `ISheetClipboardService`, `IFormulaEditorManagerService`, `ISheetSelectionRenderService`, `SheetSkeletonManagerService`. 렌더 모듈 `SheetRenderController`, `DesktopCellEditRenderController` |
| `@univerjs/sheets-formula` | 엔진을 시트에 연결. dirty, 의존성, 계산 트리거. | `UniverSheetsFormulaPlugin`; 워커 쪽 `UniverRemoteSheetsFormulaPlugin` | 있음. `FFormula` mixin (`registerFunction`, `setInitialFormulaComputing`) | 커맨드 `formula.command.insert-function`. 컨트롤러 `TriggerCalculationController`, `ActiveDirtyController`, `UpdateFormulaController`. 서비스 `FormulaRefRangeService`, `IRemoteRegisterFunctionService` |
| `@univerjs/sheets-formula-ui` | 수식 편집 UI. 수식 바, 함수 프롬프트, 범위 선택기. | `UniverSheetsFormulaUIPlugin`; 모바일 `UniverSheetsFormulaMobileUIPlugin` | 있음. `showRangeSelectorDialog` | 서비스 `IFormulaPromptService`, `GlobalRangeSelectorService`, `RefSelectionsRenderService`. 컨트롤러 `FormulaUIController`, `FormulaClipboardController` |
| `@univerjs/sheets-numfmt` | 표시 형식 커맨드. | `UniverSheetsNumfmtPlugin` | 있음. `FRange`/`FWorkbook` mixin | `sheet.command.numfmt.set.numfmt`, `.set.currency`, `.set.percent`, `.add.decimal`, `.subtract.decimal`. 컨트롤러 `SheetsNumfmtCellContentController` |
| `@univerjs/sheets-numfmt-ui` | 서식 메뉴·에디터·미리보기. | `UniverSheetsNumfmtUIPlugin`; 모바일 `UniverSheetsNumfmtMobileUIPlugin` | 없음 | `SheetNumfmtUIController`, `NumfmtEditorController`, `NumfmtMenuController`, 렌더 `NumfmtAlertRenderController` |
| `@univerjs/sheets-filter` | 필터 모델·커맨드. | `UniverSheetsFilterPlugin` | 있음 `FFilter` | `sheet.command.set-filter-range`, `.remove-sheet-filter`, `.smart-toggle-filter`, `.set-filter-criteria`, `.clear-filter-criteria`, `.re-calc-filter`. `SheetsFilterService`, `SheetsFilterFormulaService` |
| `@univerjs/sheets-sort` | 정렬. | `UniverSheetsSortPlugin` | 있음 `FRange`/`FWorksheet` mixin | `sheet.command.sort-range` → `ReorderRangeCommand`. `SheetsSortService` |
| `@univerjs/sheets-data-validation` | 시트 DV 커맨드·수식 연동. `@univerjs/data-validation`에 의존. | `UniverSheetsDataValidationPlugin` | 있음 | `sheet.command.addDataValidation`, `.updateDataValidationRuleRange`, `sheets.command.update-data-validation-setting`. `SheetDataValidationModel`, `DataValidationFormulaService`, `SheetsDataValidationValidatorService` |
| `@univerjs/sheets-conditional-formatting` | 조건부 서식 모델·계산. | `UniverSheetsConditionalFormattingPlugin` | 있음 | `sheet.command.add-conditional-rule`, `.set-conditional-rule`, `.delete-conditional-rule`, `.move-conditional-rule`, `.clear-range-conditional-rule`. `ConditionalFormattingService`, `ConditionalFormattingFormulaService` |
| `@univerjs/sheets-hyper-link` | 하이퍼링크 모델. | `UniverSheetsHyperLinkPlugin` | 있음 | `sheets.command.add-hyper-link`, `.update-hyper-link`, `.cancel-hyper-link` (+ rich 변형). `HyperLinkModel`, `SheetsHyperLinkParserService` |
| `@univerjs/sheets-note` | 셀 노트. | `UniverSheetsNotePlugin` | 있음 | `sheet.command.update-note`, `.delete-note`, `.toggle-note-popup`. `SheetsNoteModel` |
| `@univerjs/sheets-table` | 구조화 테이블. | `UniverSheetsTablePlugin` | 있음 | `sheet.command.add-table` 및 filter/sort/insert-row-col. `TableManager`, `SheetTableService`, `SheetTableFormulaController` |
| `@univerjs/sheets-find-replace` | 찾기/바꾸기. `@univerjs/find-replace`에 의존. | `UniverSheetsFindReplacePlugin`; 모바일 `UniverSheetsFindReplaceMobileUIPlugin` | 있음 `FTextFinder` | `sheet.command.replace`. `SheetsFindReplaceController` |
| `@univerjs/sheets-thread-comment` | 스레드 댓글. `@univerjs/thread-comment`에 의존. | `UniverSheetsThreadCommentPlugin` | 있음 `FThreadComment` | 자체 커맨드보다 공유 플러그인 커맨드 + `SheetsThreadCommentModel`, `SheetsThreadCommentRefRangeController` |
| `@univerjs/sheets-drawing` | 시트 드로잉(이미지 등). `@univerjs/drawing`에 의존. | `UniverSheetsDrawingPlugin` | 있음 | `sheet.command.insert-sheet-image`, `.set-sheet-image`, `.remove-sheet-image`, `.set-drawing-arrange`, `.set-worksheet-background-image`. `ISheetDrawingService` |
| `@univerjs/engine-formula` | 수식 런타임. 파싱, 함수 등록, 의존성, 계산. | `UniverFormulaEnginePlugin` (`UNIVER_ENGINE_FORMULA_PLUGIN`) | 있음 `FFormula`, `univerAPI.getFormula()` | 뮤테이션 `formula.mutation.set-formula-calculation-start` 등. `Lexer`/`AstTreeBuilder`/`Interpreter`/`CalculateFormulaService`/`FormulaDataModel` |

플러그인 클래스 위치:

- `UniverSheetsPlugin` — `packages/sheets/src/plugin.ts:57`
- `UniverSheetsUIPlugin` — `packages/sheets-ui/src/plugin.ts:137`
- `UniverSheetsFormulaPlugin` — `packages/sheets-formula/src/plugin.ts:95`
- `UniverRemoteSheetsFormulaPlugin` — 같은 파일 `:63`
- `UniverSheetsFormulaUIPlugin` — `packages/sheets-formula-ui/src/plugin.ts:66`
- `UniverFormulaEnginePlugin` — `packages/engine-formula/src/plugin.ts:78`

의존 방향은 `@DependentOn`으로 고정된다. 시트는 엔진에 의존하고 (`packages/sheets/src/plugin.ts:56`), 수식 플러그인은 엔진+시트 (`packages/sheets-formula/src/plugin.ts:94`), UI는 엔진+렌더+시트+수식+시트 UI (`packages/sheets-formula-ui/src/plugin.ts:59-65`).

---

## 2. Workbook / Worksheet / Range 모델

모델 클래스는 `packages/core/src/sheets/`에 있다. `packages/sheets`는 이 모델을 명령으로 바꾸고, 선택·인터셉터·권한을 붙인다. Facade (`FWorkbook` 등)는 다시 그 명령을 감싼다.

### 2.1 스냅샷

`IWorkbookData` (`packages/core/src/sheets/typedef.ts:31`):

| 필드 | 의미 |
| --- | --- |
| `id` | 워크북 unit id |
| `rev` | 협업 리비전. OSS 모델에 필드는 있으나 실시간 협업 구현은 Pro |
| `name`, `appVersion`, `locale` | 메타 |
| `dateSystem` | Excel 1900/1904 |
| `styles` | 스타일 id → `IStyleData` |
| `sheetOrder` | 시트 id 순서 |
| `sheets` | id → `IWorksheetData` |
| `resources` | 다른 플러그인 데이터 |
| `custom` | 사용자 필드. 외부 사용 비권장 |

`IWorksheetData` (`typedef.ts:116`): `id`, `name`, `tabColor`, `hidden` (`WorksheetHiddenState` 0/1/2), `freeze`, `rowCount`/`columnCount`, `zoomRatio`, 스크롤, 기본 행/열 크기, `mergeData`, `cellData`, `rowData`, `columnData`, 헤더, 그리드라인, `backgroundImage`, `rightToLeft`, `custom`.

셀 `ICellData` (`typedef.ts:283`):

| 필드 | 의미 |
| --- | --- |
| `v` | 원본 값 (`string \| number \| boolean`) |
| `t` | `CellValueType` |
| `s` | 스타일 id 또는 인라인 스타일 |
| `p` | 리치 텍스트 `IDocumentData` |
| `f` | 수식 문자열, 예 `=SUM(A1:B4)` |
| `ft` | `FormulaType` NORMAL/SHARED/ARRAY/DATA_TABLE |
| `si` | shared formula id |
| `ref` | 배열 수식 범위 |
| `fd` | dynamic array 플래그 |
| `xf` | `_xlfn.` 등 Excel 접두사 |
| `custom` | 플러그인 메타 |

같은 셀에 `v`/`f`/`p`가 공존할 수 있다. `undefined`는 유지, `null`은 키 삭제. `Workbook.save()`는 플러그인 resources를 빼고, 에이전트 왕복은 Facade `FWorkbook.save()`다. 빈 시트 기본은 **1000행 × 20열**, 행높이 24, 열너비 88. 상세 계약은 [13-runtime-contracts.md](./13-runtime-contracts.md).

범위 `IRange` (`typedef.ts:534`): `startRow`/`startColumn`/`endRow`/`endColumn` + `rangeType` (`NORMAL`/`ROW`/`COLUMN`/`ALL`, `:457`) + absolute ref 타입.

### 2.2 `Workbook`

`packages/core/src/sheets/workbook.ts:40` — `UnitModel<IWorkbookData, UNIVER_SHEET>`.

- 내부 `_worksheets: Map<string, Worksheet>`, `_styles: Styles`, `_snapshot: IWorkbookData`.
- `save()`는 스냅샷 deep clone (`:141`).
- `getActiveSheet()` / `setActiveSheet()` / `ensureActiveSheet()` (`:257-302`). 숨기지 않은 시트가 없으면 첫 시트를 활성화.
- `getSheets()`는 `sheetOrder` 순서 (`:339`).
- `sheetCreated$` / `sheetDisposed$` / `activeSheet$` / `name$`.

생성 시 빈 객체면 `getEmptySnapshot()`, 아니면 기본 스냅샷과 merge (`:87-119`).

### 2.3 `Worksheet`

`packages/core/src/sheets/worksheet.ts:92`.

- `_cellData: ObjectMatrix<ICellData>`, `_rowManager`, `_columnManager`, `_spanModel`(병합), `_viewModel`(`SheetViewModel`).
- `getCell(row, col)`는 raw가 아니라 인터셉터를 탄 view-model (`:590`).
- `getRange(...)`는 core `Range`를 만든다 (`:738-760`).
- 행/열 숨김, 높이/너비, freeze, 기본 스타일은 snapshot + manager.

`packages/sheets`의 `SheetInterceptorService`가 view-model에 훅을 꽂아 수식 결과, 조건부 서식, 필터 숨김 등을 합성한다.

### 2.4 Core `Range` vs Facade `FRange`

Core `Range` (`packages/core/src/sheets/range.ts:102`)는 시트 위 인접 셀 묶음이다. 주석이 Google Apps Script Range를 참조한다. `static foreach`, `transformRange`(ALL/ROW/COLUMN을 실제 좌표로 펼침).

Facade `FRange` (`packages/sheets/src/facade/f-range.ts`)는 `SetRangeValuesCommand` 등 명령을 실행한다. 에이전트/앱이 쓰는 API는 이쪽이다.

```text
IWorkbookData snapshot
    └── Workbook (core)
            └── Worksheet (core) ── getRange() → Range (core, 직접 셀 접근)
packages/sheets commands/mutations
    └── FWorkbook / FWorksheet / FRange  (Facade, 명령 실행)
```

### 2.5 `packages/sheets`가 붙이는 것

`UniverSheetsPlugin` 의존성 (`packages/sheets/src/plugin.ts:94-138`):

- 선택 `SheetsSelectionsService`
- 참조 이동 `RefRangeService` (행/열 삽입 시 수식·필터 범위 보정)
- 인터셉터 `SheetInterceptorService`
- 숫자 표시 `NumfmtService` (표시만. 서식 커맨드는 `sheets-numfmt`)
- 권한 workbook/worksheet/range protection
- range theme, auto-fill, exclusive range
- `CalculateResultApplyController` — `notExecuteFormula`가 아니면 등록. 엔진 결과 뮤테이션을 `SetRangeValuesMutation`으로 셀에 씀 (`packages/sheets/src/controllers/calculate-result-apply.controller.ts:21-42`)

커맨드는 `BasicWorksheetController`가 대량 등록한다 (`packages/sheets/src/controllers/basic-worksheet.controller.ts`). 대표 id: `sheet.command.set-range-values` (`set-range-values.command.ts:53`).

---

## 3. engine-formula 아키텍처

README 한 줄: 파싱, 함수/설명 등록, 의존성, 계산, 수식 에디터 헬퍼 (`packages/engine-formula/README.md:7`).

플러그인은 계산을 켤지 `notExecuteFormula`로 가른다 (`packages/engine-formula/src/plugin.ts:133-206`).

- **메인+워커 공통**: `FunctionService`, `DefinedNamesService`, `DescriptionService`, `FormulaDataModel`, `FormulaController`, 트리거/세션.
- **계산을 하는 쪽만** (`notExecuteFormula !== true`): `Lexer`, `AstTreeBuilder`, `Interpreter`, AST 팩토리, `CalculateFormulaService`, `FormulaDependencyGenerator`, `DependencyManagerService`.

주석이 역할을 나눈다. `_initialize()`는 “worker and main thread” (`:134`), `_initializeWithOverride()`의 계산 서비스는 “only worker” (`:196`). 워커를 쓰면 메인 스레드 플러그인은 `notExecuteFormula: true`로 파서/인터프리터를 올리지 않는다.

### 3.1 Lexer → Parser → Interpreter

파이프라인:

1. **Lexer / LexerTreeBuilder**  
   `Lexer.treeBuilder(formulaString, …)` (`packages/engine-formula/src/engine/analysis/lexer.ts:34`)가 defined name을 풀어 `LexerTreeBuilder`에 넘긴다. 토큰·연산자 우선순위·테이블 참조 정규식은 `lexer-tree-builder.ts`.

2. **AstTreeBuilder (`parser.ts`)**  
   클래스 이름은 `AstTreeBuilder`, 파일은 `parser.ts`. `parse(lexerNode)`가 `AstRootNode`를 만들고 (`:77-79`) Function/Lambda/Operator/Prefix/Reference/Suffix/Union/Value 팩토리로 트리를 조립한다.

3. **FormulaDependencyGenerator**  
   dirty 범위에서 의존 트리를 만든다 (`engine/dependency/formula-dependency.ts`). R-tree로 범위 조회.

4. **Interpreter**  
   `execute` / `executeAsync` (`engine/interpreter/interpreter.ts:49-80`). AST를 돌리고 `BaseValueObject`(숫자/문자/불리언/에러/배열/람다)를 낸다. async 노드(일부 함수)만 await.

5. **CalculateFormulaService.execute**  
   설정을 로드하고 사이클 한도만큼 `_executeStep()` (`services/calculate-formula.service.ts:145-176`). 각 스텝은 의존 트리 생성 → 트리 pop → AST 생성 → interpret. 배열 수식이 새 dirty를 만들면 한 번 더 `_apply(true)`.

값 객체: `engine/value-object/`. 참조 객체: `engine/reference-object/` (cell/range/row/column/table/multi-area).

### 3.2 함수 개수

`ALL_IMPLEMENTED_FUNCTIONS`는 카테고리 `function-map.ts`를 이어 붙인다 (`packages/engine-formula/src/functions/index.ts:37-54`). `FormulaController._registerFunctions()`가 전부 `FunctionService.registerExecutors`에 넣는다 (`controllers/formula.controller.ts:135-146`). 플러그인 config `function`으로 커스텀을 추가할 수 있다.

`function-map.ts` 배열 엔트리(이름 기준, 주석 처리된 줄 제외):

| 카테고리 | 엔트리 | 비고 |
| --- | ---: | --- |
| array | 2 | `ARRAY_CONSTRAIN`, `FLATTEN` |
| compatibility | 38 | Excel 구이름. 통계 구현을 재사용 |
| cube | 0 | 구현 파일은 있으나 map이 전부 주석 |
| database | 12 | `DAVERAGE`…`DVARP` |
| date | 27 | |
| engineering | 57 | |
| financial | 54 | `AMORDEGRC`는 map에서 주석, `NotImplementedFunction` |
| information | 23 | `INFO`/`ISOMITTED` 주석 |
| logical | 21 | `LAMBDA`/`LET`/`MAP`/`BYROW` 포함 |
| lookup | 36 | `GETPIVOTDATA`/`RTD` 주석. `XLOOKUP`/`FILTER` 포함 |
| math | 81 | `ISO.CEILING` 주석 |
| meta | 6 | `+ - * /` 비교, cube 연산자 |
| statistical | 109 | `FORECAST.ETS*` 주석. `FORECAST`/`FORECAST.LINEAR` 등 별칭 중복 |
| text | 48 | `CALL`/`PHONETIC` 등은 미구현 클래스만 |
| univer | 0 | 빈 배열 |
| web | 2 | `ENCODEURL`, `FILTERXML`. `WEBSERVICE` 주석 |

**합계 516 map 엔트리 / 구현 디렉터리 502.** 재집계는 [10-cross-check.md](./10-cross-check.md) §1.1. 호환 별칭과 같은 클래스의 이중 등록(`FORECAST`+`FORECAST.LINEAR`, `REGEXMATCH`+`REGEXTEST`)을 포함하므로 “서로 다른 Excel 함수 516개”는 아니다. 미구현은 `NotImplementedFunction`이 `#N/A`를 반환한다 (`functions/not-implemented-function.ts:25-28`). `NEW_EXCEL_FUNCTIONS`는 동적 배열·새 삼각함수 등 이름 집합이다 (`functions/new-excel-functions.ts:29`).

### 3.3 계산 스케줄

트리거 경로:

1. 시트 변경 뮤테이션 (`SetRangeValuesMutation` 등) → `ActiveDirtyController`가 `IActiveDirtyManagerService`에 dirty 범위를 등록 (`sheets-formula/src/controllers/active-dirty.controller.ts:61-79`).
2. `TriggerCalculationController`가 `SetFormulaCalculationStartMutation`을 보낸다. 초기 모드는 `CalculationMode` (`FORCED` / `WHEN_EMPTY` 기본 / `NO_CALCULATION`, `sheets-formula/src/config/config.ts:27-52`). 브라우저에서는 `onRendered` 이후, Node는 `onReady`에서 컨트롤러를 touch (`sheets-formula/src/plugin.ts:164-183`).
3. 엔진 `FormulaCalculationTriggerController`는 Node면 즉시, 브라우저면 `LifecycleStages.Rendered` 이후 `FormulaCalculationTriggerService.start()` (`engine-formula/src/controllers/formula-calculation-trigger.controller.ts:21-38`).
4. `CalculateController`가 start 뮤테이션을 받아 `CalculateFormulaService.execute` (`engine-formula/src/controllers/calculate.controller.ts:73-80`).
5. 실행 루프는 `intervalCount`(기본 500, `DEFAULT_INTERVAL_COUNT`)마다 `requestImmediateMacroTask`로 양보해 중지 명령을 받는다 (`calculate-formula.service.ts:65, 294-355`, config `intervalCount` 주석 `config/config.ts:35-38`).
6. 완료 시 `SetFormulaCalculationResultMutation` → 시트의 `CalculateResultApplyController`가 셀 `v`를 갱신. `SheetFormulaCalculationResultApplyController`가 세션에 적용 완료를 표시 (`sheets-formula/src/controllers/sheet-formula-calculation-result-apply.controller.ts:21-34`).

진행률은 `SetFormulaCalculationNotificationMutation`과 `TriggerCalculationController.progress$` (`trigger-calculation.controller.ts:71-73`). 1초가 넘으면 프로그레스 바.

순환 참조는 `maxIteration` / `ENGINE_FORMULA_CYCLE_REFERENCE_COUNT` (기본 1, `config.ts:23`).

### 3.4 워커

엔진 자체는 Worker를 만들지 않는다. `@univerjs/rpc`의 `UniverRPCMainThreadPlugin` / `UniverRPCWorkerThreadPlugin`이 메시지 채널이다.

프리셋 (`presets/packages/preset-sheets-core/src/preset.ts:107-161`):

- `workerSrc`가 있으면 메인: `UniverFormulaEnginePlugin`/`UniverSheetsPlugin`/`UniverSheetsFormulaPlugin` 모두 `notExecuteFormula: true`.
- 워커 인스턴스가 실제 Lexer/Interpreter/`CalculateFormulaService`를 띄운다.
- 뮤테이션 핸들러는 빈 `handler: () => true`인 경우가 많다. 주석: “worker와 main thread 통신 전용” (`register-function.mutation.ts:22-25`). `DataSyncPrimaryController.registerSyncingMutations`로 동기화 (`formula.controller.ts:129-131`).
- 커스텀 함수는 `UniverRemoteSheetsFormulaPlugin`이 `RemoteRegisterFunctionService` 채널로 워커에 등록 (`sheets-formula/src/plugin.ts:62-91, 137-142`).
- 필터 행 숨김은 워커에 없으므로 start 뮤테이션마다 메인이 `rowData`를 실어 보낸다 (`trigger-calculation.controller.ts:154-166`).

### 3.5 engine-formula ↔ sheets-formula

| | engine-formula | sheets-formula |
| --- | --- | --- |
| 역할 | 문서 타입 비의존 계산기 | 시트 단위 연결 |
| 데이터 | `FormulaDataModel`이 워크북 셀의 `f`/`si`를 수집 | dirty 변환, 배열 수식 interceptor, defined name/sheet rename 시 수식 rewrite |
| 실행 | `CalculateFormulaService` | `TriggerCalculationController`가 start 뮤테이션 |
| 결과 | result 뮤테이션 | `CalculateResultApplyController`(sheets)가 셀에 기록 |
| UI | 없음 | `sheets-formula-ui` |
| Facade | `FFormula` 본체 (`getFormula()`, lexer, 의존 트리 조회, start/stop) | 시트 mixin: `registerFunction`, `setInitialFormulaComputing` |

`FormulaDataModel` (`models/formula-data.model.ts:46`)은 수식 id 맵, 배열 수식 범위/셀, IMAGE 수식 데이터를 들고 LexerTreeBuilder로 참조를 고친다.

---

## 4. OSS vs Pro (README 그대로)

README 「What You Can Build」와 「Open Source and Pro」 (`README.md:288-314`). 이 저장소에 Pro 패키지는 없다.

**Sheets OSS:** 워크북/시트/범위, 선택, 수식, 숫자 서식, 필터/정렬, 데이터 유효성, 조건부 서식, 하이퍼링크, 댓글, 찾기/바꾸기, 노트, 테이블, 드로잉, 확장 UI 플러그인.

**Sheets Pro (README가 나열, 소스 없음):** 실시간 협업, 편집 이력, import/export, 인쇄, **차트**, **피벗 테이블**, 스파크라인, outline, shapes, in-cell graphics, data connectors, 서버 사이드 계산, 성능 강화 수식, range preprocessing.

**Runtime OSS:** 브라우저, Node headless, Web Worker/RPC, 멀티 인스턴스.

**Runtime Pro:** collaboration server/client, SSR, computing delegation, server-side calculation, changeset replay.

경계 (`README.md:316-321`): OSS는 Apache-2.0로 단독 사용 가능. Pro API를 OSS 패키지에 있는 것처럼 쓰면 안 된다. `GETPIVOTDATA`가 lookup에 스텁으로 있는 것은 피벗 제품이 아니라 `#N/A` 자리표시다.

---

## 5. 에이전트/임베드 시 함의

- 셀 쓰기는 Facade `FRange` 또는 `sheet.command.set-range-values`. core `Range`를 직접 만지면 undo/인터셉터/수식 dirty가 빠질 수 있다.
- 수식 계산은 비동기. `univerAPI.getFormula()` 후 완료 이벤트/`onCalculationResultApplied`를 기다린다 (`engine-formula/src/facade/f-univer.ts:23-31`).
- Headless Node는 UI 없이 `UniverFormulaEnginePlugin` + `UniverSheetsPlugin` + `UniverSheetsFormulaPlugin`. 프리셋 `preset-sheets-node-core`.
- 큰 워크북은 `workerSrc`로 계산을 워커에 넘긴다. 메인 `notExecuteFormula: true`.
- 차트/피벗/xlsx I/O/협업은 OSS 시트 커널 밖이다.
