# Univer tools and runtime — implementation contract

| Field | Value |
|---|---|
| Status | Locked for v0 |
| Date | 2026-09-25 |
| Product | Neos parent-owned Univer OSS sidecar + structured `univer.*.v1` tools |
| Inventory (descriptive, not this contract) | [`docs/univer/`](../README.md) — clone `/Users/yeonwoosung/Desktop/univer` v1.0.2 HEAD `1defaf4` |
| Does not replace | Clone inventory `07`/`09`/`11`–`14`. Those files describe Univer. This file is what Neos builds. |

이 문서는 **구현 계약**이다. 인벤토리(`docs/univer/00`–`14`)는 Univer OSS가 무엇을 제공하는지 고정한다. 여기서는 Neos가 그 런타임을 어떻게 붙이고, 어떤 도구 이름·파라미터·실패 코드·리프 allowlist를 강제하는지를 고정한다. 식별자·커맨드 ID·패키지 이름은 영어 그대로 둔다.

Univer 원본 클론은 수정하지 않는다. 에이전트 루프는 Univer가 아니라 Neos `SubagentRuntime`이 소유한다.

---

## 0. Locked decisions (v0)

1. 런타임은 **parent-owned Node sidecar**다. Sheets는 `@univerjs/preset-sheets-node-core` (`createUniver` + facade side-effect import). Docs는 `@univerjs/preset-docs-node-core`. 세션당 sidecar 하나. Parent가 start/stop한다.
2. 디스크에 남는 것은 Facade `save()`가 돌려주는 **snapshot JSON** (`IWorkbookData` / `IDocumentData`)이다. `.univer` SQLite도 xlsx도 쓰지 않는다. xlsx export는 이후 / Pro.
3. Writer는 `draft/**`만 바꾼다. `trunk/`는 parent-only `univer.merge.v1`.
4. 도구는 **구조화**한다. v0에 자유 JavaScript `execute`를 열지 않는다. univer-cli `execute`는 신뢰된 Facade JS이며 “not a sandbox”다 ([`12-ecosystem-agents.md`](../12-ecosystem-agents.md) §4). v1 플래그 `univer.facade_js`가 켜지면 `univer.facade_js.v1`을 추가할 수 있고, 허용 글로벌은 `univerAPI`뿐이다.
5. `univer.execute_command.v1` allowlist는 작은 SHEET/DOC **COMMAND** 집합이다. raw MUTATION id는 거부한다 (인터셉터/undo를 건너뛴다). 근거: [`11-commands-permissions.md`](../11-commands-permissions.md).
6. 쓰기 뒤 parent/leaf는 `univer.formula_wait.v1`으로 계산 결과가 모델에 적용될 때까지 기다린다. 엔진 적용 MUTATION은 `formula.mutation.set-formula-calculation-result`다. OSS에서 커스텀 함수를 RPC로 등록하는 경로는 throw다 — 스펙에 넣지 않는다.
7. Screenshot / PDF / layout lint는 v0에 없다. OSS `canvas.toDataURL`은 브라우저 HTMLCanvasElement 래퍼이고, Node headless preset에는 render engine이 없다.
8. xlsx/docx import/export는 v0에 없다 (Pro exchange). 이후 `univer.import.v1`은 플래그 뒤.
9. Sidecar ↔ parent 프로토콜은 **localhost JSON-RPC**이고 **Neos가 소유**한다. `@univerjs/rpc-node` formula worker에 의존하지 않는다. v0 수식은 메인 Node 프로세스에서 inline 실행한다.
10. `ToolPort`는 parent가 주입한다. Stepper `_tool_permitted`는 `allowed_tools` **정확 멤버십**이다 (`neos/subagent`).
11. 도구 이름은 `univer.<verb>.v1`이다 (`read_file.v1` 스타일). v0에 `mcp.univer.*`를 쓰지 않는다.

---

## 1. 한 줄

v0 Univer 표면은 “MCP 30도구”나 “Facade JS 실행기”가 아니다. Parent가 Node sidecar 하나를 띄우고, leaf는 `ToolPort`로 구조화 도구만 부르며, sidecar는 OSS COMMAND + Facade `save()`로 한 유닛을 읽고 쓴다.

```
ParentKind.UNIVER (v0)
  ├─ starts Node sidecar  (preset-sheets-node-core | preset-docs-node-core)
  ├─ JSON-RPC 127.0.0.1   (Neos protocol; not @univerjs/rpc-node)
  ├─ injects UniverToolPort into SubagentRuntime
  └─ leaves (catalog)
        univer-reader   inspect + range_get
        univer-formula  inspect + formula_wait
        univer-writer   range_set / execute_command + formula_wait + save(draft)
        univer-critic   inspect + range_get (디스크 쓰기 없음)
```

---

## 2. Sidecar process contract

### 2.1 소유와 수명

- Sidecar는 **parent 자식 프로세스**다. leaf가 `node`나 `execute.v1`로 띄우지 않는다.
- **세션당 프로세스 하나.** 세션이 끝나면 parent가 SIGTERM → 유예 후 SIGKILL.
- 한 sidecar는 **유닛 하나**. `kind=sheet`면 `createWorkbook` 한 번, `kind=doc`면 `createDocument` 한 번. 두 번째 유닛 생성은 `one_unit_limit`.
- 한 시각에 **in-flight RPC 하나**. 겹치면 `unit_busy`. 큐잉하지 않는다 (실패가 드러나야 한다).
- `collaboration: true`를 `createUniver`에 넘기지 않는다. 그 플래그는 `IUndoRedoService` / `IAuthzIoService` 바인딩을 빼서 Pro 슬롯을 연다 (`presets/src/preset.ts:51-55`).

### 2.2 부트 (SDK)

Sheets:

```ts
import { createUniver } from '@univerjs/presets'
import { UniverSheetsNodeCorePreset } from '@univerjs/preset-sheets-node-core'
import { UniverSheetsConditionalFormattingPlugin } from '@univerjs/sheets-conditional-formatting'
import { UniverSheetsTablePlugin } from '@univerjs/sheets-table'
import '@univerjs/sheets/facade'
import '@univerjs/sheets-formula/facade'
import '@univerjs/engine-formula/facade'
import '@univerjs/sheets-conditional-formatting/facade'
import '@univerjs/sheets-table/facade'

const { univer, univerAPI } = createUniver({
  presets: [UniverSheetsNodeCorePreset({ /* no workerSrc */ })],
  plugins: [
    UniverSheetsConditionalFormattingPlugin,
    UniverSheetsTablePlugin,
  ],
})
```

