# Univer 라이브러리·빌드 툴체인 인벤토리

조사 대상: `/Users/yeonwoosung/Desktop/univer` (DreamNum Univer 클론, 버전 **1.0.2**, Apache-2.0).  
기준일: 2026-09-25.

이 문서는 클론 안의 **모든 `package.json` 84개**와 루트 워크스페이스 설정(`package.json`, `pnpm-workspace.yaml`, `turbo.json`, `verso.toml`, `vitest.workspace.ts`)을 전수 조사한 결과다. Univer 원본은 수정하지 않았다.

인용 경로는 클론 기준 상대 경로다.

---

## 0. 조사 범위

| 위치 | `package.json` 수 | 공개 여부 |
| --- | ---: | --- |
| 루트 `package.json` | 1 | private (`univer`) |
| `packages/*/package.json` | 60 | 전부 public `@univerjs/*` |
| `presets/package.json` | 1 | public `@univerjs/presets` |
| `presets/packages/*/package.json` | 17 | public `@univerjs/preset-*` |
| `common/{shared,debugger,storybook}` | 3 | private |
| `examples/package.json` | 1 | private `univer-examples` |
| `tests/formula-integration/package.json` | 1 | private `formula-integration-test` |
| **합계** | **84** | |

워크스페이스 선언: `pnpm-workspace.yaml` — `common/*`, `examples`, `presets`, `presets/packages/*`, `packages/*`, `tests/*`.

---

## 1. 서드파티 런타임 의존성

제품 코드가 실제로 가져가는 서드파티는 **극소수 패키지에 집중**되어 있다. 60개 `packages/*` 중 `dependencies`에 `@univerjs/*`가 아닌 이름을 적는 패키지는 **5개**뿐이다: `core`, `engine-formula`, `engine-render`, `design`, `protocol`. `ui`는 DI 라이브러리 `@wendellhu/redi`만 추가한다.

`rxjs`와 `react`/`react-dom`은 거의 전부 **peerDependencies**다. 런타임 `dependencies`로 직접 박는 곳은 예제 앱뿐이다.

아래 표의 “소비 패키지”는 해당 이름을 `dependencies`에 선언한 워크스페이스 패키지다. 버전은 그 `package.json`에 적힌 specifier다.

### 1.1 코어 런타임 (DI · OT · 공간 인덱스 · 유틸)

출처: `packages/core/package.json`.

| 패키지 | 버전 | 역할 | 소비 패키지 |
| --- | --- | --- | --- |
| `@wendellhu/redi` | `1.1.3` | DI 컨테이너 (Wendell Hu / Univer 저자) | `@univerjs/core`, `@univerjs/ui` (`packages/ui/package.json`). `@univerjs/presets`는 **devDependency**로만 1.1.3 (`presets/package.json`) |
| `lodash-es` | `^4.18.1` | 유틸 | `@univerjs/core` |
| `ot-json1` | `^1.0.2` | JSON OT (실시간 편집 변환) | `@univerjs/core` |
| `fast-diff` | `1.3.0` | 텍스트 diff (OT 보조) | `@univerjs/core` |
| `rbush` | `^4.0.1` | 2D R-tree (박스 공간 인덱스) | `@univerjs/core` |
| `kdbush` | `^4.1.0` | 점 공간 인덱스 | `@univerjs/core` |
| `async-lock` | `^1.4.1` | 비동기 뮤텍스 | `@univerjs/core` |
| `rxjs` | peer `>=7.0.0` / 예제 `^7.8.2` | 스트림. 플러그인은 peer, 예제만 직접 의존 | 거의 전 플러그인 peer. 직접 `dependencies`: `univer-examples` (`examples/package.json`) |

`core`의 타입 전용 개발 의존: `@types/async-lock ^1.4.2`, `@types/lodash-es ^4.17.12`, `@types/rbush ^4.0.0` (`packages/core/package.json`).

### 1.2 수식 엔진

출처: `packages/engine-formula/package.json`.

| 패키지 | 버전 | 역할 | 소비 패키지 |
| --- | --- | --- | --- |
| `decimal.js` | `^10.6.0` | 임의 정밀 십진 연산 | `@univerjs/engine-formula` |
| `@flatten-js/interval-tree` | `1.1.3` | 구간 트리 (의존 범위 / 재계산) | `@univerjs/engine-formula` |

파서·함수 구현은 자체 코드(`packages/engine-formula` 약 1,500+ TS 파일)다. HyperFormula, Formula.js, ExcelJS, SheetJS, mathjs, numeral, numbro **없음**.

### 1.3 렌더 / 캔버스

출처: `packages/engine-render/package.json`.

| 패키지 | 버전 | 역할 | 소비 패키지 |
| --- | --- | --- | --- |
| `@floating-ui/dom` | `^1.8.0` | 플로팅 위치 계산 | `@univerjs/engine-render` |
| `@floating-ui/utils` | `^0.2.12` | floating-ui 유틸 | `@univerjs/engine-render` |
| `franc-min` | `^6.2.0` | 언어 감지 (하이픈 패턴 등) | `@univerjs/engine-render` |

캔버스 자체는 브라우저 `CanvasRenderingContext2D` 위에 직접 그린다. PixiJS, Three.js, Konva, Fabric, Skia, `node-canvas` **없음**.

테스트 전용:

| 패키지 | 버전 | 소비 패키지 |
| --- | --- | --- |
| `jest-canvas-mock` | `^2.5.8` / `^2.5.2` | `engine-render` (`^2.5.8`, `packages/engine-render/package.json`), `docs-ui` (`^2.5.2`, `packages/docs-ui/package.json`) |
| `rollup-plugin-polyfill-node` | `^0.13.0` | `engine-render` **devDependency** |
| `jsdom` | `^29.1.1` | `docs-ui` **devDependency** (`packages/docs-ui/package.json`) — 공유 vitest는 기본 `happy-dom` |

`engine-render` `prepare`는 `node --experimental-strip-types ./scripts/generate-hyphen-pattern-loaders.mts`로 하이픈 패턴 로더를 생성한다.

### 1.4 UI (React 디자인 시스템)

출처: `packages/design/package.json`. Radix/CVA/cmdk/sonner는 **design 한 패키지**에만 선언된다. 다른 UI 플러그인은 `@univerjs/design`을 통해 간접 사용한다.

