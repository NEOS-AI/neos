# Univer `packages/` 60개 인벤토리

조사 대상: `/Users/yeonwoosung/Desktop/univer` (DreamNum Univer 클론, `@univerjs/*` **1.0.2**, Apache-2.0).  
기준일: 2026-09-25. Univer 원본은 수정하지 않았다.

`packages/` 아래 디렉터리는 **60개**다. 각 디렉터리에 `package.json`이 하나씩 있고, npm 이름은 전부 `@univerjs/<dir>`, `private: false`, `license: Apache-2.0`, `version: "1.0.2"`다. 인용 경로는 클론 기준 상대 경로다.

---

## 0. 읽는 법

표 열은 다음 규칙으로 고정한다.

| 열 | 의미 | 근거 |
| --- | --- | --- |
| 디렉터리 | `packages/<dir>` | `ls packages/` |
| npm | `package.json` `name` | 각 `packages/*/package.json:2` |
| 역할 | README 첫 문장(보통 `:7`). 플러그인 클래스가 있으면 괄호에 적는다 | `packages/*/README.md`, `src/plugin.ts` |
| Facade | 소스 `exports["./facade"]` 존재 여부 | 각 `package.json` `exports` |
| UI | 자체 UI 레이어인지 | README Package Overview **CSS** 열, 또는 `-ui` 접미사 / `design`·`ui`·어댑터 / `*.tsx`+PostCSS |
| core / render / formula | `@univerjs/core` · `@univerjs/engine-render` · `@univerjs/engine-formula`를 **dependencies 또는 peerDependencies**에 적었는지. `devDependencies`는 세지 않는다 | 각 `package.json` |

Facade **예**는 워크스페이스 `exports`에 `"./facade": "./src/facade/index.ts"`가 있는 경우다. npm에 실제로 나가는 맵은 `publishConfig.exports`다. **두 패키지**(`sheets-note-ui`, `sheets-table-ui`)는 소스 `exports`에만 `./facade`가 있고 `publishConfig`와 README Facade 열은 No다. 표에는 소스 기준으로 예\* 하고 §9에 적는다.

UI **예**는 워크벤치 부품(리본·패널·CSS·React)을 가진 패키지다. `docs-find-replace`는 자체 CSS가 없지만 공유 find-replace UI를 Docs에 붙이므로 예로 센다 (`packages/docs-find-replace/README.md:7`). `sheets-find-replace`는 CSS/React가 없는 시트 로직이라 아니오다. `themes`는 토큰만 있어 아니오다. `ui-adapter-*`는 시각 위젯이 아니라 프레임워크 어댑터라 예(어댑터)로 표시한다.

자기 자신인 패키지(`core`, `engine-render`, `engine-formula`)의 해당 열은 **자기**.

그룹은 디렉터리 이름과 책임을 따른다: foundation, engines, `sheets*`, `docs*`, `slides*`, `drawing*`, ui/design/themes, network/rpc/protocol, misc. `data-validation`과 `thread-comment`는 제품 타입이 아닌 공유 모델이라 foundation에 둔다. `thread-comment-ui`는 공유 UI라 ui/design/themes에 둔다.

---

## 1. 집계

| 그룹 | 개수 | Facade 예 | UI 예 |
| --- | ---: | ---: | ---: |
| foundation | 3 | 2 | 0 |
| engines | 2 | 1 | 0 |
| sheets\* | 26 | 18 | 13 |
| docs\* | 11 | 4 | 6 |
| slides\* | 2 | 0 | 1 |
| drawing\* | 2 | 0 | 1 |
| ui / design / themes | 6 | 1 | 5 |
| network / rpc / protocol | 4 | 1 | 0 |
| misc | 4 | 1 | 2 |
| **합계** | **60** | **28 + 예\* 2** | **28** |

Facade 예 28은 `publishConfig`까지 `./facade`를 내보내는 패키지. 예\* 2를 더하면 소스 기준 30.

core에 직접 의존하지 않는 패키지는 **3개**뿐이다: `design`, `protocol`, `themes`.

---

## 2. foundation

런타임 커널과 제품 타입에 묶이지 않은 공유 모델.