근거:

- `createUniver`가 플러그인을 등록한 뒤 `FUniver.newAPI(univer)`를 돌려준다 (`presets/src/preset.ts:48-103`).
- Node Sheets preset은 UI·`engine-render` 없이 formula + sheets + DV + filter + sort + drawing + thread-comment를 묶는다 (`presets/packages/preset-sheets-node-core/src/preset.ts:64-95`). Facade side-effect는 같은 파일 `:32-40`.
- 스톡 preset에 **없는** OSS 플러그인을 allowlist COMMAND 때문에 추가한다: `sheet.command.add-conditional-rule` (`packages/sheets-conditional-formatting/src/commands/commands/add-cf.command.ts:39`), `sheet.command.add-table` (`packages/sheets-table/src/commands/commands/add-sheet-table.command.ts:46`). 둘 다 `@DependentOn(UniverSheetsPlugin)` 로직 플러그인이고 UI/render를 강제하지 않는다 (`sheets-conditional-formatting/src/plugin.ts:47-51`, `sheets-table/src/plugin.ts:44-49`).
- `workerSrc`를 넘기지 않는다. 넘기면 `UniverRPCNodeMainPlugin`이 `child_process.fork`로 수식 replica를 띄운다 (`packages/rpc-node/src/plugin.ts:136`). v0는 메인 Node에서 inline formula (`UniverFormulaEnginePlugin` `notExecuteFormula: false`, preset `:74-77`).

Docs:

```ts
import { createUniver } from '@univerjs/presets'
import { UniverDocsNodeCorePreset } from '@univerjs/preset-docs-node-core'
import '@univerjs/docs/facade'
import '@univerjs/engine-formula/facade'

const { univer, univerAPI } = createUniver({
  presets: [UniverDocsNodeCorePreset()],
})
```

스톡 `@univerjs/preset-docs-node-core`는 `@univerjs/engine-formula/facade`만 side-effect import하고 **docs facade를 안 넣는다** (`presets/packages/preset-docs-node-core/src/preset.ts:26`). sidecar는 `@univerjs/docs/facade`를 반드시 import한다. 빼면 `univerAPI.createDocument`가 `undefined`다 (mixin 규칙: [`09-facade-api.md`](../09-facade-api.md) §3). RPC worker import는 스톡에서도 주석 처리되어 있다 (`preset.ts:23, 42-44`). 그대로 둔다.

Node 런타임: Univer headless는 `>=18.17.0` (`README.md:286`). Sidecar도 그 하한을 따른다. 모노레포 개발 하한 `>=22.18`을 sidecar에 요구하지 않는다.

버전: 모든 `@univerjs/*`는 **같은 1.0.2**. 섞지 않는다.

### 2.3 Start args

Parent가 argv로 넘긴다. 환경변수만으로 listen/token을 바꾸지 않는다 (실수 재사용 방지).

| Arg | 필수 | 의미 |
|---|---|---|
| `--kind` | yes | `sheet` \| `doc`. 프로세스 수명 동안 불변. |
| `--listen` | yes | `127.0.0.1:<port>`. `0.0.0.0` 금지. 포트는 parent가 bind-before-fork 또는 ephemeral 할당. |
| `--token` | yes | JSON-RPC handshake 공유 비밀. 로그/argv 에코에 찍지 않는다. |
| `--session-dir` | yes | 아래 §3 레이아웃의 세션 루트. sidecar는 여기 밖을 읽거나 쓰지 않는다. |
| `--snapshot` | no | 기동 시 `load`할 상대 경로 (`trunk/workbook.json` 등). 없으면 빈 유닛 (`createWorkbook({})` / `createDocument({})`). |
| `--rpc-timeout-ms` | no | 기본 `30000`. |
| `--formula-timeout-ms` | no | 기본 `60000`. `univer.formula_wait.v1` 상한. |
| `--idle-timeout-ms` | no | 기본 `300000`. 마지막 RPC 이후 parent가 죽인다. sidecar 자체 watchdog도 같은 값으로 종료. |

예:

```text
node neos/univer/sidecar/index.js \
  --kind sheet \
  --listen 127.0.0.1:49152 \
  --token <opaque> \
  --session-dir /tmp/neos-univer/<session> \
  --snapshot draft/workbook.json
```

stdio는 JSON-RPC가 아니다. JSON-RPC는 TCP `127.0.0.1`. stdout은 로그 한 줄 `ready port=<n>`만 허용한다. parent는 그 줄을 읽어 health를 친다.

### 2.4 Health

RPC method `health` (도구 이름 아님. parent만).

성공 예:

```json
{
  "ok": true,
  "pid": 12345,
  "kind": "sheet",
  "lifecycle": "Steady",
  "unit_id": "workbook-01",
  "formula_dirty": false,
  "in_flight": false,
  "app_version": "1.0.2"
}
```

`lifecycle`은 `univerAPI.getCurrentLifecycleStage()` (`packages/core/src/facade/f-univer.ts:342-345`). 값 공간은 `LifecycleStages` (`Starting` / `Ready` / `Rendered` / `Steady`, `packages/core/src/services/lifecycle/lifecycle.ts:20-40`). Headless는 렌더가 없으므로 `Ready`에서 `Steady`로 빨리 올라간다. Parent는 `Steady`(또는 headless에서 `Ready` 이상) 전에 leaf 도구를 열지 않는다.

TCP connect 실패 · handshake token 불일치 · 프로세스 ESRCH → parent는 `sidecar_unavailable`. 재시작은 parent 책임. leaf는 sidecar를 재기동하지 않는다.

### 2.5 Timeout