| 패키지 | 버전 | 역할 | 소비 패키지 |
| --- | --- | --- | --- |
| `@radix-ui/react-dialog` | `^1.1.23` | 다이얼로그 | `@univerjs/design` |
| `@radix-ui/react-direction` | `^1.1.4` | RTL/LTR | `@univerjs/design` |
| `@radix-ui/react-dropdown-menu` | `^2.1.24` | 드롭다운 | `@univerjs/design` |
| `@radix-ui/react-hover-card` | `^1.1.23` | 호버 카드 | `@univerjs/design` |
| `@radix-ui/react-popover` | `^1.1.23` | 팝오버 | `@univerjs/design` |
| `@radix-ui/react-separator` | `^1.1.15` | 구분선 | `@univerjs/design` |
| `@radix-ui/react-slot` | `^1.3.3` | asChild 슬롯 | `@univerjs/design` |
| `class-variance-authority` | `^0.7.1` | variant 클래스 | `@univerjs/design` |
| `cmdk` | `1.1.1` | 커맨드 팔레트 (Command) | `@univerjs/design` |
| `sonner` | `^2.0.8` | 토스트 | `@univerjs/design` |
| `react` | 예제 `19.3.0` / 플러그인 peer | UI | `univer-examples`만 runtime `dependencies`. 플러그인은 peer |
| `react-dom` | 예제 `19.3.0` / 플러그인 peer | DOM 렌더러 | 동일 |

`design` `prepare` (`node scripts/generate-clsx.mts`)는 **`tailwind-merge` 설정에서 clsx 호환 테이블을 생성**한다. `clsx` npm 패키지는 의존성에 없다. `tailwind-merge 2.6.0`은 `design`의 **devDependency**.

UI 테스트:

| 패키지 | 버전 | 소비 패키지 |
| --- | --- | --- |
| `@testing-library/react` | `^16.3.3` | `design`, `docs-drawing-ui`, `ui` |
| `@testing-library/jest-dom` | `7.0.1` | `design`만 |

### 1.5 프로토콜 / RPC

출처: `packages/protocol/package.json`.

| 패키지 | 버전 | 역할 | 소비 패키지 |
| --- | --- | --- | --- |
| `@grpc/grpc-js` | `^1.14.4` | gRPC 클라이언트 타입/런타임 | `@univerjs/protocol` |

`protobufjs`는 어느 `package.json`에도 **직접 선언되지 않는다**. `pnpm-workspace.yaml` `allowBuilds.protobufjs: false`로 보아 `@grpc/grpc-js` 전이가 끌어올 수 있으나 네이티브 빌드는 끈다. `google-protobuf`도 없음.

`@univerjs/network`, `@univerjs/rpc`, `@univerjs/rpc-node`는 서드파티 HTTP/WS 클라이언트가 없다 (`packages/network/package.json`, `packages/rpc/package.json`, `packages/rpc-node/package.json`). fetch/MessageChannel/Node worker를 자체 구현한다.

### 1.6 클론 외부 `@univerjs` 패키지 (이 레포에 소스 없음)

워크스페이스에 패키지 폴더가 없고 npm에서 가져온다.

| 패키지 | 버전 | 종류 | 소비 패키지 |
| --- | --- | --- | --- |
| `@univerjs/icons` | `1.43.1` (고정) | 런타임 아이콘 | 아래 24개 |
| `@univerjs/icons-svg` | `^1.43.1` | 빌드 타임 SVG | `@univerjs-infra/shared` (`common/shared/package.json` dev), `@univerjs/sheets-conditional-formatting` (`packages/sheets-conditional-formatting/package.json` dev, `prepare`: `scripts/build-icons.mts`) |

`@univerjs/icons@1.43.1` runtime 소비:

- `common/debugger/package.json`
- `examples/package.json`
- `packages/action-recorder/package.json`
- `packages/design/package.json`
- `packages/docs-drawing-ui/package.json`
- `packages/docs-hyper-link-ui/package.json`
- `packages/docs-thread-comment-ui/package.json`
- `packages/docs-ui/package.json`
- `packages/drawing-ui/package.json`
- `packages/find-replace/package.json`
- `packages/sheets-conditional-formatting-ui/package.json`
- `packages/sheets-crosshair-highlight/package.json`
- `packages/sheets-data-validation-ui/package.json`
- `packages/sheets-filter-ui/package.json`
- `packages/sheets-formula-ui/package.json`
- `packages/sheets-hyper-link-ui/package.json`
- `packages/sheets-note-ui/package.json`
- `packages/sheets-numfmt-ui/package.json`
- `packages/sheets-sort-ui/package.json`
- `packages/sheets-table-ui/package.json`
- `packages/sheets-thread-comment-ui/package.json`
- `packages/sheets-ui/package.json`
- `packages/slides-ui/package.json`
- `packages/thread-comment-ui/package.json`
- `packages/ui/package.json`

### 1.7 예제 앱 런타임

출처: `examples/package.json`.

| 패키지 | 버전 |
| --- | --- |
| `react` | `19.3.0` (고정, 루트 override와 동일) |
| `react-dom` | `19.3.0` |
| `rxjs` | `^7.8.2` |

나머지는 전부 workspace `@univerjs/*` / `@univerjs/preset-*`.

### 1.8 private 인프라가 `dependencies`에 올려 둔 도구 (제품 런타임 아님)

`@univerjs-infra/shared` (`common/shared/package.json`)는 private 빌드 패키지인데 도구를 `dependencies`에 둔다. 앱에 실리지 않는다.

| 패키지 | 버전 | 용도 |
| --- | --- | --- |
| `tsdown` | `^0.23.0` | 패키지 번들러 |
| `@tsdown/css` | `^0.23.0` | tsdown CSS 플러그인 |
| `unplugin-vue` | `^7.2.0` | Vue SFC (adapter 빌드) |
| `javascript-obfuscator` | `^5.7.0` | `@univerjs-pro/*` 이름일 때만 UMD/모듈 난독화 (`common/shared/tsdown/index.ts`) |
| `sort-keys` | `^6.0.1` | publish manifest 키 정렬 |
| `vitest` | `^5.0.0` | 공유 테스트 설정 |
| `@vitest/coverage-istanbul` | `^5.0.0` | coverage provider |
| `happy-dom` | `20.14.5` (고정) | vitest 기본 환경 |
| `tailwindcss` | `3.4.18` | 공유 Tailwind preset |
| `tailwind-scrollbar` | `^3` | 스크롤바 유틸리티 |
| `autoprefixer` | `^10.6.0` | PostCSS |
| `postcss-preset-env` | `^11.5.3` | PostCSS |
| `postcss-replace` | `^2.0.1` | CSS 토큰 치환 |
| `@typescript-eslint/parser` | `^8.65.0` | ESLint TS 파서 |
| `eslint-plugin-better-tailwindcss` | `^4.7.0` | Tailwind 클래스 린트 |
| `eslint-plugin-header` | `^3.1.1` | 라이선스 헤더 |
| `eslint-plugin-no-barrel-import` | `^0.0.2` | barrel import 금지 |
| `eslint-plugin-no-penetrating-import` | `^0.0.1` | 깊은 내부 import 금지 |

