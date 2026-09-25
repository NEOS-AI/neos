# 10. 교차검증 부록

조사 기준: 2026-09-25. 문서 스위트 `docs/univer/00`–`07` + `README.md`를 `/Users/yeonwoosung/Desktop/univer` (HEAD `1defaf4ab67a63186331d37fbaec2958acd77680`, 태그 `v1.0.2`)와 대조했다. Univer 원본은 읽기만 했다.

이 파일은 다른 문서의 재작성본이 아니다. **스위트 주장 vs 소스**에서 어긋나거나 빠진 것만 적는다. 스위트가 소스와 일치하는 큰 그림(OSS SDK, Pro 별도, Facade/Command, headless preset, Slides preset 없음)은 반복하지 않는다.

검증 방법: `packages/` 60개·`presets/packages/` 17개·`package.json` 84개 전수 집계, `function-map.ts` 엔트리 재계산, `FUniver.extend` / `exports["./facade"]` grep, Authz·Segmenter·RPC README 경로 재확인.

---

## 1. 모순 · 오류

각 항목: 스위트 주장 → 소스 증거 → 교정.

### 1.1 수식 함수 개수 — `00-overview` 516 vs `02-sheets-formula` 513

**주장 (`02-sheets-formula.md` §3.2).** 카테고리 `function-map.ts`에서 주석 줄을 제외하면 합계 **513 이름**. 세부: compatibility 36, engineering 56, information 22, math 82.

**주장 (`00-overview.md` §10.6).** 같은 맵의 엔트리 합계 **516**. 세부: compatibility 38, engineering 57, information 23, math 81. `index.ts`가 있는 구현 디렉터리 502.

**증거.** `packages/engine-formula/src/functions/*/function-map.ts`를 재집계하면 주석 제외 엔트리는 다음이다.

| 카테고리 | 주석 제외 | `index.ts` 디렉터리 |
| --- | ---: | ---: |
| array | 2 | 2 |
| compatibility | **38** | 7 |
| cube | 0 (주석 7) | 7 |
| database | 12 | 12 |
| date | 27 | 27 |
| engineering | **57** | 57 |
| financial | 54 (주석 1, `AMORDEGRC`) | 55 |
| information | **23** (주석 2: `INFO`, `ISOMITTED`) | 23 |
| logical | 21 | 21 |
| lookup | 36 (주석 2) | 38 |
| math | **81** (주석 1: `ISO.CEILING`) | 82 |
| meta | 6 | 6 |
| statistical | 109 (주석 4) | 111 |
| text | 48 (주석 4) | 51 |
| univer | 0 | 0 |
| web | 2 (주석 1) | 3 |
| **합계** | **516** | **502** |

`ALL_IMPLEMENTED_FUNCTIONS`는 이 맵을 그대로 이어 붙인다 (`packages/engine-formula/src/functions/index.ts:37-54`).

**교정.** 권위 숫자는 **516 map 엔트리 / 502 구현 디렉터리**다. `02`의 513과 compatibility/engineering/information/math 칸은 오집계다. `00` 표가 소스와 맞다. 별칭 중복(`FORECAST`+`FORECAST.LINEAR` 등)을 빼면 “서로 다른 Excel 함수 516개”는 아니라는 `02`의 주의는 그대로 유효하다.

---

### 1.2 Sheets UI Facade — `02`가 “numfmt-ui만 없다”고 함

**주장 (`02-sheets-formula.md` §1).** “UI 패키지 중 `sheets-numfmt-ui`만 Facade가 없다.”

**증거.** `packages/*/package.json`의 `exports["./facade"]` 기준, Sheets UI 계열에서 Facade export가 **없는** 패키지:

- `sheets-numfmt-ui`
- `sheets-conditional-formatting-ui`
- `sheets-data-validation-ui`
- `sheets-filter-ui`
- `sheets-sort-ui`
- `sheets-thread-comment-ui`

반대로 `sheets-formula-ui`, `sheets-ui`, `sheets-drawing-ui`, `sheets-hyper-link-ui`, `sheets-crosshair-highlight`는 Facade가 있다.

추가로 `sheets-note-ui`와 `sheets-table-ui`는 `package.json`에 `"./facade": "./src/facade/index.ts"`를 **선언만** 하고, `src/facade/` 디렉터리는 **없다**.

**교정.** numfmt-ui만 빠진 것이 아니다. 로직 패키지(`sheets-numfmt`, `sheets-filter` 등)에 Facade가 있고 UI 쌍에는 없는 패턴이 다수다. `note-ui`/`table-ui`는 매니페스트만 있는 깨진 export다.

---

