# Univer Office Harness — Neos 분석 문서

DreamNum `univer` 클론(`/Users/yeonwoosung/Desktop/univer`, Apache 2.0, **v1.0.2**)을 전수 조사한 기록이다. 원본은 브라우저와 Node.js에서 같은 런타임으로 Spreadsheet · Document · Presentation을 임베드하는 Office SDK이며, README는 이를 **The Office Harness for AI Agents**라고 부른다.

이 디렉터리는 원본이 무엇을 제공하는지, 하네스(플러그인·커맨드·Facade)가 어떻게 생겼는지, 에이전트가 어떤 API로 문서를 다루는지, 어떤 라이브러리를 쓰는지 고정한다. `00`–`14`는 **원본 인벤토리**다. Neos 딥 하네스에 붙이는 구현 계약은 [spec/UNIVER_NEOS_MIGRATION_SPEC.md](./spec/UNIVER_NEOS_MIGRATION_SPEC.md)다.

조사 기준일: 2026-09-25. 클론 HEAD: `1defaf4ab67a63186331d37fbaec2958acd77680` (`chore(release): release v1.0.2`).

## 읽는 순서

| 문서 | 내용 |
|---|---|
| [00-overview.md](./00-overview.md) | 태그라인, OSS vs Pro, 레이아웃, 에코시스템, 이 클론에 없는 것 |
| [01-architecture-harness.md](./01-architecture-harness.md) | `Univer` · Plugin · DI(redi) · Command/Mutation · Undo · Lifecycle · Facade 부트 |
| [02-sheets-formula.md](./02-sheets-formula.md) | Sheets 플러그인 군, Workbook 모델, `engine-formula` (맵 516 / 구현 502) |
| [03-docs-slides-drawing.md](./03-docs-slides-drawing.md) | Docs 편집기, Slides 성숙도, Drawing, Canvas 엔진, Bases/PDF 슬롯 |
| [04-ui-presets.md](./04-ui-presets.md) | UI 워크벤치, Vue/WC 어댑터, preset 17개, Plugin/Preset/Headless |
| [05-network-rpc.md](./05-network-rpc.md) | HTTP/WS 클라이언트, Worker/Node RPC, protocol 타입. 협업 서버는 없음 |
| [06-libraries.md](./06-libraries.md) | `package.json` 84개 전수. 런타임 의존성과 빌드 툴체인 |
| [07-ai-agent-surface.md](./07-ai-agent-surface.md) | 에이전트가 실제로 호출하는 표면. 스킬/MCP는 별도 레포 |
| [08-packages.md](./08-packages.md) | `packages/` 60개 표 (Facade · UI · core/render/formula) |
| [09-facade-api.md](./09-facade-api.md) | `FUniver` mixin과 Workbook/Range/Document/Formula 메서드 |
| [10-cross-check.md](./10-cross-check.md) | 스위트 vs 소스 교차검증 |
| [11-commands-permissions.md](./11-commands-permissions.md) | COMMAND/MUTATION/OPERATION, 인터셉터, 권한 3층, 라이프사이클 |
| [11-command-ids.md](./11-command-ids.md) | 커맨드 ID 609개 전수 |
| [12-ecosystem-agents.md](./12-ecosystem-agents.md) | Skills · MCP · CLI · Workspace · DSH/WorkBuddy/OpenClaw (형제 레포) |
| [13-runtime-contracts.md](./13-runtime-contracts.md) | 스냅샷 JSON, OT, 유닛, 로케일, Canvas, examples |
| [14-formula-engine-internals.md](./14-formula-engine-internals.md) | Lexer → AST → Interpreter → dirty → worker |
| [spec/UNIVER_NEOS_MIGRATION_SPEC.md](./spec/UNIVER_NEOS_MIGRATION_SPEC.md) | Neos 딥 하네스 병합 마스터 스펙 |
| [spec/00-harness-and-profile.md](./spec/00-harness-and-profile.md) | `ParentKind.UNIVER`, 프로필 YAML, 네 kebab 리프 |
| [spec/01-tools-and-runtime.md](./spec/01-tools-and-runtime.md) | Node sidecar, `univer.*.v1` 도구 |
| [spec/02-skills-safety.md](./spec/02-skills-safety.md) | 스킬 팩 + 4층 안전 |
| [spec/agents/office-session.md](./spec/agents/office-session.md) | v0 오케스트레이터 그래프 |
| [spec/MIGRATION_PROCESS.md](./spec/MIGRATION_PROCESS.md) | live 트리 기준 착륙 순서 |

## 한 줄 요약

- **Office SDK 런타임**이지 에이전트 루프가 아니다. 에이전트는 Facade(`FUniver.newAPI`)와 `executeCommand`로 같은 커널을 구동한다.
- **플러그인 하네스:** `Univer`가 redi `Injector`를 만들고, 플러그인이 커맨드·서비스를 등록하며, COMMAND가 MUTATION을 오케스트레이션한다. UI와 로직 플러그인을 가른다 (`docs/ISOMORPHIC.md`).
- **공개 패키지 60 + preset 17.** Sheets가 가장 두껍다. Docs는 OSS 편집기로 쓸 수 있다. Slides는 모델+UI만 있고 preset/Facade가 없다.
- **수식 엔진** map 엔트리 **516**, 구현 디렉터리 **502**. Lexer → AST → Interpreter. 워커로 계산을 위임할 수 있다.
- **Canvas**는 `engine-render`의 Engine → Scene → Viewport → BaseObject. Drawing은 Docs/Sheets/Slides가 공유한다.
- **Headless Node**는 `preset-sheets-node-core` / `preset-docs-node-core` (UI·렌더 없음).
- **커맨드 609개** (command 367 / mutation 120 / operation 122). 에이전트는 COMMAND를 부르고 MUTATION은 오케스트레이션 결과다.
- **협업 서버, MCP, skill pack, Workspace, CLI, Pro(차트·피벗·import/export)** 는 이 클론에 없다. 형제 레포 인벤토리는 [12-ecosystem-agents.md](./12-ecosystem-agents.md).
- **Bases**는 `packages/core/src/bases/` 모델만. **Boards/PDF**는 protocol enum과 메타 타입만. PDF는 coming soon.

## 에이전트 구조 (이 클론 기준)

전형적인 tools/sandbox/skills 하네스가 아니라 **문서 런타임**이다.

```text
에이전트 루프 (이 레포 밖: CLI / MCP / Workspace / DSH / OpenClaw)
        │
        ▼
FUniver.newAPI(univer)     ← packages/core/src/facade
        │  side-effect mixin: @univerjs/sheets/facade, docs/facade, formula/facade
        ▼
createWorkbook / createDocument / executeCommand / FRange.setValue / FDocument.insertText / FWorkbook.save
        │
        ▼
ICommandService → MUTATION → Workbook | DocumentDataModel | SlideDataModel
        │
        ▼
engine-formula (선택) · engine-render (브라우저) · 로컬 undo 스택
```

스킬 팩의 현재 우산은 [`dream-num/skills`](https://github.com/dream-num/skills)다. README가 가리키는 [`univer-sdk-skills`](https://github.com/dream-num/univer-sdk-skills)는 구 팩(v0.21 문구). MCP는 호스티드 `mcp.univer.ai` + start-kit 도구 30개. CLI/Workspace/DSH는 Worktree + `execute`(Facade JS). 상세는 [12-ecosystem-agents.md](./12-ecosystem-agents.md).

## 원본 위치

```
/Users/yeonwoosung/Desktop/univer
```

원격: `https://github.com/dream-num/univer`. Marketplace/제품 사이트: https://univer.ai · 문서: https://docs.univer.ai.