| 시계 | 기본 | 초과 시 |
|---|---|---|
| RPC 전체 | `--rpc-timeout-ms` 30s | `sidecar_timeout`. in-flight 플래그 해제. 유닛은 그 커맨드가 중간에 멈췄을 수 있으므로 parent는 다음 쓰기 전에 `load`로 스냅샷을 다시 올린다. |
| formula wait | `--formula-timeout-ms` 60s | `formula_timeout`. Facade `onCalculationResultApplied(timeout)`이 reject (`packages/engine-formula/src/facade/f-formula.ts:229-236`, `formula-calculation-session.service.ts:202`). |
| idle | `--idle-timeout-ms` 300s | parent SIGTERM. |
| process boot → first `health` | 15s | `sidecar_unavailable`. |

### 2.6 One-unit-at-a-time (규범)

1. `--kind`와 다른 `create*` 호출 경로를 sidecar에 두지 않는다. `kind=sheet` 프로세스에서 `createDocument` 코드 경로 자체가 없다.
2. 이미 유닛이 있으면 두 번째 `load`만 허용한다. `load`는 기존 유닛을 `disposeUnit`한 뒤 새 스냅샷으로 교체한다 (`FUniver.disposeUnit`, `packages/core/src/facade/f-univer.ts:328-330`).
3. `execute_command` / `inspect` / `save` / `formula_wait`는 로드된 그 유닛만 본다. `params.unitId`가 있으면 로드된 id와 같아야 한다. 다르면 `unit_kind_mismatch`.
4. 동시 RPC 거부 (`unit_busy`).

---

## 3. Session layout and write jail

```
<session>/
  trunk/workbook.json | document.json    # parent merge.v1 만 쓴다
  draft/workbook.json | document.json    # writer save 만 쓴다
  out/_spec/*.json                       # critic/reader fold
```

`kind=sheet`면 파일 이름은 항상 `workbook.json`. `kind=doc`면 항상 `document.json`. 한 세션에 둘 다 두지 않는다.

| 행위자 | 쓸 수 있는 경로 | 읽을 수 있는 경로 |
|---|---|---|
| `univer-writer` | `draft/**` via `univer.save.v1` only | `draft/**`, `out/_spec/*.json` |
| `univer-reader` | 없음 | `trunk/**`, `draft/**`, `out/_spec/*.json` |
| `univer-critic` | `out/_spec/*.json` via `write_file.v1` | `trunk/**`, `draft/**`, `out/_spec/*.json` |
| Parent | `trunk/**` via `univer.merge.v1`; sidecar start/stop; `load` RPC | 전부 |

Writer에게 `write_file.v1`을 주지 않는다. 스냅샷 쓰기는 `univer.save.v1`만. FSI Mode B writer가 `./out/_spec/*.json`만 쓰는 것과 대칭이되, Univer writer의 산출은 draft 스냅샷이다.

`trunk/`를 leaf가 직접 덮으면 실패 코드 `path_denied`. nested `_spec` (`out/_spec/foo/_spec`)도 거부. `..` · 절대경로 · NUL → `path_denied`.

`univer.merge.v1` (parent-only, leaf `allowed_tools`에 없음): `draft/*.json`을 `trunk/`로 복사한다. critic fold가 스키마를 통과한 뒤에만. sidecar 유닛을 바꾸지 않는다 — 디스크 trunk만 갱신한다.

---

## 4. JSON-RPC (Neos owns the protocol)

`@univerjs/rpc-node`는 Univer 내부 DataSync(수식 replica)용이고 `child_process.fork` + `process.send`다 (`packages/rpc-node/src/plugin.ts:21, 136-142`, [`05-network-rpc.md`](../05-network-rpc.md) §1). **이 프로토콜을 sidecar 게이트로 쓰지 않는다.**

Neos 게이트:

```
→ { "jsonrpc": "2.0", "id": "<uuid>", "method": "<name>", "params": { ... } }
← { "jsonrpc": "2.0", "id": "<uuid>", "result": { "ok": true, ... } }
← { "jsonrpc": "2.0", "id": "<uuid>", "result": { "ok": false, "error": "<code>", "detail": "..." } }
```

첫 프레임 또는 매 요청에 `token`을 실어 handshake한다. 불일치면 소켓을 닫는다. JSON-RPC error object(`-32600` 등)는 transport 깨짐에만 쓴다. 비즈니스 실패는 `result.ok=false` + §10 코드다. `ToolPort.execute`가 그 mapping을 그대로 올린다 (`neos/subagent/types.py`).

| RPC method | Leaf tool | 누가 |
|---|---|---|
| `health` | — | parent |
| `load` | — | parent (`univer.load`는 v0 leaf 도구가 아님) |
| `inspect` | `univer.inspect.v1` | reader / writer / critic / formula |
| `range_get` | `univer.range_get.v1` | reader / writer / critic / formula |
| `range_set` | `univer.range_set.v1` | writer |
| `execute_command` | `univer.execute_command.v1` | writer |
| `formula_wait` | `univer.formula_wait.v1` | writer (쓰기 후). formula leaf (재계산·에러 수집) |
| `save` | `univer.save.v1` | writer → `draft/` |
| `dispose` | — | parent shutdown |

`load` params: `{ "path": "draft/workbook.json" }` (세션 상대). 파일이 없으면 빈 유닛. JSON 파싱 실패 → `snapshot_invalid`.

---

## 5. ToolPort and `_tool_permitted`

권위:

```154:156:neos/subagent/types.py
class ToolPort(Protocol):
    def definitions(self) -> tuple[Any, ...]: ...
    async def execute(self, name: str, input: Mapping[str, object]) -> Mapping[str, Any]: ...
```

```333:335:neos/subagent/stepper.py
def _tool_permitted(spec: SubagentSpec, name: str, *, spawn_depth: int) -> bool:
    if not name or name not in spec.allowed_tools:
        return False
```

규칙:

