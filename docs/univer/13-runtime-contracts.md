# 런타임 데이터 계약 — 스냅샷 · OT · 유닛 · 로케일 · 부가 패키지

조사 기준: `/Users/yeonwoosung/Desktop/univer` v1.0.2. 에이전트가 `save()`로 읽고 `createWorkbook`/`executeCommand`로 쓰는 JSON 계약을 고정한다. 1차 `02`/`03`의 필드 목록을 구현 규칙까지 내린다.

---

## 1. 왕복 경로

```
createWorkbook(partial IWorkbookData)
  → Workbook merge + default sheet
  → ResourceLoaderService.onLoad(resources)
  → COMMAND → MUTATION 이 스냅샷을 제자리 갱신
  → FWorkbook.save() = clone(getSnapshot()) + 플러그인 resources
```

`Workbook.getSnapshot()`은 플러그인 resources를 넣지 않는다. 에이전트 검증은 **Facade `save()`** 를 쓴다 (`packages/sheets/src/facade/f-workbook.ts:180-183`, `resource-loader.service.ts:164-173`).

---

## 2. 시트 스냅샷

권위: `packages/core/src/sheets/typedef.ts`.

### 2.1 빈 시트 기본값

`sheet-snapshot-utils.ts:22-38`:

| 상수 | 값 |
| --- | ---: |
| `DEFAULT_WORKSHEET_ROW_COUNT` | 1000 |
| `DEFAULT_WORKSHEET_COLUMN_COUNT` | 20 |
| `DEFAULT_WORKSHEET_ROW_HEIGHT` | 24 |
| `DEFAULT_WORKSHEET_COLUMN_WIDTH` | 88 |
| row header width | 46 |
| column header height | 20 |

`appVersion` empty snapshot은 `@univerjs/core` `package.json` = `"1.0.2"`. `rev` 시트는 **1부터** (`typedef.ts:39`). `dateSystem` 없으면 Excel 1900.

### 2.2 `ICellData` 공존 규칙

같은 객체에 `v`/`t`/`f`/`p`/`s`가 같이 있을 수 있다. `SetRangeValuesMutation` merge (`set-range-values.mutation.ts:192-229`):

- `undefined` = 그대로, `null` = 키 삭제
- overwrite: `f`, `p`, `si`, `custom`, `ref`, `xf`, `ft`, `fd`
- `v`는 타입 변환 후 별도 merge
- 수식을 비우면 `ft`/`fd` 삭제

`CellValueType`: STRING=1, NUMBER=2, BOOLEAN=3, FORCE_STRING=4 (`text-style.ts:140-145`). FORCE_STRING은 `"001234"` 같은 선행 0.

`FormulaType` (`typedef.ts:272-278`): NORMAL=0, SHARED=1, ARRAY=2, DATA_TABLE=3.

숫자 서식은 셀 필드가 아니라 `IStyleData.n.pattern`.

`isNullCell`: `v`/`f`/`si`/`p`가 없으면 빈 셀. **스타일만 있는 셀도 null cell로 친다.**

수식 셀은 엔진이 계산 후 `v`/`t`를 채운다. 리치텍스트 셀은 `t: STRING` + `p: IDocumentData`이고 `v` 없이도 유효하다.

---

## 3. 문서 스냅샷과 OT

권위: `packages/core/src/types/interfaces/i-document-data.ts`. 빈 문서 flavor 기본은 **MODERN**. `rev` 주석은 0부터, `getRev()`는 `?? 1`.

### 3.1 `dataStream` 토큰

구현 enum이 정본이다 (`packages/core/src/docs/data-model/types.ts:33-64`). `IDocumentBody` JSDoc의 표 끝 코드는 stale.

| 토큰 | 값 |
| --- | --- |
| PARAGRAPH | `\r` |
| SECTION_BREAK | `\n` |
| TAB | `\t` |
| PAGE_BREAK | `\f` |
| COLUMN_BREAK | `\v` |
| CUSTOM_BLOCK | `\b` |
| TABLE_START…END | `\x1A` `\x1B` `\x1C` `\x1D` `\x0E` `\x0F` |
| CUSTOM_RANGE START/END | `\x1F` / `\x1E` |

