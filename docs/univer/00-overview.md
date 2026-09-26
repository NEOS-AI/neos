# Univer 개요

DreamNum `univer` 클론(`/Users/yeonwoosung/Desktop/univer`)을 읽어 고정한 인벤토리다. Univer 원본은 수정하지 않았다. 조사 기준일 2026-09-25. 모든 주장은 클론의 `path` 또는 `path:line`을 가리킨다.

형제 레포(`univer-workspace`, `univer-cli`, `dsh-univer-office`, `workbuddy-univer-office`, `openclaw-univer-office`, `univer-sdk-skills`, `dream-num/skills`, `univer-mcp`, `univer-pro`)는 이 머신에 없다. Desktop에는 `univer`만 있다. 2차 조사(2026-09-25)에서 그 README/SKILL.md를 원격으로 읽어 [12-ecosystem-agents.md](./12-ecosystem-agents.md)에 고정했다. 커맨드 609개·스냅샷 계약·수식 파이프라인은 `11`–`14`.

---

## 1. 클론 메타

| 항목 | 값 | 근거 |
| --- | --- | --- |
| 원격 | `https://github.com/dream-num/univer.git` | `package.json:14-16`, `git remote` |
| 기본 브랜치 | `dev` | `origin/HEAD` → `refs/remotes/origin/dev` |
| HEAD | `1defaf4ab67a63186331d37fbaec2958acd77680` `chore(release): release v1.0.2` (2026-09-24 18:56:50 +0800) | `git log -1` |
| 태그 | `v1.0.2` | `git describe --tags` |
| 루트 버전 | `1.0.2` | `package.json:4` |
| 패키지 매니저 | `pnpm@12.5.1` | `package.json:6` |
| 라이선스 | Apache-2.0 | `package.json:8`, `LICENSE:1-3` |
| 저작권자 | DreamNum Co., Ltd. `<developer@univer.ai>` | `package.json:7`, `README.md:421-423` |
| 홈페이지 | https://univer.ai | `package.json:13` |
| 이슈 | https://github.com/dream-num/univer/issues | `package.json:18-20` |
| 후원 | Open Collective `univer` | `package.json:9-12`, `.github/FUNDING.yml:5` |

공개 패키지(`packages/*`, `presets`, `presets/packages/*`)도 전부 `version: "1.0.2"`다. 루트는 `"private": true` (`package.json:5`).

---

## 2. 한 줄 정의와 태그라인

영어 README 상단:

> **The Office Harness for AI Agents**
>
> Spreadsheets · Documents · Presentations · Bases · Boards · PDFs (coming soon)
>
> High-performance, fully customizable Office SDK

근거: `README.md:5-7`.

한국어 README는 같은 문장을 **「AI 에이전트를 위한 Office Harness」**, **「스프레드시트 · 문서 · 프레젠테이션 · Bases · Boards · PDF(출시 예정)」**로 옮긴다 (`docs/readme/ko-KR.md:5-7`).

본문 정의 (`README.md:37-47`):

- 제품 안에 오피스 애플리케이션을 만드는 **오픈소스 SDK**.
- 호스팅 앱이나 고정 UI를 강제하지 않는다.
- 스프레드시트·문서·프레젠테이션의 빌딩 블록을 제공한다.
- SaaS, 내부 도구, BI, AI 앱에 편집 표면을 임베드할 때 쓴다.
- 브라우저와 같은 아키텍처로 서버에서 워크북/문서를 처리한다.
- 플러그인으로 기능을 고르거나 preset으로 빠르게 시작한다.
- 커스텀 플러그인, 커맨드, 서비스, UI, Facade API로 확장한다.

`DREAMNUM.md:3`은 책임을 한 문장으로 다시 적는다.

> The open-source, isomorphic office SDK for building embeddable spreadsheet, document, and presentation experiences in browsers and Node.js.

---

## 3. Univer가 아닌 것

이 저장소와 README가 명시적으로 가르는 경계.

| 오해 | 실제 | 근거 |
| --- | --- | --- |
| 스프레드시트 **파일 뷰어** | 자체 생산성 표면을 만드는 **프레임워크** | `README.md:47` 「Univer is not a spreadsheet file viewer only.」 |
| **MCP 서버** | MCP는 별도 레포 `dream-num/univer-mcp`. 이 클론에 MCP 패키지/서버 코드 없음 | `README.md:334` |
| **AI skill pack** | 스킬은 별도 레포 `dream-num/univer-sdk-skills` | `README.md:327` |
| **Univer Workspace / CLI / DSH / WorkBuddy / OpenClaw** | README가 가리키는 **다른 GitHub 레포**. 이 클론에 구현 없음 | `README.md:60-80` |
| **Univer Pro** | 상업 확장 레이어. 별도 저장소 `dream-num/univer-pro` | `README.md:301-314`, `.github/workflows/dispatch-sync-univer-pro.yml:17` |
| **Server SDK (협업·파일 변환)** | docs.univer.ai/server 문서. OSS 런타임은 headless/RPC 프리미티브만 | `README.md:330`, `README.md:312` |
| **실시간 협업·import/export·차트·피벗** | Pro 열에만 적힌 기능 | `README.md:290-297`, `README.md:307-313` |

태그라인의 **Boards / PDFs (coming soon)** 은 마케팅 서피스다. 이 클론에는 `packages/*board*`, `packages/*pdf*` 패키지가 없다. 프로토콜 enum에만 자리한다 (`packages/protocol/src/ts/univer/constants/univer.ts:17-26`).

---

## 4. 라이선스와 저작권

루트 `LICENSE`는 Apache License 2.0, January 2004 전문이다 (`LICENSE:1-3`). 조건 요약:

- 저작권·특허 라이선스 (`LICENSE:66-87`)
- 재배포 시 라이선스 사본, 변경 고지, NOTICE 보존 (`LICENSE:89-121`)
- 상표권은 부여하지 않음 (`LICENSE:138-141`)
- AS IS, 보증 없음 (`LICENSE:143-151`)

`LICENSE` 파일 자체에는 Apache 부록의 저작권 헤더가 없다. README와 소스 헤더가 대신 채운다.

| 위치 | 문구 |
| --- | --- |
| `README.md:421-423` | `Copyright (c) 2021-present DreamNum Co., Ltd.` / Apache-2.0 |
| `docs/readme/ko-KR.md:423-425` | 동일, 한국어 |
| 소스 파일 헤더 (예: `packages/core/src/univer.ts:2`, `presets/src/index.ts:2`) | `Copyright 2023-present DreamNum Co., Ltd.` |

저작권 연도가 README(2021)와 소스 헤더(2023)에서 어긋난다. 클론 안 사실로만 기록한다.

내장 서드파티: `packages/core/src/shared/numfmt/LICENSE`는 `numfmt 3.2.6`(Borgar Þorsteinsson, MIT). Univer Apache-2.0와 별도 고지다.

`eslint.config.ts:8`은 `header: true`로 Apache 헤더 강제.

---

## 5. 버전 · 도구 · 런타임

### 5.1 버전 라인

`package.json:4`와 공개 패키지 매니페스트가 `1.0.2`다. git 태그: `v1.0.0-alpha.0` … `v1.0.0-beta.2`, `v1.0.0-rc.0`, `v1.0.0`, `v1.0.1`, `v1.0.2`.