- Parent가 `UniverToolPort`를 `ChildStepper(tools=...)`에 주입한다. `neos/subagent`는 `neos.univer`를 import하지 않는다 (FSI와 같은 import law).
- `definitions()`는 `ToolDefinition(name, description, input_schema)`를 돌려준다 (`neos/coding/model/base.py` `ToolDefinition`. `input_schema.type == "object"`).
- Stepper는 port가 가진 이름과 `spec.allowed_tools`의 **교집합만** 모델에 보여 준다 (`stepper.py` `_child_tools`). 포트에 있어도 spec에 없으면 안 보인다. spec에 있어도 포트가 안 내리면 안 보인다.
- 멤버십은 문자열 정확 일치다. glob (`univer.*`, `mcp.univer.*`) 금지. FSI MCP가 `mcp.screening.search`를 집합에 넣는 것과 같다.
- 모델이 없는 이름을 부르면 stepper가 도구를 실행하지 않는다. port `execute`가 같은 이름으로 다시 불려도 `{"ok": false, "error": "tool_not_allowed"}`.
- 도구 결과 본문은 stepper `_MAX_TOOL_BODY` (32 KiB)에 잘린다. inspect는 이 한도에 맞게 설계한다 (§8). 스냅샷 전체는 `save`가 디스크에 쓰고, 모델에게 32 KiB JSON을 돌려주지 않는다.

현재 `ParentKind` (`neos/subagent/types.py:10-17`)는 `CODING` / `DEEP_ANALYSIS` / `WORKFLOW` / `FSI`다. v0는 **`ParentKind.UNIVER`를 추가**한다. 티켓 `parent_kind`가 이 값이어야 Univer leaf spec을 spawn한다. DA/coding이 같은 포트를 쓰는 길은 §11 (v1).

---

## 6. Leaf catalog (v0)

`neos/subagent/catalog.py`에 kebab **네** 개. `sandbox_mode=SandboxMode.NONE`. `can_spawn=False`, `can_approve=False`, `one_shot=True`. `load_project_instructions=False`.

| spec `name` | `allowed_tools` | 하는 일 |
|---|---|---|
| `univer-reader` | `read_file.v1`, `search_text.v1`, `univer.inspect.v1`, `univer.range_get.v1` | trunk/draft를 읽어 구조화 관찰. 쓰기 없음. |
| `univer-formula` | `read_file.v1`, `search_text.v1`, `univer.inspect.v1`, `univer.range_get.v1`, `univer.formula_wait.v1` | 재계산 대기 + ErrorType 수집. 디스크 쓰기 없음. |
| `univer-writer` | `read_file.v1`, `univer.inspect.v1`, `univer.range_get.v1`, `univer.range_set.v1`, `univer.execute_command.v1`, `univer.formula_wait.v1`, `univer.save.v1`, `write_file.v1`, `load_skill.v1` | draft만 바꾸고, 수식을 기다린 뒤 snapshot JSON을 `draft/`에 저장. |
| `univer-critic` | `read_file.v1`, `search_text.v1`, `univer.inspect.v1`, `univer.range_get.v1` | draft vs trunk 재검사. fold 텍스트만. `write_file.v1` 없음. |

Writer `read_file.v1` jail: `draft/**`와 `out/_spec/*.json`만. trunk 읽기 → `path_denied`.

Critic은 디스크에 쓰지 않는다. 부모가 fold 텍스트를 `out/_spec/`에 수집한다.

어느 leaf에도 주지 않는 것: `execute.v1`, `univer.facade_js.v1`, `univer.merge.v1`, `univer.load` RPC, `spawn_agent.v1`, `mcp.*`.

Parent 오케스트레이터 `allowed_tools` (v0): `read_file.v1`, `search_text.v1`, `glob_files.v1`, `spawn_agent.v1`, `load_skill.v1`. Univer RPC 도구는 오케스트레이터에 없다.

쓰기 뒤 순서 (규범):

```
execute_command.v1 → formula_wait.v1 → inspect.v1? → save.v1
```

`formula_dirty`가 true인 채 `inspect`의 계산된 `v`를 요청하면 `formula_dirty`. `save`도 같다 — 수식 셀을 가진 시트는 wait 없이 저장하지 않는다. 수식이 한 칸도 없으면 dirty가 아니므로 wait를 건너뛸 수 있다.

---

## 7. Tool table

공통 성공: `{ "ok": true, ... }`. 공통 실패: `{ "ok": false, "error": "<code>", "detail"?: string }`. `detail`은 로그용 짧은 영어. 모델이 재시도 분기에 쓸 수 있는 값은 `error` 코드뿐이다.

### 7.1 `univer.inspect.v1`

| | |
|---|---|
| Params | 아래 JSON Schema |
| Leaves | reader, writer, critic (+ parent) |
| Sidecar RPC | `inspect` |

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "include_values": { "type": "boolean", "default": false },
    "sheet": { "type": "string", "description": "sheet id or name; sheet kind only" },
    "range": {
      "oneOf": [
        { "type": "string", "description": "A1, e.g. 'A1:B10'" },
        {
          "type": "object",
          "additionalProperties": false,
          "required": ["startRow", "startColumn", "endRow", "endColumn"],
          "properties": {
            "startRow": { "type": "integer", "minimum": 0 },
            "startColumn": { "type": "integer", "minimum": 0 },
            "endRow": { "type": "integer", "minimum": 0 },
            "endColumn": { "type": "integer", "minimum": 0 }
          }
        }
      ]
    },
    "include_formula_errors": { "type": "boolean", "default": true },
    "paragraph_query": { "type": "string", "description": "doc kind: literal findParagraphByText" }
  }
}
```

실패: `sidecar_unavailable`, `sidecar_timeout`, `unit_busy`, `formula_dirty` (`include_values=true`이고 dirty), `not_found` (없는 시트/레인지), `inspect_too_large`.

성공 payload는 §8.

### 7.2 `univer.execute_command.v1`

| | |
|---|---|
| Params | 아래 |
| Leaves | **writer only** |
| Sidecar RPC | `execute_command` |

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["id"],
  "properties": {
    "id": { "type": "string" },
    "params": { "type": "object" }
  }
}
```

Sidecar가 로드된 `unitId` (및 sheet면 active `subUnitId`)를 COMMAND params에 채운다. 모델이 다른 id를 넣으면 `unit_kind_mismatch`.

게이트 순서:

1. `id`가 §8 allowlist **정확 멤버십**이 아니면 `command_not_allowlisted`.
2. `id`가 `*.mutation.*` 또는 `*.operation.*`이면 `mutation_forbidden` (allowlist 우회 금지).
3. `kind=sheet`에 `doc.command.*` (또는 반대) → `unit_kind_mismatch`.
4. `univerAPI.executeCommand(id, params)` (`packages/core/src/facade/f-univer.ts:547-553`). handler가 `false`를 반환하면 `command_failed`.
5. 시트 값/수식/행열을 바꾸는 COMMAND 뒤 `formula_dirty=true`.

