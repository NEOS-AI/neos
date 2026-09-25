# Univer Facade API — 에이전트가 실제로 호출하는 표면

조사 범위는 클론 `/Users/yeonwoosung/Desktop/univer` (버전 `1.0.2`)뿐이다. Univer 원본은 수정하지 않았다. 모든 주장은 `path` 또는 `path:line`을 가리킨다.

README는 Facade를 “브라우저와 Node에서 같은 구조화 API”로 부른다 (`README.md:21`). 이 레포에는 에이전트 루프·MCP·스킬이 없다. 에이전트가 문서를 읽고 바꾸는 실제 표면은 **`FUniver`와 그 mixin**이다. 자세한 하네스 경계는 [07-ai-agent-surface.md](./07-ai-agent-surface.md).

---

## 1. 한 줄 결론

에이전트가 잡는 핸들은 `FUniver.newAPI(univer)`가 돌려주는 `univerAPI`다 (`packages/core/src/facade/f-univer.ts:86-89`). 코어 클래스는 커맨드·라이프사이클·테마·리치텍스트 빌더만 안다. `createWorkbook` / `createDocument` / `getFormula` 같은 도메인 메서드는 **플러그인 facade의 side-effect import**가 `FUniver.extend(...)`로 프로토타입에 붙인다. Slides 패키지에는 facade 디렉터리·`./facade` export가 없다.

---

## 2. 에이전트가 Facade를 얻는 경로

생성자는 `@hideconstructor`다. 직접 `new FUniver()` 하지 않는다.

| 경로 | 코드 | 근거 |
| --- | --- | --- |
| 정적 팩토리 | `FUniver.newAPI(univer \| injector)` | `packages/core/src/facade/f-univer.ts:86-89`. `Univer`면 `__getInjector()`, 아니면 injector를 그대로 쓴다. |
| Preset | `createUniver({ presets })` → `{ univer, univerAPI }` | `presets/src/preset.ts:48-103`. 플러그인 등록 뒤 `FUniver.newAPI(univer)` (`presets/src/preset.ts:98-99`). `export * from '@univerjs/core/facade'` (`presets/src/preset.ts:21`). |
| 패키지 export | `@univerjs/core/facade` | `packages/core/package.json:30`. `@univerjs/core` 본체(`packages/core/src/index.ts`)는 facade를 re-export하지 않는다. |

헤드리스 에이전트는 Node 프리셋이 이미 facade를 끌어온다.

```32:40:/Users/yeonwoosung/Desktop/univer/presets/packages/preset-sheets-node-core/src/preset.ts
import '@univerjs/sheets/facade';
import '@univerjs/sheets-formula/facade';
import '@univerjs/sheets-data-validation/facade';
import '@univerjs/engine-formula/facade';
import '@univerjs/sheets-filter/facade';
import '@univerjs/sheets-hyper-link/facade';
import '@univerjs/sheets-numfmt/facade';
import '@univerjs/sheets-sort/facade';
import '@univerjs/sheets-thread-comment/facade';
```

브라우저 Sheets 프리셋은 UI facade까지 붙인다 (`presets/packages/preset-sheets-core/src/preset.ts:38-46`).

Plugin Mode에서는 호출부가 직접 `import '@univerjs/sheets/facade'`를 넣어야 한다. 빼면 `univerAPI.createWorkbook`은 런타임에 `undefined`다.

전형적인 호출 사슬:

```
FUniver.newAPI(univer)
  → univerAPI.createWorkbook(data)          // sheets mixin
  → FWorkbook.getActiveSheet()
  → FWorksheet.getRange('A1')
  → FRange.setValue / getValue / setFormula
  → FWorkbook.save()                        // IWorkbookData 스냅샷
```

문서:

```
univerAPI.createDocument(data)              // docs mixin
  → FDocument.insertText / getParagraphs / save
```

수식:

```
univerAPI.getFormula()                      // engine-formula mixin
  → FFormula.onCalculationResultApplied()
```

저수준 탈출구는 항상 `univerAPI.executeCommand(id, params)` (`packages/core/src/facade/f-univer.ts:547-553`). Facade 메서드 대부분은 내부에서 `ICommandService.syncExecuteCommand`를 부른다.

---

## 3. Mixin 등록 — `import '@univerjs/sheets/facade'`가 하는 일

### 3.1 패키지 엔트리

각 플러그인은 `package.json`에 `"./facade": "./src/facade/index.ts"`를 연다. facade `index.ts`는 **값 export보다 먼저** mixin 파일을 side-effect import한다.

| 패키지 | facade index가 하는 import | 근거 |
| --- | --- | --- |
| `@univerjs/sheets` | `import './f-univer'`, `import './f-enum'` | `packages/sheets/src/facade/index.ts:17-18` |
| `@univerjs/docs` | `import './f-univer'`, `import './f-enum'` | `packages/docs/src/facade/index.ts:17-18` |
| `@univerjs/engine-formula` | `import './f-univer'` | `packages/engine-formula/src/facade/index.ts:17` |
| `@univerjs/sheets-formula` | `import './f-formula'`, `./f-enum`, `./f-workbook`, `./f-range` | `packages/sheets-formula/src/facade/index.ts:17-20` |
| `@univerjs/ui` | `import './f-univer'`, `./f-menu-builder`, `./f-enum` | `packages/ui/src/facade/index.ts:17-19` |

플러그인 본체 `src/index.ts`는 facade를 import하지 않는다. 플러그인을 등록해도 facade mixin은 **붙지 않는다.** 반드시 `@univerjs/<pkg>/facade`를 import해야 한다.

### 3.2 `extend`가 프로토타입에 복사한다

세 계층이 같은 패턴이다.