`CHANGELOG.md` 최상단은 `## [1.0.0-beta.2]` (`CHANGELOG.md:3`). `1.0.0` / `1.0.1` / `1.0.2` / `rc` 항목이 **파일에 없다**. verso 설정은 changelog를 `CHANGELOG.md`에 angular preset으로 쓰라고 한다 (`verso.toml:13-15`). 릴리스 커밋은 있는데 changelog 본문이 따라가지 못한 상태다.

`docs/API_STABILITY.md:5`는 「Univer is currently pre-1.0」이라고 적는다. `SECURITY.md:13`도 「As Univer is still not reaching version 1.0」. 루트 버전은 이미 `1.0.2`다. 정책 문서가 릴리스 번호보다 늦다.

### 5.2 모노레포 개발 vs headless 런타임

| 대상 | 요구 | 근거 |
| --- | --- | --- |
| 이 모노레포 개발 | Node.js `>=22.18` | `package.json:21-26` `devEngines.runtime`, `README.md:287`, `README.md:353`, `CONTRIBUTING.md:33` |
| pnpm | README/CONTRIBUTING는 `>=11`, 루트는 `pnpm@12.5.1` | `README.md:354`, `CONTRIBUTING.md:33`, `package.json:6` |
| Headless Univer | Node.js `>=18.17.0` | `README.md:287` |
| CI Node | `node@24.3.0` | `.github/actions/setup-node/action.yml:15`, `.github/workflows/release-npm.yml:40` |
| 브라우저 타깃 | Chrome 88. Edge `>=88`, Firefox `>=90`, Chrome `>=88`, Safari `>=14.1`, Electron `>=12` | `README.md:282` |
| Polyfill | `Intl.Segmenter` (`@formatjs/intl-segmenter`) | `README.md:283` |
| 빌드 도구 | Vite, esbuild, Webpack 5. Webpack 4는 `exports` 매핑 필요할 수 있음 | `README.md:284` |
| React | 뷰 레이어는 React 18 기반, 18·19 지원, 16.9+/17 최소 호환 | `README.md:285` |
| 워크스페이스 React 고정 | `react` / `react-dom` `19.3.0` | `pnpm-workspace.yaml:15-19`, `package.json:65-66` |

독립 릴리스 패키지 `@univerjs/icons`, `@univerjs/icons-svg`는 SDK 버전을 따르지 않는다 (`README.md:276`, `docs/API_STABILITY.md:75`). examples는 `@univerjs/icons: 1.43.1` (`examples/package.json:22`).

### 5.3 루트 스크립트

`package.json:27-45`:

| 명령 | 동작 |
| --- | --- |
| `pnpm dev` | `pnpm --filter univer-examples dev` |
| `pnpm dev:umd` | `serve .` |
| `pnpm build` | `build:plugins` 후 `build:presets` |
| `pnpm build:plugins` | turbo, `common/*`와 `presets/**` 제외 |
| `pnpm test` | `turbo test -- --passWithNoTests` |
| `pnpm typecheck` / `pnpm lint` | turbo / eslint |
| `pnpm storybook:dev` | `@univerjs/storybook` |
| `pnpm release` | `verso` |

영어 README 개발 표 (`README.md:365-372`)는 `pnpm dev`를 「Vite 8 Bundled Dev and HMR」로 적는다. 한국어 README (`docs/readme/ko-KR.md:368-369`)는 `pnpm dev`를 HMR 없는 저메모리 미리보기, `pnpm dev:source`를 HMR 소스 워크벤치로 적는다. **루트 `package.json`에 `dev:source`는 없다.** 한국어 README가 뒤처진 상태다.

릴리스 CLI는 `@amamo/verso` `1.2.0` (`package.json:47`). `DREAMNUM.md:28`은 `[jikkai/verso](https://github.com/jikkai/verso)`를 의존으로 적는다. 패키지 이름은 `@amamo/verso`다.

---

## 6. DREAMNUM.md — 이 레포가 소유하는 것

`DREAMNUM.md`는 DreamNum 내부 책임 계약이다.

**Owns** (`DREAMNUM.md:7-13`):

- OSS 런타임, 플러그인 시스템, 커맨드/서비스 인프라, Facade API, 수식 엔진, Canvas 렌더링 엔진
- Sheets / Docs / Slides의 OSS 모델·편집·UI 플러그인, drawing / commenting / validation / formatting / i18n
- 브라우저, Node.js, Web Worker 경로, React UI, Vue 3·Web Component 어댑터
- first-party OSS preset, examples, 테스트
- public API 호환 규칙 (stable / experimental / internal / deprecated)

**명시적으로 소유하지 않음** (`DREAMNUM.md:15`):

> Univer Pro's commercial collaboration, import/export, server, or enterprise capabilities

**Provides** (`DREAMNUM.md:19-23`):

- `@univerjs/core`, `@univerjs/engine-formula`, `@univerjs/engine-render`
- `@univerjs/sheets`, `@univerjs/docs`, `@univerjs/slides`와 UI·기능 패키지
- `@univerjs/presets`와 `@univerjs/preset-*`
- `@univerjs/ui-adapter-vue3`, `@univerjs/ui-adapter-web-component`
- `sync-univer` repository-dispatch — `dev`에 푸시되면 Pro 레포에 알림. 워크플로: `.github/workflows/dispatch-sync-univer-pro.yml`

**Depends on** (`DREAMNUM.md:27-28`):

- `dream-num/univer-icons` — UI가 쓰는 React 아이콘/SVG
- `jikkai/verso` — 버전/태그 CLI

권위 문서 (`DREAMNUM.md:32-37`): docs.univer.ai, Facade API reference, README/CONTRIBUTING, `packages/`·`presets/`·`docs/API_STABILITY.md`, `.github/workflows/release-npm.yml`, `SECURITY.md`.

---

## 7. OSS vs Pro 경계

`README.md:301-321`과 `docs/readme/ko-KR.md:302-322`가 같은 표를 쓴다. 이 클론은 **오픈소스 코어 + first-party OSS 플러그인**만 담는다. Pro는 상업 확장 레이어로 따로 개발한다.

### 7.1 기능 매트릭스 (README 원문 요약)

| 영역 | 이 레포(OSS) | Univer Pro / 상업 |
| --- | --- | --- |
| Foundation | Core SDK, 플러그인, 렌더링 엔진, 수식 엔진, Facade, 테마, i18n, 프레임워크 어댑터 | Pro presets, enterprise deployment |
| Sheets | 편집, 수식, 숫자 서식, filter/sort, 데이터 유효성, 조건부 서식, 노트, 테이블, 하이퍼링크, 댓글, drawing, 찾기/바꾸기 | 협업, 편집 기록, import/export, print, charts, pivot, sparklines, outlines, shapes, in-cell graphics, data connectors, range preprocessing, 강화 수식 |
| Docs | 문서 모델·편집 UI, 목록, 하이퍼링크, 댓글, quick insert, drawing | 협업, import/export, print, 강화 테이블/목록, columns, callouts, code blocks, quotes, shapes, remote thread-comment |
| Slides | OSS presentation 모델과 UI (활발히 개발 중, `README.md:295`) | Pro slide 모델/UI, import/export, charts, tables, shape editor |
| Bases | 커스텀 structured-data를 위한 **플러그인 아키텍처** | Base DB 모델, commands, mutations, formula, workbench UI, field editors, render-engine |
| Server/runtime | Node.js headless, RPC/Web Worker, 서버 지향 자동화 프리미티브 | collaboration server/client, SSR, computing delegation, server-side calculation, changeset replay |
| Integrations | React, Vue, Web Components, 테마, i18n, 커스텀 플러그인 | Pro presets, enterprise packages |