실패: 위 + `sidecar_*`, `unit_busy`, `command_failed`.

### 7.3 `univer.formula_wait.v1`

| | |
|---|---|
| Params | `{ "type": "object", "additionalProperties": false, "properties": { "timeout_ms": { "type": "integer", "minimum": 1, "maximum": 120000 } } }` |
| Leaves | writer. critic/parent도 port가 내리면 호출 가능하나 critic catalog에는 기본적으로 없다 — parent가 writer 종료 직후 기다린다. |
| Sidecar RPC | `formula_wait` |

구현: `univerAPI.getFormula().onCalculationResultApplied(timeout)` (`packages/engine-formula/src/facade/f-formula.ts:229-236`). 적용 통지는 `formula.mutation.set-formula-calculation-result` (`packages/engine-formula/src/commands/mutations/set-formula-calculation.mutation.ts:135`). dirty가 아닌데 호출하면 no-op 성공.

성공: `{ "ok": true, "formula_dirty": false }`. 실패: `formula_timeout`, `sidecar_*`.

커스텀 함수 등록 API를 이 도구에 넣지 않는다. `sheets-formula.remote-register-function.service`는 역직렬화 시 throw한다 (`packages/sheets-formula/src/services/remote/remote-register-function.service.ts:52-58`: “function deserialization over RPC is unsafe”). v0 inline 엔진에서도 `registerFunction` RPC를 노출하지 않는다.

### 7.4 `univer.save.v1`

| | |
|---|---|
| Params | `{ "type": "object", "additionalProperties": false, "properties": { "path": { "type": "string", "description": "must be draft/workbook.json or draft/document.json" } } }` |
| Leaves | **writer only** |
| Sidecar RPC | `save` |

`path` 생략 시 kind 기본값 `draft/workbook.json` / `draft/document.json`. 그 외 경로는 `path_denied`.

구현: `FWorkbook.save()` / `FDocument.save()` → UTF-8 JSON write. **`Workbook.getSnapshot()`을 쓰지 않는다.** `save()`는 `IResourceLoaderService.saveUnit`으로 플러그인 `resources`를 합친다 (`packages/sheets/src/facade/f-workbook.ts:180-183`, `packages/docs/src/facade/f-document.ts:348-350`, `packages/core/src/services/resource-loader/resource-loader.service.ts:164-173`). `Workbook.getSnapshot()`은 모델 참조만 주고 resources를 안 넣는다 (`packages/core/src/sheets/workbook.ts:151-153`).

수식 시트가 dirty면 `formula_dirty`. 성공: `{ "ok": true, "path": "draft/workbook.json", "bytes": 1234 }`.

### 7.5 파일 도구 (재사용)

`read_file.v1` / `write_file.v1` / `search_text.v1`은 기존 Neos 이름이다. Univer parent workspace port가 jail만 덧씌운다 (§3). 새 이름을 만들지 않는다.

### 7.6 Parent-only (leaf `allowed_tools`에 없음)

| 이름 | 역할 |
|---|---|
| sidecar start/stop | §2 |
| RPC `load` | 스냅샷을 유닛으로 올린다. `createWorkbook(partial)` / `createDocument(partial)` 후 resource `onLoad`. |
| `univer.merge.v1` | draft JSON → trunk JSON. sidecar 메모리와 무관. |

### 7.7 v1 only (v0에 구현하지 말 것)

| 이름 | 플래그 | 메모 |
|---|---|---|
| `univer.facade_js.v1` | `univer.facade_js` | 본문은 JS. 글로벌 `univerAPI`만. 샌드박스 아님 — 플래그 기본 off. |
| `univer.import.v1` | 별도 | xlsx/docx Pro exchange. |
| `univer.screenshot.v1` / `univer.print_pdf.v1` | — | Node core preset에 renderer 없음. |

---

## 8. Command allowlist v0

`univer.execute_command.v1`의 `id`는 아래 집합의 원소여야 한다. 전수 609개는 [`11-command-ids.md`](../11-command-ids.md). 에이전트가 직접 MUTATION을 치면 undo/인터셉터/권한 훅을 건너뛴다 ([`11-commands-permissions.md`](../11-commands-permissions.md) §2.2). 그래서 allowlist에 `sheet.mutation.*`, `doc.mutation.rich-text-editing`, `formula.mutation.*`를 **넣지 않는다**.

COMMAND는 `CommandType.COMMAND = 0`이다 (`packages/core/src/services/command/command.service.ts:37-55`). ID 패턴 `<namespace>.<type>.<command-name>` (`:67-71`).

### 8.1 Sheets

| ID | 하는 일 | 근거 | 왜 v0에 있나 |
|---|---|---|---|
| `sheet.command.set-range-values` | 셀 `v`/`f`/`s` | `packages/sheets/src/commands/commands/set-range-values.command.ts:53`. Facade `FRange.setValue`가 이 COMMAND를 친다. | 값·수식 쓰기의 정본. |
| `sheet.command.insert-row` | 행 삽입 | `InsertRowCommandId` `packages/sheets/src/commands/commands/insert-row-col.command.ts:64` | 구조 편집. interceptor `beforeCommandExecute`를 탄다 (`:79-86`). |
| `sheet.command.insert-col` | 열 삽입 | 같은 파일 `InsertColCommandId` `:389` | 대칭. |
| `sheet.command.remove-row` | 행 삭제 | `RemoveRowCommandId` `packages/sheets/src/commands/commands/remove-row-col.command.ts:80` | 대칭. by-range 변형은 내부 COMMAND라 열지 않는다. |
| `sheet.command.remove-col` | 열 삭제 | `RemoveColCommandId` 같은 파일 `:223` | 대칭. |
| `sheet.command.add-worksheet-merge` | 병합 | `packages/sheets/src/commands/commands/add-worksheet-merge.command.ts:179` | 자주 쓰는 레이아웃. |
| `sheet.command.sort-range` | 정렬 | `packages/sheets-sort/src/commands/commands/sheets-sort.command.ts:49`. Node preset이 `UniverSheetsSortPlugin`을 넣는다. | 데이터 정리. UI 전용 `sort-range-asc` 등은 열지 않는다. |
| `sheet.command.addDataValidation` | DV 규칙 | `packages/sheets-data-validation/src/commands/commands/data-validation.command.ts:364`. Node preset이 DV 플러그인을 넣는다. | 검증 가능한 제약. Sheets-only ([`13-runtime-contracts.md`](../13-runtime-contracts.md) 인벤토리). |
| `sheet.command.add-conditional-rule` | CF 규칙 | `packages/sheets-conditional-formatting/src/commands/commands/add-cf.command.ts:39` | 스톡 node-core에 없으므로 sidecar가 플러그인을 추가한다 (§2.2). resources에 남아 `save()`로 왕복한다. |
| `sheet.command.add-table` | 구조화 테이블 | `packages/sheets-table/src/commands/commands/add-sheet-table.command.ts:46` | 위와 같음. 테이블 이름/범위만. 테마 COMMAND는 열지 않는다. |

