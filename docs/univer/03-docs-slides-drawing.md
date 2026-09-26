# Univer Docs · Slides · Drawing / Canvas

조사 기준일: 2026-09-25. 원본: `/Users/yeonwoosung/Desktop/univer`, 버전 `1.0.2`, Apache-2.0.

이 문서는 Univer OSS 클론에서 **문서(Docs), 슬라이드(Slides), 드로잉, Canvas 렌더 엔진**이 실제로 어떤 코드로 존재하는지를 고정한다. README 마케팅 문장과 이 저장소의 패키지 표면은 같지 않다. Sheets가 가장 성숙하고, Docs는 OSS 편집기로 쓸 수 있는 수준이며, Slides는 README가 말하는 대로 **active development**다.

인용은 클론 루트 기준 `path:line`이다. 절대 경로는 `/Users/yeonwoosung/Desktop/univer/` 아래에 붙이면 된다.

---

## 1. 한줄 결론

- **Docs**: `IDocumentData` + `dataStream` 리치텍스트 모델이 `@univerjs/core`에 있고, 편집·레이아웃·UI·Facade·Worker가 OSS에 있다. Word 왕복(SDT/필드/노트)까지 모델에 들어와 있다. Pro 쪽은 협업·가져오기/내보내기·인쇄·고급 블록이다.
- **Slides**: `@univerjs/slides` + `@univerjs/slides-ui`가 있고 예제도 돈다. 그러나 패키지가 작고, 협업 revision이 없으며, Facade/Preset이 없고, 차트/표/비디오는 인터페이스에만 주석으로 남아 있다.
- **Drawing**: Docs/Sheets/Slides가 공유하는 객체 모델이다. 이미지·도형·그룹·정렬·크롭 UI가 OSS에 있다. 차트/SmartArt/비디오 enum은 자리만 있다.
- **Canvas 엔진**: `@univerjs/engine-render`이 Engine → Scene → Layer/Viewport → BaseObject 계층을 공유한다. Docs 페이지네이션 스켈레톤도 여기 산다.
- **Bases**: `packages/core/src/bases/`에 `BaseDataModel`이 **있다**. 별도 `packages/bases` 플러그인·UI는 이 클론에 없다.
- **Boards / PDF**: 프로토콜 enum과 메타 타입만 있다. 제품 패키지는 없다. README의 “PDFs (coming soon)”은 이 클론과 일치한다.

---

## 2. README가 말하는 제품군 vs 이 클론

README 헤드라인은 Spreadsheets · Documents · Presentations · Bases · Boards · PDFs (coming soon)이다 (`README.md:7`).

같은 파일의 OSS/Pro 표는 더 정직하다 (`README.md:289–312`).

| 영역 | README가 OSS라고 한 것 | 이 클론의 실제 |
| --- | --- | --- |
| Docs | 리치 문서 모델, 편집 UI, 리스트, 하이퍼링크, drawing, 댓글, quick insert | `@univerjs/docs` + `docs-ui` + drawing/hyper-link/thread-comment/toc/find-replace. 테이블·머리글/바닥글·섹션·워커 레이아웃까지 OSS. |
| Slides | “Presentation data model and UI packages **under active development**” (`README.md:294`) | `packages/slides` 약 22개 TS, `packages/slides-ui` 약 70개 파일. 예제는 플러그인을 직접 등록한다. Preset 없음. |
| Bases | “plugin/command/model architecture 위에 커스텀 구조화 데이터” (`README.md:295`) | `packages/core/src/bases/`에 스냅샷·필드·뷰 타입이 있다. `packages/bases*` 패키지는 없다. |
| Boards | 제품군 헤드라인에만 등장 | `UniverType.UNIVER_BOARD = 6`과 `IBoardMeta`. `BoardDataModel` 없음. 테스트용 Mock만. |
| PDF | coming soon (`README.md:7`) | `UniverType.UNIVER_PDF = 7`과 `IPdfMeta`. `UNIVER_PDF` 참조는 protocol enum 한 곳뿐. |

Sheets가 가장 성숙한 표면이라는 문장도 README에 있다 (`README.md:299`). Docs/Slides는 같은 SDK 아키텍처를 공유하지만 완성도는 다르다.

프로토콜 유닛 타입:

```17:26:/Users/yeonwoosung/Desktop/univer/packages/protocol/src/ts/univer/constants/univer.ts
export enum UniverType {
    UNIVER_UNKNOWN = 0,
    UNIVER_DOC = 1,
    UNIVER_SHEET = 2,
    UNIVER_SLIDE = 3,
    UNIVER_PROJECT = 4,
    UNIVER_BASE = 5,
    UNIVER_BOARD = 6,
    UNIVER_PDF = 7,
    UNRECOGNIZED = -1,
}
```

`UnitModel`은 이 enum을 `UniverInstanceType`으로 재export한다 (`packages/core/src/common/unit.ts:18-21`).

---

## 3. 문서 데이터 모델 (`packages/core/src/docs`)

문서 스냅샷의 권위 타입은 `@univerjs/core`다. `@univerjs/docs`는 그 위에 커맨드/뮤테이션/서비스를 얹는다.

### 3.1 `IDocumentData`

`packages/core/src/types/interfaces/i-document-data.ts:29-47`.

- `id`, `rev`(협업용, 0부터), `locale`, `title`
- `body?: IDocumentBody` — 본문 리치텍스트
- `notes` / `noteSettings` — 각주·미주
- `documentStyle: IDocumentStyle` — 페이지/마진/flavor
- `styles?: IDocStyles` — OOXML 호환 named style
- `resources?: IResources` — 플러그인 리소스
- `IReferenceSource`: `tableSource`, `headers`, `footers`, `footnotes`, `endnotes`, `lists`, `drawings`, `drawingsOrder`