`@univerjs/storybook` (`common/storybook/package.json`) 역시 Storybook 스택을 `dependencies`에 둔다.

| 패키지 | 버전 |
| --- | --- |
| `storybook` | `^10.4.6` |
| `@storybook/react` | `^10.4.6` |
| `@storybook/react-webpack5` | `^10.4.6` |
| `@storybook/addon-docs` | `^10.4.6` |
| `@storybook/addon-links` | `^10.4.6` |
| `@storybook/addon-styling-webpack` | `^3.0.2` |
| `@storybook/addon-webpack5-compiler-swc` | `^4.0.3` |
| `@storybook/icons` | `^2.1.0` |
| `@chromatic-com/storybook` | `^5.2.1` |
| `storybook-addon-swc` | `^1.2.0` |
| `css-loader` | `^7.1.4` |
| `style-loader` | `^4.0.0` |
| `postcss-loader` | `^8.2.1` |
| `tsconfig-paths-webpack-plugin` | `^4.2.0` |
| `typescript` | `^6.0.3` |

Storybook 경로가 이 클론에서 **Webpack 5 + SWC**를 쓰는 유일한 곳이다. 제품 패키지 빌드는 tsdown.

---

## 2. 내부 `@univerjs/*` 그래프

모든 워크스페이스 내부 의존은 `workspace:*`. 버전 핀은 `@univerjs/icons`처럼 **레포 밖 패키지**에만 있다.

커널 세 패키지:

```
@univerjs/themes          (의존 없음)
@univerjs/protocol        → @grpc/grpc-js
@univerjs/core            → protocol, themes, redi, lodash-es, ot-json1, fast-diff, rbush, kdbush, async-lock
@univerjs/engine-render   → core
@univerjs/engine-formula  → core, rpc
@univerjs/rpc             → core
```

`core` 자신이 런타임으로 가리키는 워크스페이스 패키지는 `protocol`과 `themes`뿐이다 (`packages/core/package.json`).

### 2.1 `@univerjs/core`를 런타임 `dependencies`로 갖는 패키지

`packages/*`에서 **core를 직접 의존하지 않는 것**: `design`, `protocol`, `themes` (그리고 `core` 자신). 프리셋 다수는 플러그인을 묶기만 하고 core는 **devDependency**로만 둔다.

**직접 runtime 의존 (경로 포함):**

| 소비 패키지 | `package.json` |
| --- | --- |
| `@univerjs/action-recorder` | `packages/action-recorder/package.json` |
| `@univerjs/data-validation` | `packages/data-validation/package.json` |
| `@univerjs/docs` | `packages/docs/package.json` |
| `@univerjs/docs-drawing` | `packages/docs-drawing/package.json` |
| `@univerjs/docs-drawing-ui` | `packages/docs-drawing-ui/package.json` |
| `@univerjs/docs-find-replace` | `packages/docs-find-replace/package.json` |
| `@univerjs/docs-hyper-link` | `packages/docs-hyper-link/package.json` |
| `@univerjs/docs-hyper-link-ui` | `packages/docs-hyper-link-ui/package.json` |
| `@univerjs/docs-thread-comment` | `packages/docs-thread-comment/package.json` |
| `@univerjs/docs-thread-comment-ui` | `packages/docs-thread-comment-ui/package.json` |
| `@univerjs/docs-toc` | `packages/docs-toc/package.json` |
| `@univerjs/docs-toc-ui` | `packages/docs-toc-ui/package.json` |
| `@univerjs/docs-ui` | `packages/docs-ui/package.json` |
| `@univerjs/drawing` | `packages/drawing/package.json` |
| `@univerjs/drawing-ui` | `packages/drawing-ui/package.json` |
| `@univerjs/engine-formula` | `packages/engine-formula/package.json` |
| `@univerjs/engine-render` | `packages/engine-render/package.json` |
| `@univerjs/find-replace` | `packages/find-replace/package.json` |
| `@univerjs/network` | `packages/network/package.json` |
| `@univerjs/rpc` | `packages/rpc/package.json` |
| `@univerjs/rpc-node` | `packages/rpc-node/package.json` |
| `@univerjs/sheets` | `packages/sheets/package.json` |
| `@univerjs/sheets-conditional-formatting` | `packages/sheets-conditional-formatting/package.json` |
| `@univerjs/sheets-conditional-formatting-ui` | `packages/sheets-conditional-formatting-ui/package.json` |
| `@univerjs/sheets-crosshair-highlight` | `packages/sheets-crosshair-highlight/package.json` |
| `@univerjs/sheets-data-validation` | `packages/sheets-data-validation/package.json` |
| `@univerjs/sheets-data-validation-ui` | `packages/sheets-data-validation-ui/package.json` |
| `@univerjs/sheets-drawing` | `packages/sheets-drawing/package.json` |
| `@univerjs/sheets-drawing-ui` | `packages/sheets-drawing-ui/package.json` |
| `@univerjs/sheets-filter` | `packages/sheets-filter/package.json` |
| `@univerjs/sheets-filter-ui` | `packages/sheets-filter-ui/package.json` |
| `@univerjs/sheets-find-replace` | `packages/sheets-find-replace/package.json` |
| `@univerjs/sheets-formula` | `packages/sheets-formula/package.json` |
| `@univerjs/sheets-formula-ui` | `packages/sheets-formula-ui/package.json` |
| `@univerjs/sheets-hyper-link` | `packages/sheets-hyper-link/package.json` |
| `@univerjs/sheets-hyper-link-ui` | `packages/sheets-hyper-link-ui/package.json` |
| `@univerjs/sheets-note` | `packages/sheets-note/package.json` |
| `@univerjs/sheets-note-ui` | `packages/sheets-note-ui/package.json` |
| `@univerjs/sheets-numfmt` | `packages/sheets-numfmt/package.json` |
| `@univerjs/sheets-numfmt-ui` | `packages/sheets-numfmt-ui/package.json` |
| `@univerjs/sheets-sort` | `packages/sheets-sort/package.json` |
| `@univerjs/sheets-sort-ui` | `packages/sheets-sort-ui/package.json` |
| `@univerjs/sheets-table` | `packages/sheets-table/package.json` |
| `@univerjs/sheets-table-ui` | `packages/sheets-table-ui/package.json` |
| `@univerjs/sheets-thread-comment` | `packages/sheets-thread-comment/package.json` |
| `@univerjs/sheets-thread-comment-ui` | `packages/sheets-thread-comment-ui/package.json` |
| `@univerjs/sheets-ui` | `packages/sheets-ui/package.json` |
| `@univerjs/slides` | `packages/slides/package.json` |
| `@univerjs/slides-ui` | `packages/slides-ui/package.json` |
| `@univerjs/telemetry` | `packages/telemetry/package.json` |
| `@univerjs/thread-comment` | `packages/thread-comment/package.json` |
| `@univerjs/thread-comment-ui` | `packages/thread-comment-ui/package.json` |
| `@univerjs/ui` | `packages/ui/package.json` |
| `@univerjs/ui-adapter-vue3` | `packages/ui-adapter-vue3/package.json` |
| `@univerjs/ui-adapter-web-component` | `packages/ui-adapter-web-component/package.json` |
| `@univerjs/watermark` | `packages/watermark/package.json` |
| `@univerjs/presets` | `presets/package.json` |
| `@univerjs/preset-docs-drawing` | `presets/packages/preset-docs-drawing/package.json` |
| `@univerjs/preset-sheets-drawing` | `presets/packages/preset-sheets-drawing/package.json` |
| `@univerjs/debugger` | `common/debugger/package.json` |
| `@univerjs/storybook` | `common/storybook/package.json` |
| `univer-examples` | `examples/package.json` |
| `formula-integration-test` | `tests/formula-integration/package.json` |