고의로 빼는 시트 COMMAND 예: `insert-row-by-range` (내부), `remove-sheet` / `insert-sheet` (유닛 하나·시트 추가는 v0에서 `FWorkbook.create`를 안 연다 — 필요하면 후속 allowlist), `sheet.command.add-comment`, freeze, filter UI, hyperlink UI.

### 8.2 Docs

| ID | 하는 일 | 근거 | 왜 v0에 있나 |
|---|---|---|---|
| `doc.command.insert-text` | 텍스트 삽입 | `packages/docs/src/commands/commands/core-editing.command.ts:51`. params: `unitId`, `body`, `range`. | 문서 쓰기의 정본 COMMAND. 내부에서 `doc.mutation.rich-text-editing`을 오케스트레이션한다. |
| `doc.command.update-text` | 속성/백스페이스류 갱신 | 같은 파일 `:251` | 삽입의 쌍. `dataStream`을 직접 고치면 paragraphId/OT가 깨진다 ([`13-runtime-contracts.md`](../13-runtime-contracts.md) §3.2). |

고의로 빼는 것: `doc.command.insert-doc-image` (drawing IO), 자유 `doc.mutation.rich-text-editing`. Facade `FDocument.insertText` / `FDocumentTextRange.setText`는 이 COMMAND들을 감싼다. v0 leaf는 Facade JS가 아니라 COMMAND id + serializable params만 보낸다.

### 8.3 절대 열지 않는 ID

- 모든 `*.mutation.*` — 특히 `sheet.mutation.set-range-values` (`packages/sheets/src/commands/mutations/set-range-values.mutation.ts:151`), `formula.mutation.set-formula-calculation-result`.
- 모든 `*.operation.*` (스크롤·선택·사이드바. 스냅샷에 안 남음).
- `univer.command.undo` / `univer.command.redo` — v0 writer는 명시적 역연산 대신 스냅샷 reload.
- `formula.command.insert-function` — UI 커맨드.
- Slides COMMAND (`add-text` 등) — slides facade/preset 없음 ([`07-ai-agent-surface.md`](../07-ai-agent-surface.md) §3.5).

---

## 9. Inspect payload

`univer.inspect.v1` 성공 본문. 빈 시트 1000×20 전체를 실어 보내지 않는다. `include_values=true`여도 `range`가 없으면 active sheet의 **non-null 셀만**, 최대 400칸. 넘치면 `inspect_too_large` (부분 결과를 섞지 않는다).

### 9.1 공통

```json
{
  "ok": true,
  "unit": {
    "type": "sheet",
    "unit_id": "workbook-01",
    "name": "Workbook",
    "lifecycle": "Steady",
    "univer_instance_type": 2
  }
}
```

`type`은 Neos 문자열 `sheet` \| `doc`. `univer_instance_type`은 프로토콜 enum: `UNIVER_DOC = 1`, `UNIVER_SHEET = 2` (`packages/protocol/src/ts/univer/constants/univer.ts:17-26`, core re-export `UniverInstanceType`). v0에 `3` (SLIDE) 이상을 올리지 않는다.

### 9.2 Sheet outline + values

```json
{
  "outline": {
    "sheet_order": ["sheet-01"],
    "sheets": [
      {
        "id": "sheet-01",
        "name": "Sheet1",
        "row_count": 1000,
        "column_count": 20,
        "row_height": 24,
        "column_width": 88
      }
    ],
    "active_sheet_id": "sheet-01"
  },
  "range": {
    "sheet": "sheet-01",
    "a1": "A1:B2",
    "startRow": 0,
    "startColumn": 0,
    "endRow": 1,
    "endColumn": 1,
    "cells": [
      { "r": 0, "c": 0, "v": 1, "t": 2, "f": null },
      { "r": 1, "c": 0, "v": 2, "t": 2, "f": "=A1+1" }
    ]
  },
  "formula_errors": [
    {
      "sheetName": "Sheet1",
      "row": 0,
      "column": 1,
      "formula": "=1/0",
      "errorType": "#DIV/0!"
    }
  ]
}
```

빈 시트 기본값은 `DEFAULT_WORKSHEET_ROW_COUNT = 1000`, `DEFAULT_WORKSHEET_COLUMN_COUNT = 20`, 행 높이 24, 열 너비 88 (`packages/core/src/sheets/sheet-snapshot-utils.ts:22-32`, [`13-runtime-contracts.md`](../13-runtime-contracts.md) §2.1). `createWorkbook({})` 왕복 후 outline이 이 숫자를 보고해야 한다.

셀 필드는 `ICellData`: `v` / `t` / `f` / `p` / `s`가 공존할 수 있다. `null`은 키 삭제, `undefined`는 유지 (`set-range-values.mutation.ts` merge, 인벤토리 §2.2). inspect `cells[]`는 요청 레인지의 **존재하는** 셀만. `t`는 `CellValueType` (STRING=1, NUMBER=2, BOOLEAN=3, FORCE_STRING=4).