Sheets가 가장 성숙하다 (`README.md:299`).

### 7.2 Boundary principles (`README.md:316-321`)

1. OSS 패키지는 Apache-2.0 아래 **단독으로 유용**해야 한다. Pro는 공개 OSS API 사용에 **필수가 아니다**.
2. OSS 버그/회귀/보안은 Pro 기능이 있어도 **OSS 레포에서** 고친다.
3. OSS 문서가 Pro-only 기능을 `@univerjs/*`에 있는 것처럼 암시하면 안 된다. Pro API/패키지/배포 경로는 이름을 명시한다.
4. OSS 기능에 Pro 강화가 있어도 OSS 동작은 독립 문서화한다.

Pro 가이드: https://docs.univer.ai/guides/pro (`README.md:314`).

### 7.3 클론 코드가 보여주는 경계

**이 레포에 있는 것**

- `@univerjs/*` 패키지 60개, `@univerjs/preset-*` 17개, `@univerjs/presets`.
- `createUniver`의 `collaboration?: true` 옵션. 켜면 `IUndoRedoService`, `IAuthzIoService`, `IMentionIOService`를 `null`로 override한다 (`presets/src/preset.ts:37-55`). OSS는 로컬 undo/authz/mention을 두고, Pro 협업이 그 자리를 대체할 훅을 남긴다.
- 빌드 도구가 `@univerjs-pro/` 이름을 안다. obfuscation (`common/shared/tsdown/index.ts:54`), UMD prefix `univer-pro-` (`common/shared/tsdown/configs/umd.ts:28`), cleanup (`common/shared/tsdown/utils/cleanup-pkg.ts:38-46`). **Pro 패키지 소스는 없다.**
- `UniverType` enum에 `UNIVER_BASE = 5`, `UNIVER_BOARD = 6`, `UNIVER_PDF = 7` (`packages/protocol/src/ts/univer/constants/univer.ts:17-26`).
- `packages/core/src/bases/`에 `BaseDataModel`이 있다 (`packages/core/src/bases/base-data-model.ts:38`). 스냅샷·필드·레코드 타입과 수식 테이블 이름 헬퍼를 export한다 (`packages/core/src/bases/index.ts:17-50`).
- `Univer._init`이 등록하는 생성자는 **SHEET / DOC / SLIDE뿐**이다 (`packages/core/src/univer.ts:203-205`). BASE/BOARD/PDF 생성자는 여기서 붙지 않는다.

**이 레포에 없는 것**

- `@univerjs-pro/*` 패키지
- Boards / PDF 플러그인
- Base workbench UI, field editors, Pro 렌더 뷰
- collaboration server/client, import/export, print, charts, pivot
- MCP 서버, skill pack, Workspace 앱, CLI

`dev` 푸시 시 `dream-num/univer-pro`로 `sync-univer` 이벤트를 보낸다 (`.github/workflows/dispatch-sync-univer-pro.yml:1-24`). payload는 `ref`와 `sha`.

버전 정렬: `@univerjs/*`는 같은 릴리스 라인, Pro를 쓰면 `@univerjs-pro/*`도 맞춘다 (`README.md:276`, `docs/API_STABILITY.md:75-77`).

---

## 8. 에코시스템 링크 — 이 머신에 클론되지 않음

`README.md:323-334`와 `README.md:60-80`. Desktop 확인 결과 아래 디렉터리는 **모두 없음**.

| 이름 | README가 가리키는 URL | 역할 (README 문장) | 로컬 |
| --- | --- | --- | --- |
| Core SDK | `dream-num/univer` | 이 모노레포 | 있음 (`../univer`) |
| Univer Workspace | https://github.com/dream-num/univer-workspace | self-hostable workspace. 사람과 에이전트가 Office 콘텐츠를 만들고 검토 | 없음 |
| Univer CLI | https://github.com/dream-num/univer-cli | 에이전트가 로컬에서 Office 콘텐츠를 만들고 편집·검사·전달 | 없음 |
| DSH Office | https://github.com/dream-num/dsh-univer-office | DeepSeek Harness용 Office 플러그인. 연결 콘텐츠, 검증, 격리 worktree | 없음 |
| WorkBuddy | https://github.com/dream-num/workbuddy-univer-office | WorkBuddy 로컬 통합. MCP preview와 draft review. **개발 프리뷰** | 없음 |
| OpenClaw | https://github.com/dream-num/openclaw-univer-office | OpenClaw에서 Office 콘텐츠 생성·검토·전달 | 없음 |
| AI skills | https://github.com/dream-num/univer-sdk-skills | 에이전트용 재사용 지침. 통합, Pro, 플러그인, Node 백엔드 | 없음 |
| Univer MCP | https://github.com/dream-num/univer-mcp | 자연어로 Sheets를 다루는 Platform / MCP 통합 | 없음 |
| Univer Pro | `dream-num/univer-pro` (워크플로) | 상업 확장 | 없음 |
| univer-icons | https://github.com/dream-num/univer-icons | 아이콘. npm 의존으로만 존재 | 소스 없음 |
| documentation | `dream-num/documentation` (`docs/CONTRIBUTING-FACADE.md:51`) | Facade 가이드 MDX | 없음 |

문서 사이트 (클론 밖):

- https://univer.ai/ — 제품
- https://docs.univer.ai — 가이드
- https://docs.univer.ai/ai — AI SDK (에이전트 워크플로)
- https://docs.univer.ai/server — Server SDK
- https://docs.univer.ai/guides/skills — AI Skills
- https://docs.univer.ai/guides/pro — Pro
- https://docs.univer.ai/reference/classes/univer — Facade 레퍼런스
- https://docs.univer.ai/showcase — 쇼케이스

AI 워크플로 세 축 (`README.md:135-141`): programmatic editing, output verification (콘텐츠 검사·스크린샷·레이아웃), worktree collaboration. **Live editing, shared revisions, Worktree는 Web SDK와 협업 기능이 필요하며 패키지/라이선스가 기능마다 다르다** (`README.md:141`).

각 예시 프로젝트는 자체 셋업과 SDK 라이선스 요구를 문서화한다 (`README.md:82`).

---

## 9. 저장소 레이아웃

영어 README (`README.md:339-345`)와 CONTRIBUTING (`CONTRIBUTING.md:62-70`)이 같은 나무를 그린다. presets는 CONTRIBUTING 트리에만 명시된다.