| 클래스 | `extend` | `_initialize` 수집 |
| --- | --- | --- |
| `FUniver` | `packages/core/src/facade/f-univer.ts:101-121` | `_initialize`를 `InitializerSymbol` 배열에 push. 생성자 끝에서 호출 (`f-univer.ts:163-168`). |
| `FBase` | `packages/core/src/facade/f-base.ts:30-44` | 없음. 인스턴스·정적 멤버만 복사. |
| `FBaseInitialable` | `packages/core/src/facade/f-base.ts:107-134` | `_initialize`를 배열에 모아 생성자에서 실행. `FWorkbook` / `FWorksheet` / `FRange` / `FDocument`의 베이스. |

Sheets mixin의 실제 등록:

```744:747:/Users/yeonwoosung/Desktop/univer/packages/sheets/src/facade/f-univer.ts
FUniver.extend(FUniverSheetsMixin);
declare module '@univerjs/core/facade' {
    interface FUniver extends IFUniverSheetsMixin { }
}
```

`FUniver.extend`는 런타임에 메서드를 붙인다. `declare module '@univerjs/core/facade'`는 타입만 연다. 둘 다 빠지면 런타임 또는 타입이 깨진다.

같은 패턴이 `FWorkbook.extend`, `FWorksheet.extend`, `FRange.extend`, `FDocument.extend`, `FFormula.extend`, `FEventName.extend`, `FEnum.extend`, `FUtil.extend`에도 있다.

이벤트 이름도 mixin이다. 코어 `FEventName`은 `CommandExecuted` 등만 안다 (`packages/core/src/facade/f-event.ts:279-280`). Sheets는 `FEventName.extend(FSheetsEventNameMixin)` (`packages/sheets/src/facade/f-event.ts:749`)로 `SheetValueChanged`, `WorkbookCreated` 등을 붙인다.

### 3.3 생성 시점

`FUniver` 생성자는 코어 이벤트(`LifeCycleChanged`, undo/redo, `CommandExecuted`, `DocCreated`)를 먼저 걸고, 그다음 mixin `_initialize`를 돈다 (`packages/core/src/facade/f-univer.ts:136-168`). mixin이 `registerEventHandler`로 시트/필터 이벤트를 다는 이유다. **`newAPI` 호출 전에 facade import가 끝나 있어야 한다.** import가 늦으면 이벤트 핸들러가 비어 있다.

---

## 4. 클래스 계층

```
FUniver                          @univerjs/core/facade
  ├─ (mixin) createWorkbook      @univerjs/sheets/facade
  ├─ (mixin) createDocument      @univerjs/docs/facade
  ├─ (mixin) getFormula          @univerjs/engine-formula/facade
  └─ (mixin) copy/paste/UI       @univerjs/ui/facade

FWorkbook / FWorksheet / FRange / FSelection
                                 @univerjs/sheets/facade  (FBaseInitialable)
FDocument / FDocumentParagraph / FDocumentTextRange / FDocumentSection
                                 @univerjs/docs/facade
FFormula                         @univerjs/engine-formula/facade
  └─ (mixin) registerFunction    @univerjs/sheets-formula/facade
```

코어 `FDoc` (`packages/core/src/facade/f-doc.ts:25-32`)는 빈 스텁이다. `DocCreated` 이벤트 페이로드에만 쓰인다. 에이전트가 문서를 다루는 클래스는 `FDocument`다.

---

## 5. `FUniver` — 코어 (`packages/core/src/facade`)

파일: `packages/core/src/facade/f-univer.ts`. 클래스는 `Disposable`.

### 5.1 인스턴스·커맨드

| 메서드 | 줄 | 역할 |
| --- | --- | --- |
| `static newAPI(wrapped)` | 86-89 | Facade 인스턴스 생성 |
| `static extend(source)` | 101-121 | mixin 등록 |
| `disposeUnit(unitId)` | 328-330 | 유닛 언로드 |
| `getCurrentLifecycleStage()` | 342-345 | `LifecycleStages` |
| `undo()` / `redo()` | 356-371 | 포커스된 유닛에 undo/redo 커맨드 |
| `executeCommand(id, params?, options?)` | 547-553 | 비동기 커맨드. 에이전트 저수준 탈출구 |
| `syncExecuteCommand(id, params?, options?)` | 570-576 | 동기 커맨드 |

`executeCommand` 예시 주석이 시트 값 쓰기다 (`f-univer.ts:541-544`): `sheet.command.set-range-values`. Facade `setValue`가 같은 커맨드를 감싼다.

### 5.2 이벤트

| 메서드 | 줄 | 역할 |
| --- | --- | --- |
| `addEvent(event, callback)` | 615-618 | 리스너. `IDisposable` 반환 |
| `fireEvent(event, params)` | 630-632 | 내부 발화. `params.cancel`로 before 이벤트를 막을 수 있다 |
| `registerEventHandler(event, handler)` | 132-134 | 구독이 있을 때만 하위 구독을 연다 |

코어 이벤트 이름 (`packages/core/src/facade/f-event.ts`):

| getter | 줄 | 의미 |
| --- | --- | --- |
| `Event.DocCreated` | 154 | 문서 유닛 생성. 페이로드 `doc`은 스텁 `FDoc` |
| `Event.DocDisposed` | 171 | 문서 언로드 + 스냅샷 |
| `Event.LifeCycleChanged` | 188 | 라이프사이클 |
| `Event.Undo` / `Redo` | 205, 222 | undo/redo 실행 후 |
| `Event.BeforeUndo` / `BeforeRedo` | 242, 262 | 실행 전. `event.cancel = true`면 `CanceledError` |
| `Event.CommandExecuted` | 279 | undo/redo 제외 모든 커맨드 후 |
| `Event.BeforeCommandExecute` | 299 | 실행 전 취소 가능 |