차원 단위는 주석대로 기본 pt (`i-document-data.ts:25`). 페이지 마진·페이지 크기는 96-DPI 레이아웃 픽셀이라고 따로 적혀 있다 (`i-document-data.ts:429-436`, `:711-735`).

### 3.2 `dataStream` + 병렬 어노테이션

본문은 문자 스트림과 오프셋 배열의 조합이다 (`i-document-data.ts:196-244`).

| 필드 | 역할 |
| --- | --- |
| `dataStream: string` | 본문 + 구조 토큰 |
| `textRuns` | `[st, ed)` 스타일 런 |
| `paragraphs` | 단락 |
| `sectionBreaks` | 섹션 |
| `tables` / `columnGroups` / `blockRanges` | 표·다단·콜아웃 등 |
| `customBlocks` | 흐름에 안 들어가는 이미지/멘션 등 (`\b`) |
| `customRanges` | 하이퍼링크·필드·SDT·북마크·댓글 |
| `customDecorations` | 댓글 하이라이트 등 |
| `docxRaw*` | DOCX 무손실 왕복용 opaque XML |
| `payloads` | 복사/붙여넣기 전용, 디스크 저장 안 함 |

구조 토큰은 `DataStreamTreeTokenType` (`packages/core/src/docs/data-model/types.ts:33-64`). **구현 enum이 정본**이다. `IDocumentBody` JSDoc이 표 끝을 `\x1E`/`\x1F`로 적은 부분은 stale — 그 코드는 custom range다.

- `\r` 단락, `\n` 섹션, `\f` 페이지 브레이크, `\0` 문서 끝, `\t` 탭, `\b` custom block
- 표: `\x1A`…`\x0F`
- 컬럼 그룹: `\x12`…`\x15`
- 블록: `\x10`/`\x11`
- custom range: `\x1F` start / `\x1E` end

문서 쓰기의 정본 mutation은 `doc.mutation.rich-text-editing` (JSONX/TextX). Canvas 계층·스켈레톤·DrawingType 구현 여부는 [13-runtime-contracts.md](./13-runtime-contracts.md) §7·§9.

`renderedPageBreaks`는 레이아웃 엔진이 저장한 **soft** 페이지 브레이크다. exporter는 이를 저자 페이지 브레이크로 바꾸면 안 된다 (`i-document-data.ts:199-204`).

### 3.3 Custom range / decoration

`CustomRangeType` (`i-document-data.ts:620-633`): `HYPERLINK`, `FIELD`, `SDT`, `BOOKMARK`, `COMMENT`, `CUSTOM`, `MENTION`, `UNI_FORMULA`, `FOOTNOTE`, `ENDNOTE`.

SDT(Word content control)와 FIELD는 OOXML 왕복을 위해 상당히 두껍다 (`i-document-data.ts:487-598`). 매크로 이름은 데이터로만 보존하고 SDK가 실행하지 않는다고 적혀 있다 (`i-document-data.ts:487`).

### 3.4 Document flavor

```703:709:/Users/yeonwoosung/Desktop/univer/packages/core/src/types/interfaces/i-document-data.ts
export enum DocumentFlavor {
    UNSPECIFIED,
    TRADITIONAL,
    MODERN,
    /** DrawingML text semantics for host-prepared shape and slide text models. */
    DRAWINGML,
}
```

빈 스냅샷 기본값은 `MODERN`이다 (`packages/core/src/docs/data-model/empty-snapshot.ts:38`). TRADITIONAL은 페이지 크기/마진이 있는 Word-like 페이지네이션, MODERN은 웹 문서 폭, DRAWINGML은 슬라이드/도형 텍스트다.

### 3.5 `DocumentDataModel`

`packages/core/src/docs/data-model/document-data-model.ts`.

- `DocumentDataModelSimple`이 `UnitModel<IDocumentData, UNIVER_DOC>` (`:126-127`).
- 생성 시 empty snapshot과 merge. 내부 에디터 ID는 기본값만 얹는다 (`:87-117`).
- header/footer/note는 각각 별도 `DocumentDataModel` 맵 (`:337-341`, `getSelfOrHeaderFooterModel` `:401-418`).
- 변경은 `JSONX.apply` (`:425-443`). JSONX는 `ot-json1` 위에 TextX subtype을 등록한 래퍼다 (`packages/core/src/docs/data-model/json-x/json-x.ts:17-65`).

`packages/core/src/facade/f-doc.ts`의 `FDoc`은 거의 빈 껍데기다 (`:25-31`). 실제 Facade는 `@univerjs/docs/facade`의 `FDocument`.

### 3.6 TextX — 문서 OT

`packages/core/src/docs/data-model/text-x/README.md:1-5`: insert / retain / delete.

```24:28:/Users/yeonwoosung/Desktop/univer/packages/core/src/docs/data-model/text-x/action-types.ts
export enum TextXActionType {
    RETAIN = 'r',
    INSERT = 'i',
    DELETE = 'd',
}
```

`TextX.apply/compose/transform/invert` (`text-x.ts:102-`). JSONX는 body 경로에 TextX를 subtype으로 붙인다 (`json-x.ts:76-79`). 이게 Docs 협업의 OT 층이다. Slides에는 대응물이 없다.

---

## 4. Docs 패키지 군

### 4.1 `@univerjs/docs` — 헤드리스 문서 런타임

플러그인 `UniverDocsPlugin` (`packages/docs/src/plugin.ts:65-165`).

등록 커맨드 (`plugin.ts:118-141`):