```text
.
├── packages/      코어, 엔진, 문서 타입, UI·기능 플러그인
├── presets/       curated plugin collections          (CONTRIBUTING.md:68)
├── examples/      브라우저용 all-in-one Vite workbench
├── common/        공유 툴링, Storybook, utilities
├── tests/         추가 integration test
└── docs/          레포 로컬 문서, 이미지, TLDR
```

`pnpm-workspace.yaml:1-6`:

```yaml
packages:
    - common/*
    - examples
    - presets
    - presets/packages/*
    - packages/*
    - tests/*
```

`verso.toml:4-11`은 릴리스 대상에서 `examples`와 `tests/*`를 빼고 `include_root = true`.

기타 루트 파일:

| 경로 | 역할 |
| --- | --- |
| `turbo.json` | test / coverage / build(`lib/**`) / typecheck |
| `vitest.workspace.ts:4-6` | `projects: ['packages/*']` |
| `eslint.config.ts` | `@univerjs-infra/shared/eslint`, Apache header, facade import 규칙 |
| `commitlint.config.cjs` | `@commitlint/config-conventional` |
| `codecov.yml` | 커버리지 |
| `CODE_OF_CONDUCT.md` | Contributor Covenant. 신고 `huwenzhao@univer.ai` (`CODE_OF_CONDUCT.md:37`) |
| `scripts/build-analysis.mts`, `scripts/coverage-shard.mts` | 빌드 분석, CI 샤드 |

패키지 수: `packages/` 60, `presets/packages/` 17, `common/` 3 (`debugger`, `shared`, `storybook`), `examples` 1, `tests/` 1 (`formula-integration`).

---

## 10. `packages/` — OSS 플러그인 목록

모두 `@univerjs/*`, `version: 1.0.2`, `private: false`, `license: Apache-2.0`, author DreamNum. description은 각 `packages/*/package.json`.

### 10.1 런타임 · 엔진 · 프로토콜

| 패키지 | description |
| --- | --- |
| `@univerjs/core` | Core runtime, data models, command system, DI, Facade |
| `@univerjs/protocol` | Shared protocol types, generated service interfaces, data contracts |
| `@univerjs/engine-formula` | Formula parsing, function registration, dependency, calculation |
| `@univerjs/engine-render` | Canvas rendering for documents, sheets, slides |
| `@univerjs/network` | Network service abstractions |
| `@univerjs/rpc` | Browser RPC, main thread ↔ worker |
| `@univerjs/rpc-node` | Node.js RPC counterpart |
| `@univerjs/telemetry` | Telemetry service interface |
| `@univerjs/themes` | Built-in theme definitions |
| `@univerjs/design` | Shared React design components, styles, locales |

`@univerjs/core` 의존 (`packages/core/package.json:80-89`): `@univerjs/protocol`, `@univerjs/themes`, `@wendellhu/redi` 1.1.3, `async-lock`, `fast-diff`, `kdbush`, `lodash-es`, `ot-json1`, `rbush`. peer: `rxjs >=7.0.0`.

코어 소스 큰 덩어리 (`packages/core/src/`):

- `univer.ts` — `Univer` 클래스
- `services/` — command, plugin, lifecycle, instance, locale, theme, undo, permission, authz-io, mention-io, resource, log, config, context, user-manager
- `facade/` — `FUniver`, `FDoc`, `FBlob`, `FEnum`, `FEvent`, `FUtil`, `FUserManager`
- `sheets/` — `Workbook`, `Worksheet` 데이터 모델 (UI 없는 코어 모델)
- `docs/` — `DocumentDataModel`, Text-X OT
- `slides/` — `SlideDataModel`
- `bases/` — `BaseDataModel` (생성자는 `Univer._init`에 미등록)
- `shared/numfmt/` — 숫자 서식 (MIT numfmt 이식)

### 10.2 Sheets

로직 패키지와 `*-ui`가 쌍이다 (`docs/ISOMORPHIC.md:18` 예: `sheets-filter` / `sheets-filter-ui`).

| 로직 | UI | 역할 |
| --- | --- | --- |
| `@univerjs/sheets` | `@univerjs/sheets-ui` | 스프레드시트 모델 / UI |
| `@univerjs/sheets-formula` | `@univerjs/sheets-formula-ui` | 수식 서비스 / 편집 UI |
| `@univerjs/sheets-numfmt` | `@univerjs/sheets-numfmt-ui` | 숫자 서식 |
| `@univerjs/sheets-filter` | `@univerjs/sheets-filter-ui` | 필터 |
| `@univerjs/sheets-sort` | `@univerjs/sheets-sort-ui` | 정렬 |
| `@univerjs/sheets-data-validation` | `@univerjs/sheets-data-validation-ui` | 데이터 유효성 |
| `@univerjs/sheets-conditional-formatting` | `@univerjs/sheets-conditional-formatting-ui` | 조건부 서식 |
| `@univerjs/sheets-hyper-link` | `@univerjs/sheets-hyper-link-ui` | 하이퍼링크 |
| `@univerjs/sheets-note` | `@univerjs/sheets-note-ui` | 셀 노트 |
| `@univerjs/sheets-table` | `@univerjs/sheets-table-ui` | 구조화 테이블 |
| `@univerjs/sheets-drawing` | `@univerjs/sheets-drawing-ui` | 드로잉 |
| `@univerjs/sheets-thread-comment` | `@univerjs/sheets-thread-comment-ui` | 스레드 댓글 |
| `@univerjs/sheets-find-replace` | (공유 find-replace UI) | 찾기/바꾸기 |
| — | `@univerjs/sheets-crosshair-highlight` | 크로스헤어 하이라이트 |

`@univerjs/sheets` README: UI와 독립인 코어 모델 (`packages/sheets/README.md:7`). Facade 있음. `createWorkbook`은 여기 mixin (`packages/sheets/src/facade/f-univer.ts:93,161-165`).

### 10.3 Docs

| 로직 | UI | 역할 |
| --- | --- | --- |
| `@univerjs/docs` | `@univerjs/docs-ui` | 문서 모델 / 편집 UI |
| `@univerjs/docs-drawing` | `@univerjs/docs-drawing-ui` | 드로잉 |
| `@univerjs/docs-hyper-link` | `@univerjs/docs-hyper-link-ui` | 하이퍼링크 |
| `@univerjs/docs-thread-comment` | `@univerjs/docs-thread-comment-ui` | 스레드 댓글 |
| `@univerjs/docs-toc` | `@univerjs/docs-toc-ui` | 목차 |
| `@univerjs/docs-find-replace` | | 찾기/바꾸기 |

`@univerjs/docs` README: UI와 독립인 리치 텍스트 모델 (`packages/docs/README.md:7`). Facade 있음.

### 10.4 Slides

| 패키지 | description |
| --- | --- |
| `@univerjs/slides` | Core presentation model and services |
| `@univerjs/slides-ui` | Presentation editor UI |

README는 「under active development」 (`README.md:295`). **Slides preset은 `presets/packages/`에 없다.** examples 슬라이드 엔트리는 Plugin Mode로 직접 조립한다 (`examples/src/slides/mount.ts:3-11`).

### 10.5 공유 UI · 기능