### 1.3 `data-validation`을 “공유”로 적은 `00`

**주장 (`00-overview.md` §10.5).** `@univerjs/data-validation` — “공유 데이터 유효성 모델”.

**증거.** 플러그인 `type = UniverInstanceType.UNIVER_SHEET` (`packages/data-validation/src/plugin.ts:31-35`). README도 “used by sheet data validation features”. Docs DV 패키지는 없다. `03-docs-slides-drawing.md` §9.2는 이 점을 올바르게 고친다.

**교정.** 이름은 공유처럼 보이지만 **Sheets 전용**이다. `00`의 “공유”는 오해 소지.

---

### 1.4 `UNIVER_BASE` = “Base 패키지” (`01`)

**주장 (`01-architecture-harness.md` §8 표).** `UNIVER_BASE` 코어 모델 = “Base 패키지”.

**증거.** `packages/bases*` 없음. `BaseDataModel`만 `packages/core/src/bases/base-data-model.ts:38`. `Univer._init`은 SHEET/DOC/SLIDE만 등록 (`packages/core/src/univer.ts:203-205`). `00` §7.3·`03` §10.1이 맞다.

**교정.** Base **패키지가 아니라** 코어 모델 타입만 있다. workbench/commands/UI는 Pro 쪽 README 칸.

---

### 1.5 `preset-sheets-core` 플러그인 목록 인용 (`00`)

**주장 (`00-overview.md` §11.1).** `preset-sheets-core`가 묶는 플러그인을 `presets/packages/preset-sheets-core/src/preset.ts:23-36`으로 적고, “RPC main”을 항상 넣는 것처럼 나열한다.

**증거.** `:23-36`은 **import**다. 실제 `plugins` 배열은 `:110-165`. `UniverRPCMainThreadPlugin`은 `workerSrc`가 있을 때만 들어간다 (`:127-129`). `04-ui-presets.md` §6 표(“optional RPCMainThread”)가 맞다.

**교정.** 라인은 `:110-165`. RPC는 워커 URL이 있을 때만.

---

### 1.6 Facade 이벤트 라인 (`00`)

**주장 (`00-overview.md` §16.4).** `FUniver` 이벤트 LifeCycleChanged, Undo/Redo, CommandExecuted, BeforeUndo/BeforeRedo를 `packages/core/src/facade/f-univer.ts:144-214`로 묶음.

**증거.** `:144-214`는 LifeCycleChanged + Undo/Redo + CommandExecuted까지다. `BeforeRedo`/`BeforeUndo`는 `_initBeforeCommandEvent` `:217-246`.

**교정.** Before* 구독은 `:217-246`. 이벤트 이름 자체는 `f-event.ts:231-263`.

---

### 1.7 `Univer` 공개 메서드 라인 (`00`)

**주장 (`00-overview.md` §16.1).** 공개 메서드 `registerPlugin` / `registerPlugins` / `createUnit` / `setLocale` / `setRegion` / `dispose` / `onDispose`를 `:180-243`으로 묶음.

**증거.** `onDispose` `:180`, `createUnit` `:198-200`, `registerPlugin` `:241-243`, **`registerPlugins` `:249-271`**. `01`의 `:241-271`이 `registerPlugin(s)`에 더 정확하다.

**교정.** `:180-243`은 `registerPlugins`를 잘라 먹는다. 범위는 `:180-271`.

---

### 1.8 문서 `rev` 시작값 — 타입 주석 0 vs 구현 기본 1

**주장 (`03-docs-slides-drawing.md` §3.1).** `IDocumentData.rev`는 “협업용, **0부터**”.

**주장 (`01-architecture-harness.md` §8).** `UnitModel.getRev()` — “revision은 **1부터**”.

**증거.** 둘 다 소스에 있다.

- 타입 주석: “Starts with zero.” (`packages/core/src/types/interfaces/i-document-data.ts:32`)
- 워크북 타입: “Starts from one.” (`packages/core/src/sheets/typedef.ts:39`)
- `UnitModel` 주석: “revision should start from 1.” (`packages/core/src/common/unit.ts:36`)
- `DocumentDataModel.getRev()`는 `this.snapshot.rev ?? 1` (`document-data-model.ts:146-148`)

**교정.** 스위트 내부 모순이라기보다 **원본 주석이 갈라진 상태**다. 런타임 기본은 문서도 `?? 1`. “0부터”는 타입 JSDoc만의 문장이고, 빈 스냅샷에서 `getRev()`는 1이다.

---

### 1.9 Authz 스텁을 “Owner/Editor 전부 허용”으로만 요약 (`01`)