- 편집: `InsertTextCommand`, `DeleteTextCommand`, `UpdateTextCommand`
- 뮤테이션: `RichTextEditingMutation`, `DocsRenameMutation`
- 섹션/머리글: `CreateHeaderFooterCommand`, `UpdateDocumentSectionCommand`, `InsertDocumentSectionBreakCommand`, `InsertDocumentColumnBreakCommand`, `DeleteDocumentSectionBreakCommand`
- 권한: `SetDocumentPermission(s)Command` + rule mutations
- 선택: `SetTextSelectionsOperation`

서비스: selection, state emit/change, layout executor, text resolver, content insert, block-move validator, custom-range controller, permission.

Word 패키지 메타(`DOC_WORD_STYLES_PLUGIN`, `DOC_NOTE_PLUGIN`)는 opaque 리소스로 저장만 하고 편집하지 않는다 (`plugin.ts:102-115`).

`RichTextEditingMutation` 파라미터는 `JSONXActions` + 텍스트 레인지다 (`packages/docs/src/commands/mutations/core-editing.mutation.ts:63-83`). `isSync`/`syncer` 필드가 있어 협업 경로를 염두에 두지만, 실제 실시간 협업 서버는 Pro다.

### 4.2 Facade

`packages/docs/src/facade/f-univer.ts:25-90`:

- `univerAPI.createDocument(data)`
- `getActiveDocument()`
- `getDocument(id)`

`FDocument` (`packages/docs/src/facade/f-document.ts`)은 본문/헤더푸터, 단락, 섹션, 텍스트 레인지, 권한, custom block 레이아웃(렌더 없이 모델 오프셋만)을 제공한다. `getCustomBlockLayout()`은 폰트 측정·페이지네이션을 하지 않는다고 명시한다 (`f-document.ts:127-148`). Node/headless에 맞다.

코어 `FDoc`은 ignore/hideconstructor (`packages/core/src/facade/f-doc.ts:21-31`). Docs Facade를 쓰려면 `@univerjs/docs`의 facade entry를 로드해야 한다.

### 4.3 레이아웃 Worker

`DocLayoutExecutorType`은 `main-thread` | `worker` (`packages/docs/src/services/doc-layout-executor.service.ts:58-61`).

`UniverDocsLayoutWorkerPlugin`은 `workerFactory`가 필수다 (`packages/docs/src/layout-worker/index.ts:279-313`). 채널 이름 `univer.docs-layout-worker`, 프로토콜 버전 5 (`layout-worker/protocol.ts:20-21`).

워커 본체 (`layout-worker/worker.ts`)는 `@univerjs/rpc` `ChannelService`로 메시지를 받고, `DocumentDataModel` + `DocumentLayoutSession`(`@univerjs/engine-render`)으로 페이지를 점진 publish한다. 폰트 메트릭이 메인 스레드와 1px 넘게 다르면 `DocsLayoutWorkerCapabilityError` (`layout-worker/index.ts:37-40`, `:270-274`).

예제 Docs 마운트는 이 플러그인을 켠다 (`examples/src/docs/mount.ts:59-61`).

### 4.4 `@univerjs/docs-ui` — 실제 편집기

가장 큰 Docs 패키지(약 300 TS + 44 TSX). `UniverDocsUIPlugin`이 인라인 포맷, 리스트, 헤딩, 테이블 CRUD, 클립보드, IME, 줌, 페이지 설정, 모바일 플러그인까지 등록한다 (`packages/docs-ui/src/plugin.ts:41-143` 근처).

렌더 컨트롤러 예:

- `doc.render-controller.ts` — 캔버스 문서 그리기
- `doc-selection-render.controller.ts` — 캐럿/셀렉션
- `doc-ime-input.controller.ts`, `doc-clipboard.controller.ts`
- `zoom.render-controller.ts`, `doc-layout-progress.render-controller.ts`

클립보드 HTML ↔ UDM 변환이 `services/clipboard/html-to-udm`, `udm-to-html`에 있다. 인쇄는 interceptor (`doc-print-interceptor.service.ts`) — OSS는 훅만, 실제 인쇄 파이프라인은 Pro라는 README 구분과 맞다.

모바일: `mobile-plugin.ts`, `MobileDocCanvasViewport.tsx`, `MobileRichTextEditor.tsx`.

### 4.5 Docs drawing

`@univerjs/docs-drawing` (`UniverDocsDrawingPlugin`, `DependentOn(UniverDocsPlugin, UniverDrawingPlugin)`, `packages/docs-drawing/src/plugin.ts:28-33`).

문서 드로잉 타입 (`docs-drawing/src/services/doc-drawing.service.ts:22-31`):

- `IDocImage` = `IImageData` + `IDocDrawingBase`
- `IDocShape`
- `IDocFloatDom` — 임베드 블록용 DOM drawing

모델 쪽 wrapping은 Word DrawingML에 가깝다 (`i-document-data.ts:968-1041`):

- `PositionedObjectLayoutType`: `INLINE`, `WRAP_NONE`, `WRAP_POLYGON`, `WRAP_SQUARE`, `WRAP_THROUGH`, `WRAP_TIGHT`, `WRAP_TOP_AND_BOTTOM`
- `behindDoc`이 텍스트 앞/뒤를 가른다. `WRAP_NONE`만으로는 앞뒤가 결정되지 않는다 (`:1021-1026`).

UI 커맨드 `TextWrappingStyle`는 더 좁다 (`docs-drawing/src/commands/commands/update-doc-drawing-wrapping-style.command.ts:41-81`): `inline` / `behindText` / `inFrontOfText` / `wrapSquare` / `wrapTopAndBottom`. `WRAP_POLYGON/THROUGH/TIGHT`는 모델에 있으나 UI enum에는 없다.

`docs-drawing-ui`는 insert image/shape, group/ungroup, crop, float-dom, 인쇄용 float DOM, 모바일 패널을 담당한다.