| 패키지 | description |
| --- | --- |
| `@univerjs/ui` | workbench, menus, dialogs, Facade UI. `UniverUIPlugin` + `UniverMobileUIPlugin` (`packages/ui/README.md:39-40`) |
| `@univerjs/ui-adapter-vue3` | Vue 3 어댑터 |
| `@univerjs/ui-adapter-web-component` | Web Component 어댑터 |
| `@univerjs/drawing` / `@univerjs/drawing-ui` | 공유 드로잉 모델/UI |
| `@univerjs/thread-comment` / `@univerjs/thread-comment-ui` | 공유 스레드 댓글 |
| `@univerjs/find-replace` | 공유 찾기/바꾸기 |
| `@univerjs/data-validation` | Sheets 전용 데이터 유효성 모델 (`UNIVER_SHEET`). 이름은 공유처럼 보이지만 Docs DV 패키지는 없다 |
| `@univerjs/watermark` | 워터마크 렌더링 |
| `@univerjs/action-recorder` | 액션 기록/재생 (디버그·데모) |

### 10.6 수식 엔진 규모

`packages/engine-formula/src/functions/` 카테고리와 `function-map.ts` 엔트리 수(클론에서 집계):

| 카테고리 | map 엔트리 |
| --- | --- |
| statistical | 109 |
| math | 81 |
| engineering | 57 |
| financial | 54 |
| text | 48 |
| compatibility | 38 |
| lookup | 36 |
| date | 27 |
| information | 23 |
| logical | 21 |
| database | 12 |
| meta | 6 |
| array | 2 |
| web | 2 |
| cube | 0 (주석만, `packages/engine-formula/src/functions/cube/function-map.ts:26-29`) |
| univer | 0 |

합계 516 map 엔트리. `index.ts`가 있는 구현 디렉터리 502. `ALL_IMPLEMENTED_FUNCTIONS`가 위 맵을 합친다 (`packages/engine-formula/src/functions/index.ts:37-54`).

---

## 11. `presets/` — curated 조합

`@univerjs/presets` description: 「Build Univer apps faster and easier with pre-configured plugin collections.」 (`presets/package.json:5`).

`createUniver` (`presets/src/preset.ts:48-103`):

1. `collaboration`이면 undo/authz/mention 서비스를 null override.
2. `new Univer({ logLevel: WARN, ... })`.
3. preset 플러그인을 `pluginName` 맵에 넣고, 나중 preset이 같은 이름을 덮어쓴다.
4. 추가 `plugins`가 preset과 이름이 겹치면 throw (`presets/src/preset.ts:87-89`).
5. `FUniver.newAPI(univer)`를 감싸 `{ univer, univerAPI }` 반환.

### 11.1 Sheets presets

| 패키지 | description |
| --- | --- |
| `@univerjs/preset-sheets-core` | 브라우저 코어 스프레드시트. CSS·locales·Facade |
| `@univerjs/preset-sheets-node-core` | Node.js 코어. CSS 없음 |
| `@univerjs/preset-sheets-conditional-formatting` | 조건부 서식 |
| `@univerjs/preset-sheets-data-validation` | 데이터 유효성 |
| `@univerjs/preset-sheets-drawing` | 드로잉 |
| `@univerjs/preset-sheets-filter` | 필터 |
| `@univerjs/preset-sheets-find-replace` | 찾기/바꾸기 |
| `@univerjs/preset-sheets-hyper-link` | 하이퍼링크 |
| `@univerjs/preset-sheets-note` | 노트 |
| `@univerjs/preset-sheets-sort` | 정렬 |
| `@univerjs/preset-sheets-table` | 테이블 |
| `@univerjs/preset-sheets-thread-comment` | 스레드 댓글 |

`preset-sheets-core`가 묶는 플러그인 (`presets/packages/preset-sheets-core/src/preset.ts:23-36`): Docs+DocsUI, FormulaEngine, RenderEngine, Network, RPC main, Sheets, SheetsFormula(+UI), SheetsNumfmt(+UI), SheetsUI, UI. Facade side-effect import (`:38-46`).

### 11.2 Docs presets

| 패키지 | description |
| --- | --- |
| `@univerjs/preset-docs-core` | 브라우저 Docs 편집+UI |
| `@univerjs/preset-docs-node-core` | Node.js Docs. CSS 없음 |
| `@univerjs/preset-docs-drawing` | 드로잉 |
| `@univerjs/preset-docs-hyper-link` | 하이퍼링크 |
| `@univerjs/preset-docs-thread-comment` | 스레드 댓글 |

**preset-docs-toc, preset-slides-\* 는 없다.** TOC는 패키지로만 있고, docs-core preset 옵션 `toc: true`로 켠다 (`examples/src/docs/mount.ts:53`).

Preset vs Plugin vs Headless (`README.md:270-274`):

| 모드 | 언제 |
| --- | --- |
| Plugin Mode | 패키지·lazy load·런타임 조합을 직접 통제 |
| Preset Mode | Sheets/Docs/Node를 최소 설정으로 |
| Headless Mode | UI 없이 서버 처리·수식·자동화. 가이드 https://docs.univer.ai/guides/sheets/getting-started/node |

---

## 12. `examples/` — 로컬 워크벤치

`examples/package.json`:

- name `univer-examples`, `private: true`, version 없음
- description 「Low-memory Univer development workbench」 (`examples/package.json:5`)
- Vite `^8.3.0`, React 19.3.0
- 의존: core/design/docs/docs-ui/drawing/engine-render/slides/slides-ui/themes/ui + 거의 모든 sheets/docs preset. **node-core preset은 없음** (브라우저 워크벤치).

엔트리 `examples/src/main.ts:23-27`:

```ts
const loaders = {
    docs: () => import('./docs/mount'),
    sheets: () => import('./sheets/mount'),
    slides: () => import('./slides/mount'),
}
```

해시 `#sheets` / `#docs` / `#slides`. 기본 `#sheets` (`examples/src/main.ts:58-65`). 인스턴스 하나, 라우트 전환 시 교체. CONTRIBUTING (`CONTRIBUTING.md:175-177`): Settings가 locale, LTR/RTL, region, theme, appearance, ribbon, UI chrome, zoom을 localStorage에 저장하고 런타임 API로 적용. 로케일은 온디맨드.

제품별 조립:

| 라우트 | 방식 | 파일 |
| --- | --- | --- |
| sheets | Preset Mode. core + drawing + CF + filter + hyperlink + validation + find-replace + note + sort + table + thread-comment | `examples/src/sheets/mount.ts:59-71` |
| docs | Preset Mode + `UniverDocsLayoutWorkerPlugin` | `examples/src/docs/mount.ts:52-61` |
| slides | Plugin Mode. Univer + Render + UI + Docs(+UI) + Drawing + Slides(+UI) | `examples/src/slides/mount.ts:3-11,46-50` |

로케일 19종 (`examples/src/sheets/mount.ts:24-44` 등과 `LocaleType`): enUS, frFR, zhCN, ruRU, zhTW, zhHK, viVN, faIR, jaJP, koKR, esES, caES, skSK, ptBR, deDE, itIT, idID, plPL, arSA (`packages/core/src/types/enum/locale-type.ts:20-40`).

CONTRIBUTING (`CONTRIBUTING.md:177`): E2E는 이 레포 소스 examples에 묶지 말고 빌드된 패키지를 밖에서 소비하라.