`formula_errors[]`는 `FRange.getFormulaError()` (`packages/sheets-formula/src/facade/f-range.ts:44-81`) → `ISheetFormulaError`. `errorType`은 `ErrorType` **리터럴 문자열**이지 enum 키가 아니다 (`packages/engine-formula/src/basics/error-type.ts:17-47`):

`#DIV/0!` `#NAME?` `#VALUE!` `#NUM!` `#N/A` `#CYCLE!` `#REF!` `#SPILL!` `#CALC!` `#ERROR!` `#GETTING_DATA` `#NULL!`.

표시값과 원본: `FRange.getValue()`는 `_worksheet.getCell(...).v`다 (`packages/sheets/src/facade/f-range.ts:512-518`). 인터셉터(`CELL_CONTENT`)가 표시값을 합성할 수 있다 ([`11-commands-permissions.md`](../11-commands-permissions.md) §4.2). inspect `cells[].v`는 그 getCell 경로의 `v`다. 수식 원문은 `f`.

### 9.3 Doc outline

```json
{
  "outline": {
    "title": "Document1",
    "data_stream_length": 2,
    "paragraph_count": 1,
    "sections": [{ "startIndex": 1 }]
  },
  "paragraphs": [
    {
      "startIndex": 0,
      "text": "",
      "length": 0
    }
  ]
}
```

문단 텍스트는 `FDocumentParagraph.getTextRange().describe()` (`packages/docs/src/facade/f-document-text-range.ts:143-162`, JSDoc: “serializable summary suitable for an agent/tool response”). `paragraph_query`가 있으면 `findParagraphByText`로 좁힌다. 픽셀 레이아웃/`getCustomBlockLayout` pagination은 넣지 않는다 (모델 인덱스만 있고 렌더가 없다).

빈 문서 body는 `dataStream: '\r\n'` + paragraph startIndex 0 + sectionBreak startIndex 1 (`packages/core/src/docs/data-model/empty-snapshot.ts:52-76`).

---

## 10. Failure codes

모든 Univer 도구·RPC 비즈니스 실패는 이 집합이다. 새 코드를 조용히 추가하지 않는다.

| `error` | 언제 |
|---|---|
| `tool_not_allowed` | 이름이 port/spec 교집합 밖. |
| `sidecar_unavailable` | 프로세스 없음, health 실패, token 실패. |
| `sidecar_timeout` | RPC 시계. |
| `unit_busy` | in-flight RPC 겹침. |
| `one_unit_limit` | 두 번째 유닛 생성 시도. |
| `unit_kind_mismatch` | sheet 도구를 doc 세션에, 또는 잘못된 `unitId`. |
| `command_not_allowlisted` | `execute_command.id`가 §8 밖. |
| `mutation_forbidden` | `*.mutation.*` / `*.operation.*`. |
| `command_failed` | COMMAND handler가 false / throw. |
| `formula_dirty` | wait 없이 계산된 `v`를 inspect/save. |
| `formula_timeout` | `onCalculationResultApplied` reject. |
| `path_denied` | jail 밖 경로. writer→trunk, critic→draft 쓰기 등. |
| `snapshot_invalid` | JSON/`IWorkbookData`/`IDocumentData` 파싱·필수 필드 실패. |
| `not_found` | 시트/레인지/파일 없음. |
| `inspect_too_large` | 셀 수/본문 한도. |
| `decode_error` | 스냅샷 파일이 UTF-8이 아님. |

FSI port와 같이 `ok: false` mapping을 쓴다 (`neos/fsi/ports.py` `_NO_TOOL` 등). 예외를 throw해서 stepper를 죽이지 않는다.

---

## 11. Save / load round-trip

규범 경로 ([`13-runtime-contracts.md`](../13-runtime-contracts.md) §1):

```
load JSON
  → createWorkbook(partial IWorkbookData) | createDocument(partial IDocumentData)
  → ResourceLoaderService.onLoad(resources)
  → COMMAND → MUTATION 이 스냅샷을 제자리 갱신
  → formula_wait (시트, 수식이 있으면)
  → FWorkbook.save() | FDocument.save()
       = deepClone(getSnapshot()) + plugin resources
  → draft/workbook.json | draft/document.json
```

테스트가 고정할 사실:

1. **빈 시트 1000×20.** `createWorkbook({})` 후 `save()`의 첫 시트 `rowCount=1000`, `columnCount=20`, 기본 행 높이 24, 열 너비 88. `appVersion`은 `@univerjs/core` `"1.0.2"`. `rev`는 1부터 (`typedef.ts:39`). `dateSystem` 없으면 Excel 1900.
2. **resources 왕복.** DV / CF / table / filter를 COMMAND로 넣은 뒤 `save().resources`는 `IResources = Array<{ id?, name, data: string }>` (`packages/core/src/services/resource-manager/type.ts:22`). 그 JSON을 새 sidecar에 `load`하면 같은 규칙이 살아 있다. `getSnapshot()`만 저장한 파일은 이 테스트에 실패해야 한다.
3. **수식 결과.** `A1=1`, `B1==A1+1`을 `set-range-values`로 넣고 `formula_wait` 후 `save()`의 `B1.v`가 2이고 `t`가 NUMBER. wait 없이 save하면 계약 위반 (`formula_dirty`).
4. **셀 merge 규칙.** 같은 객체에 `v`/`f`가 공존. `null`은 키 삭제. 수식을 비우면 `ft`/`fd` 삭제.
5. **문서.** 빈 `createDocument({})`의 `body.dataStream`은 `'\r\n'`. `insert-text` 후 `save()`에 텍스트가 남고, 재load 후 `inspect` `describe()`가 같은 문자열을 준다. `body` JSON을 손으로 고친 파일은 `snapshot_invalid`이거나 OT/paragraphId가 깨진 채 로드된다 — writer 경로로 권하지 않는다.
6. **바이트.** 파일은 UTF-8 JSON. sidecar는 pretty-print 2-space. parent merge는 바이트 복사여도 되고 재직렬화여도 되지만 schema는 Facade `save()` 출력과 호환해야 한다.

`.univer` SQLite, xlsx, docx는 이 왕복에 등장하지 않는다.

---

## 12. DA / coding parents injecting the same ToolPort (v1, not v0)