| 디렉터리 | npm | 역할 | Facade | UI | core | render | formula | 근거 |
| --- | --- | --- | :---: | :---: | :---: | :---: | :---: | --- |
| `core` | `@univerjs/core` | Univer 런타임, DI, 커맨드/뮤테이션, 데이터 모델, 설정, 로케일, 공유 Facade 엔트리 | 예 | 아니오 | 자기 | 아니오 | 아니오 | `package.json:2,4,28-30,80-89`; `README.md:7,13` |
| `data-validation` | `@univerjs/data-validation` | 시트 데이터 유효성이 쓰는 공유 규칙 모델·서비스 (`UniverDataValidationPlugin`) | 아니오 | 아니오 | 예 | 아니오 | 아니오 | `package.json:2,4,76`; `README.md:7,13`; `src/plugin.ts` |
| `thread-comment` | `@univerjs/thread-comment` | Docs/Sheets 댓글 패키지가 쌓는 공유 스레드 댓글 모델·커맨드·서비스 (`UniverThreadCommentPlugin`) | 예 | 아니오 | 예 | 아니오 | 아니오 | `package.json:2,4,29,81`; `README.md:7,13` |

`core` dependencies (`packages/core/package.json:80-89`): `@univerjs/protocol`, `@univerjs/themes`, `@wendellhu/redi`, `async-lock`, `fast-diff`, `kdbush`, `lodash-es`, `ot-json1`, `rbush`. peer: `rxjs`. 플러그인 클래스는 없다. `Univer` 런타임이 이 패키지다 (`packages/core/src/univer.ts`).

---

## 3. engines

| 디렉터리 | npm | 역할 | Facade | UI | core | render | formula | 근거 |
| --- | --- | --- | :---: | :---: | :---: | :---: | :---: | --- |
| `engine-formula` | `@univerjs/engine-formula` | 수식 파싱, 함수 등록, 의존성, 계산, 수식 편집 헬퍼 (`UniverFormulaEnginePlugin`) | 예 | 아니오 | 예 | 아니오 | 자기 | `package.json:2,4,30,88`; `README.md:7,13` |
| `engine-render` | `@univerjs/engine-render` | Docs/Sheets/Slides 캔버스 렌더 엔진. 레이아웃·프리미티브·스크롤·줌 (`UniverRenderEnginePlugin`) | 아니오 | 아니오 | 예 | 자기 | 아니오 | `package.json:2,4,73`; `README.md:7,13` |

`engine-formula` dependencies (`packages/engine-formula/package.json`): `@univerjs/core`, `@univerjs/rpc`, `@flatten-js/interval-tree`, `decimal.js`.  
`engine-render` dependencies (`packages/engine-render/package.json`): `@univerjs/core`, `@floating-ui/dom`, `@floating-ui/utils`, `franc-min`.

---

## 4. sheets\* (26)

로직 패키지와 `*-ui`가 쌍이다 (`docs/ISOMORPHIC.md`). `sheets-crosshair-highlight`만 UI 단일 패키지. `sheets-find-replace`는 공유 `find-replace` UI를 시트에 붙이는 로직이다.