**devDependency로만 core를 갖는 프리셋 (15):**  
`preset-docs-core`, `preset-docs-hyper-link`, `preset-docs-node-core`, `preset-docs-thread-comment`, `preset-sheets-conditional-formatting`, `preset-sheets-core`, `preset-sheets-data-validation`, `preset-sheets-filter`, `preset-sheets-find-replace`, `preset-sheets-hyper-link`, `preset-sheets-node-core`, `preset-sheets-note`, `preset-sheets-sort`, `preset-sheets-table`, `preset-sheets-thread-comment`. 각 `presets/packages/<name>/package.json`.

### 2.2 `@univerjs/engine-render` 런타임 의존

렌더 엔진은 docs/sheets/slides UI와 문서 모델이 직접 가져간다. 수식 워커·Node 프리셋은 렌더를 안 넣는다.

**runtime (37):**

- 문서: `docs`, `docs-drawing-ui`, `docs-find-replace`, `docs-hyper-link-ui`, `docs-thread-comment-ui`, `docs-toc`, `docs-toc-ui`, `docs-ui`
- 시트: `sheets`, `sheets-conditional-formatting`, `sheets-conditional-formatting-ui`, `sheets-crosshair-highlight`, `sheets-data-validation-ui`, `sheets-drawing`, `sheets-drawing-ui`, `sheets-filter`, `sheets-filter-ui`, `sheets-find-replace`, `sheets-formula-ui`, `sheets-hyper-link-ui`, `sheets-note-ui`, `sheets-numfmt-ui`, `sheets-table-ui`, `sheets-thread-comment-ui`, `sheets-ui`
- 슬라이드: `slides`, `slides-ui`
- 공통 UI: `drawing-ui`, `find-replace`, `thread-comment-ui`, `ui`, `watermark`
- 프리셋: `presets`, `preset-docs-core`, `preset-sheets-core`
- 기타: `debugger`, `univer-examples`

경로 패턴: `packages/<name>/package.json`, 프리셋은 `presets/package.json` 및 `presets/packages/preset-{docs,sheets}-core/package.json`.

**devDependency로만:** `docs-drawing`, `sheets-formula`, `sheets-note`, `sheets-table`.

### 2.3 `@univerjs/engine-formula` 런타임 의존

수식은 **시트 도메인 + 프리셋 코어**에 묶인다. docs 플러그인 본체(`packages/docs*`)는 formula를 직접 의존하지 않지만, `preset-docs-core` / `preset-docs-node-core`가 엔진을 넣는다.

**runtime (25):**

- 시트 모델/기능: `sheets`, `sheets-conditional-formatting`, `sheets-conditional-formatting-ui`, `sheets-data-validation`, `sheets-data-validation-ui`, `sheets-filter`, `sheets-formula`, `sheets-formula-ui`, `sheets-hyper-link`, `sheets-hyper-link-ui`, `sheets-numfmt`, `sheets-numfmt-ui`, `sheets-sort`, `sheets-sort-ui`, `sheets-table`, `sheets-table-ui`, `sheets-thread-comment`, `sheets-thread-comment-ui`, `sheets-ui`
- 프리셋: `presets`, `preset-docs-core`, `preset-docs-node-core`, `preset-sheets-core`, `preset-sheets-node-core`
- 테스트: `formula-integration-test`

**devDependency로만:** `sheets-note` (`packages/sheets-note/package.json`).

### 2.4 패키지별 내부 runtime 인접 리스트 (`packages/*` + 주요 프리셋)

서드파티는 생략. `@univerjs/icons`는 외부 패키지라 여기 넣지 않는다.