`CommandExecuted`는 `ICommandService.onCommandExecuted`에 연결된다 (`f-univer.ts:202-214`). 워크북 한정 구독은 `FWorkbook.onCommandExecuted` (`packages/sheets/src/facade/f-workbook.ts:518-526`)가 `unitId`로 필터한다.

### 5.3 테마·로케일·유틸

| 메서드 | 줄 |
| --- | --- |
| `setTheme` / `getCurrentTheme` / `isDarkMode` / `toggleDarkMode` | 389-432 |
| `loadLocales` / `setLocale` / `getCurrentLocale` / `getLocales` | 446-530 |
| `setRegion` / `getCurrentRegion` | 472-489 |
| `setDirection('ltr' \| 'rtl')` | 499-502 |
| `get Enum` / `get Event` / `get Util` | 581-597 |
| `getUserManager()` | 642-644 → `FUserManager.getCurrentUser` (`f-usermanager.ts:40`) |
| `newBlob()` | 654-656 |
| `newRichText()` / `newRichTextFromDocumentData` / `newRichTextValue` | 669-699 |
| `newParagraphStyle` / `newParagraphStyleValue` | 711-726 |
| `newTextStyle` / `newTextStyleValue` / `newTextDecoration` | 737-765 |

`newRichTextFromDocumentData`와 `newRichTextValue`는 JSDoc이 “agent code should prefer `newRichText()`”라고 적는다 (`f-univer.ts:676-677`, `690-691`).

`FEnum` (`packages/core/src/facade/f-enum.ts`)은 `UniverInstanceType`, `WrapStrategy`, `DocumentFlavor` 등 코어 enum의 레지스트리다. `FUtil` (`packages/core/src/facade/f-util.ts`)은 `Rectangle`·`numfmt` 헬퍼다. 둘 다 `extend`로 플러그인이 키를 보탠다.

---

## 6. Sheets Facade — `FWorkbook` / `FWorksheet` / `FRange` / `FSelection`

패키지: `packages/sheets/src/facade`. export는 `packages/sheets/src/facade/index.ts:22-26`.

### 6.1 `FUniver`에 붙는 시트 mixin

파일: `packages/sheets/src/facade/f-univer.ts`. 클래스 `FUniverSheetsMixin`, 등록 `FUniver.extend` (744).

| 메서드 | 줄 | 반환 |
| --- | --- | --- |
| `createWorkbook(data, options?)` | 161-165 | `FWorkbook`. `IUniverInstanceService.createUnit(UNIVER_SHEET, ...)` |
| `getActiveWorkbook()` | 167-174 | `FWorkbook \| null` |
| `getWorkbook(id)` | 176-183 | `FWorkbook \| null` |
| `getSheetCommandTarget(params?)` | 185-204 | 커맨드 params에서 워크북/시트 해석 |
| `getActiveSheet()` | 206-218 | `{ workbook, worksheet } \| null` |
| `setFreezeSync(enabled)` | 220-223 | 협업 freeze 동기화 |

`options.makeCurrent: false`면 생성만 하고 포커스하지 않는다 (JSDoc `f-univer.ts:87-91`).

시트 mixin `_initialize`가 등록하는 이벤트: `BeforeSheetCreate`, `SheetCreated`, `BeforeActiveSheetChange`, `ActiveSheetChanged`, `BeforeSheetDelete`, `SheetDeleted`, `SheetMoved`, `SheetNameChanged`, `SheetTabColorChanged`, `SheetHideChanged`, `GridlineChanged`, `SheetValueChanged`, `WorkbookCreated`, `WorkbookDisposed` (`f-univer.ts:228-741`, 이름 정의 `f-event.ts:30-345`).

### 6.2 `FWorkbook`

파일: `packages/sheets/src/facade/f-workbook.ts`. `FBaseInitialable`. `id`는 unit id (79, 94).

**스냅샷·식별**

| 메서드 | 줄 | 역할 |
| --- | --- | --- |
| `getWorkbook()` | 108-110 | 내부 `Workbook` 모델 |
| `getId()` | 130-132 | unit id |
| `getName()` / `setName(name)` | 145-167 | 이름. `SetWorkbookNameCommand` |
| `save()` | 180-183 | **스냅샷.** `IResourceLoaderService.saveUnit<IWorkbookData>`. 조건부서식·검증 등 플러그인 리소스 포함 |
| `getUrl()` | 749 | 워크북 URL |
| `setCustomMetadata` / `getCustomMetadata` | 1060-1077 | 커스텀 메타 |

`save()`가 에이전트가 결과를 직렬화하는 공식 API다. 별도 `snapshot()` 메서드는 없다. dispose 이벤트 페이로드의 `snapshot` 필드만 같은 `IWorkbookData`를 담는다 (`f-event.ts:384`).

**시트 탐색·생성**

| 메서드 | 줄 | 역할 |
| --- | --- | --- |
| `getActiveSheet()` | 197-200 | 활성 `FWorksheet` |
| `getSheets()` | 213-217 | 전 시트 |
| `getNumSheets()` | 734 | 개수 |
| `getSheetBySheetId(id)` | 295-297 | id로 |
| `getSheetByName(name)` | 316-318 | 이름으로 |
| `create(name, rows, columns, options?)` | 255-281 | 시트 생성 후 활성화 |
| `insertSheet(sheetName?, options?)` | 385 | 생성. 이름은 선택 |
| `setActiveSheet(sheet \| name)` | 337 | 활성 시트 |
| `deleteSheet(sheet \| name)` | 430 | 삭제 |
| `deleteActiveSheet()` | 681 | 활성 시트 삭제 |
| `duplicateSheet` / `duplicateActiveSheet` | 700, 719 | 복제 |
| `moveSheet` / `moveActiveSheet` | 767, 793 | 순서 |