### 4.6 하이퍼링크 · 댓글 · TOC · 찾기바꾸기

| 패키지 | 역할 | 크기 감각 |
| --- | --- | --- |
| `docs-hyper-link` | custom range 하이퍼링크 뮤테이션 + 리소스 | 7 TS |
| `docs-hyper-link-ui` | 팝업, 클릭, 리본 | ~58 파일 |
| `docs-thread-comment` | 텍스트 레인지 댓글 생성 + decoration mutation | 9 TS |
| `docs-thread-comment-ui` | 선택/렌더/UI. thread-comment-ui + drawing에 의존 | ~44 파일 |
| `docs-toc` | TOC insert/update/delete 커맨드만 | 5 TS |
| `docs-toc-ui` | 리본·하이라이트 렌더 | ~37 파일 |
| `docs-find-replace` | 공유 `find-replace`에 Docs provider 등록 | 15 TS |

하이퍼링크 플러그인은 `Add/Delete/UpdateHyperLinkMuatation`을 등록한다 (파일명에 Mutation 오타가 그대로 있다, `docs-hyper-link/src/plugin.ts:21`).

댓글 앵커는 `IThreadComment.startOffset/endOffset` + `segmentId` (`thread-comment/src/types/interfaces/i-thread-comment.ts:44-50`). 본문 텍스트 자체는 `IDocumentBody`다 (`:33`).

찾기바꾸기는 `UniverFindReplacePlugin`에 provider를 꽂는 얇은 어댑터다 (`docs-find-replace/src/index.ts:28-57`). Docs 전용 Preset은 없다.

TOC Preset은 `UniverDocsCorePreset`의 `toc` 플래그로 UI에 넘긴다 (`presets/packages/preset-docs-core/src/preset.ts:35-68`).

### 4.7 Docs Preset / 예제

`presets/packages/`에 있는 Docs 프리셋:

- `preset-docs-core` — network, docs, render, ui, docs-ui, formula engine
- `preset-docs-drawing`
- `preset-docs-hyper-link`
- `preset-docs-thread-comment`
- `preset-docs-node-core` — 헤드리스

`preset-slides-*`는 **없다**.

브라우저 예제 (`examples/src/docs/mount.ts:52-67`)는 core+drawing+hyper-link+thread-comment 프리셋 후 레이아웃 워커를 추가하고 `createDocumentFixture`로 유닛을 만든다.

---

## 5. Slides

### 5.1 코어 스텁 vs 실제 모델

`packages/core/src/slides/slide-data-model.ts`는 **전부 throw**인 자리표시자다 (`:20-45`). 실제 구현은 `@univerjs/slides`.

### 5.2 `ISlideData`

`packages/slides/src/types/interfaces/i-slide-data.ts:36-42`.

```
id, locale?, title, pageSize, body?: { pages, pageOrder }
```

참조 소스: `master`, `handoutMaster`, `notesMaster`, `layouts`, `lists` (`:44-50`). Google Slides / PPT 구조를 흉내 낸다.

페이지 (`ISlidePage`, `:57-72`): `pageType`, `zIndex`, `pageBackgroundFill`, `pageElements`.

`PageType` (`:141-147`): `SLIDE`, `MASTER`, `LAYOUT`, `HANDOUT_MASTER`, `NOTES_MASTER`.

`PageElementType` (`:149-156`): `SHAPE`, `IMAGE`, `TEXT`, `SPREADSHEET`, `DOCUMENT`, `SLIDE`.

페이지 엘리먼트는 위치/회전/스케일과 union payload를 가진다 (`:102-139`):

- `shape?: IShape` — `shapeType` + `shapeProperties` + 텍스트
- `image?: IImage`
- `richText?: ISlideRichTextProps` — 평문 `text` 또는 통째 `IDocumentData`
- `spreadsheet?: { worksheet, styles }` — 슬라이드 안에 시트 임베드
- `document?: IDocumentData`
- `slide?: ISlideData` — 중첩 슬라이드
- 주석 처리: `video`, `line`, `table`, `chart` (`:134-137`)

도형 preset은 DrawingML `prstGeom` 이름이다 (`packages/slides/src/types/enum/prst-geom-type.ts:19-`). `BasicShapes.Rect = 'rect'` 등.

기본 스냅샷은 `id/title/pageSize 300×300`뿐이다 (`packages/slides/src/basics/const/default-slide.ts:17-24`).

### 5.3 `SlideDataModel`

`packages/slides/src/data-model/slide-data-model.ts`.

- `UniverInstanceType.UNIVER_SLIDE` (`:25-26`)
- 페이지 CRUD: `getPages`, `getPageOrder`, `appendPage`, `updatePage`, `setActivePage`
- **협업 없음**: `getRev()`이 `0`을 반환하고 increment/setRev는 no-op. 주석: “slide has not implement collaborative editing yet” (`:68-78`).

플러그인 `UniverSlidesPlugin`은 렌더 엔진에 의존하고, `onStarting`에서 `SlideDataModel` 생성자만 등록한다 (`packages/slides/src/plugin.ts:28-58`). CanvasView 의존성은 주석 처리되어 있다 (`:70-73`).

렌더 어댑터 (`packages/slides/src/views/render/adaptors/`): docs, image, rich-text, shape, slide, spreadsheet. 페이지 엘리먼트 타입을 `ObjectAdaptor.check/convert`로 캔버스 객체에 매핑한다 (`slide-adaptor.ts:36-80`).

### 5.4 `@univerjs/slides-ui`