| 패키지 | runtime `@univerjs/*` |
| --- | --- |
| `core` | `protocol`, `themes` |
| `protocol` | (없음) |
| `themes` | (없음) |
| `design` | (icons만 외부) |
| `engine-render` | `core` |
| `engine-formula` | `core`, `rpc` |
| `rpc` | `core` |
| `rpc-node` | `core`, `rpc` |
| `network` | `core` |
| `telemetry` | `core` |
| `docs` | `core`, `engine-render`, `protocol`, `rpc` |
| `docs-ui` | `core`, `design`, `docs`, `drawing`, `engine-render`, `protocol`, `ui` |
| `docs-drawing` | `core`, `docs`, `drawing` |
| `docs-drawing-ui` | `core`, `design`, `docs`, `docs-drawing`, `docs-ui`, `drawing`, `drawing-ui`, `engine-render`, `ui` |
| `docs-find-replace` | `core`, `docs`, `docs-ui`, `engine-render`, `find-replace`, `ui` |
| `docs-hyper-link` | `core` |
| `docs-hyper-link-ui` | `core`, `design`, `docs`, `docs-hyper-link`, `docs-ui`, `engine-render`, `protocol`, `ui` |
| `docs-thread-comment` | `core`, `docs`, `thread-comment` |
| `docs-thread-comment-ui` | `core`, `docs`, `docs-thread-comment`, `docs-ui`, `drawing`, `engine-render`, `protocol`, `thread-comment`, `thread-comment-ui`, `ui` |
| `docs-toc` | `core`, `docs`, `engine-render` |
| `docs-toc-ui` | `core`, `design`, `docs`, `docs-toc`, `docs-ui`, `engine-render`, `protocol`, `ui` |
| `drawing` | `core` |
| `drawing-ui` | `core`, `design`, `drawing`, `engine-render`, `ui` |
| `find-replace` | `core`, `design`, `engine-render`, `ui` |
| `sheets` | `core`, `engine-formula`, `engine-render`, `protocol`, `rpc` |
| `sheets-ui` | `core`, `design`, `docs`, `docs-ui`, `engine-formula`, `engine-render`, `protocol`, `sheets`, `telemetry`, `ui` |
| `sheets-formula` | `core`, `docs`, `engine-formula`, `rpc`, `sheets` |
| `sheets-formula-ui` | `core`, `design`, `docs`, `docs-ui`, `engine-formula`, `engine-render`, `sheets`, `sheets-formula`, `sheets-ui`, `ui` |
| `sheets-numfmt` | `core`, `engine-formula`, `sheets` |
| `sheets-numfmt-ui` | `core`, `design`, `engine-formula`, `engine-render`, `sheets`, `sheets-numfmt`, `sheets-ui`, `ui` |
| `sheets-filter` | `core`, `engine-formula`, `engine-render`, `rpc`, `sheets` |
| `sheets-filter-ui` | `core`, `design`, `engine-render`, `rpc`, `sheets`, `sheets-filter`, `sheets-ui`, `ui` |
| `sheets-sort` | `core`, `engine-formula`, `sheets` |
| `sheets-sort-ui` | `core`, `design`, `engine-formula`, `sheets`, `sheets-sort`, `sheets-ui`, `ui` |
| `sheets-table` | `core`, `engine-formula`, `sheets` |
| `sheets-table-ui` | `core`, `design`, `engine-formula`, `engine-render`, `sheets`, `sheets-formula-ui`, `sheets-sort`, `sheets-table`, `sheets-ui`, `ui` |
| `sheets-data-validation` | `core`, `data-validation`, `engine-formula`, `protocol`, `sheets`, `sheets-formula` |
| `sheets-data-validation-ui` | `core`, `data-validation`, `design`, `engine-formula`, `engine-render`, `sheets`, `sheets-data-validation`, `sheets-formula-ui`, `sheets-numfmt`, `sheets-ui`, `ui` |
| `data-validation` | `core` |
| `sheets-conditional-formatting` | `core`, `engine-formula`, `engine-render`, `sheets` |
| `sheets-conditional-formatting-ui` | `core`, `design`, `engine-formula`, `engine-render`, `sheets`, `sheets-conditional-formatting`, `sheets-formula`, `sheets-formula-ui`, `sheets-ui`, `ui` |
| `sheets-drawing` | `core`, `drawing`, `engine-render`, `sheets` |
| `sheets-drawing-ui` | `core`, `design`, `docs`, `docs-drawing`, `docs-ui`, `drawing`, `drawing-ui`, `engine-render`, `sheets`, `sheets-drawing`, `sheets-ui`, `ui` |
| `sheets-find-replace` | `core`, `engine-render`, `find-replace`, `sheets`, `sheets-ui` |
| `sheets-hyper-link` | `core`, `docs`, `engine-formula`, `sheets` |
| `sheets-hyper-link-ui` | `core`, `design`, `docs`, `docs-ui`, `engine-formula`, `engine-render`, `sheets`, `sheets-data-validation`, `sheets-formula-ui`, `sheets-hyper-link`, `sheets-ui`, `ui` |
| `sheets-note` | `core`, `sheets` |
| `sheets-note-ui` | `core`, `design`, `engine-render`, `sheets`, `sheets-note`, `sheets-ui`, `ui` |
| `sheets-thread-comment` | `core`, `engine-formula`, `sheets`, `thread-comment` |
| `sheets-thread-comment-ui` | `core`, `drawing`, `engine-formula`, `engine-render`, `sheets`, `sheets-thread-comment`, `sheets-ui`, `thread-comment`, `thread-comment-ui`, `ui` |
| `sheets-crosshair-highlight` | `core`, `design`, `engine-render`, `sheets`, `sheets-ui`, `ui` |
| `slides` | `core`, `engine-render` |
| `slides-ui` | `core`, `design`, `docs`, `docs-ui`, `drawing`, `engine-render`, `slides`, `ui` |
| `thread-comment` | `core` |
| `thread-comment-ui` | `core`, `design`, `docs-ui`, `engine-render`, `thread-comment`, `ui` |
| `ui` | `core`, `design`, `engine-render`, `protocol` |
| `ui-adapter-vue3` | `core`, `ui` |
| `ui-adapter-web-component` | `core`, `ui` |
| `watermark` | `core`, `engine-render` |
| `action-recorder` | `core`, `design`, `sheets`, `sheets-filter`, `sheets-ui`, `ui` |
| `preset-sheets-core` | `design`, `docs`, `docs-ui`, `engine-formula`, `engine-render`, `network`, `rpc`, `sheets`, `sheets-formula`, `sheets-formula-ui`, `sheets-numfmt`, `sheets-numfmt-ui`, `sheets-ui`, `ui` |
| `preset-sheets-node-core` | `docs`, `engine-formula`, `rpc-node`, `sheets`, `sheets-data-validation`, `sheets-drawing`, `sheets-filter`, `sheets-formula`, `sheets-hyper-link`, `sheets-numfmt`, `sheets-sort`, `sheets-thread-comment`, `thread-comment` |
| `preset-docs-core` | `design`, `docs`, `docs-ui`, `engine-formula`, `engine-render`, `network`, `ui` |
| `preset-docs-node-core` | `docs`, `docs-drawing`, `docs-hyper-link`, `engine-formula`, `rpc-node`, `thread-comment` |
| `presets` | `core`, `drawing`, `engine-formula`, `engine-render`, `network`, `protocol`, `rpc`, `telemetry`, `themes` |

기능 프리셋은 해당 `*-ui` 쌍만 묶는다. 예: `preset-sheets-filter` → `sheets-filter` + `sheets-filter-ui` (`presets/packages/preset-sheets-filter/package.json`). 전체 17개 프리셋 목록은 §0.