**선택·편집·권한**

| 메서드 | 줄 | 역할 |
| --- | --- | --- |
| `undo()` / `redo()` | 450-469 | 이 워크북에 포커스 후 undo/redo |
| `onBeforeCommandExecute(cb)` | 490-498 | 이 unitId 커맨드만 |
| `onCommandExecuted(cb)` | 518-526 | 이 unitId 커맨드만. 에이전트 관찰용 |
| `onSelectionChange(cb)` | 546 | 선택 변경 |
| `setActiveRange(range)` | 598 | 활성 범위 |
| `getActiveRange()` | 636 | 활성 `FRange \| null` |
| `getActiveCell()` | 656 | 활성 셀 |
| `setEditable(value)` | 574 | 워크북 편집 권한 |
| `getWorkbookPermission()` | 823 | `FWorkbookPermission` |

**정의된 이름·테마**

| 메서드 | 줄 |
| --- | --- |
| `getDefinedName` / `getDefinedNames` | 839, 859 |
| `newDefinedNameBuilder` / `insertDefinedName` / `deleteDefinedName` | 884, 943, 964 |
| `insertDefinedNameBuilder` / `updateDefinedNameBuilder` | 903, 927 |
| `registerRangeTheme` / `unregisterRangeTheme` / `createRangeThemeStyle` | 1005, 1021, 1046 |
| `addStyles` / `removeStyles` | 1116, 1159 |

`FDefinedName` / `FDefinedNameBuilder`: `packages/sheets/src/facade/f-defined-name.ts` (`setName` 366, `setFormula` 381, `setRef` 396, `delete` 523).

### 6.3 `FWorksheet`

파일: `packages/sheets/src/facade/f-worksheet.ts`. `FBaseInitialable`.

**식별·범위**

| 메서드 | 줄 | 역할 |
| --- | --- | --- |
| `getSheet()` / `getWorkbook()` | 173, 203 | 내부 모델 |
| `getSheetId()` / `getSheetName()` | 218, 233 | id / 이름 |
| `getIndex()` | 2358 | 탭 순서 |
| `setName(name)` | 2319 | `SetWorksheetNameCommand` |
| `activate()` | 2340 | 이 시트를 활성 |
| `equalTo(other)` | 2543 | 동일 시트 |
| `getRange(...)` | 427-480 | 오버로드. `(row, col)`, `(row, col, numRows, numCols)`, A1 문자열, `IRange` |
| `getSelection()` | 248-255 | `FSelection \| null` |
| `getActiveRange()` / `setActiveRange` | 1792, 1807 | 활성 범위 |
| `getActiveCell()` | 1828 | 활성 셀 |
| `getDataRange()` | 2489 | 사용 영역 |
| `getMaxRows()` / `getMaxColumns()` | 553, 538 | 격자 크기 |
| `getLastRow()` / `getLastColumn()` | 2526, 2508 | 마지막 사용 행/열 |
| `setRowCount` / `setColumnCount` | 2758, 2781 | 격자 리사이즈 |
| `appendRow(rowContents)` | 2719 | 맨 아래 행 추가 |

A1 표기는 `deserializeRangeWithSheet`로 파싱한다 (`f-worksheet.ts:488-489`). `'Sheet1!A1:C3'`도 받는다.

**행·열**

| 메서드 | 줄 |
| --- | --- |
| `insertRowAfter` / `insertRowBefore` / `insertRows` / `insertRowsAfter` / `insertRowsBefore` | 571-675 |
| `deleteRow` / `deleteRows` / `deleteRowsByPoints` / `moveRows` | 719-792 |
| `hideRow` / `hideRows` / `unhideRow` / `showRows` | 831-924 |
| `setRowHeight` / `setRowHeights` / `setRowHeightsForced` / `getRowHeight` / `autoFitRow` / `setRowAutoHeight` | 959-1092 |
| `insertColumnAfter` / `insertColumns` / `deleteColumns` / `moveColumns` | 1228-1444 |
| `hideColumn` / `showColumns` / `setColumnWidth` / `getColumnWidth` | 1483-1671 |

**표시·고정·병합·클리어**

| 메서드 | 줄 |
| --- | --- |
| `hideSheet` / `showSheet` / `isSheetHidden` / `setHiddenState` | 2227-2281 |
| `setTabColor` / `getTabColor` | 2190, 2211 |
| `setHiddenGridlines` / `hasHiddenGridLines` / `setGridLinesColor` | 2131, 2115, 2152 |
| `setFreeze` / `cancelFreeze` / `getFreeze` | 1863-1904 |
| `setFrozenRows` / `setFrozenColumns` / `getFrozenRows` / `getFrozenColumns` | 1978-2054 |
| `getMergeData` / `getMergedRanges` / `getCellMergeData` | 1729-1768 |
| `clear` / `clearContents` / `clearFormats` | 2380-2453 |
| `getWorksheetPermission()` | 2820 |

스타일: `getDefaultStyle` / `setDefaultStyle` / `setRowDefaultStyle` / `setColumnDefaultStyle` (272-393). 정의된 이름: `insertDefinedName` 2562, `getDefinedNames` 2584.

### 6.4 `FRange`

파일: `packages/sheets/src/facade/f-range.ts`. 에이전트가 셀을 읽고 쓰는 중심 API. 생성자가 격자 밖으로 나가면 throw (`f-range.ts:146-150`).

**위치**