| 디렉터리 | npm | 역할 | Facade | UI | core | render | formula | 근거 |
| --- | --- | --- | :---: | :---: | :---: | :---: | :---: | --- |
| `sheets` | `@univerjs/sheets` | UI와 독립인 스프레드시트 코어 모델·비즈니스 로직 (`UniverSheetsPlugin`) | 예 | 아니오 | 예 | 예 | 예 | `package.json:2,4,31,87-89`; `README.md:7` |
| `sheets-ui` | `@univerjs/sheets-ui` | 시트 메인 UI. 선택, 메뉴, 클립보드, 수식 입력줄, 렌더 인터랙션 (`UniverSheetsUIPlugin`) | 예 | 예 | 예 | 예 | 예 | `package.json:2,4,31,88,92-93`; `README.md:7,13` |
| `sheets-formula` | `@univerjs/sheets-formula` | 수식 엔진을 시트에 연결. 데이터 서비스·의존성·계산 (`UniverSheetsFormulaPlugin`, `UniverRemoteSheetsFormulaPlugin`) | 예 | 아니오 | 예 | 아니오 | 예 | `package.json:2,4,31,87-89`; `README.md:7` |
| `sheets-formula-ui` | `@univerjs/sheets-formula-ui` | 수식 입력, 제안, 하이라이트, 범위 선택 UI (`UniverSheetsFormulaUIPlugin`) | 예 | 예 | 예 | 예 | 예 | `package.json:2,4,31,89,93-94`; `README.md:7,13` |
| `sheets-numfmt` | `@univerjs/sheets-numfmt` | 숫자 서식 서비스·커맨드 (`UniverSheetsNumfmtPlugin`) | 예 | 아니오 | 예 | 아니오 | 예 | `package.json:2,4,30,81-82`; `README.md:7` |
| `sheets-numfmt-ui` | `@univerjs/sheets-numfmt-ui` | 숫자 서식 메뉴, 에디터, 미리보기 (`UniverSheetsNumfmtUIPlugin`) | 아니오 | 예 | 예 | 예 | 예 | `package.json:2,4,77,79-80`; `README.md:7,13` |
| `sheets-filter` | `@univerjs/sheets-filter` | 필터 모델·커맨드·서비스 (`UniverSheetsFilterPlugin`) | 예 | 아니오 | 예 | 예 | 예 | `package.json:2,4,30,87-89`; `README.md:7` |
| `sheets-filter-ui` | `@univerjs/sheets-filter-ui` | 필터 메뉴·패널 (`UniverSheetsFilterUIPlugin`) | 아니오 | 예 | 예 | 예 | 아니오 | `package.json:2,4,77,79`; `README.md:7,13` |
| `sheets-sort` | `@univerjs/sheets-sort` | 정렬 모델·커맨드·서비스 (`UniverSheetsSortPlugin`) | 예 | 아니오 | 예 | 아니오 | 예 | `package.json:2,4,30,78-79`; `README.md:7` |
| `sheets-sort-ui` | `@univerjs/sheets-sort-ui` | 정렬 메뉴·패널 (`UniverSheetsSortUIPlugin`) | 아니오 | 예 | 예 | 아니오 | 예 | `package.json:2,4,77,79`; `README.md:7,13` |
| `sheets-data-validation` | `@univerjs/sheets-data-validation` | 공유 유효성 규칙을 시트에 연결. 커맨드·서비스·Facade (`UniverSheetsDataValidationPlugin`) | 예 | 아니오 | 예 | 아니오 | 예 | `package.json:2,4,30,87-89`; `README.md:7` |
| `sheets-data-validation-ui` | `@univerjs/sheets-data-validation-ui` | 유효성 메뉴, 다이얼로그, 드롭다운 (`UniverSheetsDataValidationUIPlugin`) | 아니오 | 예 | 예 | 예 | 예 | `package.json:2,4,77,80-81`; `README.md:7,13` |
| `sheets-conditional-formatting` | `@univerjs/sheets-conditional-formatting` | 조건부 서식 모델·커맨드·계산 (`UniverSheetsConditionalFormattingPlugin`) | 예 | 아니오 | 예 | 예 | 예 | `package.json:2,4,30,88-90`; `README.md:7` |
| `sheets-conditional-formatting-ui` | `@univerjs/sheets-conditional-formatting-ui` | 조건부 서식 패널·메뉴 (`UniverSheetsConditionalFormattingUIPlugin`) | 아니오 | 예 | 예 | 예 | 예 | `package.json:2,4,77,79-80`; `README.md:7,13` |
| `sheets-hyper-link` | `@univerjs/sheets-hyper-link` | 시트 하이퍼링크 모델·커맨드 (`UniverSheetsHyperLinkPlugin`) | 예 | 아니오 | 예 | 아니오 | 예 | `package.json:2,4,30,87-89`; `README.md:7` |
| `sheets-hyper-link-ui` | `@univerjs/sheets-hyper-link-ui` | 하이퍼링크 메뉴, 다이얼로그, 렌더 (`UniverSheetsHyperLinkUIPlugin`) | 예 | 예 | 예 | 예 | 예 | `package.json:2,4,31,88,92-93`; `README.md:7,13` |
| `sheets-note` | `@univerjs/sheets-note` | 셀 노트 모델·커맨드 (`UniverSheetsNotePlugin`) | 예 | 아니오 | 예 | 아니오 | 아니오 | `package.json:2,4,30,81-82`; `README.md:7` |
| `sheets-note-ui` | `@univerjs/sheets-note-ui` | 셀 노트 보기/편집 UI (`UniverSheetsNoteUIPlugin`) | 예\* | 예 | 예 | 예 | 아니오 | `package.json:2,4,31,76,78`; `README.md:7,13` |
| `sheets-table` | `@univerjs/sheets-table` | 구조화 테이블 모델·커맨드 (`UniverSheetsTablePlugin`) | 예 | 아니오 | 예 | 아니오 | 예 | `package.json:2,4,30,87-88`; `README.md:7` |
| `sheets-table-ui` | `@univerjs/sheets-table-ui` | 테이블 메뉴·컨트롤 (`UniverSheetsTableUIPlugin`) | 예\* | 예 | 예 | 예 | 예 | `package.json:2,4,30,79,81-82`; `README.md:7,13` |
| `sheets-drawing` | `@univerjs/sheets-drawing` | 공유 드로잉 모델을 워크시트에 연결 (`UniverSheetsDrawingPlugin`) | 예 | 아니오 | 예 | 예 | 아니오 | `package.json:2,4,30,78-80`; `README.md:7` |
| `sheets-drawing-ui` | `@univerjs/sheets-drawing-ui` | 시트 드로잉 생성·선택·편집·보내기 UI (`UniverSheetsDrawingUIPlugin`) | 예 | 예 | 예 | 예 | 아니오 | `package.json:2,4,31,88,95`; `README.md:7,13` |
| `sheets-thread-comment` | `@univerjs/sheets-thread-comment` | 공유 스레드 댓글을 시트에 연결 (`UniverSheetsThreadCommentPlugin`) | 예 | 아니오 | 예 | 아니오 | 예 | `package.json:2,4,30,81-82`; `README.md:7` |
| `sheets-thread-comment-ui` | `@univerjs/sheets-thread-comment-ui` | 시트 스레드 댓글 UI (`UniverSheetsThreadCommentUIPlugin`) | 아니오 | 예 | 예 | 예 | 예 | `package.json:2,4,77,79-80`; `README.md:7,13` |
| `sheets-find-replace` | `@univerjs/sheets-find-replace` | 공유 찾기/바꾸기를 워크시트에 확장 (`UniverSheetsFindReplacePlugin`) | 예 | 아니오 | 예 | 예 | 아니오 | `package.json:2,4,30,81-82`; `README.md:7,13` |
| `sheets-crosshair-highlight` | `@univerjs/sheets-crosshair-highlight` | 활성 행/열 크로스헤어 하이라이트 (`UniverSheetsCrosshairHighlightPlugin`) | 예 | 예 | 예 | 예 | 아니오 | `package.json:2,4,31,88,90`; `README.md:7,13` |

