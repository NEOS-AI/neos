# Univer는 AI 에이전트용 Office 하네스인가

조사 범위는 클론 `/Users/yeonwoosung/Desktop/univer` (버전 `1.0.2`)뿐이다. README가 가리키는 `univer-sdk-skills`, `univer-mcp`, `univer-cli`, `dsh-univer-office`, `univer-workspace`는 **이 워크스페이스에 클론되어 있지 않다.** 아래 인용은 이 클론의 파일:라인이다.

**한 줄 결론.** 이 레포는 에이전트 루프·MCP 서버·스킬 팩이 아니다. 브라우저와 Node에서 같은 명령/모델로 문서·시트를 돌리는 **Office 런타임/SDK**다. README가 “The Office Harness for AI Agents”라고 부르는 이유는 Facade가 에이전트가 호출할 수 있는 구조화 API이기 때문이지, 전형적인 에이전트 하네스(tools / sandbox / skills / MCP)가 여기 들어 있기 때문이 아니다.

2차 조사에서 형제 레포 공개 README를 읽었다. 전문은 [12-ecosystem-agents.md](./12-ecosystem-agents.md). 현재 스킬 우산은 `dream-num/skills`. Hosted MCP는 `mcp.univer.ai` + start-kit 도구 30개. CLI/Workspace/DSH는 Worktree + Facade `execute`. OSS 정본 경로는 여전히 `FUniver` + `executeCommand` + `save()`.

---

## 1. README가 약속하는 세 가지

배너와 부제는 이 제품을 에이전트용 Office 하네스로 포지셔닝한다.

```5:12:/Users/yeonwoosung/Desktop/univer/README.md
**The Office Harness for AI Agents**

Spreadsheets · Documents · Presentations · Bases · Boards · PDFs (coming soon)

High-performance, fully customizable Office SDK

Build embeddable productivity experiences with a plugin architecture, Canvas-based rendering,
a formula engine, and one Facade API that works in the browser and on Node.js.
```

에이전트 워크플로 섹션은 세 축을 적는다.

```133:141:/Users/yeonwoosung/Desktop/univer/README.md
## 🤖 Office Workflows for AI Agents

Univer's AI and collaboration capabilities connect agent operations with interactive editing and human review:

- **Programmatic editing**: agents inspect and modify Office content through structured APIs.
- **Output verification**: agents check results through content inspection, rendered screenshots, and layout diagnostics.
- **Worktree collaboration**: agents work in isolated drafts, then people review their changes and decide what to merge.

See the [AI SDK documentation](https://docs.univer.ai/ai) for integration details. Live editing, shared revisions, and Worktree workflows require the corresponding Web SDK and collaboration capabilities; package availability and licensing vary by feature.
```

같은 README는 이 세 축의 구현 본체가 **다른 GitHub 레포 / Pro 패키지 / 외부 문서**에 있다고 바로 밝힌다.

| README가 가리키는 것 | 이 클론에 있는가 |
| --- | --- |
| `dream-num/univer-sdk-skills` — AI agent skills | 없음. Ecosystem 링크만 (`README.md:327`) |
| `dream-num/univer-mcp` — MCP로 Sheets 조작 | 없음. Ecosystem 링크만 (`README.md:334`) |
| `dream-num/univer-cli` — 로컬 CLI 워크스페이스 | 없음. 표 링크만 (`README.md:78`) |
| `dream-num/dsh-univer-office` — DeepSeek Harness 플러그인 + isolated worktrees | 없음 (`README.md:77`) |
| `dream-num/univer-workspace` — 사람+에이전트 워크스페이스 | 없음 (`README.md:62`) |
| `docs.univer.ai/ai` — AI SDK | 외부 문서. 이 클론 `docs/`에는 없음 |
| Worktree / live editing / shared revisions | “Web SDK and collaboration capabilities” 필요, 라이선스 상이 (`README.md:141`) |

에코시스템 목록 원문:

```323:334:/Users/yeonwoosung/Desktop/univer/README.md
## 🌐 Ecosystem

- **Core SDK**: [`dream-num/univer`](https://github.com/dream-num/univer), this monorepo.
- **Presets**: this repository's [`presets/`](./presets), curated plugin collections for browser and Node.js apps.
- **AI agent skills**: [`dream-num/univer-sdk-skills`](https://github.com/dream-num/univer-sdk-skills), reusable instructions for AI agents working with Univer integration, Pro features, plugin development, and Node backends. See the [AI Skills guide](https://docs.univer.ai/guides/skills).
...
- **AI SDK**: [agent workflows](https://docs.univer.ai/ai) for inspecting, editing, and verifying Office content.
...
- **AI-native spreadsheets**: [`dream-num/univer-mcp`](https://github.com/dream-num/univer-mcp), Univer Platform / MCP integration for driving Univer Sheets with natural language.
```

Open Source vs Pro 표도 이 레포 경계를 고정한다. 협업·히스토리·import/export·인쇄·차트·서버 계산은 Pro다 (`README.md:301–312`). OSS에 있는 것은 코어 SDK, 플러그인, 렌더/수식 엔진, Facade, **Node.js headless runtime**이다 (`README.md:305–312`).

---

## 2. 이 클론이 실제로 제공하는 “에이전트 표면”

전형적인 에이전트 하네스와 Univer OSS의 대응은 아래와 같다.

| 전형적인 에이전트 하네스 | Univer OSS (`dream-num/univer`) | 이 클론의 증거 |
| --- | --- | --- |
| Agent loop (think → tool → observe) | 없음 | 루프/오케스트레이터 패키지 없음 |
| Tool schema / MCP server | 없음. 외부 `univer-mcp` | `SKILL.md` 0건, `mcp` 구현 0건 (README 링크만) |
| Skills (`SKILL.md`) | 없음. 외부 `univer-sdk-skills` | `SKILL.md` 검색 결과 없음 |
| Sandbox | 없음 | `sandbox` 문자열 0건 |
| Structured document API | **Facade** (`FUniver` / `FWorkbook` / `FRange` / `FDocument`) | `packages/core/src/facade`, 플러그인 mixin |
| Mutation protocol | **Command / Mutation** (`executeCommand`) | `FUniver.executeCommand` |
| Headless runtime | **Node presets** (UI·render 없음) | `preset-sheets-node-core`, `preset-docs-node-core` |
| Content verification | **snapshot `save()`**, 수식 에러, `describe()` | Facade + resource loader |
| Screenshot | Canvas `toDataURL`만. Facade 스크린샷 API 없음 | `engine-render/src/canvas.ts` |
| Layout diagnostics | 모델 요약은 있음. 픽셀 레이아웃 Facade는 없음 | `getCustomBlockLayout`, `describe()`, 내부 executor `diagnostic` |
| Isolated drafts / Worktree | **이 레포에 구현 없음** | CLI/Workspace/DSH 형제 레포. [12](./12-ecosystem-agents.md) |

에이전트가 이 SDK를 쓰는 경로를 한 줄로 쓰면:

`createUniver` / `FUniver.newAPI` → `createWorkbook` / `createDocument` → `FRange` / `FDocument`로 읽고 쓰기 → `executeCommand`가 실제 mutation → `save()`로 스냅샷 검증 → (브라우저 UI가 있을 때만) canvas `toDataURL`.

Command는 도구(tool)가 아니다. 문서 런타임의 트랜잭션이다. Facade는 그 트랜잭션 위의 Google Apps Script 스타일 API다 (`docs/CONTRIBUTING-FACADE.md:3–5`).

---

## 3. Programmatic editing — Facade가 에이전트가 호출하는 API

### 3.1 진입점

`FUniver.newAPI(univer)`가 루트 핸들이다.

```69:89:/Users/yeonwoosung/Desktop/univer/packages/core/src/facade/f-univer.ts
 * The root Facade API object to interact with Univer. Please use `newAPI` static method
 * to create a new instance.
...
    static newAPI(wrapped: Univer | Injector): FUniver {
        const injector = wrapped instanceof Univer ? wrapped.__getInjector() : wrapped;
        return injector.createInstance(FUniver);
    }
```