| 메서드 | 줄 |
| --- | --- |
| `getUnitId` / `getSheetId` / `getSheetName` | 177, 209, 193 |
| `getRange()` | 227 | 내부 `IRange` |
| `getRow` / `getLastRow` / `getColumn` / `getLastColumn` | 243-291 |
| `getWidth` / `getHeight` | 307, 323 |
| `getA1Notation(withSheet?, ...)` | 2129 |
| `offset(rowOffset, columnOffset, ...)` | 2805-2846 |
| `isMerged` / `isPartOfMerge` / `isBlank` | 342, 2036, 2764 |
| `forEach(callback)` | 2085 |
| `getDataRegion(dimension?)` | 2671 |

**값 — 에이전트 핵심**

| 메서드 | 줄 | 역할 |
| --- | --- | --- |
| `getValue()` | 489-517 | 좌상단 셀 `v`. `true`면 리치텍스트 |
| `getValues()` | 583-599 | 2D 배열 |
| `getRawValue` / `getRawValues` | 540, 662 | 서식 전 원본 |
| `getDisplayValue` / `getDisplayValues` | 565, 725 | 표시 문자열 |
| `getCellData` / `getCellDatas` / `getCellDataGrid` | 756-788 | `ICellData` |
| `setValue(value)` | 1351-1366 | 범위 전체에 스칼라/`ICellData`. `SetRangeValuesCommand` |
| `setValueForCell(value)` | 1385-1405 | 좌상단만 |
| `setValues(matrix)` | 1631-1648 | 2D 또는 sparse 매트릭스 |
| `setRichTextValueForCell` / `setRichTextValues` | 1428, 1469 | 리치텍스트 |
| `clear` / `clearContent` / `clearFormat` | 2435-2489 | 내용/서식 |

`setValue`는 `'=SUM(A1:A2)'`, `'25%'`, `{ v, f, p, s }`를 받는다 (`f-range.ts:1333-1348`). 무효 값은 throw (`1354-1356`).

**수식**

| 메서드 | 줄 |
| --- | --- |
| `getFormula()` | 892-899 | `FormulaDataModel.getFormulaStringByCell` |
| `getFormulas()` | 913 | 2D |
| `setFormula(formula)` | 2880-2884 | `{ f: formula }`로 `setValue` |
| `setFormulas(formulas)` | 2903-2905 | 2D |

**스타일·정렬·병합**

| 메서드 | 줄 |
| --- | --- |
| `getCellStyle` / `getCellStyles` / `getCellStyleData` | 437, 460, 367 |
| `setFontWeight` / `setFontStyle` / `setFontLine` / `setFontFamily` / `setFontSize` / `setFontColor` | 1663-1885 |
| `setBackground` / `setBackgroundColor` / `getBackground` | 1271, 1243, 1208 |
| `setBorder` | 1180 |
| `setWrap` / `setWrapStrategy` / `setShrinkToFit` | 1499, 1544, 1519 |
| `setHorizontalAlignment` / `setVerticalAlignment` / `setTextRotation` | 1593, 1568, 1289 |
| `merge` / `mergeAcross` / `mergeVertically` / `breakApart` | 1933-2057 |
| `useThemeStyle` / `removeThemeStyle` / `getUsedThemeStyle` | 2355-2406 |
| `insertCells` / `deleteCells` | 2554, 2622 |
| `autoFill(targetRange, applyType?)` | 2987 | `Promise<boolean>` |
| `splitTextToColumns(...)` | 2261-2332 |
| `activate()` / `activateAsCurrentCell()` | 2151, 2190 |
| `getRangePermission()` | 2936 |
| `setCustomMetaData` / `getCustomMetaData` | 1078, 1139 |

### 6.5 `FSelection`

파일: `packages/sheets/src/facade/f-selection.ts`. `FWorksheet.getSelection()`이 만든다.

| 메서드 | 줄 | 역할 |
| --- | --- | --- |
| `getActiveRange()` | 64-71 | primary가 있는 선택 → `FRange` |
| `getActiveRangeList()` | 88-92 | 모든 선택 범위 |
| `getCurrentCell()` | 111-118 | primary 셀 (`ISelectionCell`) |
| `getActiveSheet()` | 133-136 | 이 선택의 시트 |
| `updatePrimaryCell(cell)` | 160 | immutable. 새 `FSelection` 반환 |
| `getNextDataRange(direction)` | 226 | 인접 데이터 영역 |

---

## 7. Docs Facade — `FDocument`

패키지: `packages/docs/src/facade`.

### 7.1 `FUniver` docs mixin

파일: `packages/docs/src/facade/f-univer.ts`. 등록 93행.

| 메서드 | 줄 | 역할 |
| --- | --- | --- |
| `createDocument(data, options?)` | 64-72 | `createUnit(UNIVER_DOC, ...)` → `FDocument` |
| `getActiveDocument()` | 74-81 | `FDocument \| null` |
| `getDocument(id)` | 83-90 | id로 |

### 7.2 `FDocument`

파일: `packages/docs/src/facade/f-document.ts`. `FBaseInitialable`. `id`는 unit id (90, 102).