관찰:

- `sheets-ui`가 `docs`/`docs-ui`를 끌어 **시트 안에 문서 편집기**(리치 셀)가 들어간다.
- `sheets-drawing-ui`도 `docs`/`docs-drawing`/`docs-ui`를 끌어 시트 도형과 문서 도형이 공유된다.
- Node 프리셋은 `engine-render`/`ui`/`design` 없이 `rpc-node` + 모델 플러그인만 담는다.

---

## 3. Peer dependencies

`peerDependenciesMeta`는 **어느 패키지에도 없다** (전부 필수 peer).

### 3.1 선언 패턴

공통 React specifier: `^16.9.0 || ^17.0.0 || ^18.0.0 || ^19.0.0 || ^19.0.0-rc`.  
공통 RxJS specifier: `>=7.0.0`.

| 패턴 | 패키지 수 | 대상 |
| --- | ---: | --- |
| `rxjs`만 | 26 | 모델/엔진/Node 프리셋. `core`, `engine-formula`, `engine-render`, `docs`, `sheets`, `rpc`, `rpc-node`, `network`, `preset-docs-node-core`, `preset-sheets-node-core` 등 |
| `react` + `rxjs` | 23 | 대부분의 `*-ui`와 `action-recorder`, `debugger`. **`react-dom` peer 없음** |
| `react` + `react-dom` + `rxjs` | 18 | `ui`, `sheets-formula-ui`, `sheets-table-ui`, 브라우저 프리셋 전부 |
| `react` + `react-dom` (rxjs 없음) | 1 | `design` (`packages/design/package.json`) |
| `vue >=3.0.0` | 1 | `ui-adapter-vue3` (`packages/ui-adapter-vue3/package.json`) |
| peer 없음 | 15 | `protocol`, `themes`, `telemetry`, `sheets-sort`, `sheets-drawing`, `docs-drawing`, `docs-hyper-link`, `docs-thread-comment`, `ui-adapter-web-component`, `presets`, 루트/예제/shared/storybook/formula-integration |

`sheets-sort`는 `engine-formula`를 쓰면서도 rxjs peer가 없다 (`packages/sheets-sort/package.json`). `telemetry`도 core만 있고 peer 없음.

### 3.2 워크스페이스가 실제로 까는 버전

루트 `package.json` + `pnpm-workspace.yaml` overrides:

```
react = 19.3.0
react-dom = 19.3.0
@types/react = 19.3.0
@types/react-dom = 19.3.0
```

플러그인 `devDependencies`는 관례적으로 `react`/`react-dom` **18.3.1**을 적지만, override가 **19.3.0으로 강제**한다. 예제와 루트는 처음부터 19.3.0.

rxjs 개발 버전은 일관되게 `^7.8.2`. Vue 개발 버전은 `^3.5.42` (`ui-adapter-vue3`, `debugger`).

### 3.3 UMD 글로벌 맵

`common/shared/tsdown/data/peer-deps.ts`가 번들에서 외부화할 peer와 글로벌 이름을 고정한다.

| import | 글로벌 | npm 이름 |
| --- | --- | --- |
| `react`, `react/jsx-runtime` | `React` | `react` |
| `react-dom`, `react-dom/client` | `ReactDOM` | `react-dom` |
| `rxjs`, `rxjs/operators` | `rxjs` / `rxjs.operators` | `rxjs` |
| `@wendellhu/redi`, `@wendellhu/redi/react-bindings` | 동명 | `@wendellhu/redi` |
| `vue` | `Vue` | `vue` |

---

## 4. 빌드 · 테스트 · 릴리스 툴체인

### 4.1 패키지 매니저 · 엔진

출처: 루트 `package.json`, `pnpm-workspace.yaml`.

| 항목 | 값 |
| --- | --- |
| 패키지 매니저 | `pnpm@12.5.1` (`packageManager`) |
| Node | `devEngines.runtime` `>=22.18` |
| 모듈 형식 | `"type": "module"` |
| hoist | `publicHoistPattern: '@storybook/react'` |
| 네이티브 빌드 차단 | `allowBuilds`: `@parcel/watcher`, `@swc/core`, `esbuild`, `protobufjs` 전부 `false` |
| 릴리스 에이지 제외 | `@amamo/*`, `@univerjs/*` |

`esbuild`/`@swc/core`는 직접 의존이 아니지만 tsdown·Storybook 전이가 끌어올 수 있어 빌드를 막아 둔다. `common/shared/esbuild/index.ts`는 **esbuild 패키지를 import하지 않는** CSS ignore 플러그인 스텁이다.

### 4.2 Turbo

출처: 루트 `package.json` scripts, `turbo.json`.

| 태스크 | 출력 | 비고 |
| --- | --- | --- |
| `build` | `lib/**` | 플러그인: `turbo build --filter '!./common/*' --filter '!./presets/**'`. 프리셋은 두 단계 (`presets/**...` 후 `presets/**`) |
| `test` | (없음) | `turbo test -- --passWithNoTests` |
| `coverage` | `coverage/**` | env `CI`, concurrency 50% |
| `typecheck` | (없음) | `turbo typecheck` |

루트 버전: `turbo ^2.10.12`.

### 4.3 패키지 빌드: `univer-cli` + tsdown + tsc

`@univerjs-infra/shared` bin `univer-cli` (`common/shared/package.json` → `bin/index.mts`).

표준 플러그인 스크립트 (`packages/*/package.json` 거의 전부):

```
build:bundle = univer-cli build
build:types  = tsc -p tsconfig.node.json
build        = pnpm run build:bundle && pnpm run build:types
```

예외:

- `engine-render`: `univer-cli build --config tsdown.override.mts`
- 프리셋 / `@univerjs/presets`: `univer-cli preset build --cleanup`, `prepare`: `univer-cli preset prepare`

tsdown (`^0.23.0`)이 ESM(`lib/es`) · CJS(`lib/cjs`) · UMD(`lib/umd`)를 만든다. 브라우저 타깃 `chrome88` (`common/shared/tsdown/constants.ts`). 타입은 별도 `tsc`. `@univerjs-pro/*` 이름이면 `javascript-obfuscator`가 켜지지만 **이 클론의 패키지 이름은 전부 `@univerjs/`**라서 난독화는 꺼진 상태다.

### 4.4 예제 앱: Vite

`examples/package.json`: `vite ^8.3.0`, `tsx ^4.23.13`. `dev`/`build`/`preview`가 Vite. 제품 패키지는 Vite로 빌드하지 않는다.