`UniverSlidesUIPlugin` 의존성 (`packages/slides-ui/src/plugin.ts:50-56`): Docs + DocsUI + Drawing + RenderEngine + Slides. 슬라이드 텍스트 편집이 **Docs 내부 에디터** (`__INTERNAL_EDITOR__DOCS_NORMAL`, `:114-115`)를 재사용한다.

제공하는 operation (mutation이 아니라 operation):

- `append-slide`, `activate`, `insert-image/shape/text`, `delete-element`, `update-element`, `text-edit`, `set-thumb`

`InsertSlideShapeRectangleCommand` 같은 커맨드는 focused unit id를 읽어 operation을 실행한다 (`slides-ui/src/commands/operations/insert-shape.operation.ts:30-38`). JSONX/OT가 없다.

UI: `SlideBar`(페이지 썸네일), `Sidebar`, Arrange/Fill/Transform 패널, 이미지 팝업, `EditorContainer`. Facade entry는 패키지 README 기준으로 **No**.

예제는 프리셋 없이 플러그인을 직접 등록한다 (`examples/src/slides/mount.ts:58-73`). Docs 예제와 대비된다.

### 5.5 엔진 쪽 Slide 컴포넌트

`packages/engine-render/src/components/slides/slide.ts`. `Slide extends SceneViewer`. 페이지는 sub-scene이고 `changePage`가 active sub-scene을 바꾼다 (`:43-72`). 좌우 네비게이션 화살표 패스가 하드코딩되어 있다 (`:33-34`).

성숙도: 데모/임베드용 캔버스 슬라이드는 동작한다. PPT 호환, 차트, 표, 협업, import/export, Facade는 OSS에 없다. README Pro 열과 일치한다 (`README.md:294`, `:310`).

---

## 6. Drawing 객체

### 6.1 공유 모델 (`@univerjs/core` + `@univerjs/drawing`)

`DrawingTypeEnum` (`packages/core/src/types/interfaces/i-drawing.ts:46-99`):

| 값 | 의미 | OSS 구현 감각 |
| --- | --- | --- |
| `DRAWING_IMAGE = 0` | 이미지 | 있음 |
| `DRAWING_SHAPE = 1` | 도형 | Docs/Slides UI에 insert-shape |
| `DRAWING_CHART = 2` | 차트 | enum만. Pro |
| `DRAWING_TABLE = 3` | 표(drawing으로서) | Docs 본문 표는 별도 dataStream 표 |
| `DRAWING_SMART_ART = 4` | SmartArt | enum만 |
| `DRAWING_VIDEO = 5` | 비디오 | enum만 |
| `DRAWING_GROUP = 6` | 그룹 | drawing-ui group operation |
| `DRAWING_UNIT = 7` | 다른 Univer 유닛을 플로팅 | 임베드 경로 |
| `DRAWING_DOM = 8` | HTML 플로팅 | `IDocFloatDom` |
| `DRAWING_BLOCK = 9` | 호스트 임베드 블록 | custom block drawing |
| `DRAWING_SLICER = 10` | 시트 슬라이서 | Sheets |
| `DRAWING_TIMELINE = 11` | 시트 타임라인 | Sheets |

`IDrawingParam`: `unitId` + `subUnitId` + `drawingId` + `transform` + 그룹/락/hidden (`i-drawing.ts:143-169`). `subUnitId`는 sheetId 또는 pageId, Docs는 기본 이름 (`:105-106`).

`ArrangeTypeEnum`: forward/backward/front/back (`:24-41`).

### 6.2 `@univerjs/drawing`

플러그인 (`packages/drawing/src/plugin.ts:29-76`)이 등록하는 것:

- `IDrawingManagerService` → `DrawingManagerService`
- `IImageIoService`, `IURLImageService`
- `SetDrawingSelectedOperation`

이미지는 `IImageData` (`packages/drawing/src/models/image-model-interface.ts:19-37`): `imageSourceType`, `source`, `srcRect`, `prstGeom`, `adjustValues`.

매니저 인터페이스는 add/remove/update/focus/group/order 스트림과 batch op 생성이다 (`drawing/src/services/drawing-manager.service.ts:60-115`). Docs는 `UnitDrawingService<IDocDrawing>`로 특수화한다.

유틸: copy plan, group, rotate-enabled, image size. 회전 금지는 차트 등 “엑셀에서 돌리면 안 되는” 객체를 위한 것 (`i-drawing.ts:120-122`).

### 6.3 `@univerjs/drawing-ui`

공유 변환 UI (`packages/drawing-ui/src/plugin.ts:32-68`): align, arrange, group, image crop, reset size, object list panel, transformer. Docs/Sheets/Slides UI가 이 패널을 재사용한다.

`DrawingRenderService`가 `IDrawingParam`을 엔진 `Image`/`Rect` 객체로 올린다 (`drawing-ui/src/services/drawing-render.service.ts:46-50`). Docs는 `behindDoc`/`layoutType`을 같이 본다.

모바일 플러그인 `mobile-plugin.ts`가 따로 있다.

---

## 7. Canvas 렌더 엔진 (`@univerjs/engine-render`)

README: layout, primitives, interaction, scroll, zoom (`packages/engine-render/README.md:7`).

플러그인은 `IRenderManagerService`와 `ICanvasColorService`만 등록한다 (`packages/engine-render/src/plugin.ts:26-52`). Scene 그래프 자체는 라이브러리 코드다.

### 7.1 계층

```
Engine
  └── Scene[]          (active scene 하나)
        ├── Layer[]    (z-order, dirty/cache)
        ├── Viewport[] (scroll/clip; MAIN_VIEW_PORT_KEY = 'viewMain')
        └── BaseObject / Group / SceneViewer
              └── Slide / Documents / Spreadsheet / Image / Shape / ...
```