| 메서드 | 줄 | 역할 |
| --- | --- | --- |
| `getDocumentDataModel(segmentId?)` | 118-124 | 본문 또는 헤더/푸터 모델 |
| `getBody(segmentId?)` | 166-172 | `IDocumentBody` |
| `getCustomBlockLayout()` | 140-149 | 커스텀 블록. 헤드리스에서 측정/렌더 없이 동작 (128-130) |
| `getId()` / `getName()` / `setName` | 188, 243, 258 | 식별 |
| `getDocumentFlavor()` / `isTraditional()` / `isModern()` | 293, 312, 330 | Traditional vs Modern. 섹션 API는 Traditional만 |
| `save()` | 348-350 | **스냅샷** `IDocumentData`. 리소스 포함 |
| `undo()` / `redo()` | 362-379 | 이 문서에 포커스 후 |
| `insertText(index, text, segmentId?)` | 427-438 | 오프셋에 평문 삽입 |
| `deleteRange(range)` | 880-894 | 범위 삭제 |
| `insertParagraph(index, text?, segmentId?)` | 820 | 단락 삽입 |
| `appendParagraph(text?, segmentId?)` | 862-864 | 맨 뒤 단락 |
| `getParagraphs` / `getParagraph` / `findParagraphByText` / `findParagraphs` | 718, 739, 764, 786 | 단락 탐색 |
| `getTextRange(start, end, segmentId?)` | 501 | `FDocumentTextRange` |
| `getSections` / `getSection` / `getSectionAt` | 515, 534, 551 | Traditional 섹션 |
| `insertSectionBreak` / `insertColumnBreak` / `insertHorizontalRule` | 610, 645, 672 | Traditional 전용 |
| `ensurePageHeader` / `ensurePageFooter` | 393, 408 | 헤더/푸터 세그먼트 id |
| `getHeaderFooterOptions` / `setHeaderFooterOptions` | 448, 477 |  |
| `getPermission()` / `getEntityPermission(...)` | 202, 224 | 권한 |

### 7.3 단락·텍스트 범위·섹션

`FDocumentParagraph` (`packages/docs/src/facade/f-document-paragraph.ts`). `paragraphId`로 재해석하므로 앞쪽 삽입에도 핸들이 깨지지 않는다 (61-63).

| 메서드 | 줄 |
| --- | --- |
| `getId` / `getSegmentId` / `getInfo` | 89, 105, 143 |
| `getText` / `setText` / `appendText` | 295, 313, 339 |
| `getTextRange` / `findText` / `findAllText` | 195, 224, 256 |
| `setStyle` / `isListItem` / `isTask` / `setTaskChecked` | 394, 416, 431, 452 |
| `remove` | 498 |

`FDocumentTextRange` (`f-document-text-range.ts`). 생성 시점 오프셋은 고정. 앞쪽 편집 뒤에는 새로 만든다 (47-48).

| 메서드 | 줄 |
| --- | --- |
| `getRange` / `getText` / `describe` | 73, 90, 152 |
| `getExplicitTextStyleRuns` / `getCommonExplicitTextStyle` | 104, 125 |
| `setTextStyle` / `setText` | 178, 210 |

`FDocumentSection` (`f-document-section.ts`): `setColumns` 229, `getPageSetup` 350, `ensureHeader`/`ensureFooter` 472/491, `remove` 620. Modern 문서에서 섹션 API를 치면 `DocsSectionUnsupportedDocumentFlavorError` (74-75).

### 7.4 docs-ui mixin

`packages/docs-ui/src/facade/f-document.ts`. `FDocument.extend(FDocumentUIMixin)` (103). `setSelection(startOffset, endOffset)` (40) — 렌더/스켈레톤이 필요하므로 헤드리스에서는 쓰지 않는다.

---

## 8. Formula Facade

두 패키지가 겹친다. 엔진이 `FFormula`와 `getFormula()`를 만들고, 시트 수식 플러그인이 커스텀 함수 등록을 얹는다.

### 8.1 `@univerjs/engine-formula/facade`

`FUniverEngineFormulaMixin.getFormula()` (`packages/engine-formula/src/facade/f-univer.ts:37-39`, extend 42).

`FFormula` (`packages/engine-formula/src/facade/f-formula.ts`)는 `FBase`.

| 메서드 | 줄 | 역할 |
| --- | --- | --- |
| `moveFormulaRefOffset(...)` | 111 | 수식 참조 오프셋 |
| `sequenceNodesBuilder(formula)` | 127 | 렉서 노드 |
| `executeCalculation()` | 145 | **강제** 재계산. `setFormula`는 이미 dirty를 남긴다 (134-137) |
| `stopCalculation()` | 158 | 중단 |
| `calculationStart` / `calculationEnd` / `calculationProcessing` | 175, 197, 251 | 콜백 |
| `calculationResultApplied(cb)` | 216 | 결과 적용 후 |
| `onCalculationResultApplied(timeout?)` | 234-236 | **에이전트 대기.** Promise. 계산이 셀에 반영될 때까지 |
| `setMaxIteration(n)` | 277 | 순환 참조 최대 반복 |
| `executeFormulas(formulas, timeout?)` | 350 | 배치 수식 실행 Promise |
| `getAllDependencyTrees` / `getCellDependencyTree` | 406, 472 | 의존성 트리 |
| `getRangeDependents` / `getInRangeFormulas` / `getRangeDependentsAndInRangeFormulas` | 535, 605, 805 | 범위 질의 |
| `setFormulaReturnDependencyTree(value)` | 688 | 의존성 트리 방출 |
| `getFormulaExpressTree(formula, unitId)` | 756 | 구문 트리. 계산 없음 |

### 8.2 `@univerjs/sheets-formula/facade`

`FFormula.extend(FFormulaSheetsMixin)` (`packages/sheets-formula/src/facade/f-formula.ts:376`).

| 메서드 | 줄 | 역할 |
| --- | --- | --- |
| `setInitialFormulaComputing(mode)` | 312 | 다음 시트 생성 때 초기 계산 모드 |
| `registerFunction(name, func, desc?)` | 333-352 | 동기 커스텀 함수. dispose하면 해제. 등록 후 debounce 재계산 |
| `registerAsyncFunction(name, func, desc?)` | 354-373 | 비동기 커스텀 함수 |

같은 패키지가 범위/워크북에 에러 조회를 붙인다.