Preset 경로는 `createUniver`가 플러그인을 등록한 뒤 같은 핸들을 돌려준다.

```48:103:/Users/yeonwoosung/Desktop/univer/presets/src/preset.ts
export function createUniver(options: CreateUniverOptions) {
    ...
    // Finally we wrap all plugins into a Facade API to make it for convenient usage.
    const univerAPI = FUniver.newAPI(univer);
    return {
        univer,
        univerAPI,
    };
}
```

플러그인은 `FUniver.extend(...)`로 메서드를 붙인다. 코어 `FUniver`만으로는 시트/문서/수식이 없다. 시트 mixin, 문서 mixin, 수식 mixin을 import해야 한다. Node preset이 그 import를 대신 한다 (`presets/packages/preset-sheets-node-core/src/preset.ts:32–40`).

### 3.2 코어 `FUniver` — 에이전트가 항상 쓸 수 있는 것

`packages/core/src/facade/f-univer.ts`에 있는 공개 메서드(에이전트 관점):

| 메서드 | 역할 | 라인 |
| --- | --- | --- |
| `newAPI` | 인스턴스 래핑 | 86 |
| `disposeUnit(unitId)` | 유닛 언로드 | 328 |
| `getCurrentLifecycleStage()` | 라이프사이클 | 342 |
| `undo()` / `redo()` | 편집 취소/재실행 | 356, 369 |
| `executeCommand(id, params?, options?)` | 비동기 커맨드 | 547 |
| `syncExecuteCommand(id, params?, options?)` | 동기 커맨드 | 570 |
| `addEvent` / `fireEvent` | 이벤트 | 615, 630 |
| `getUserManager()` | 현재 사용자 | 642 |
| `newBlob()` / `newRichText()` | 빌더 | 654, 669 |
| `setTheme` / `setLocale` / `setRegion` / `toggleDarkMode` | 테마·로케일 | 389–431 |

커맨드 실행 예시가 시트 값 쓰기다. Facade를 건너뛰고 command id를 직접 부르는 탈출구다.

```532:553:/Users/yeonwoosung/Desktop/univer/packages/core/src/facade/f-univer.ts
     * Execute a command with the given id and parameters.
...
     * univerAPI.executeCommand('sheet.command.set-range-values', {
     *   value: { v: "Hello, Univer!" },
     *   range: { startRow: 0, startColumn: 0, endRow: 0, endColumn: 0 }
     * });
...
    executeCommand<P extends object = object, R = boolean>(
        id: string,
        params?: P,
        options?: IExecutionOptions
    ): Promise<R> {
        return this._commandService.executeCommand(id, params, options);
    }
```

이벤트 레지스트리는 커맨드 전/후를 구독한다. `CommandExecuted`, `BeforeCommandExecute`, `Undo`/`Redo`, `LifeCycleChanged`, `DocCreated`/`DocDisposed` (`packages/core/src/facade/f-event.ts:154–280`, `f-univer.ts:171–273`). 에이전트 루프의 tool-result 스트림이 아니라, 문서 런타임의 내부 버스다.

코어 주석은 이미 “agent code”를 상정한다. 저수준 문서 데이터는 에이전트가 쓰지 말라는 뜻이다.

```673:677:/Users/yeonwoosung/Desktop/univer/packages/core/src/facade/f-univer.ts
     * This is an advanced integration escape hatch for importers and adapters. Application and agent code should use
     * the fluent builder returned by `newRichText()`.
```

`RichTextBuilder.text()`도 “agent-friendly alias”다 (`packages/core/src/docs/data-model/rich-text-builder.ts:2237–2238`).

### 3.3 Sheets mixin — 워크북/시트/레인지

`@univerjs/sheets/facade`가 `FUniver`에 붙이는 것:

```75:117:/Users/yeonwoosung/Desktop/univer/packages/sheets/src/facade/f-univer.ts
export interface IFUniverSheetsMixin {
    createWorkbook(data: Partial<IWorkbookData>, options?: ICreateUnitOptions): FWorkbook;
    getActiveWorkbook(): FWorkbook | null;
    getWorkbook(id: string): FWorkbook | null;
    getSheetCommandTarget(...): { workbook; worksheet; unitId; subUnitId } | null;
    getActiveSheet(): { workbook: FWorkbook; worksheet: FWorksheet } | null;
    setFreezeSync(enabled: boolean): void;
}
```