`sheets`는 세 엔진 의존을 모두 직접 적는 유일한 제품 코어다 (`packages/sheets/package.json:87-89`: `@univerjs/core`, `@univerjs/engine-formula`, `@univerjs/engine-render`). `sheets-sort-ui`는 UI 패키지 중 `engine-render`를 의존하지 않는다 (`packages/sheets-sort-ui/package.json` dependencies에 없음).

---

## 5. docs\* (11)

| 디렉터리 | npm | 역할 | Facade | UI | core | render | formula | 근거 |
| --- | --- | --- | :---: | :---: | :---: | :---: | :---: | --- |
| `docs` | `@univerjs/docs` | UI와 독립인 문서 데이터 모델·리치 텍스트 연산 (`UniverDocsPlugin`) | 예 | 아니오 | 예 | 예 | 아니오 | `package.json:2,4,30,81-82`; `README.md:7` |
| `docs-ui` | `@univerjs/docs-ui` | Docs 편집 UI. 선택 렌더, 클립보드, 메뉴, 인터랙션 (`UniverDocsUIPlugin`) | 예 | 예 | 예 | 예 | 아니오 | `package.json:2,4,31,88,92`; `README.md:7,13` |
| `docs-drawing` | `@univerjs/docs-drawing` | 공유 드로잉 모델을 문서에 연결 (`UniverDocsDrawingPlugin`) | 예 | 아니오 | 예 | 아니오 | 아니오 | `package.json:2,4,30,78-80`; `README.md:7` |
| `docs-drawing-ui` | `@univerjs/docs-drawing-ui` | Docs 드로잉 생성·선택·편집 UI (`UniverDocsDrawingUIPlugin`) | 아니오 | 예 | 예 | 예 | 아니오 | `package.json:2,4,77,84`; `README.md:7,13` |
| `docs-hyper-link` | `@univerjs/docs-hyper-link` | Docs 하이퍼링크 모델·커맨드 (`UniverDocsHyperLinkPlugin`) | 아니오 | 아니오 | 예 | 아니오 | 아니오 | `package.json:2,4,67`; `README.md:7` |
| `docs-hyper-link-ui` | `@univerjs/docs-hyper-link-ui` | Docs 하이퍼링크 편집 UI (`UniverDocsHyperLinkUIPlugin`) | 아니오 | 예 | 예 | 예 | 아니오 | `package.json:2,4,77,82`; `README.md:7,13` |
| `docs-thread-comment` | `@univerjs/docs-thread-comment` | 문서 텍스트 범위에 고정된 댓글 모델·Facade. UI/렌더 의존 없음, Node 가능 (`UniverDocsThreadCommentPlugin`) | 예 | 아니오 | 예 | 아니오 | 아니오 | `package.json:2,4,28,77`; `README.md:7` |
| `docs-thread-comment-ui` | `@univerjs/docs-thread-comment-ui` | Docs 스레드 댓글 UI (`UniverDocsThreadCommentUIPlugin`) | 아니오 | 예 | 예 | 예 | 아니오 | `package.json:2,4,77,82`; `README.md:7,13` |
| `docs-toc` | `@univerjs/docs-toc` | 목차 삽입·갱신·삭제, FIELD 범위 조회 (`UniverDocsTocPlugin`) | 아니오 | 아니오 | 예 | 예 | 아니오 | `package.json:2,4,70,72`; `README.md:7` |
| `docs-toc-ui` | `@univerjs/docs-toc-ui` | 목차 Ribbon, 컨텍스트 메뉴, 갱신 다이얼로그 (`UniverDocsTocUIPlugin`) | 아니오 | 예 | 예 | 예 | 아니오 | `package.json:2,4,77,82`; `README.md:7,13` |
| `docs-find-replace` | `@univerjs/docs-find-replace` | 공유 찾기/바꾸기 UI를 Docs에 통합 (`UniverDocsFindReplacePlugin`) | 아니오 | 예 | 예 | 예 | 아니오 | `package.json:2,4,70,73`; `README.md:7,13` |