**Engine** (`engine.ts:41-62`): 네이티브 canvas 래퍼, rAF 루프, 포인터/드래그/드롭을 Scene InputManager로 전달. `renderEvenInBackground = true`. DPR, `CanvasRenderMode.Rendering | Printing` (`canvas.ts:26-37`). Printing 모드는 “high dpi pdf”를 염두에 둔 주석이 있다 (`canvas.ts:32-35`) — PDF 제품이 아니라 인쇄용 캔버스 모드.

**Scene** (`scene.ts:41`, `:255-277`): Engine 또는 SceneViewer의 자식. Layer + Viewport + Transformer + InputManager. 스크롤 중 헤더 픽셀이 본문으로 새지 않게 shared edge를 trim한다 (`scene.ts:114-115`).

**Viewport** (`viewport.ts:50-63`): 위치, wheel prevent, cache, buffer edge. 스크롤바 좌표와 콘텐츠 `viewportScrollX/Y`를 분리한다 (`:65-88`).

**Layer** (`layer.ts:47-80`): dirty bounds를 clip하고, 스크롤 시 canvas `copy`로 픽셀을 재사용한다.

**BaseObject** (`base-object.ts:48-57`, `:59-88`): `top/left/width/height/angle/scale/skew/flip`. 포인터·드래그 Observable. `ObjectType`: RICH_TEXT, SHAPE, IMAGE, RECT, CIRCLE, CHART, DRAWING_DOM.

**SceneViewer** (`scene-viewer.ts:26-41`): 객체이면서 자식 Scene을 담는다. 슬라이드 페이지, 임베드 유닛에 쓴다.

**RenderUnit** (`render-manager/render-unit.ts:38-46`): `unitId`, `type`, `engine`, `scene`, `mainComponent`. `RenderManagerService.createRender`가 유닛 타입별 DI로 렌더 모듈을 붙인다 (`render-manager.service.ts:49-80`).

`RenderComponentType = SheetComponent | DocComponent | Slide | BaseObject` (`render-manager.service.ts:47`).

### 7.2 Docs 레이아웃/페인트

엔진 안에 Docs 전용 서브트리가 크다.

- `components/docs/view-model/document-view-model.ts` — `dataStream`을 `DataStreamTreeNode` 트리로
- `components/docs/layout/doc-skeleton.ts` — 페이지/라인/glyph 스켈레톤. hyphenation, line-breaker, shaping, 각주/미주, 테이블
- `DocumentLayoutSession` (`worker-layout.ts:55-78`) — 워커-안전 레이아웃 소유자. 한 publication에 최대 4페이지 (`:31`)
- `components/docs/document.ts` — 스켈레톤을 캔버스에 그림. extensions: background, border, font-and-base-line, line

하이픈 패턴이 수십 개 언어로 `layout/hyphenation/patterns/`에 있다. line-breaker는 Unicode 트라이 (`layout/line-breaker/`).

Sheets 스켈레톤/확장도 같은 패키지에 있다. 이 문서 범위 밖이지만, **엔진은 Sheets/Docs/Slides 공유**라는 점이 중요하다.

### 7.3 Shape primitives

`packages/engine-render/src/shape/`: `rect`, `circle`, `line`, `path`, `image`, `text`, `rich-text`, `regular-polygon`, `checkbox`, `scroll-bar`, `control`, `dashedrect`, `drawing`.

Transformer (`scene.transformer.ts`)가 선택 객체 리사이즈/회전 핸들을 그린다. Drawing-ui가 이걸 쓴다.

---

## 8. Web Worker 노트

`docs/tldr/web-worker-architecture.tldr`는 **읽을 수 있는 아키텍처 문서가 아니다**. tldraw JSON(`tldrawFileFormatVersion: 1`)이다. 도형/카메라 좌표만 있고, 엔진 설명을 추출할 수 없다.

이 클론에서 확인되는 Worker 경로:

1. **Docs 레이아웃 워커** (위 4.3). RPC 채널 + `DocumentLayoutSession`. 예제 `examples/src/docs/worker.ts`.
2. **공유 RPC 플러그인** `@univerjs/rpc`: `UniverRPCMainThreadPlugin`이 워커를 띄우고 `ChannelService`로 메인↔워커 포트를 잇는다 (`packages/rpc/src/plugin.ts:44-50`, `:39-42`).
3. **Sheets 공식 워커**는 `preset-sheets-core/src/worker.ts` 등. Docs와 별개(수식 엔진 위주).

레이아웃 세션 주석: “Scheduling, transport, presentation and model revision ordering belong to callers” (`worker-layout.ts:56-57`). 워커는 스켈레톤만 계산하고, 메인 스레드가 페인팅한다.

---

## 9. 공유 패키지: thread-comment, data-validation, watermark

### 9.1 `@univerjs/thread-comment`

제품 비의존 댓글 코어. `UniverInstanceType.UNIVER_UNKNOWN` (`packages/thread-comment/src/plugin.ts:50-54`). Docs/Sheets가 각각 `docs-thread-comment`, `sheets-thread-comment`로 앵커를 특수화한다.

커맨드: add/delete/resolve/update. 텍스트는 `IDocumentBody`라서 댓글 본문도 Docs 모델을 쓴다.

원격 댓글 리소스는 README상 Pro (`README.md:293`).

### 9.2 `@univerjs/data-validation`

이름은 공유지만 **Sheets 플러그인**이다.

```31:35:/Users/yeonwoosung/Desktop/univer/packages/data-validation/src/plugin.ts
export class UniverDataValidationPlugin extends Plugin {
    static override pluginName = 'UNIVER_DATA_VALIDATION_PLUGIN';
    static override packageName = pkg.name;
    static override version = pkg.version;
    static override type = UniverInstanceType.UNIVER_SHEET;
```