에이전트 편집의 핵심은 `FWorkbook` → `FWorksheet` → `FRange`.

- `FWorkbook.save()`: 플러그인 리소스까지 포함한 스냅샷 (`packages/sheets/src/facade/f-workbook.ts:169–183`)
- `FWorkbook.getActiveSheet()` / `getSheets()` / `create(name, rows, columns)` (`f-workbook.ts:197–227`)
- `FWorksheet.getRange('A1:B2')` A1 표기 (`packages/sheets/src/facade/f-worksheet.ts:427–480`)
- `FRange.getValue()` / `getValues()` / `setValue()` / `setValues()` / `getFormula()` / `setFormula()` (`f-range.ts:489–518`, `1351–1365`, `1631–1648`, `892–898`, `2880–2883`)

`setValue`/`setValues`는 `SetRangeValuesCommand`를 동기 실행한다. UI가 없어도 동작한다.

수식 엔진 mixin:

```23:39:/Users/yeonwoosung/Desktop/univer/packages/engine-formula/src/facade/f-univer.ts
export interface IFUniverEngineFormulaMixin {
    getFormula(): FFormula;
}
...
    override getFormula(): FFormula {
        return this._injector.createInstance(FFormula);
    }
```

에이전트 검증에 가까운 수식 API:

- `executeCalculation()` — dirty가 안 잡힌 외부 변경 후 강제 재계산 (`f-formula.ts:131–147`)
- `onCalculationResultApplied(timeout?)` — 결과가 모델에 적용될 때까지 대기 (`f-formula.ts:229–236`)
- `FRange.getFormulaError()` — `#DIV/0!` 등 (`packages/sheets-formula/src/facade/f-range.ts:24–37`)

### 3.4 Docs mixin — 문서/문단/텍스트 레인지

```25:61:/Users/yeonwoosung/Desktop/univer/packages/docs/src/facade/f-univer.ts
export interface IFUniverDocsMixin {
    createDocument(data: Partial<IDocumentData>, options?: ICreateUnitOptions): FDocument;
    getActiveDocument(): FDocument | null;
    getDocument(id: string): FDocument | null;
}
```

문서 쪽은 CHANGELOG가 명시적으로 “agent-friendly”라고 부른다.

- `#7329` “add agent-friendly text range lookup” (`CHANGELOG.md:145`)
- `#7243` “add section and agent-friendly facade APIs” (`CHANGELOG.md:296`)

에이전트가 쓸 공개 메서드:

| API | 하는 일 | 위치 |
| --- | --- | --- |
| `FDocument.save()` | 스냅샷 + 리소스 | `f-document.ts:348` |
| `insertText(index, text, segmentId?)` | 평문 삽입 | `f-document.ts:427` |
| `getParagraphs()` / `findParagraphByText()` / `findParagraphs()` | 문단 조회 | `f-document.ts:718`, `764` |
| `getCustomBlockLayout()` | 모델 좌표 블록 목록. **픽셀/페이지 없음** | `f-document.ts:127–140` |
| `FDocumentParagraph.getTextRange()` | “agent-friendly facade” | `f-document-paragraph.ts:185` |
| `findText()` | 문단 안 리터럴 검색 | `f-document-paragraph.ts:224` |
| `FDocumentTextRange.describe()` | “serializable summary suitable for an agent/tool response” | `f-document-text-range.ts:143–152` |
| `setText()` / `setTextStyle()` | 고정 오프셋 편집 | `f-document-text-range.ts:178`, `210` |
| `FDocumentSection.describe()` | 섹션 요약 | `f-document-section.ts:188` |

`describe()`가 이 레포에서 가장 솔직한 “에이전트 도구 응답”이다.