UMD 정적 서빙: 루트 `serve ^14.2.6` (`dev:umd` / `serve:umd`).

### 4.5 CSS: Tailwind 3 + PostCSS

| 패키지 | 버전 | 위치 |
| --- | --- | --- |
| `tailwindcss` | `3.4.18` (고정) | 루트, shared, 거의 모든 `*-ui`, examples, storybook, debugger, action-recorder |
| `tailwindcss-animate` | `^1.0.7` | `design`, `ui`, `storybook`, `examples` |
| `tailwind-merge` | `2.6.0` | `design` dev (clsx 생성기) |
| `tailwind-scrollbar` | `^3` | shared |
| `postcss` | `^8.5.28` (거의 전부), `docs-toc-ui`만 `^8.5.26` | UI 패키지 27곳 |
| `autoprefixer` | `^10.6.0` | shared |
| `postcss-preset-env` | `^11.5.3` | shared |
| `postcss-replace` | `^2.0.1` | shared |

Tailwind **v4 아님**. 디자인 토큰은 `@univerjs/themes` (의존성 없는 순수 패키지, `packages/themes/package.json`).

### 4.6 린트 · 커밋 · 훅

루트 `package.json` + `eslint.config.ts` + `commitlint.config.cjs`.

| 패키지 | 버전 | 역할 |
| --- | --- | --- |
| `eslint` | `^10.8.0` | 루트 `eslint .` |
| `@antfu/eslint-config` | `^9.2.0` | Antfu 프리셋. `createUniverEslintConfig`가 래핑 (`eslint.config.ts`) |
| `@eslint/compat` | `^2.1.0` | ESLint 호환 레이어 |
| `@eslint-react/eslint-plugin` | `^5.18.1` | React |
| `eslint-plugin-react` | `^7.37.5` | React |
| `eslint-plugin-react-hooks` | `^7.1.1` | hooks |
| `eslint-plugin-react-refresh` | `^0.5.3` | refresh |
| `eslint-plugin-format` | `^2.0.1` | 포맷 |
| `@typescript-eslint/parser` | `^8.65.0` | shared |
| `eslint-plugin-better-tailwindcss` | `^4.7.0` | shared |
| `eslint-plugin-header` | `^3.1.1` | Apache 헤더 (`eslint.config.ts` `header: true`) |
| `eslint-plugin-no-barrel-import` | `^0.0.2` | shared |
| `eslint-plugin-no-penetrating-import` | `^0.0.1` | shared |
| `husky` | `^9.1.7` | `prepare: husky` |
| `lint-staged` | `^17.5.1` | `*: eslint --fix` |
| `@commitlint/cli` | `^21.2.2` | conventional |
| `@commitlint/config-conventional` | `^21.2.2` | `commitlint.config.cjs`가 이 프리셋만 extends |

### 4.7 테스트

| 패키지 | 버전 | 역할 |
| --- | --- | --- |
| `vitest` | `^5.0.0` | 단위/통합. 루트, 거의 모든 `packages/*`, examples, formula-integration, shared |
| `@vitest/coverage-istanbul` | `^5.0.0` | Istanbul (V8 coverage 아님) |
| `happy-dom` | `20.14.5` | 기본 테스트 DOM (`common/shared/vitest/index.ts`) |
| `jsdom` | `^29.1.1` | `docs-ui`만 |
| `jest-canvas-mock` | `^2.5.2` / `^2.5.8` | 캔버스 모의 |

`vitest.workspace.ts`는 `projects: ['packages/*']`만 등록한다. 프리셋은 테스트 스크립트가 없고, `tests/formula-integration`은 자체 `vitest` 스크립트 + turbo `test`로 돈다.

vitest가 **없는** 패키지: `debugger`, `storybook`, `themes`, `@univerjs/presets`, 프리셋 17개.

커버리지 게이트: `codecov.yml` 프로젝트 타깃 **80%**, patch off.

수식 통합 테스트 전용 패키지: `tests/formula-integration/package.json` — `core` + `engine-formula` + `sheets` + `sheets-filter` + `sheets-formula`.

### 4.8 타입스크립트

전 워크스페이스 `typescript ^6.0.3`. `@types/node ^26.1.2`는 루트만. `vue-tsc ^3.3.11`은 shared dev (`ui-adapter-vue3` 타입체크 보조). `themes`는 `typescript`를 자기 `package.json`에 적지 않고 shared에 의존한다.

### 4.9 릴리스

| 패키지 | 버전 | 역할 |
| --- | --- | --- |
| `@amamo/verso` | `1.2.0` | 루트 `release: verso` |

`verso.toml`: 루트 `package.json` 버전, 워크스페이스 `common/*` · `packages/*` · `presets` · `presets/packages/*`, changelog `CHANGELOG.md` angular 프리셋, 커밋 `chore(release): release v${version}`, 태그 `v${version}`, `push = follow-tags`.

Changesets, semantic-release, lerna, nx **없음**.

### 4.10 Storybook

`common/storybook/package.json`. Storybook **10.4.x**, React Webpack5, Chromatic, SWC 컴파일러. 루트 스크립트 `storybook:dev` / `storybook:build`.

### 4.11 generate/prepare 스크립트 (라이브러리가 아닌 코드젠)

| 패키지 | 명령 |
| --- | --- |
| 루트 | `husky` |
| `design` | `scripts/generate-clsx.mts` (`tailwind-merge` 기반) |
| `engine-render` | `scripts/generate-hyphen-pattern-loaders.mts` |
| `ui` | `scripts/generate-emojis.mts` |
| `sheets-conditional-formatting` | `scripts/build-icons.mts` (`@univerjs/icons-svg`) |
| 프리셋 17개 | `univer-cli preset prepare` |

루트 `analyze:build`는 `scripts/build-analysis.mts` (`node --experimental-strip-types`).

---

## 5. 눈에 띄는 부재

이 클론의 모든 `package.json` `dependencies` / `peerDependencies` / `devDependencies`와 README 언급을 대조한 결과.

### 에이전트 · LLM · MCP