README도 “used by sheet data validation features” (`packages/data-validation/README.md:7`). Docs 데이터 검증 패키지는 이 클론에 없다. 스코프에 “shared”로 적혀 있어 확인한 결과, **코드 공유는 시트 쪽**이다.

### 9.3 `@univerjs/watermark`

렌더 모듈을 SHEET/DOC/SLIDE/**BASE**에 등록한다 (`packages/watermark/src/plugin.ts:116-124`). 텍스트·이미지·유저정보 워터마크. localStorage 키로 설정 보존 (`:69-101`). Facade 있음.

README는 “documents and sheets”만 말하지만 (`watermark/README.md:7`), 코드는 슬라이드·베이스 타입에도 붙는다. 베이스 UI가 OSS에 없으므로 BASE 등록은 자리만 있을 가능성이 크다.

---

## 10. Bases / Boards / PDF — 이 클론에 있는 것

### 10.1 Bases: 모델은 있고 제품 패키지는 없다

경로: `packages/core/src/bases/`.

- `BaseDataModel extends UnitModel<IBaseSnapshot, UNIVER_BASE>` (`base-data-model.ts:38-39`)
- 필드 타입: text, select, person, date, attachment, number, checkbox, link, formula, recordLink, createdBy 등 (`typedef.ts:95-119`)
- 뷰: grid, kanban, calendar, gantt, gallery, pivot (`typedef.ts:155-162`)
- 레코드 identity, formula table name, empty snapshot (`empty-snapshot.ts:34-40`)
- 셀 값은 시트와 비슷하게 `v/t/p/f`이고 `p`가 `IDocumentData`일 수 있다 (`typedef.ts:39-45`)

없는 것: `packages/bases`, `packages/bases-ui`, Preset, examples/bases, Facade 전용 패키지. README OSS 칸 “architecture 위에 직접 구축” (`README.md:295`)과 Pro 칸 “database model, commands, workbench UI” (`README.md:311`)의 경계가 코드와 맞다. **모델 타입은 OSS 코어에 이미 상당히 들어가 있다.** 워크벤치가 없을 뿐이다.

### 10.2 Boards: 훅과 메타만

- `IBoardMeta` (`packages/protocol/src/ts/univer/board.ts:19-27`): unitID, rev, creator, name, resources, originalMeta
- `ResourceLoader`가 `UNIVER_BOARD` 유닛을 로드/언로드한다 (`packages/core/src/services/resource-loader/resource-loader.service.ts:75-76`, `:124`)
- 테스트에서만 `MockBoardUnit` (`authz-io-local.service.spec.ts:34-35`)

`packages/core/src/boards/` 없음. `packages/boards*` 없음.

### 10.3 PDF: coming soon이 맞다

- `IPdfMeta` (`packages/protocol/src/ts/univer/pdf.ts:25-41`): source PDF, model JSON, decode manifest, schema version, assets, editor/export patch 파일 id
- `UNIVER_PDF` 심볼 사용처는 protocol enum 정의가 유일 (`rg` 결과 1건)
- 엔진 `CanvasRenderMode.Printing`은 PDF 제품이 아니라 인쇄 캔버스다

---

## 11. 성숙도 (정직하게)

상대 규모 (이 클론 `packages/*/src` 대략치):

| 표면 | 패키지 | TS/TSX 규모 | Facade | Preset | 협업 OT | 평가 |
| --- | --- | ---: | :---: | :---: | :---: | --- |
| Sheets | sheets + sheets-ui + 다수 | 매우 큼 | 있음 | 많음 | 있음 | OSS 주력 |
| Docs | docs ~105, docs-ui ~345, 위성 패키지 | 큼 | 있음 | core/drawing/link/comment/node | TextX+JSONX | 임베드 가능한 편집기. Word 고급 기능·협업 서버는 Pro |
| Slides | slides ~22, slides-ui ~70 | 작음 | 없음 | 없음 | 없음 (`getRev=0`) | 데모 가능. 제품 슬라이드로 보기엔 이름 그대로 under development |
| Drawing | drawing ~23, drawing-ui ~90 | 중간 | 없음 | docs/sheets drawing preset | Docs는 JSONX에 실림 | 이미지/도형/그룹은 실사용. 차트는 Pro |
| Engine | engine-render ~360 | 큼 | 없음 | (core에 포함) | n/a | Docs/Sheets가 공유하는 가장 두꺼운 런타임 중 하나 |
| Bases | core/src/bases only | 모델만 | 없음 | 없음 | 모델에 rev 필드 | 타입은 두꺼움. UI/커맨드 패키지 없음 |
| Boards/PDF | protocol | 메타만 | — | — | — | 자리표시자 |

Docs OSS가 실제로 하는 일:

- 타이핑, 인라인 스타일, 리스트, 헤딩, 정렬
- 테이블 삽입/행열 편집
- 머리글/바닥글, 섹션, 다단 토큰
- 이미지/도형 wrapping
- 하이퍼링크, 스레드 댓글, TOC, 찾기바꾸기
- 줌, 클립보드 HTML, IME, 모바일 UI
- 레이아웃 워커
- Facade로 헤드리스 생성/편집

Docs OSS가 하지 않거나 Pro인 일 (README `README.md:293` + 코드 공백):

- 실시간 협업 서버 / changeset replay
- DOCX import/export 실행 패키지 (모델에 raw XML 슬롯만)
- 인쇄 완성 파이프라인
- callout/code/quote 고급 블록의 전용 패키지 (`blockRanges` 타입은 있음)
- 원격 댓글 스토리지

Slides OSS가 하는 일:

- 페이지 추가, 활성 페이지, 썸네일
- 이미지/사각형/텍스트 삽입, 위치 변환
- Docs 에디터로 텍스트 박스 편집
- 페이지를 SceneViewer sub-scene으로 렌더

Slides가 하지 않는 일:

- OT/rev, Facade, Preset
- 마스터/레이아웃 상속의 실제 편집 UX (타입만)
- 차트·표·비디오·애니메이션
- PPT import/export

Drawing 주의: enum에 차트/SmartArt/비디오가 있어도 구현으로 단정하면 안 된다.

---

## 12. 패키지 맵 (절대 경로)

클론 루트: `/Users/yeonwoosung/Desktop/univer`

| 경로 | npm | 한줄 |
| --- | --- | --- |
| `packages/core/src/docs/` | `@univerjs/core` | `DocumentDataModel`, TextX, JSONX, empty snapshot |
| `packages/core/src/types/interfaces/i-document-data.ts` | 〃 | 문서 스냅샷 스키마 |
| `packages/core/src/types/interfaces/i-drawing.ts` | 〃 | DrawingType/Param |
| `packages/core/src/slides/slide-data-model.ts` | 〃 | **throw stub** |
| `packages/core/src/bases/` | 〃 | `BaseDataModel` + typedef. UI 없음 |
| `packages/docs/` | `@univerjs/docs` | 커맨드/뮤테이션/레이아웃 워커/Facade |
| `packages/docs-ui/` | `@univerjs/docs-ui` | 편집기 UI·렌더 컨트롤러 |
| `packages/docs-drawing/` | `@univerjs/docs-drawing` | 문서 앵커 drawing 모델 |
| `packages/docs-drawing-ui/` | `@univerjs/docs-drawing-ui` | 삽입/wrapping/크롭 UI |
| `packages/docs-hyper-link/` | `@univerjs/docs-hyper-link` | 링크 뮤테이션 |
| `packages/docs-hyper-link-ui/` | `@univerjs/docs-hyper-link-ui` | 링크 팝업 |
| `packages/docs-thread-comment/` | `@univerjs/docs-thread-comment` | 텍스트 레인지 댓글 |
| `packages/docs-thread-comment-ui/` | `@univerjs/docs-thread-comment-ui` | 댓글 UI |
| `packages/docs-toc/` | `@univerjs/docs-toc` | TOC 커맨드 |
| `packages/docs-toc-ui/` | `@univerjs/docs-toc-ui` | TOC UI |
| `packages/docs-find-replace/` | `@univerjs/docs-find-replace` | find-replace 어댑터 |
| `packages/slides/` | `@univerjs/slides` | `SlideDataModel` + 어댑터 |
| `packages/slides-ui/` | `@univerjs/slides-ui` | 슬라이드 편집 UI |
| `packages/drawing/` | `@univerjs/drawing` | 공유 drawing 매니저 |
| `packages/drawing-ui/` | `@univerjs/drawing-ui` | 공유 transformer UI |
| `packages/engine-render/` | `@univerjs/engine-render` | Engine/Scene/Viewport + Docs skeleton |
| `packages/thread-comment/` | `@univerjs/thread-comment` | 공유 댓글 코어 |
| `packages/thread-comment-ui/` | `@univerjs/thread-comment-ui` | 공유 댓글 UI |
| `packages/data-validation/` | `@univerjs/data-validation` | **Sheets only** |
| `packages/watermark/` | `@univerjs/watermark` | 워터마크 렌더 모듈 |
| `packages/rpc/` | `@univerjs/rpc` | 메인↔워커 채널 |
| `packages/protocol/src/ts/univer/constants/univer.ts` | `@univerjs/protocol` | DOC/SHEET/SLIDE/BASE/BOARD/PDF enum |
| `packages/protocol/src/ts/univer/board.ts` | 〃 | `IBoardMeta` only |
| `packages/protocol/src/ts/univer/pdf.ts` | 〃 | `IPdfMeta` only |
| `presets/packages/preset-docs-*` | `@univerjs/preset-docs-*` | Docs 프리셋. Slides 프리셋 없음 |
| `examples/src/docs/` | examples | Docs 마운트 + worker |
| `examples/src/slides/` | examples | Slides 마운트, 프리셋 없음 |
| `docs/tldr/web-worker-architecture.tldr` | — | tldraw JSON. 텍스트 아키텍처 아님 |

---

## 13. 에이전트/임베드 관점

Docs를 하네스로 쓸 때 이 클론에서 바로 닿는 축:

1. `univerAPI.createDocument` / `getActiveDocument` (`packages/docs/src/facade/f-univer.ts:64-90`)
2. `RichTextEditingMutation` + TextX (`packages/docs/src/commands/mutations/core-editing.mutation.ts:63-69`)
3. 헤드리스는 `preset-docs-node-core`. 레이아웃 픽셀이 필요하면 워커 또는 메인 스레드 `DocLayoutExecutorService`
4. 이미지는 `docs-drawing` 커맨드. wrapping은 UI enum 5종이 실사용 표면

Slides를 하네스로 쓸 때:

1. Facade가 없다. `univer.createUnit(UNIVER_SLIDE, snapshot)` (`examples/src/slides/mount.ts:73`)
2. 페이지 조작은 `SlideDataModel.appendPage` 또는 slides-ui operations
3. 텍스트 박스는 내부 Docs 에디터. 문서 OT가 슬라이드 스냅샷 전체를 커버하지 않는다
4. revision이 항상 0이므로 협업/워크트리 전제로 쓰면 안 된다

Canvas를 직접 건드릴 때:

- 유닛당 `IRenderManagerService.getRenderUnitById` → `engine` / `scene` / `mainComponent`
- Docs mainComponent는 `Documents`(`components/docs/document.ts`), Slides는 `Slide`(`components/slides/slide.ts`)