```143:162:/Users/yeonwoosung/Desktop/univer/packages/docs/src/facade/f-document-text-range.ts
     * Returns a serializable summary suitable for an agent/tool response.
...
    describe(): IFDocumentTextRangeDescription {
        const explicitTextStyleRuns = this.getExplicitTextStyleRuns();
        const commonExplicitTextStyle = this.getCommonExplicitTextStyle();
        return {
            ...this.getRange(),
            text: this.getText(),
            length: this._endOffset - this._startOffset,
            explicitTextStyleRuns,
            commonExplicitTextStyle,
        };
    }
```

오프셋은 생성 시점에 고정이다. 앞쪽을 고치면 레인지를 다시 잡아야 한다 (`f-document-text-range.ts:47–48`). 에이전트 루프가 아니라 문서 모델 제약이다.

Node 테스트가 UI 없이 섹션을 바꾼다.

```31:46:/Users/yeonwoosung/Desktop/univer/packages/docs/src/facade/__tests__/f-document.node.spec.ts
    it('updates traditional sections without loading Docs UI or browser globals', () => {
        ...
        expect(globalThis).not.toHaveProperty('window');
        expect(section?.setColumns(2, {
```

### 3.5 Facade 확장 목록 (이 클론)

`FUniver.extend`를 호출하는 패키지:

`sheets`, `docs`, `engine-formula`, `ui`, `sheets-ui`, `sheets-formula-ui`, `sheets-data-validation`, `sheets-filter`, `sheets-sort`, `sheets-hyper-link`, `sheets-drawing`, `sheets-drawing-ui`, `sheets-thread-comment`, `sheets-note`, `sheets-find-replace`, `sheets-crosshair-highlight`, `thread-comment`, `watermark`, `network`.

**Slides에는 facade 디렉터리가 없다.** `packages/slides/src`는 데이터 모델과 렌더 어댑터만 있다. README도 Slides는 “under active development” (`README.md:294`). 에이전트가 슬라이드를 Facade로 편집하는 OSS API는 이 클론에 없다.

`@univerjs/engine-render` README는 Facade entry가 **No**다 (`packages/engine-render/README.md:13`).

---

## 4. Headless Node presets

README Highlights:

```99:101:/Users/yeonwoosung/Desktop/univer/README.md
      <strong>Headless for AI infrastructure</strong><br />
      <sub>Run workbook and document logic in Node.js to power agents, automation, and server-side workflows.</sub>
```

Headless Mode 안내: “server-side workbook/document processing, formula calculation, or automation without UI” (`README.md:274`). Node 런타임은 `>=18.17.0` (`README.md:286`).

Isomorphic 설계 문서:

```1:34:/Users/yeonwoosung/Desktop/univer/docs/ISOMORPHIC.md
Univer is an isomorphic (full-stack) framework for building productivity tools, which means **support of Node.js is
at the same priority as browsers**.
...
**The Facade API is designed to be used by both the server and the client**.
...
Commands and especially those of type `MUTATION` should be implemented in the underlying logic plugins, and should not
read UI status directly
```

### 4.1 `@univerjs/preset-sheets-node-core`

플러그인 목록 (`presets/packages/preset-sheets-node-core/src/preset.ts:64–95`):

- `UniverFormulaEnginePlugin` (선택적 `UniverRPCNodeMainPlugin` + worker)
- `UniverThreadCommentPlugin`, `UniverDocsPlugin` (시트 셀 리치텍스트용)
- `UniverSheetsPlugin`, `UniverSheetsFormulaPlugin`
- data-validation, filter, hyper-link, drawing, sort, thread-comment

**없는 것:** `@univerjs/engine-render`, `@univerjs/ui`, `@univerjs/sheets-ui`. CSS도 없다 (`preset-sheets-node-core/README.md:13`: CSS No, Facade Yes).

의존성도 render/ui가 없다 (`preset-sheets-node-core/package.json:77–91`). Worker preset은 수식 계산만 옮긴다 (`src/worker.ts:36–48`).

즉 Node 시트 프리셋은 **모델 + 커맨드 + 수식**이지 캔버스가 아니다. 스크린샷을 여기서 찍을 수 없다.

### 4.2 `@univerjs/preset-docs-node-core`