| mixin | 메서드 | 줄 |
| --- | --- | --- |
| `FRangeEngineFormulaMixin` | `getFormulaError()` | `packages/sheets-formula/src/facade/f-range.ts:44-82` |
| `FWorkbookEngineFormulaMixin` | `getAllFormulaError()` | `packages/sheets-formula/src/facade/f-workbook.ts:39-75` |

에이전트 패턴: `range.setFormula('=SUM(A1:A10)')` → `await univerAPI.getFormula().onCalculationResultApplied()` → `range.getValue()` / `range.getFormulaError()`.

### 8.3 `@univerjs/sheets-formula-ui/facade`

브라우저 전용. `univerAPI.showRangeSelectorDialog(opts)` (`packages/sheets-formula-ui/src/facade/f-univer.ts:56-59`). 헤드리스 에이전트 표면이 아니다.

---

## 9. UI Facade

`@univerjs/ui/facade`와 `@univerjs/sheets-ui/facade`. Node 코어 프리셋은 이 import를 하지 않는다 (`preset-sheets-node-core` 목록에 `ui/facade` 없음).

### 9.1 `@univerjs/ui/facade` — `FUniverUIMixin`

파일: `packages/ui/src/facade/f-univer.ts`. 인터페이스 52행, extend 602.

| 메서드 | 인터페이스 줄 | 구현 줄 |
| --- | --- | --- |
| `getURL()` | 61 | 502 |
| `getShortcut()` | 96 | 506 → `FShortcut` |
| `copy()` / `paste()` | 128, 160 | 510, 514 |
| `createMenu` / `createSubmenu` / `updateMenuConfig` | 210, 246, 270 | 518-526 |
| `openSidebar` / `openDialog` / `showMessage` | 296, 329, 355 | 531, 536, 551 |
| `setRibbonType` / `setUIVisible` / `isUIVisible` | 366, 388, 401 | 557-569 |
| `registerUIPart` / `registerComponent` | 412, 457 | 574, 579 |
| `setCurrent(unitId)` | 474 | 584 | 포커스 유닛 |
| `addFonts(fonts)` | 495 | 594 |
| `getComponentManager()` | 340 | 547 |

`FShortcut` (`packages/ui/src/facade/f-shortcut.ts`): `enableShortcut` 49, `disableShortcut` 65, `triggerShortcut(e)` 설명 73행대.

### 9.2 `@univerjs/sheets-ui/facade`

`FUniverSheetsUIMixin` (`packages/sheets-ui/src/facade/f-univer.ts:71`). 렌더 확장·붙여넣기·권한 그림자.

| 메서드 | 줄 |
| --- | --- |
| `registerSheetRowHeaderExtension` / `ColumnHeader` / `Main` | 78-92 |
| `registerCellCustomRender` | 100 |
| `pasteIntoSheet(html?, text?, files?)` | 124 |
| `setProtectedRangeShadowStrategy` / `getProtectedRangeShadowStrategy` | 149, 160 |

`FWorkbook` UI mixin (`packages/sheets-ui/src/facade/f-workbook.ts`): `startEditing` 104, `endEditingAsync` 116, `disableSelection` 171, `customizeColumnHeader` 70.

`FWorksheet` UI mixin (`packages/sheets-ui/src/facade/f-worksheet.ts`): `zoom` 98, `scrollToCell` 169, `highlightRanges` 80, `getVisibleRange` 129, `refreshCanvas` 60.

`FRange` UI mixin (`packages/sheets-ui/src/facade/f-range.ts`): `highlight` 221, `generateHTML` 91, `attachPopup` 127, `getCellRect` 73.

시트 UI는 `FEventName.extend`로 `CellClicked`, `SheetEditEnded`, 클립보드 이벤트 등을 연다 (`packages/sheets-ui/src/facade/f-event.ts:938`). 브라우저 검증용이지 헤드리스 도구 스키마가 아니다.

---

## 10. Slides에는 Facade가 없다

참이다.

| 검사 | 결과 |
| --- | --- |
| `packages/slides/src/` 아래 `facade/` | 없음 |
| `packages/slides-ui/src/` 아래 `facade/` | 없음 |
| `packages/slides/package.json` `exports` | `"."`, `"./*"`만. `./facade` 없음 (`package.json:27-29`) |
| 패키지 안 `facade` 문자열 | 0건 |

슬라이드 예제는 `FUniver.newAPI(univer)`를 쓰지만 (`examples/src/slides/mount.ts:69`) `createWorkbook` 같은 슬라이드 헬퍼는 없다. 유닛은 `univer.createUnit(UniverInstanceType.UNIVER_SLIDE, fixture)` (`examples/src/slides/mount.ts:73`)로 만든다. 에이전트가 슬라이드를 다루려면 Facade가 아니라 코어 `createUnit` / 커맨드 / 렌더 서비스로 내려가야 한다.

---

## 11. 플러그인 mixin 인벤토리

`FUniver.extend` / `FWorkbook.extend` / `FRange.extend` 등 등록 지점. 코어·시트·문서·수식·UI 외에 기능 플러그인이 같은 패턴으로 메서드를 보탠다.