- **LangGraph / LangChain / LlamaIndex 없음**
- **`@modelcontextprotocol/sdk` 및 어떤 MCP 서버/클라이언트도 없음**
- OpenAI / Anthropic / Google GenAI SDK 없음
- README는 별도 저장소 [`dream-num/univer-mcp`](https://github.com/dream-num/univer-mcp)를 “AI-native spreadsheets”로 **링크만** 한다. 이 클론에 패키지로 들어오지 않는다.

Univer 자체는 오피스 런타임(커맨드·Facade·플러그인)이지 에이전트 오케스트레이터가 아니다.

### 오피스 파서 · 수식 대안

- ExcelJS, SheetJS/`xlsx`, LuckyExcel, HyperFormula, Formula.js, mathjs 없음
- `numeral` / `numbro` 없음. 숫자 포맷은 core에 **vendored MIT `numfmt` 3.2.6** (`packages/core/src/shared/numfmt/`). `@univerjs/sheets-numfmt`는 이 복사본을 쓴다.
- `dayjs` / `moment` / `date-fns` / `luxon` 없음

### 렌더 · 에디터

- Pixi, Three, Konva, Fabric, Paper.js, Skia 없음
- Monaco, CodeMirror, TipTap, ProseMirror, Slate, Quill, Draft.js 없음 (문서 에디터는 `docs` + `engine-render`)
- Handsontable, ag-Grid, Luckysheet 없음

### 상태 · 스키마 · 서버

- Redux, Zustand, MobX, Jotai, Recoil, Valtio, Immer 없음 (상태 = Univer 모델 + rxjs)
- Zod, Ajv, Yup, io-ts 없음
- Express, Fastify, Koa, Next.js, Nuxt 없음
- Socket.IO, yjs, Automerge 없음 (OT는 `ot-json1`)
- protobuf 직접 의존 없음 (`@grpc/grpc-js`만)

### 빌드 스택에서 안 쓰는 것

- 제품 빌드에 **Webpack / Rollup CLI / Vite** 없음 (Vite는 examples, Webpack은 Storybook)
- Babel, tsup, unbuild, nx, lerna, changesets 없음
- Tailwind v4, shadcn CLI 없음 (Radix + CVA + 자체 design은 shadcn 스타일이지만 패키지는 아님)
- Prettier 단독 패키지 없음 (`eslint-plugin-format` / Antfu 설정에 위임)
- Jest 러너 없음 (`jest-canvas-mock`만 이름에 jest)

### UI 어댑터 한계

- Vue 3 어댑터는 있으나 **Vue가 기본 UI가 아니다** (peer `vue>=3`, 구현은 `ui`를 감싼다).
- Angular / Svelte 어댑터 패키지 없음.
- `ui-adapter-web-component`는 서드파티 없이 `core`+`ui`만.

---

## 6. 서드파티 이름 전체 목록

`package.json` 84개에서 등장하는 **모든 비-`@univerjs` / 비-`@univerjs-infra` 패키지 이름**. 알파벳 순. 클론 외부 `@univerjs/icons`는 별도.

### 6.1 제품에 실릴 수 있는 런타임 (`dependencies` 또는 `peerDependencies`)

`@flatten-js/interval-tree`, `@floating-ui/dom`, `@floating-ui/utils`, `@grpc/grpc-js`, `@radix-ui/react-dialog`, `@radix-ui/react-direction`, `@radix-ui/react-dropdown-menu`, `@radix-ui/react-hover-card`, `@radix-ui/react-popover`, `@radix-ui/react-separator`, `@radix-ui/react-slot`, `@wendellhu/redi`, `async-lock`, `class-variance-authority`, `cmdk`, `decimal.js`, `fast-diff`, `franc-min`, `kdbush`, `lodash-es`, `ot-json1`, `rbush`, `react`, `react-dom`, `rxjs`, `sonner`, `vue` (peer, adapter만).

외부 스코프: `@univerjs/icons`.

### 6.2 개발·빌드·테스트·스토리북 전용

`@amamo/verso`, `@antfu/eslint-config`, `@chromatic-com/storybook`, `@commitlint/cli`, `@commitlint/config-conventional`, `@eslint-react/eslint-plugin`, `@eslint/compat`, `@storybook/addon-docs`, `@storybook/addon-links`, `@storybook/addon-styling-webpack`, `@storybook/addon-webpack5-compiler-swc`, `@storybook/icons`, `@storybook/react`, `@storybook/react-webpack5`, `@testing-library/jest-dom`, `@testing-library/react`, `@tsdown/css`, `@types/async-lock`, `@types/lodash-es`, `@types/node`, `@types/rbush`, `@types/react`, `@types/react-dom`, `@typescript-eslint/parser`, `@vitest/coverage-istanbul`, `autoprefixer`, `css-loader`, `eslint`, `eslint-plugin-better-tailwindcss`, `eslint-plugin-format`, `eslint-plugin-header`, `eslint-plugin-no-barrel-import`, `eslint-plugin-no-penetrating-import`, `eslint-plugin-react`, `eslint-plugin-react-hooks`, `eslint-plugin-react-refresh`, `happy-dom`, `husky`, `javascript-obfuscator`, `jest-canvas-mock`, `jsdom`, `lint-staged`, `postcss`, `postcss-loader`, `postcss-preset-env`, `postcss-replace`, `rollup-plugin-polyfill-node`, `serve`, `sort-keys`, `storybook`, `storybook-addon-swc`, `style-loader`, `tailwind-merge`, `tailwind-scrollbar`, `tailwindcss`, `tailwindcss-animate`, `tsconfig-paths-webpack-plugin`, `tsdown`, `tsx`, `turbo`, `typescript`, `unplugin-vue`, `vite`, `vitest`, `vue` (debugger/adapter **dev**), `vue-tsc`.

외부 스코프 개발: `@univerjs/icons-svg`.

### 6.3 `package.json`에 없고 `pnpm-workspace.yaml` `allowBuilds`에만 있는 이름

전이 의존으로 들어올 수 있어 네이티브 빌드를 끈 것:

- `@parcel/watcher`
- `@swc/core`
- `esbuild`
- `protobufjs`

---

## 7. 한 줄 요약

Univer 1.0.2 클론의 제품 런타임은 **`@wendellhu/redi` + `rxjs`(peer) + `lodash-es` + `ot-json1`/`fast-diff` + `rbush`/`kdbush` + `decimal.js` + `@flatten-js/interval-tree` + `@floating-ui/*` + `franc-min` + Radix/CVA/cmdk/sonner + React 16–19 peer + `@grpc/grpc-js` + `@univerjs/icons`** 이다. 캔버스·수식·문서 모델은 자체 구현이다. 빌드는 **pnpm 12 + turbo 2 + tsdown + tsc + Tailwind 3 + ESLint (Antfu) + Vitest 5 + verso**. 에이전트 스택(LangGraph, MCP SDK, LLM 클라이언트)은 이 클론에 없다.