docs 계열은 **어느 패키지도 `engine-formula`를 의존하지 않는다.** `docs-drawing`의 `engine-render`는 `devDependencies`뿐이다 (`packages/docs-drawing/package.json:84`).

---

## 6. slides\* (2)

| 디렉터리 | npm | 역할 | Facade | UI | core | render | formula | 근거 |
| --- | --- | --- | :---: | :---: | :---: | :---: | :---: | --- |
| `slides` | `@univerjs/slides` | 프레젠테이션 코어 모델·서비스 (`UniverSlidesPlugin`) | 아니오 | 아니오 | 예 | 예 | 아니오 | `package.json:2,4,70-71`; `README.md:7,13` |
| `slides-ui` | `@univerjs/slides-ui` | 프레젠테이션 편집 UI (`UniverSlidesUIPlugin`) | 아니오 | 예 | 예 | 예 | 아니오 | `package.json:2,4,77,82`; `README.md:7,13` |

둘 다 Facade 엔트리가 없다. Slides preset도 `presets/packages/`에 없다.

---

## 7. drawing\* (2)

| 디렉터리 | npm | 역할 | Facade | UI | core | render | formula | 근거 |
| --- | --- | --- | :---: | :---: | :---: | :---: | :---: | --- |
| `drawing` | `@univerjs/drawing` | Docs/Sheets가 쓰는 공유 드로잉 모델·커맨드·서비스 (`UniverDrawingPlugin`) | 아니오 | 아니오 | 예 | 아니오 | 아니오 | `package.json:2,4,70`; `README.md:7,13` |
| `drawing-ui` | `@univerjs/drawing-ui` | 제품별 드로잉 UI가 쌓는 공통 드로잉 UI (`UniverDrawingUIPlugin`) | 아니오 | 예 | 예 | 예 | 아니오 | `package.json:2,4,77,80`; `README.md:7,13` |