| 패키지 | 대상 | 등록 파일 |
| --- | --- | --- |
| `@univerjs/sheets` | `FUniver` | `packages/sheets/src/facade/f-univer.ts:744` |
| `@univerjs/docs` | `FUniver` | `packages/docs/src/facade/f-univer.ts:93` |
| `@univerjs/engine-formula` | `FUniver` | `packages/engine-formula/src/facade/f-univer.ts:42` |
| `@univerjs/sheets-formula` | `FFormula`, `FRange`, `FWorkbook` | `f-formula.ts:376`, `f-range.ts:85`, `f-workbook.ts:78` |
| `@univerjs/ui` | `FUniver` | `packages/ui/src/facade/f-univer.ts:602` |
| `@univerjs/sheets-ui` | `FUniver`, `FWorkbook`, `FWorksheet`, `FRange` | `f-univer.ts:1229`, `f-workbook.ts:342`, `f-worksheet.ts:558`, `f-range.ts:373` |
| `@univerjs/docs-ui` | `FDocument` | `packages/docs-ui/src/facade/f-document.ts:103` |
| `@univerjs/network` | `FUniver` (`getNetwork`, `createSocket`) | `packages/network/src/facade/f-univer.ts:100` |
| `@univerjs/sheets-numfmt` | `FRange`, `FWorkbook` | `f-range.ts:156`, `f-workbook.ts:53` |
| `@univerjs/sheets-filter` | `FUniver`, `FRange`, `FWorksheet` | `f-univer.ts:135`, `f-range.ts:107`, `f-worksheet.ts:59` |
| `@univerjs/sheets-sort` | `FUniver`, `FRange`, `FWorksheet` | `f-univer.ts:97`, `f-range.ts:76`, `f-worksheet.ts:73` |
| `@univerjs/sheets-data-validation` | `FUniver`, `FWorkbook`, `FWorksheet`, `FRange` | `f-univer.ts:330` 등 |
| `@univerjs/sheets-hyper-link` | `FUniver`, `FWorkbook`, `FWorksheet`, `FRange` | `f-univer.ts:123` 등 |
| `@univerjs/sheets-thread-comment` | `FUniver`, `FWorkbook`, `FWorksheet`, `FRange` | `f-univer.ts:320` 등 |
| `@univerjs/sheets-note` | `FUniver`, `FWorksheet`, `FRange` | `f-univer.ts:331` 등 |
| `@univerjs/sheets-conditional-formatting` | `FWorksheet`, `FRange` | `f-worksheet.ts:258`, `f-range.ts:129` |
| `@univerjs/sheets-table` | `FWorkbook`, `FWorksheet` | `f-workbook.ts:288`, `f-worksheet.ts:514` |
| `@univerjs/sheets-drawing` | `FUniver`, `FWorksheet` | `f-univer.ts:289`, `f-worksheet.ts:963` |
| `@univerjs/sheets-drawing-ui` | `FUniver`, `FWorksheet`, `FRange` | `f-univer.ts:285` 등 |
| `@univerjs/sheets-find-replace` | `FUniver` | `f-univer.ts:73` |
| `@univerjs/sheets-crosshair-highlight` | `FUniver` | `f-univer.ts:102` |
| `@univerjs/docs-drawing` | `FDocument` | `f-document.ts:260` |
| `@univerjs/thread-comment` | `FUniver` | `f-univer.ts:217` |
| `@univerjs/watermark` | `FUniver` | `f-univer.ts:130` |

`./facade` export가 있는 패키지는 위 목록과 `sheets-formula-ui`, `sheets-hyper-link-ui`, `sheets-note-ui`, `sheets-table-ui`, `docs-thread-comment`를 포함한다. **`@univerjs/slides`, `@univerjs/slides-ui`는 없다.**

---

## 12. 에이전트가 실제로 쓰는 최소 집합

헤드리스 시트 에이전트 기준. UI mixin은 빼도 된다.

| 목적 | 호출 | 위치 |
| --- | --- | --- |
| API 핸들 | `FUniver.newAPI(univer)` 또는 `createUniver(...).univerAPI` | `f-univer.ts:86`, `presets/src/preset.ts:99` |
| mixin 활성화 | `import '@univerjs/sheets/facade'` 등 | `packages/sheets/src/facade/index.ts:17` |
| 워크북 생성 | `univerAPI.createWorkbook(data)` | `sheets/.../f-univer.ts:161` |
| 활성 워크북 | `univerAPI.getActiveWorkbook()` | `sheets/.../f-univer.ts:167` |
| 시트 | `workbook.getActiveSheet()` / `getSheetByName` | `f-workbook.ts:197`, `316` |
| 범위 | `sheet.getRange('A1:B2')` | `f-worksheet.ts:473` |
| 쓰기 | `range.setValue` / `setValues` / `setFormula` | `f-range.ts:1351`, `1631`, `2880` |
| 읽기 | `range.getValue` / `getValues` / `getFormula` | `f-range.ts:512`, `599`, `892` |
| 수식 대기 | `await univerAPI.getFormula().onCalculationResultApplied()` | `engine-formula/.../f-formula.ts:234` |
| 관찰 | `workbook.onCommandExecuted(cb)` 또는 `univerAPI.addEvent(Event.CommandExecuted, cb)` | `f-workbook.ts:518`, `f-univer.ts:615` |
| 스냅샷 | `workbook.save()` / `document.save()` | `f-workbook.ts:180`, `f-document.ts:348` |
| 문서 생성 | `univerAPI.createDocument(data)` | `docs/.../f-univer.ts:64` |
| 문서 편집 | `document.insertText` / `appendParagraph` / `deleteRange` | `f-document.ts:427`, `862`, `880` |
| 저수준 | `univerAPI.executeCommand(id, params)` | `core/.../f-univer.ts:547` |
| 슬라이드 | Facade 없음. `univer.createUnit(UNIVER_SLIDE, data)` | `examples/src/slides/mount.ts:73` |

커맨드 id를 에이전트 도구로 직접 노출할 필요는 없다. Facade가 이미 `SetRangeValuesCommand`, `InsertSheetCommand`, `UndoCommand` 등을 감싼다. Facade에 없는 연산(슬라이드, 일부 Pro 기능)만 `executeCommand`로 내려가면 된다.