`preset.ts:37–56`: formula engine, thread-comment, docs, hyper-link, drawing. RPC worker는 주석 처리되어 꺼져 있다. 역시 **engine-render / docs-ui 없음**. CSS No (`preset-docs-node-core/README.md:13`).

### 4.3 RPC

`@univerjs/rpc-node`는 브라우저가 아닌 환경의 main/worker RPC다 (`packages/rpc-node/README.md:7–40`). README가 `examples/src/node/sdk/worker.ts`를 가리키지만, 이 클론 `examples/src`에는 `docs/`, `sheets/`, `slides/`만 있고 **`node/` 디렉터리는 없다.** Node 예제는 문서 링크 수준이다.

---

## 5. Output verification — 스냅샷은 있고, 스크린샷 Facade는 없다

README는 “content inspection, rendered screenshots, and layout diagnostics”를 약속한다 (`README.md:138`). 이 클론에서 각각을 추적하면 아래와 같다.

### 5.1 Content inspection — 실제로 있는 검증 API

**스냅샷 export**가 정식 경로다.

```169:183:/Users/yeonwoosung/Desktop/univer/packages/sheets/src/facade/f-workbook.ts
     * Save workbook snapshot data, including conditional formatting, data validation, and other plugin data.
...
    save(): IWorkbookData {
        const snapshot = this._resourceLoaderService.saveUnit<IWorkbookData>(this._workbook.getUnitId())!;
        return snapshot;
    }
```

문서도 같다 (`packages/docs/src/facade/f-document.ts:338–350`). 둘 다 `IResourceLoaderService.saveUnit`을 탄다.

```164:172:/Users/yeonwoosung/Desktop/univer/packages/core/src/services/resource-loader/resource-loader.service.ts
    saveUnit<T = object>(unitId: string) {
        const unit = this._univerInstanceService.getUnit(unitId);
        if (!unit) {
            return null;
        }
        const resources = this._resourceManagerService.getResources(unitId, unit.type);
        const snapshot = Tools.deepClone(unit.getSnapshot()) as { resources: typeof resources } & T;
        snapshot.resources = resources;
        return snapshot;
    }
```

`Workbook.getSnapshot()`은 현재 모델 참조일 뿐, 플러그인 리소스를 모으지 않는다 (`packages/core/src/sheets/workbook.ts:145–153`). 에이전트가 “파일로 내보내기”에 해당하는 OSS API는 `save()`이지 xlsx/docx writer가 아니다. Import/export는 Pro (`README.md:292, 308`).

그 외 구조화 검사:

- `FRange.getValue` / `getFormula` / `getFormulaError`
- `FDocumentTextRange.describe()`, `FDocumentSection.describe()`
- `FDocument.getCustomBlockLayout()` — 모델 순서의 `blockId`/`startIndex`. **렌더된 픽셀 위치와 pagination을 의도적으로 제외** (`f-document.ts:57–60`, `127–130`)

### 5.2 Rendered screenshots — Facade에 없고, Node preset에도 없다

이 클론에서 `screenshot` 문자열은 README 한 줄뿐이다. `toDataURL`은 렌더 엔진 캔버스 래퍼에만 있다.

```184:207:/Users/yeonwoosung/Desktop/univer/packages/engine-render/src/canvas.ts
     * to data url
...
    toDataURL(mimeType: string, quality: number) {
        try {
            return this.getCanvasEle().toDataURL(mimeType, quality);
        } catch (e) {
            try {
                return this.getCanvasEle().toDataURL();
            } catch (err: unknown) {
                ...
                return '';
            }
        }
    }
```

이것은 HTMLCanvasElement 래핑이다. `FUniver` / `FWorkbook` / `FWorksheet` / `FRange` / `FDocument`에 `screenshot`, `toImage`, `exportImage`, `capture` 같은 공개 API는 없다. `sheets-ui` Facade는 렌더 확장 등록, 붙여넣기, 보호 영역 그림자다 (`packages/sheets-ui/src/facade/f-univer.ts:71–188`). `docs-ui` Facade는 `setSelection`뿐이다 (`packages/docs-ui/src/facade/f-document.ts:23–39`).