제품 연결은 `docs-drawing` / `sheets-drawing`이 한다. 공유 레이어 자체에는 Facade가 없다.

---

## 8. ui / design / themes (6)

| 디렉터리 | npm | 역할 | Facade | UI | core | render | formula | 근거 |
| --- | --- | --- | :---: | :---: | :---: | :---: | :---: | --- |
| `design` | `@univerjs/design` | UI 패키지가 쓰는 공유 React 컴포넌트, 토큰, 스타일, 로케일 | 아니오 | 예 | 아니오 | 아니오 | 아니오 | `package.json:2,4`; `README.md:7,13` |
| `themes` | `@univerjs/themes` | 내장 테마 정의 (default, dark blue, green, orange, purple, red, yellow) | 아니오 | 아니오 | 아니오 | 아니오 | 아니오 | `package.json:2,4`; `README.md:7,13,28` |
| `ui` | `@univerjs/ui` | 워크벤치, 메뉴, 다이얼로그, 클립보드, Facade UI (`UniverUIPlugin`, `UniverMobileUIPlugin`) | 예 | 예 | 예 | 예 | 아니오 | `package.json:2,4,31,90,92`; `README.md:7,13,39-40` |
| `ui-adapter-vue3` | `@univerjs/ui-adapter-vue3` | Univer UI 서비스를 Vue 3에 적응 (`UniverVue3AdapterPlugin`) | 아니오 | 예 (어댑터) | 예 | 아니오 | 아니오 | `package.json:2,4,70`; `README.md:7,13` |
| `ui-adapter-web-component` | `@univerjs/ui-adapter-web-component` | Univer UI 서비스를 Web Component에 적응 (`UniverWebComponentAdapterPlugin`) | 아니오 | 예 (어댑터) | 예 | 아니오 | 아니오 | `package.json:2,4,67`; `README.md:7,13` |
| `thread-comment-ui` | `@univerjs/thread-comment-ui` | Docs/Sheets 댓글 UI가 공유하는 스레드 댓글 컴포넌트 (`UniverThreadCommentUIPlugin`) | 아니오 | 예 | 예 | 예 | 아니오 | `package.json:2,4,77,80`; `README.md:7,13` |

`design`은 `@univerjs/core`를 의존하지 않는다. Radix/CVA/cmdk/sonner는 이 패키지에만 있다 (`packages/design/package.json`). `ui` plugin 주석: workbench (menus, UI parts, notifications), copy paste, shortcut (`packages/ui/src/plugin.ts:88-92`).

---

## 9. network / rpc / protocol (4)

| 디렉터리 | npm | 역할 | Facade | UI | core | render | formula | 근거 |
| --- | --- | --- | :---: | :---: | :---: | :---: | :---: | --- |
| `protocol` | `@univerjs/protocol` | 공유 프로토콜 타입, 생성된 서비스 인터페이스, 데이터 컨트랙트 | 아니오 | 아니오 | 아니오 | 아니오 | 아니오 | `package.json:2,4`; `README.md:7,13` |
| `network` | `@univerjs/network` | 런타임 네트워크 추상화. 협업 연동용 (`UniverNetworkPlugin`) | 예 | 아니오 | 예 | 아니오 | 아니오 | `package.json:2,4,30,81`; `README.md:7,13` |
| `rpc` | `@univerjs/rpc` | 브라우저 메인 스레드 ↔ 워커 RPC (`UniverRPCMainThreadPlugin`, `UniverRPCWorkerThreadPlugin`) | 아니오 | 아니오 | 예 | 아니오 | 아니오 | `package.json:2,4,70`; `README.md:7` |
| `rpc-node` | `@univerjs/rpc-node` | Node.js 메인/워커 RPC (`UniverRPCNodeMainPlugin`, `UniverRPCNodeWorkerPlugin`) | 아니오 | 아니오 | 예 | 아니오 | 아니오 | `package.json:2,4,70`; `README.md:7` |