**주장 (`01-architecture-harness.md` §12 표).** `AuthzIoLocalService` — “Owner/Editor 전부 허용. 협업자 API는 no-op”.

**증거.** `allowed()` 폴백은 실제로 Owner **또는** Editor (`authz-io-local.service.ts:157-175`). 그러나 `create()`가 넣는 기본 `strategies`는 **Owner 액션만** (`:129-144`, action 6/16–19/33–40). strategy가 있으면 그 role만 본다 (`:178-182`). 주석은 “Do not use the mock implementation in a production environment” (`:41-54`). collaborator list/role/update는 빈 구현이 맞다.

**교정.** “전부 허용”은 objectID가 없거나 strategy가 없을 때의 폴백이다. 생성된 보호 객체는 Owner 전략이 기본이다. 프로덕션 금지 주석은 표에 남겨야 한다.

---

### 1.10 React 18 워크벤치 (`04`) vs 워크스페이스 핀 19.3.0

**주장 (`04-ui-presets.md` §1).** “Univer UI는 React **18** 워크벤치다.”

**증거.** README는 “view layer is built on React 18, supports React 18 and 19, minimal compatibility 16.9+/17” (`README.md:285`). 워크스페이스 override와 examples는 `react`/`react-dom` **19.3.0** (`pnpm-workspace.yaml`, `examples/package.json`). peer specifier는 `^16.9 \|\| ^17 \|\| ^18 \|\| ^19`.

**교정.** 설계 기준은 React 18, **이 클론이 실제로 까는 버전은 19.3.0**. “React 18 워크벤치”만 적으면 핀이 가려진다. `00` §5.2가 더 정확하다.

---

### 1.11 `07` FUniver.extend 목록은 맞지만 Facade 표면을 다 덮지 않음

**주장 (`07-ai-agent-surface.md` §3.5).** `FUniver.extend` 호출 패키지 19개를 나열. Slides facade 없음.

**증거.** `FUniver.extend(` grep 결과는 그 19개(+테스트)와 일치한다. 그러나 `exports["./facade"]`가 있는 패키지는 더 많다. extend 없이 `FRange`/`FWorksheet`/`FDocument` mixin만 하는 예: `sheets-formula`, `sheets-numfmt`, `sheets-table`, `sheets-conditional-formatting`, `docs-drawing`, `docs-thread-comment`, `docs-ui`.

**교정.** §3.5 제목을 “FUniver.extend 호출”로 읽으면 맞다. “이 클론의 Facade 패키지 전체”로 읽으면 빠진다. Slides에 facade 디렉터리가 없다는 결론은 유효하다.

---

### 1.12 `00` CommandType 인용 라인

**주장 (`00-overview.md` §16.3).** “모든 데이터 변경은 커맨드 (`command.service.ts:58-63`)”.

**증거.** 그 문장은 `:58-60`의 블록 주석이 맞다. `CommandType` enum 본체는 `:37-55`. `01` §5가 enum+주석을 같이 가리킨다.

**교정.** 내용 오류는 아니다. enum 값을 인용할 때는 `:37-55`.

---

## 2. 스위트에 없거나 얕은 중요 사실

아래는 소스가 보여 주는데 `00`–`07`이 거의 안 적었거나, 한 줄만 있고 검증이 없는 항목이다.

### 2.1 수식 함수 개수 검증

`00`과 `02`가 다른 합계를 들고 있어, 스위트만 보면 513인지 516인지 알 수 없다. 소스 재집계는 **516 / 502** (§1.1). cube 구현 디렉터리 7개는 맵이 전부 주석이라 `ALL_IMPLEMENTED_FUNCTIONS`에 안 들어간다.

### 2.2 패키지 수 60 vs 목록

`packages/` 디렉터리 **60**, 전부 `@univerjs/*` `private: false` `version: 1.0.2`. `00` §10 표(런타임 10 + Sheets 26 + Docs 11 + Slides 2 + 공유 11)를 세면 **60과 일치**한다. 목록 누락은 없다. `presets/packages/` 17 + `presets` 메타, `package.json` 84도 `06`과 맞다.

빠진 것은 “60 vs listed” 불일치가 아니라, **매니페스트만 있는 facade**(`sheets-note-ui`, `sheets-table-ui`)와 **UI 쌍에 facade가 없는 목록**이다 (§1.2).

### 2.3 Authz / Mention / Undo 스텁

`01` §10·§12와 `05` §8.3이 가장 두껍다. 그래도 스위트가 약하게 두는 점:

- 기본 바인딩은 `AuthzIoLocalService` (비-lazy) + `MentionIOLocalService` (lazy) + `LocalUndoRedoService` (lazy) (`packages/core/src/univer.ts:289-296`).
- 리소스 훅 이름 `SHEET_AuthzIoMockService_PLUGIN`. businesses에 SHEET/DOC/SLIDE/**BOARD** (`authz-io-local.service.ts:102-108`).
- `createUniver({ collaboration: true })`는 세 토큰을 **null로 제거만** 한다. 대체 구현을 넣지 않는다 (`presets/src/preset.ts:51-55`). drawing preset은 여기에 `IImageIoService`도 null.
- 헤드리스 에이전트는 기본 Owner라 권한 게이트가 거의 통과한다. 멀티유저 권한을 이 스텁에 기대면 안 된다.

`07`은 “권한 게이트 없음” 한 줄로 접는다. 에이전트 표면 문서에 스텁 계약을 더 명시해야 한다.

### 2.4 `Intl.Segmenter` 폴리필 — README만 있고 의존성은 없음

`00` §5.2는 README 문장만 옮긴다: Univer는 `Intl.Segmenter`에 의존, `@formatjs/intl-segmenter`를 쓰라는 안내 (`README.md:283`).

소스에서 확인한 추가 사실:

- **어느 `package.json`에도 `@formatjs/intl-segmenter`가 없다.** 폴리필을  bundling하지 않는다.
- 실제 호출: `packages/engine-render/src/basics/tools.ts:410` (모듈 로드 시 `new Intl.Segmenter`, grapheme), `packages/core/src/docs/data-model/document-statistics.ts:108-109`, `packages/docs-ui/src/services/selection/word-boundary.ts:30`, `packages/docs-find-replace/src/controllers/utils.ts:45`.
- format painter만 가드가 있다. `typeof Intl.Segmenter === 'function'`가 아니면 정규식 폴백. 주석: “Safari 14.1 and Firefox 90 do not provide Intl.Segmenter.” (`packages/docs-ui/src/commands/commands/format-painter.command.ts:175-179`).
- README 브라우저 타깃(Safari `>=14.1`, Firefox `>=90`)과 Segmenter 요구가 **겹친다**. 그 타깃에서 엔진 `tools.ts`의 최상위 `new Intl.Segmenter`는 폴리필 없이 throw할 수 있다.

스위트는 “README가 폴리필을 말한다”까지만 있고, **미번들 + 가드 불일치**는 없다.

### 2.5 RPC README가 가리키는 examples 경로

`00` §12·`05` §3·`07` §4.3이 이미 “그 파일 없음”을 적는다. 보강: 실제 워커 엔트리는 `presets/packages/preset-sheets-core/src/worker.ts`, `preset-sheets-node-core/src/worker.ts`, `examples/src/docs/worker.ts`. `examples/src/sheets-mobile/`, `examples/src/node/`는 디렉터리 자체가 없다.

### 2.6 Facade export와 `src/facade` 불일치

`sheets-note-ui` / `sheets-table-ui`는 `package.json` exports만 있고 소스 파일이 없다. 빌드된 npm 패키지와 이 클론 소스가 다를 수 있다. 스위트는 “Facade 있음/없음”을 매니페스트 또는 mixin 중 하나만 보고 이 깨짐을 안 적었다.

### 2.7 `onMutationExecutedForCollab` 리스너는 하나

`05` §8.2가 적는다. 스위트 나머지(특히 `07` 에이전트 관측)는 `CommandExecuted`만 말하고, collab 훅이 **단일 리스너**·프로덕션 구독자 없음·테스트/clipboard spec만 사용이라는 점을 에이전트 계약으로 끌어오지 않는다.

### 2.8 수식 워커와 필터 `rowData`

`02` §3.4가 한 줄로 적는다: 필터 행 숨김은 워커에 없어서 start 뮤테이션마다 메인이 `rowData`를 실어 보낸다. `05` RPC 장에는 이 제약이 약하다. 헤드리스+워커 에이전트는 필터 상태 동기화를 메인에 의존한다.

### 2.9 Docs `rev` vs Sheets `rev` 주석

§1.8. import/export·협업 서버가 없는 OSS에서 에이전트가 `rev`를 버전 시계로 쓰면, 문서 타입 JSDoc(0) / 구현 기본(1) / 시트(1)가 다르다.

### 2.10 CHANGELOG는 1.0.0 이후가 비어 있음

`00` §5.1·§20이 이미 적는다. `07`이 인용하는 “agent-friendly” CHANGELOG 줄(`#7329` `:145`, `#7243` `:296`)은 **`## [1.0.0-beta.2]` 섹션 안**이다. 태그 `v1.0.2`와 changelog 헤더가 어긋난 채로 에이전트 API 연혁을 changelog에 의존하면 안 된다.

---

## 3. 확인만 하고 넘어간 것 (오류 아님)

스위트가 소스와 맞아서 교정할 필요 없는 표본.

| 항목 | 결과 |
| --- | --- |
| HEAD / 태그 / 원격 / 기본 브랜치 `dev` | `00`과 일치 |
| 루트·공개 패키지 `1.0.2`, `pnpm@12.5.1`, Node 개발 `>=22.18`, headless `>=18.17.0`, CI `node@24.3.0` | 일치 |
| `packages/` 60, preset 17, `package.json` 84 | 일치 (`06` §0) |
| peer 패턴 26 / 23 / 18 / 1 / 1 / 15 | `06` §3.1과 일치 |
| 서드파티 runtime deps가 있는 `packages/*`는 core / design / engine-formula / engine-render / protocol / ui(redi) | `06` §1과 일치 |
| `createUniver` collaboration null override | `presets/src/preset.ts:51-55` |
| Slides preset 없음, examples는 Plugin Mode | 일치 |
| `UNIVER_PDF` 심볼 사용처는 protocol enum 1곳 | 일치 |
| `SKILL.md` 0, MCP 구현 0, `sandbox` 문자열 0 | `07`과 일치 |
| `screenshot` 문자열은 README `:138` 한 줄, Facade 스크린샷 API 없음 | `07`과 일치 |
| 한국어 README `pnpm dev:source`, 루트 scripts에 없음 | `00` §20과 일치. 다른 번역 README도 동일 |
| `docs/API_STABILITY.md`·`SECURITY.md`의 pre-1.0 언어 vs 버전 1.0.2 | `00` 드리프트 표와 일치 |
| vitest 4샤드, `vitest.workspace.ts`는 `packages/*`만 | 일치 |
| 로케일 enum 19종 | `locale-type.ts:20-40` |
| STEADY 3000ms, 헤드리스는 Ready에서 정지 | `ui-shared.controller.ts:23,94-96` |
| `IPreset.locales` / `lazy`는 `createUniver`가 안 씀 | `04` §7과 일치 |

파일 규모 “약” 표기 (`03` slides ~22 TS, slides-ui ~70, engine-render ~360)는 실제 21 / 68 / 357이라 근사로 허용.

---

## 4. 한 줄

스위트의 큰 그림은 클론과 맞다. 고쳐 읽어야 하는 숫자는 **수식 맵 516(02의 513은 오집계)**, **Sheets UI Facade는 numfmt-ui만 빠진 게 아님**, **`data-validation`과 Base는 공유/패키지가 아님**이다. 빠져 있는 운영 사실은 **Authz 로컬 스텁의 프로덕션 금지·Owner 기본 전략**, **`Intl.Segmenter` 미번들 + 타깃 브라우저 가드 공백**, **`note-ui`/`table-ui`의 빈 facade export**다.

---

## 5. 2차 조사에서 추가로 고친 것 (2026-09-25)

1차 스위트에 없거나 틀린 운영 사실. 본문은 `11`–`14`.

| 항목 | 1차 | 2차 |
| --- | --- | --- |
| 커맨드 ID 개수 | 일부 예시만 | **609** (command 367 / mutation 120 / operation 122) |
| HTTP interceptor 우선순위 | JSDoc대로 큰 숫자 먼저 | 구현·테스트는 **낮은 priority 먼저** |
| DataSync `onlyLocal` | replica 동기화 억제로 읽힘 | DataSync는 `fromSync` + allowlist. `onlyLocal`은 안 봄 |
| 원격 커스텀 함수 | 워커 등록 가능처럼 읽힘 | 역직렬화 **throw** (unsafe) |
| `IDocumentBody` 표 토큰 JSDoc | `\x1E`/`\x1F` 표 끝 | 구현은 `\x0E`/`\x0F`. `\x1E`/`\x1F`는 custom range |
| 스킬 팩 | `univer-sdk-skills`만 | 현재 우산 `dream-num/skills`. CLI 운영 스킬은 바이너리 안 |
| MCP 도구 | 링크만 | start-kit 이름 **30개**. `univer-mcp` 레포에는 소스 없음 |
| protocol | 타입만 | `.proto` 없음. 체크인된 TS 서비스 인터페이스. protobufjs allowBuilds false |
| numfmt | 자체 구현 | vendored MIT **numfmt 3.2.6** |
| Node RPC | worker로 뭉뚱그림 | **`child_process.fork`**, `worker_threads` 없음 |
| 빈 시트 | 언급 없음 | 1000×20, 행 24px, 열 88px |
| collab mutation listener | “하나만” | **배열**. 같은 함수 두 번이면 throw |