브라우저에서 엔진이 마운트되어 있으면 `Engine.getCanvasElement()` (`packages/engine-render/src/engine.ts:251–253`)로 캔버스에 접근한 뒤 `toDataURL`을 호출하는 **비공식 경로**는 가능하다. 에이전트용 스크린샷 도구가 아니다. Node core preset은 `engine-render`를 넣지 않으므로 이 경로 자체가 없다.

인쇄(print)도 OSS Facade에 없고 Pro 표에만 있다 (`README.md:292`).

### 5.3 Layout diagnostics — 내부 엔진 상태이지 에이전트 도구가 아니다

이름에 diagnostic이 있는 것은 Docs 레이아웃 워커 복구 상태다.

```78:82:/Users/yeonwoosung/Desktop/univer/packages/docs/src/services/doc-layout-executor.service.ts
export interface IDocLayoutExecutorStatus {
    state: DocLayoutExecutorState;
    executor: DocLayoutExecutorType | null;
    diagnostic: string | null;
    recoveryUnitId: string | null;
}
```

실패 시 `error.message`를 `diagnostic`에 넣는다 (`doc-layout-executor.service.ts:463–467`). Facade로 export되지 않는다. UI 복구 패널(`DocLayoutRecovery.tsx`)용 내부 필드다.

`createDocumentLayoutSnapshot`은 레이아웃 워커에 넘길 모델 투영이다. “exchange-only payloads remain in the authoritative Main model” (`packages/docs/src/services/document-layout-snapshot.ts:57–62`). 에이전트 검증 리포트가 아니다.

에이전트가 쓸 수 있는 “레이아웃”에 가장 가까운 OSS API는:

1. `getCustomBlockLayout()` — 모델 인덱스만, 픽셀 없음
2. `FDocumentSection.describe()` — 단 수, 여백, 페이지 크기 (96-DPI 레이아웃 픽셀 숫자)
3. `FDocumentTextRange.describe()` — 텍스트 + 스타일 런

렌더된 overflow / collision / screenshot diff는 이 클론에 없다.

---

## 6. Worktree — 언급만 있고 구현은 없다

`worktree` / `Worktree` 검색 결과는 README 계열 18줄뿐이다. TypeScript 구현, 패키지, 커맨드, Facade 메서드가 없다.

README 본문이 이미 이 레포 밖이라고 적는다.

- 에이전트가 isolated draft에서 일하고 사람이 머지한다 (`README.md:139`)
- Live editing, shared revisions, Worktree는 **해당 Web SDK와 collaboration**이 필요하며 패키지/라이선스가 기능마다 다르다 (`README.md:141`)
- Collaboration은 Univer Pro (`README.md:292, 307–312`)
- isolated worktrees는 `dsh-univer-office` 설명 문구 (`README.md:77`)

이 OSS 클론의 격리 단위는 `createWorkbook(..., { makeCurrent: false })`와 `disposeUnit(unitId)` 수준의 유닛 핸들뿐이다 (`packages/sheets/src/facade/f-univer.ts:87–90`, `packages/core/src/facade/f-univer.ts:328`). Git worktree나 에이전트 초안 브랜치가 아니다.

---

## 7. Skills / MCP / tools — 이 클론에 없다

확인한 검색:

- `SKILL.md`: **0건**
- `univer-sdk-skills` / `univer-mcp`: README 링크만
- MCP 서버, tool schema, `tools` 레지스트리: 없음
- `sandbox`: **0건**

README가 스킬을 “reusable instructions for AI agents working with Univer integration, Pro features, plugin development, and Node backends”로 설명한다 (`README.md:327`). 그 파일들은 이 런타임 레포가 아니라 별도 레포의 프롬프트 팩이다.

WorkBuddy 항목은 “MCP previews and draft review”를 **다른 레포**의 개발 프리뷰로 적는다 (`README.md:79`).

이 클론의 “도구”에 해당하는 것은 command id (`sheet.command.set-range-values` 등)와 Facade 메서드다. JSON Schema tool list가 아니라 TypeScript API다.