`protocol` dependencies는 `@grpc/grpc-js`뿐이다 (`packages/protocol/package.json`). OSS에 협업 서버는 없다.

---

## 10. misc (4)

telemetry, action-recorder, watermark, find-replace.

| 디렉터리 | npm | 역할 | Facade | UI | core | render | formula | 근거 |
| --- | --- | --- | :---: | :---: | :---: | :---: | --- | --- |
| `telemetry` | `@univerjs/telemetry` | 사용/진단 이벤트를 받을 텔레메트리 서비스 인터페이스 (`ITelemetryService`) | 아니오 | 아니오 | 예 | 아니오 | 아니오 | `package.json:2,4,67`; `README.md:7,13,28` |
| `action-recorder` | `@univerjs/action-recorder` | 사용자 액션을 기록하고 디버그·데모·재현을 위해 재생 (`UniverActionRecorderPlugin`) | 아니오 | 예 | 예 | 아니오 | 아니오 | `package.json:2,4,77`; `README.md:7,13` |
| `watermark` | `@univerjs/watermark` | 렌더 엔진으로 문서/시트에 워터마크를 그림 (`UniverWatermarkPlugin`) | 예 | 아니오 | 예 | 예 | 아니오 | `package.json:2,4,30,81-82`; `README.md:7,13` |
| `find-replace` | `@univerjs/find-replace` | 제품별 패키지가 확장하는 공유 찾기/바꾸기 서비스·UI (`UniverFindReplacePlugin`) | 아니오 | 예 | 예 | 예 | 아니오 | `package.json:2,4,77,79`; `README.md:7,13` |

`telemetry`는 플러그인 클래스가 없다. `src/services/telemetry.service.ts`의 토큰만 export한다. `action-recorder`는 `@univerjs/sheets` / `sheets-ui` / `sheets-filter`에 묶여 시트 워크벤치용이다 (`packages/action-recorder/package.json` dependencies).

---

## 11. Facade 엔트리 목록

소스 `package.json` `exports["./facade"]`가 있는 30개. 별표는 `publishConfig.exports`에 `./facade`가 **없는** 패키지.