빈 body: `dataStream: '\r\n'` + paragraph startIndex 0 + sectionBreak startIndex 1 (`empty-snapshot.ts:52-76`).

### 3.2 JSONX / TextX

`ot-json1` 래퍼. `JSONX.registerSubtype(TextX)`. `editOp` 경로는 `['body']` 하드코딩 (`json-x.ts:125-131`).

TextX 액션: RETAIN=`r`, INSERT=`i`, DELETE=`d`.

문서 쓰기의 정본 mutation: `doc.mutation.rich-text-editing`. 핸들러가 `JSONX.invertWithDoc`으로 undo를 만들고 `documentDataModel.apply(actions)` (`core-editing.mutation.ts:283-346`). 스냅샷 `body`를 직접 고치면 paragraphId/OT가 깨진다.

`payloads`는 복사/붙여넣기 전용, 디스크에 안 남는다.

---

## 4. 슬라이드

코어 `SlideDataModel`은 전부 throw (`packages/core/src/slides/slide-data-model.ts:20-45`). `@univerjs/slides`가 ctor를 덮어쓴다.

실제 모델:

- `getRev()` **항상 0**. increment/setRev no-op. 협업 revision 없음.
- `appendPage` / `updatePage`가 **스냅샷을 직접 mutate**. JSONX 없음.
- Facade/`createSlide`/preset 없음.
- `DEFAULT_SLIDE` pageSize 300×300, pages 없음.

`PageElementType`: SHAPE, IMAGE, TEXT, SPREADSHEET, DOCUMENT, SLIDE. 차트/표/비디오는 인터페이스 주석.

---

## 5. 유닛 라이프사이클

`UnitModel` (`packages/core/src/common/unit.ts:26-42`): `type`, `getUnitId`, `name$`, `getSnapshot`, `getRev`/`incrementRev`/`setRev`.

`IUniverInstanceService`:

- `createUnit` / `getUnit` / `disposeUnit`
- 타입별 `current`와 앱당 `focused`는 다르다. undo 스택은 **focused unit**.
- `focusUnit`이 `FOCUSING_SHEET|DOC|SLIDE|BOARD` 컨텍스트 플래그를 켠다.
- `ICreateUnitOptions`: `makeCurrent` 기본 true, `skipAutoRender`, `embeddedRender`, `renderParentInjector`.

첫 유닛이 해당 타입 플러그인을 깨우고 lifecycle을 `Ready`로 올린다.

---

## 6. Bases 모델 (패키지 없이 코어만)

`packages/core/src/bases/`. `Univer._init`은 SHEET/DOC/SLIDE만 등록하므로 이 클론에서 `createUnit(UNIVER_BASE)`는 기본 경로로 안 뜬다. 타입은 있다.

`BaseFieldType` (`typedef.ts:95-119`): text, singleSelect, multiSelect, person, group, date, attachment, number, checkbox, link, formula, numbering, phone, email, progress, currency, rating, recordLink, recordId, createdBy/updatedBy/createdAt/updatedAt.

`BaseViewType`: grid, kanban, calendar, gantt.

RecordLink는 같은 Base의 다른 테이블을 `targetTableId`로 가리킨다.

---

## 7. Drawing 타입

`DrawingTypeEnum` (`packages/core/src/types/interfaces/i-drawing.ts:46-98`):

| 값 | 이름 | OSS |
| ---: | --- | --- |
| 0 | IMAGE | 실사용 |
| 1 | SHAPE | Docs는 SVG를 IMAGE로 삽입. Slides는 Rect/Circle |
| 2 | CHART | enum + float-dom 훅. 렌더러 없음 |
| 3 | TABLE | drawing 표 아님. Docs 표는 dataStream |
| 4–5 | SMART_ART / VIDEO | enum만 |
| 6 | GROUP | 있음 |
| 7–9 | UNIT / DOM / BLOCK | 임베드·HTML overlay |
| 10–11 | SLICER / TIMELINE | Sheets 인터페이스 |

`DrawingRenderService.renderImages`는 IMAGE가 아니면 return.

---

## 8. 로케일