**없는 예시 경로:** `packages/rpc/README.md:35`는 `examples/src/sheets-mobile/worker.ts`를, `packages/rpc-node/README.md:35`는 `examples/src/node/sdk/worker.ts`를 가리킨다. 둘 다 클론에 **없다**. docs 워커만 `examples/src/docs/worker.ts`로 있다.

---

## 13. `common/` — 내부 툴링

워크스페이스 `common/*`. verso 릴리스에 포함되지만 npm 공개 여부는 `private`으로 갈린다.

| 패키지 | private | 역할 |
| --- | --- | --- |
| `@univerjs-infra/shared` | true | eslint, tsconfig, vitest, esbuild, tailwind, postcss, tsdown, locale, preset-build. bin `univer-cli` (`common/shared/package.json:27-29`) |
| `@univerjs/storybook` | true | Storybook 10, port 6006 (`common/storybook/package.json:15`) |
| `@univerjs/debugger` | true | 디버그 유틸. README CAUTION: 프로덕션에서 쓰지 말 것 (`common/debugger/README.md:3-4`) |

`@univerjs-infra/shared` tsdown은 Pro 패키지 난독화를 지원하지만, 이 클론의 패키지 이름은 `@univerjs/`만 쓴다.

---

## 14. `tests/`

`tests/formula-integration/`만 있다.

- name `formula-integration-test`, private (`tests/formula-integration/package.json:2-3`)
- README 한 줄: 「test repository for the formula integration feature」 (`tests/formula-integration/README.md:3`)
- 의존: core, engine-formula, sheets, sheets-filter, sheets-formula
- 스펙: 수식 정확성, 수식 이동, 필터 행 삭제. 스냅샷 JSON이 `src/__snapshots__/`

단위 테스트는 각 패키지 vitest + 루트 `vitest.workspace.ts`의 `packages/*`. CI는 4 샤드 (`.github/workflows/ci-quality-checks.yml:34-36`).

---

## 15. `docs/` — 레포 로컬 문서

제품 가이드는 docs.univer.ai. 이 폴더는 기여자용.

| 파일 | 내용 |
| --- | --- |
| `docs/API_STABILITY.md` | stable / experimental / internal / deprecated, breaking change, 버전 정렬 |
| `docs/ISOMORPHIC.md` | 브라우저=Node 우선순위. 로직/UI 플러그인 분리, Facade는 양쪽, MUTATION은 UI 상태 금지 |
| `docs/NAMING_CONVENTION.md` | kebab-case 파일, `I` prefix 인터페이스, DI 토큰, 플러그인/커맨드/locale 키 |
| `docs/CONTRIBUTING-FACADE.md` | Facade는 AppScript 스타일. sync 우선, chaining, `univerAPI`에서 접근 |
| `docs/FIX_MEMORY_LEAK.md` | heap snapshot, dispose, 싱글톤에서 unit 구독 금지. Node 절은 `TODO @wzhudev` (`docs/FIX_MEMORY_LEAK.md:48`) |
| `docs/readme/{zh-CN,zh-TW,ja-JP,ko-KR,es-ES}.md` | README 번역 |
| `docs/img/` | banner, architecture, vitest, workspace mini-app |
| `docs/tldr/` | formula engine, web worker, permission, selection, ref-range, graphs `.tldr` |

### 15.1 API 안정성 요지 (`docs/API_STABILITY.md`)

- **Stable**: 공개 엔트리 + 문서화된 Facade/플러그인/커맨드/서비스. 메이저 전까지 제거 금지(pre-1.0은 마이너 제거 가능, breaking으로 문서화) (`docs/API_STABILITY.md:9-21,58`).
- **Experimental**: alpha/beta/preview, 활발히 개발 중인 서피스 (Slides가 해당될 수 있음).
- **Internal**: controllers/models/views, `@internal`. 앱이 의존하지 말 것 (`docs/API_STABILITY.md:35-46`).
- **Deprecated**: JSDoc `@deprecated`, `ILogService.deprecate`, 마이그레이션 문서 (`docs/API_STABILITY.md:48-58`, `CONTRIBUTING.md:216-223`).
- 문서와 export가 다르면 **문서를 공개 계약으로 보고 불일치를 제보** (`docs/API_STABILITY.md:94`).

문서가 아직 pre-1.0 언어를 쓰는 점은 §5.1.

### 15.2 네이밍 (`docs/NAMING_CONVENTION.md`)

- 파일/폴더 kebab-case. React 컴포넌트 파일은 PascalCase (`docs/NAMING_CONVENTION.md:7-23`).
- 폴더 복수, 파일 단수. `*.service.ts`, `*.controller.ts`, `*.command.ts` (`docs/NAMING_CONVENTION.md:25-54`).
- 인터페이스 `I` prefix (`docs/NAMING_CONVENTION.md:54-62`).
- DI 토큰: `createIdentifier<ILogService>('core.log.service')` (`docs/NAMING_CONVENTION.md:64-80`).
- 플러그인 상수: `SHEET_CONDITIONAL_FORMATTING_PLUGIN`. 클래스 `Univer*Plugin` (`docs/NAMING_CONVENTION.md:82-107`).
- 커맨드 id: `<business-type>.<command-type>.<command-name>`, 단수 (`docs/NAMING_CONVENTION.md:114-144`). 예: `sheet.command.set-selection-frozen`.
- locale 키 첫 세그먼트 = 패키지 이름. 크로스 패키지 참조 금지 (`docs/NAMING_CONVENTION.md:159-238`).

### 15.3 플러그인 폴더 규약 (`CONTRIBUTING.md:74-99`)

```text
common / models / services / commands/{commands,mutations,operations}
controllers / views/{components,parts} / plugin.ts / index.ts
```

import 방향: common ↛ 다른 폴더, models ← common, services ← models+common, commands ← common+models+services. 레거시 `Enum`/`Interface`/`Basics`/`Shared` 폴더는 제거 권장. 루트 `index.ts` 외 barrel 금지.

2024-06 이후 UI는 desktop/mobile 분리 (`CONTRIBUTING.md:101-120`).

---

## 16. 런타임 아키텍처 (클론 코드)

### 16.1 `Univer`

`packages/core/src/univer.ts:123`. `IUniverConfig` (`:63-118`): theme, darkMode, locale, region, direction `ltr|rtl`, locales, logLevel, logCommandExecution, undoRedoHistoryLimit(기본 50), override.

생성 시 Theme/Locale/Region/Log/Undo 설정을 주입하고 (`:142-160`) 인스턴스 타입별 생성자를 등록한다 (`:203-205`): `UNIVER_SHEET → Workbook`, `UNIVER_DOC → DocumentDataModel`, `UNIVER_SLIDE → SlideDataModel`.

공개 메서드: `registerPlugin`, `registerPlugins`, `createUnit`, `setLocale`, `setRegion`, `dispose`, `onDispose` (`:180-243`). Facade는 `univer.__getInjector()` (`:168-170`)로 내부 injector를 받는다.

### 16.2 플러그인