| 패키지 | `exports["./facade"]` 줄 | publishConfig에도 있는지 |
| --- | ---: | :---: |
| `@univerjs/core` | `packages/core/package.json:30` | 예 (`:49`) |
| `@univerjs/engine-formula` | `packages/engine-formula/package.json:30` | 예 |
| `@univerjs/network` | `packages/network/package.json:30` | 예 |
| `@univerjs/ui` | `packages/ui/package.json:31` | 예 |
| `@univerjs/docs` | `packages/docs/package.json:30` | 예 |
| `@univerjs/docs-drawing` | `packages/docs-drawing/package.json:30` | 예 |
| `@univerjs/docs-thread-comment` | `packages/docs-thread-comment/package.json:28` | 예 |
| `@univerjs/docs-ui` | `packages/docs-ui/package.json:31` | 예 |
| `@univerjs/sheets` | `packages/sheets/package.json:31` | 예 |
| `@univerjs/sheets-ui` | `packages/sheets-ui/package.json:31` | 예 |
| `@univerjs/sheets-formula` | `packages/sheets-formula/package.json:31` | 예 |
| `@univerjs/sheets-formula-ui` | `packages/sheets-formula-ui/package.json:31` | 예 |
| `@univerjs/sheets-numfmt` | `packages/sheets-numfmt/package.json:30` | 예 |
| `@univerjs/sheets-filter` | `packages/sheets-filter/package.json:30` | 예 |
| `@univerjs/sheets-sort` | `packages/sheets-sort/package.json:30` | 예 |
| `@univerjs/sheets-data-validation` | `packages/sheets-data-validation/package.json:30` | 예 |
| `@univerjs/sheets-conditional-formatting` | `packages/sheets-conditional-formatting/package.json:30` | 예 |
| `@univerjs/sheets-hyper-link` | `packages/sheets-hyper-link/package.json:30` | 예 |
| `@univerjs/sheets-hyper-link-ui` | `packages/sheets-hyper-link-ui/package.json:31` | 예 |
| `@univerjs/sheets-note` | `packages/sheets-note/package.json:30` | 예 |
| `@univerjs/sheets-note-ui` | `packages/sheets-note-ui/package.json:31` | **아니오** |
| `@univerjs/sheets-table` | `packages/sheets-table/package.json:30` | 예 |
| `@univerjs/sheets-table-ui` | `packages/sheets-table-ui/package.json:30` | **아니오** |
| `@univerjs/sheets-drawing` | `packages/sheets-drawing/package.json:30` | 예 |
| `@univerjs/sheets-drawing-ui` | `packages/sheets-drawing-ui/package.json:31` | 예 |
| `@univerjs/sheets-thread-comment` | `packages/sheets-thread-comment/package.json:30` | 예 |
| `@univerjs/sheets-find-replace` | `packages/sheets-find-replace/package.json:30` | 예 |
| `@univerjs/sheets-crosshair-highlight` | `packages/sheets-crosshair-highlight/package.json:31` | 예 |
| `@univerjs/thread-comment` | `packages/thread-comment/package.json:29` | 예 |
| `@univerjs/watermark` | `packages/watermark/package.json:30` | 예 |

`sheets-note-ui` README Facade 열은 No (`packages/sheets-note-ui/README.md:13`)인데 소스 `exports`는 `./facade`를 연다 (`packages/sheets-note-ui/package.json:31`). `publishConfig.exports`에는 locale만 있고 facade가 없다 (`:43-60`). `sheets-table-ui`도 같다 (`packages/sheets-table-ui/package.json:30` vs `:39-56`, `README.md:13`).

사이드이펙트 import 패턴은 `import '@univerjs/<pkg>/facade'`다. `FUniver.extend`로 mixin한다 (`packages/core/src/facade/f-univer.ts`).

---

## 12. 60개 디렉터리 전체 목록

`packages/` 알파벳순. 위 표와 1:1이다.

1. `action-recorder`
2. `core`
3. `data-validation`
4. `design`
5. `docs`
6. `docs-drawing`
7. `docs-drawing-ui`
8. `docs-find-replace`
9. `docs-hyper-link`
10. `docs-hyper-link-ui`
11. `docs-thread-comment`
12. `docs-thread-comment-ui`
13. `docs-toc`
14. `docs-toc-ui`
15. `docs-ui`
16. `drawing`
17. `drawing-ui`
18. `engine-formula`
19. `engine-render`
20. `find-replace`
21. `network`
22. `protocol`
23. `rpc`
24. `rpc-node`
25. `sheets`
26. `sheets-conditional-formatting`
27. `sheets-conditional-formatting-ui`
28. `sheets-crosshair-highlight`
29. `sheets-data-validation`
30. `sheets-data-validation-ui`
31. `sheets-drawing`
32. `sheets-drawing-ui`
33. `sheets-filter`
34. `sheets-filter-ui`
35. `sheets-find-replace`
36. `sheets-formula`
37. `sheets-formula-ui`
38. `sheets-hyper-link`
39. `sheets-hyper-link-ui`
40. `sheets-note`
41. `sheets-note-ui`
42. `sheets-numfmt`
43. `sheets-numfmt-ui`
44. `sheets-sort`
45. `sheets-sort-ui`
46. `sheets-table`
47. `sheets-table-ui`
48. `sheets-thread-comment`
49. `sheets-thread-comment-ui`
50. `sheets-ui`
51. `slides`
52. `slides-ui`
53. `telemetry`
54. `themes`
55. `thread-comment`
56. `thread-comment-ui`
57. `ui`
58. `ui-adapter-vue3`
59. `ui-adapter-web-component`
60. `watermark`