v0: Univer 세션의 `SubagentTicket.parent_kind`는 `ParentKind.UNIVER`뿐이다. coding durable loop와 DA orchestrator는 Univer sidecar를 띄우지 않는다.

v1 (이 문서가 허용하는 확장, 지금 구현하지 않음):

- `UniverToolPort`는 `ParentKind`에 묶이지 않는다. `ToolPort` 프로토콜만 만족하면 된다 (`definitions` / `execute`).
- DA (`ParentKind.DEEP_ANALYSIS`)나 coding (`ParentKind.CODING`) parent는 **자기 kind를 `UNIVER`로 바꾸지 않고** 같은 포트 인스턴스를 `ChildStepper`에 주입할 수 있다.
- 그때도 leaf spec은 `univer-reader` 등 **정확 이름**이고, `_tool_permitted`는 그 spec의 `allowed_tools` 멤버십이다. explore/implement spec에 `univer.execute_command.v1`을 몰래 넣지 않는다.
- Sidecar 수명은 그 parent 세션에 남는다. DA `Worker` / `deep_analysis.worker.Worker`에 sidecar를 넣지 않는다. FSI가 DA Worker를 호스트로 쓰지 않는 것과 같다.
- `neos/subagent`는 계속 `neos.univer`를 import하지 않는다. 주입 방향은 parent → stepper.
- v1에서도 `mcp.univer.*` 이름을 만들지 않는다. 호스티드 MCP 30도구를 그대로 옮기는 길이 아니다 (§13).

v0 코드가 `ParentKind.UNIVER` 외에서 sidecar를 켜면 계약 위반이다.

---

## 13. Non-goals (v0)

아래를 구현·래핑·이름만 빌려오는 것도 거부한다. 근거는 [`12-ecosystem-agents.md`](../12-ecosystem-agents.md)와 [`07-ai-agent-surface.md`](../07-ai-agent-surface.md).

| Non-goal | 왜 |
|---|---|
| Hosted MCP 30 tools as-is (`set_range_data`, `scroll_and_screenshot`, …) | `univer-mcp` + start-kit + `@univerjs-pro/mcp*`. 브라우저 `window.univerAPI` 브리지. Neos 이름은 `univer.<verb>.v1`. |
| univer-cli daemon / `.univer` SQLite / `univer execute` | 신뢰된 Facade JS, “not a sandbox”. v0는 구조화 COMMAND만. |
| Pro History semantic diff | Pro. OSS undo 스택은 로컬 50개일 뿐 (`LocalUndoRedoService`). |
| Charts / pivot | Pro. OSS `DrawingTypeEnum.CHART`는 enum + float-dom 훅, 렌더러 없음 ([`13-runtime-contracts.md`](../13-runtime-contracts.md) §7). |
| Slides facade | `packages/slides`에 facade/preset 없음. |
| Screenshot, PDF, layout lint | `engine-render` `Canvas.toDataURL`은 HTMLCanvasElement (`packages/engine-render/src/canvas.ts:191-206`). Node core preset은 engine-render를 넣지 않는다 (`preset-sheets-node-core/src/preset.ts`, package.json dependencies). |
| xlsx / docx import-export / print | Pro exchange (`README.md:292, 308`). |
| Worktree 프로토콜 (`markReady` / `mergeWorktree` as Univer collab) | 형제 레포 / Pro. Neos `draft/` + `merge.v1`이 그 자리를 대신한다. Git worktree가 아니다. |
| `@univerjs/rpc-node`를 sidecar 게이트로 | 수식 replica IPC. Neos JSON-RPC와 섞지 않는다. |
| Custom function registration over RPC | `remote-register-function.service.ts:57` throw. |
| `mcp.univer.*` 도구 이름 | v0 네이밍 거절. |
| Bases / Boards / PDF units | 프로토콜 enum만. `createUnit(UNIVER_BASE)` 기본 경로 없음. |

---

## 14. Package / process map

구현이 만들 자리 (이름 잠금; 이 스펙 PR은 문서를 쓸 뿐 코드를 열지 않는다):

| Path | 책임 |
|---|---|
| `neos/univer/sidecar/` | Node 진입점. `createUniver` + JSON-RPC 서버. |
| `neos/univer/port.py` | `UniverToolPort` (`ToolPort`). |
| `neos/univer/session.py` | sidecar spawn, health, `load`/`merge`, idle kill. |
| `neos/univer/allowlist.py` | §8 frozenset. |
| `neos/subagent/types.py` | `ParentKind.UNIVER`. |
| `neos/subagent/catalog.py` | `univer-reader` / `univer-writer` / `univer-critic`. |
| tests | sidecar round-trip 1000×20 + resources; allowlist 거부; `_tool_permitted`; writer draft jail. |

`neos/subagent/stepper.py`의 `_tool_permitted` 로직은 바꾸지 않는다. 정확 멤버십이 정책이다.

---

## 15. References

Univer clone (읽기 전용):

- [`docs/univer/07-ai-agent-surface.md`](../07-ai-agent-surface.md) — Facade가 에이전트 표면, MCP/CLI는 다른 레포.
- [`docs/univer/09-facade-api.md`](../09-facade-api.md) — mixin / `save()` / `executeCommand` / `getFormula`.
- [`docs/univer/11-commands-permissions.md`](../11-commands-permissions.md) — COMMAND vs MUTATION, interceptor, 권한.
- [`docs/univer/12-ecosystem-agents.md`](../12-ecosystem-agents.md) — MCP 30, CLI execute, DSH tools — **감싸지 않음**.
- [`docs/univer/13-runtime-contracts.md`](../13-runtime-contracts.md) — snapshot JSON, 1000×20, resources.
- [`docs/univer/14-formula-engine-internals.md`](../14-formula-engine-internals.md) — dirty → `set-formula-calculation-result`, RPC 함수 등록 금지.

Neos:

- `neos/subagent/types.py` — `ParentKind`, `ToolPort`.
- `neos/subagent/stepper.py` — `_tool_permitted`, `_MAX_TOOL_BODY`.
- `neos/subagent/catalog.py` — `*.v1` 도구 이름, FSI leaf 패턴.
- `neos/coding/model/base.py` — `ToolDefinition`.
- `neos/fsi/ports.py` — parent-injected port + `ok/error` mapping 선행 사례.