`LocaleType` 19개 (`packages/core/src/types/enum/locale-type.ts:20-40`): enUS, frFR, zhCN, ruRU, zhTW, zhHK, viVN, faIR, jaJP, koKR, esES, caES, skSK, ptBR, deDE, itIT, idID, plPL, arSA.

RTL: `faIR`, `arSA` (`LOCALE_META`). 로케일 파일은 JSON이 아니라 **`src/locale/*.ts` 모듈**.

`mergeLocales(...)`로 패키지 팩을 합친다. 키 첫 세그먼트 = 패키지 이름 (`docs/NAMING_CONVENTION.md`).

examples 워크벤치는 이 19 로케일 + 7 테마 + ribbon 4종 + chrome 3종을 `localStorage` 키 `univer.examples.workbench.settings`에 저장한다.

---

## 9. Canvas 계층 (엔진)

```
Engine  native <canvas> + rAF
 └── Scene[]
      ├── Layer[]     z-order. drawing layer index 3/4/5
      ├── Viewport[]  MAIN_VIEW_PORT_KEY = 'viewMain'
      └── BaseObject  Shape/Rect/Circle/Image/Group/SceneViewer/Spreadsheet/Documents
```

셀은 Scene 객체가 아니다. `Spreadsheet` 하나가 viewport range를 extension(Background/Border/Font)으로 그린다. 셀 텍스트는 Docs `DocumentSkeleton`을 재사용한다.

줌 헬퍼 범위 **0.1–4.0**. `Canvas.toDataURL`은 있고 OSS Facade 스크린샷 API는 없다.

Docs 레이아웃 워커: 채널 `univer.docs-layout-worker`, protocol v5, `workerFactory` 필수, `OffscreenCanvas`.

---

## 10. 부가 패키지

| 패키지 | 계약 |
| --- | --- |
| action-recorder | 로컬 커맨드 기록/리플레이. 에이전트 루프 아님 |
| telemetry | `ITelemetryService` 인터페이스만. 기본 전송 없음 |
| watermark | 렌더 위 워터마크. Facade 있음 |
| `@univerjs/debugger` | `common/debugger`, private. examples에 안 올라감. FAB 스모크 테스트 |
| core vendored numfmt | MIT `numfmt` 3.2.6 (`packages/core/src/shared/numfmt/`). sheets-numfmt는 이 복사본 |

---

## 11. 개발자 계약 문서

| 파일 | 규칙 |
| --- | --- |
| `docs/ISOMORPHIC.md` | 로직/UI 분리. MUTATION은 UI를 읽지 않음 |
| `docs/CONTRIBUTING-FACADE.md` | Apps Script 스타일. modify→this, create→instance, delete→boolean. async 이름은 `Async` |
| `docs/NAMING_CONVENTION.md` | 커맨드 id `<business>.<type>.<name>` 단수 (`sheet.` not `sheets.` — 실제 코드는 hyper-link가 `sheets.command.*`로 예외) |
| `docs/API_STABILITY.md` | Stable / Experimental / Internal / Deprecated. 본문은 아직 “pre-1.0” |
| `docs/FIX_MEMORY_LEAK.md` | `univer.dispose()` 후 heap snapshot. 루트 싱글톤에 현재 유닛을 들고 있지 말 것 |

커스텀 메뉴 Facade:

```ts
univerAPI.createMenu({ id, icon, title, action }).appendTo('ribbon.start.others')
```

`appendTo` 전까지 트리에 안 붙는다.

---

## 12. examples 워크벤치

`examples/`는 기능별 데모 파일이 아니라 Vite 워크벤치 하나. 해시 `#sheets|#docs|#slides`. 한 번에 인스턴스 하나.

| 엔트리 | 부트 |
| --- | --- |
| Sheets | Preset `createUniver` + 11개 기능 탭 fixture |
| Docs | Preset + `UniverDocsLayoutWorkerPlugin` |
| Slides | Plugin Mode (`new Univer`). preset 없음 |

콘솔: `window.univer` / `window.univerAPI`. 헤드리스 예제는 `examples/`에 없고 Node preset / `tests/formula-integration`이다.