`Plugin` 추상 클래스 (`packages/core/src/services/plugin/plugin.service.ts:42-74`). 정적 필드 `pluginName`, `packageName`, `version`, `type`. 라이프사이클 훅: `onStarting` / `onReady` / `onRendered` / `onSteady`. `DependentOnSymbol`로 의존 플러그인.

라이프사이클 enum (`packages/core/src/services/lifecycle/lifecycle.ts:20-41`): Starting → Ready → Rendered → Steady.

### 16.3 커맨드

모든 데이터 변경은 커맨드 (`packages/core/src/services/command/command.service.ts:58-63`).

| `CommandType` | 의미 |
| --- | --- |
| `COMMAND = 0` | 비즈니스 오케스트레이션. MUTATION/OPERATION을 만듦 |
| `OPERATION = 1` | 스냅샷에 안 남는 변경 (스크롤, 사이드바). 충돌 해소 없음 |
| `MUTATION = 2` | 스냅샷에 남는 변경. 협업 시 최소 충돌 단위 |

id 패턴 `<namespace>.<type>.<command-name>` (`packages/core/src/services/command/command.service.ts:67-70`).

`docs/ISOMORPHIC.md:32-34`: MUTATION은 로직 플러그인에 두고 UI 상태를 읽지 말 것. Node와 브라우저에서 돌아가야 한다.

### 16.4 Facade

루트 `FUniver` (`packages/core/src/facade/f-univer.ts:74-89`): `FUniver.newAPI(univer)`. `extend`로 패키지가 prototype을 mixin (`:101-121`). 이벤트: LifeCycleChanged, Undo/Redo, CommandExecuted, BeforeUndo/BeforeRedo (`:144-214`).

Sheets mixin이 `createWorkbook` / `getActiveWorkbook` / `getWorkbook` / `getActiveSheet`을 붙인다 (`packages/sheets/src/facade/f-univer.ts:75-157`). 유닛 생성은 `IUniverInstanceService.createUnit(UNIVER_SHEET, data)` (`:161-165`).

설계 규칙 (`docs/CONTRIBUTING-FACADE.md`):

- Google Apps Script Spreadsheet를 참고 (`docs/CONTRIBUTING-FACADE.md:5`)
- 동기 API 우선. 비동기는 `addCommentAsync`처럼 이름에 표시 (`:32-35`)
- modify → `this`, create → 인스턴스, delete → boolean (`:39-43`)
- 모든 API는 `univerAPI`에서 (`:47`)

Preset Mode는 Facade 등록을 preset이 수행한다 (`README.md:230`). Plugin Mode는 `@univerjs/*/facade`를 앱이 import한다 (`README.md:186-191`).

### 16.5 유닛 타입

`UniverType` (`packages/protocol/src/ts/univer/constants/univer.ts:17-26`), `packages/core/src/common/unit.ts:18-21`에서 `UniverInstanceType`으로 re-export.

| 값 | 이름 | 이 클론의 구현 |
| --- | --- | --- |
| 0 | UNIVER_UNKNOWN | 기본 Plugin.type |
| 1 | UNIVER_DOC | `DocumentDataModel` + `@univerjs/docs*` |
| 2 | UNIVER_SHEET | `Workbook` + `@univerjs/sheets*` |
| 3 | UNIVER_SLIDE | `SlideDataModel` + `@univerjs/slides*` |
| 4 | UNIVER_PROJECT | 패키지 없음 |
| 5 | UNIVER_BASE | `BaseDataModel` 소스만. `Univer._init` 미등록 |
| 6 | UNIVER_BOARD | enum만 |
| 7 | UNIVER_PDF | enum만 |

### 16.6 Isomorphic / headless / RPC

`docs/ISOMORPHIC.md:1-4`: Node 지원이 브라우저와 **같은 우선순위**.

분리 규칙:

- 서버+클라이언트 기능은 최소 두 플러그인 (로직 / UI) (`docs/ISOMORPHIC.md:11-18`)
- `fs`/`path`/`child_process`는 server-only 플러그인 (`:20-21`)
- Facade는 로직 플러그인에 구현, `@univerjs/presets`가 합성 (`:25-29`)

RPC:

- 브라우저: `UniverRPCMainThreadPlugin` / `UniverRPCWorkerThreadPlugin` (`packages/rpc/README.md:37-40`)
- Node: `UniverRPCNodeMainPlugin` / `UniverRPCNodeWorkerPlugin` (`packages/rpc-node/README.md:37-40`)

네트워크 패키지 README는 「collaboration-oriented integrations」용 추상화라고 적는다 (`packages/network/README.md:7`). OSS에 협업 서버는 없다.

테마 export 예: `defaultTheme`, `darkBlueTheme`, `blueTheme`, `greenTheme`, `orangeTheme`, `purpleTheme`, `redTheme`, `yellowTheme` (`packages/themes/README.md:28`).

---

## 17. 보안

`SECURITY.md` 적용 범위: 「Univer (SDK and Univer Services)」 (`SECURITY.md:3`).

| 항목 | 내용 | 근거 |
| --- | --- | --- |
| 지원 버전 | `latest`만 | `SECURITY.md:9-11` |
| 보고 | `developer@univer.ai` 또는 GitHub private advisory | `SECURITY.md:19-21` |
| 응답 | 1 영업일 확인, 7–30일 수정 목표 | `SECURITY.md:27-29` |
| 탐지 | Dependabot, GitHub Security Alerts | `SECURITY.md:36` |
| 개발 | PR 1인 리뷰, CodeQL, 정기 펜테스트 | `SECURITY.md:50-55` |

Dependabot: npm, 주간, PR 한도 5 (`.github/dependabot.yml:8-13`). Semgrep 워크플로는 `main` 푸시에서만 (`.github/workflows/security-semgrep.yml:3-5`). 기본 브랜치는 `dev`라 이 클론 설정만 보면 Semgrep이 dev CI에 붙지 않는다.

---

## 18. CI와 릴리스

`.github/workflows/`:

| 워크플로 | 트리거 | 요지 |
| --- | --- | --- |
| `ci-quality-checks.yml` | `dev` push/PR | vitest 4샤드 + coverage, eslint, (이어서 typecheck 등) |
| `build-packages.yml` | `dev` push/PR | 패키지 빌드, 15분 |
| `release-npm.yml` | 태그 `v*.*.*`(alpha/beta/rc 포함) | `pnpm build` 후 `pnpm publish -r --provenance`. pre-release는 dist-tag |
| `dispatch-sync-univer-pro.yml` | `dev` push | `dream-num/univer-pro`에 `sync-univer` |
| `validate-pr-title.yml` | PR 제목 | conventional |
| `sync-gitee-mirror.yml` | Gitee 미러 |
| `collect-pr-metadata.yml` | PR 메타 |
| `security-semgrep.yml` | `main` | Semgrep |

릴리스 메시지: `chore(release): release v${version}`, 태그 `v${version}` (`verso.toml:17-20`). npm 퍼블리시는 `github.repository == 'dream-num/univer'`일 때만 (`.github/workflows/release-npm.yml:23`).

---

## 19. 하이라이트 (README가 약속하는 OSS 능력)

`README.md:86-131`:

- Canvas 렌더링 + 전용 수식 엔진 → 큰 워크북
- 플러그인 기본. 추가·제거·교체·lazy-load
- Headless Node → 에이전트·자동화
- Facade 하나로 workbook/range/formula/document, 브라우저와 Node 동일
- React / Vue / Web Components
- 다크 모드 (UI + 렌더 엔진)

「Why Univer」 여섯 줄 (`README.md:123-131`): isomorphic, plugin-first, preset, plugin mode, Facade, Canvas, extensible UI.

Quick Start Plugin Mode가 설치하는 패키지 (`README.md:153`): core, design, docs, docs-ui, engine-formula, engine-render, sheets, sheets-formula, sheets-formula-ui, sheets-numfmt, sheets-numfmt-ui, sheets-ui, ui. Preset Mode는 `@univerjs/presets` + `@univerjs/preset-sheets-core` (`README.md:233`).

---

## 20. 클론 안에서 보이는 문서 드리프트

조사 중 원문끼리 어긋난 점. 버그가 아니라 **이 스냅샷의 상태**.

| 불일치 | 내용 |
| --- | --- |
| 버전 vs API_STABILITY/SECURITY | 코드 `1.0.2`, 문서는 여전히 pre-1.0 (`docs/API_STABILITY.md:5`, `SECURITY.md:13`) |
| CHANGELOG | `1.0.0` 이후 항목 없음. 최신 헤더는 `1.0.0-beta.2` (`CHANGELOG.md:3`) |
| 한국어 README 스크립트 | `pnpm dev:source` 설명 (`docs/readme/ko-KR.md:368-369`). 루트 scripts에 없음 |
| 저작권 연도 | README 2021-present vs 소스 헤더 2023-present |
| verso 패키지 이름 | `DREAMNUM.md:28` `jikkai/verso` vs `package.json:47` `@amamo/verso` |
| RPC README 예시 경로 | `examples/src/sheets-mobile/worker.ts`, `examples/src/node/sdk/worker.ts` 없음 |
| Semgrep 브랜치 | 워크플로 `main`, 기본 브랜치 `dev` |
| CONTRIBUTING pnpm | `>=11` vs 고정 `pnpm@12.5.1` |

---

## 원본에서 확인한 사실 / 이 클론에 없는 것

### 원본(이 클론)에서 확인한 사실

- DreamNum `univer`는 Apache-2.0 모노레포이고, 루트·공개 패키지 버전이 **1.0.2**, 패키지 매니저 **pnpm 12.5.1**, 모노레포 개발 Node **>=22.18**, headless Node **>=18.17.0**이다 (`package.json`, `README.md:287`).
- 자기 정의는 **The Office Harness for AI Agents**이며, 서피스로 Sheets · Docs · Slides · Bases · Boards · PDFs(coming soon)를 내건다 (`README.md:5-7`). 동시에 **파일 뷰어가 아니라 임베드 SDK**라고 못 박는다 (`README.md:47`).
- 이 레포 범위는 OSS 코어·플러그인·preset·examples·테스트다 (`DREAMNUM.md:7-15`, `README.md:301-303`). Pro 협업·import/export·서버·엔터프라이즈는 소유하지 않는다.
- 공개 `@univerjs/*` 패키지 **60** + preset **17 + presets 메타**. Sheets가 가장 두껍고, Docs는 모델+UI+drawing/link/comment/toc, Slides는 모델+UI만(preset 없음).
- 런타임 축은 `Univer` + Plugin + Command(COMMAND/OPERATION/MUTATION) + Facade(`FUniver`) + Canvas(`engine-render`) + Formula(`engine-formula`, map 엔트리 516)다.
- 브라우저와 Node를 같은 우선순위로 두고, 로직/UI 플러그인을 가른다 (`docs/ISOMORPHIC.md`).
- Protocol enum은 DOC/SHEET/SLIDE뿐 아니라 PROJECT/BASE/BOARD/PDF 슬롯을 이미 가진다 (`packages/protocol/src/ts/univer/constants/univer.ts:17-26`). core에 `BaseDataModel` 소스가 있으나 `Univer` 부트스트랩은 SHEET/DOC/SLIDE만 등록한다.
- `dev` 푸시가 `dream-num/univer-pro`에 `sync-univer`를 보낸다. OSS와 Pro는 같은 커밋 라인으로 동기화되는 **별도 레포**다.
- 기본 브랜치 `dev`, 릴리스는 verso가 태그를 달고 GitHub Actions가 npm provenance publish한다.

### 이 클론에 없는 것

아래는 README/DREAMNUM/워크플로가 **이름을 대지만**, `/Users/yeonwoosung/Desktop/univer` 트리와 이 머신 Desktop에 **소스가 없다.**

| 없는 것 | 어디서 이름이 나오나 |
| --- | --- |
| Univer Pro 소스 (`@univerjs-pro/*`, collaboration server, import/export, charts, pivot, print, SSR) | `README.md:290-314`, `DREAMNUM.md:15`, tsdown의 `@univerjs-pro/` 분기 |
| Boards / PDF 패키지와 편집 표면 | 태그라인 `README.md:7`, enum `UNIVER_BOARD`/`UNIVER_PDF` |
| Base workbench UI · field editors · formula/workbench 플러그인 | `README.md:296,312`. core `bases/` 모델만 있음 |
| Slides preset, Pro slide import/export/charts | `README.md:295,311`. OSS는 `slides`+`slides-ui`와 examples Plugin Mode |
| `dream-num/univer-mcp` (MCP 서버) | `README.md:334`. 공개 README + start-kit 도구 30개는 [12](./12-ecosystem-agents.md) |
| `dream-num/univer-sdk-skills` / `dream-num/skills` (skill pack) | `README.md:327`. 현재 우산은 `dream-num/skills` |
| `dream-num/univer-workspace` | `README.md:60-69` |
| `dream-num/univer-cli` | `README.md:78` |
| `dream-num/dsh-univer-office` | `README.md:77` |
| `dream-num/workbuddy-univer-office` | `README.md:79` |
| `dream-num/openclaw-univer-office` | `README.md:80` |
| `dream-num/univer-icons` 소스 | `DREAMNUM.md:27` (npm `1.43.1`만) |
| `dream-num/documentation` | `docs/CONTRIBUTING-FACADE.md:51` |
| `dream-num/univer-pro` | `.github/workflows/dispatch-sync-univer-pro.yml:17` |
| examples의 mobile/node worker 트리 | RPC README가 가리키나 디렉터리 없음 |
| CHANGELOG의 1.0.0·1.0.1·1.0.2 섹션 | 태그와 커밋은 있음, 파일 본문 없음 |
| NOTICE 파일 | `LICENSE:106-116`가 NOTICE를 언급하나 루트에 없음 |

이 클론은 **Office SDK 런타임**이다. MCP 서버도, 에이전트 skill pack도, Workspace 앱도, Pro 협업 스택도 아니다. 에이전트가 붙는 지점은 이 레포의 **Facade · Command · headless Node preset**이고, 그 위 하네스(CLI, MCP, skills, DSH, OpenClaw, WorkBuddy)는 전부 다른 저장소다. 커맨드 ID는 609개, 빈 시트는 1000행×20열, 수식 에러 리터럴은 `#DIV/0!`부터 `#NULL!`까지 12종이다.