---

## 8. 전형적인 에이전트 하네스 vs Univer

```
전형적인 코딩/오피스 에이전트 하네스
  ├─ loop: model ↔ tool calls ↔ observation
  ├─ tools: MCP / function schema / bash / browser
  ├─ sandbox: 파일시스템·네트워크 격리
  └─ skills: SKILL.md 절차 문서

Univer OSS (이 클론)
  ├─ runtime: Univer + plugins + commands/mutations
  ├─ document model: IWorkbookData / IDocumentData
  ├─ Facade: FUniver / FWorkbook / FRange / FDocument  (에이전트가 호출하는 API)
  ├─ headless: preset-sheets-node-core / preset-docs-node-core
  └─ verify: save() snapshot, formula errors, describe()

이 클론 밖의 Univer 제품군 (README만 증거)
  ├─ univer-mcp          MCP 서버
  ├─ univer-sdk-skills   SKILL.md 팩
  ├─ univer-cli          로컬 에이전트 CLI
  ├─ dsh-univer-office   DeepSeek Harness + worktrees
  ├─ univer-workspace    사람+에이전트 앱
  └─ Univer Pro          협업, Worktree, import/export, print
```

README 문장 “People and AI agents can work in the same files” (`README.md:50`)는 제품군 주장이다. 이 레포가 에이전트 세션을 돌린다는 뜻이 아니다.

문서 주석이 “agent code should use `newRichText()`”라고 하는 것은, 팀이 Facade를 에이전트 통합 표면으로 **다듬고 있다**는 증거다. 루프는 여전히 호출자(MCP 서버, CLI, Workspace, 사용자 백엔드)가 소유한다.

---

## 9. 에이전트가 이 SDK만으로 할 수 있는 것 / 없는 것

**할 수 있는 것 (OSS, 이 클론)**

1. Node에서 워크북/문서를 만들고 Facade로 읽고 쓴다.
2. 수식을 넣고 `getFormula().onCalculationResultApplied()`로 기다린 뒤 `getValue()` / `getFormulaError()`로 검사한다.
3. `workbook.save()` / `document.save()`로 JSON 스냅샷을 얻는다.
4. 문서는 `findParagraphByText` → `getTextRange().describe()`로 구조화 요약을 얻는다.
5. `executeCommand`로 플러그인 커맨드를 직접 친다.
6. `addEvent(Event.CommandExecuted, ...)`로 mutation을 관찰한다.

**이 클론만으로는 할 수 없는 것**

1. MCP tool로 시트를 조작한다 → `univer-mcp` (미클론).
2. SKILL.md를 로드한다 → `univer-sdk-skills` (미클론).
3. 렌더 스크린샷을 Facade로 찍는다 → API 없음. Node preset은 렌더러 없음.
4. 픽셀 레이아웃 진단 / overflow QC → Facade 없음.
5. Worktree 초안·사람 리뷰 머지 → Pro / 외부 앱.
6. xlsx/docx/pptx 파일 import·export·print → Pro (`README.md:292`).
7. Slides를 Facade로 편집한다 → slides facade 없음.
8. 에이전트 루프, 샌드박스, 권한 게이트 → 없음.

---

## 10. 정직한 위치

Univer README의 “Office Harness for AI Agents”는 **마케팅 + 제품군 아키텍처 이름**이다. 이 레포가 그 하네스의 **문서 런타임 층**이다.

- 하네스의 “도구”에 해당하는 것은 Facade와 Command다.
- 하네스의 “관측”에 해당하는 것은 snapshot `save()`, 수식 에러, `describe()`다. 스크린샷은 브라우저 캔버스 원시 API일 뿐 제품화된 에이전트 도구가 아니다.
- 하네스의 루프·스킬·MCP·Worktree는 다른 레포와 Pro에 있다.

에이전트를 Univer OSS에 붙일 때 이 클론이 제공하는 계약은 다음 한 줄이다.

`FUniver`로 유닛을 만들고, Command로 바꾸고, `save()`로 JSON을 돌려받는다. UI와 협업과 MCP는 선택 사항이며 여기 없다.
