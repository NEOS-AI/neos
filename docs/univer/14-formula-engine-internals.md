# 수식 엔진 내부 — Lexer · AST · Interpreter · Dirty · Worker

조사 기준: `/Users/yeonwoosung/Desktop/univer` v1.0.2. 함수 개수 권위는 **516 map / 502 구현 디렉터리** (`02-sheets-formula.md`, `10-cross-check.md`). 이 문서는 파이프라인이다.

```text
formula string
  → Lexer.treeBuilder (defined-name 치환)
  → LexerTreeBuilder._nodeMaker (문자 스캔) + shunting-yard
  → AstTreeBuilder.parse
  → Interpreter.execute / executeAsync
  → BaseValueObject / BaseReferenceObject
  → SetRangeValuesMutation 로 셀 v/t 기록
```

---

## 1. Lexer

고전 `TokenType` enum이 없다. 재귀 하강 문자 스캐너가 `LexerNode` 트리(문자열 토큰)를 만든다. 저자 주석: “over complex… without a standalone lexer phase” (`lexer-tree-builder.ts:1567-1569`).

| 역할 | 경로 |
| --- | --- |
| defined name 래퍼 | `packages/engine-formula/src/engine/analysis/lexer.ts` |
| 실제 토크나이저 | `lexer-tree-builder.ts` |
| 연산자/괄호 문자 | `basics/token.ts` |
| `LAMBDA`/`LET`/`CUBE`/`R_1` | `basics/token-type.ts` |
| A1/table/array regex | `basics/regex.ts` |

연산자 우선순위 (`OPERATOR_TOKEN_PRIORITY`): compare=4, `&`=3, `+/-`=2, `*/`=1, `^`=0. 낮은 숫자 = 더 Tight. 같은 우선순위는 좌결합.

특수:

- `#DIV/0!` 등은 `ERROR_TYPE_SET` 통째 인식.
- `:` 는 이진 노드 (`A1:B5`, `Sheet1:Sheet3!A1`).
- `[` 는 테이블 구조화 참조.
- 쉼표 다중 영역 `INDEX((A6:B6,C6:D7),…)` 는 합성 `CUBE` 노드.
- `treeBuilder` LRU 2000. `LET`/`LAMBDA`는 캐시하지 않음.
- 선행 `=` 제거. 형식 오류(`=1/3+`)는 `#VALUE!`.

Defined name은 렉서 토큰이 아니다. 1차 스캔 뒤 `IDefinedNamesService.getValueByName`으로 치환하고 **다시 렉스**한다. 함수 레지스트리에 있는 이름은 치환하지 않는다.

Excel 공백 교차(`SUM(B1 C1)`)는 AST 노드가 없다. `ErrorType.NULL` 주석만 있고, 공백은 세그먼트에 흡수되어 대개 `#NAME?`. 암시적 교차는 prefix `@`.

---

## 2. AST

`AstTreeBuilder` (`engine/analysis/parser.ts`). `NODE_ORDER_MAP`: LAMBDA → LAMBDA_PARAMETER → UNION → PREFIX → SUFFIX → FUNCTION → REFERENCE → OPERATOR → VALUE → ROOT.

| 노드 | 표현 |
| --- | --- |
| 배열 `{1,2;3,4}` | `ArrayValueObject`. 쉼표=열, 세미콜론=행 |
| 연산자 | `OperatorNode` → PLUS/MINUS/MULTIPLY/DIVIDED/CONCATENATE/POWER/COMPARE |
| 함수 | `FunctionNode`. `needsReferenceObject`가 아니면 ref를 배열로 |
| `:` | `UnionNode`. 3D 시트 스팬 또는 범위 결합 |
| 쉼표 다중 영역 | `CubeValueObject` |
| `@` | 현재 셀로 투영 또는 배열 `[0,0]` |
| `%` | /100, pattern `0.00%` |
| `#` spill ref | stub, 아직 `#VALUE!` (`todo`) |
| `LET` | 파서에서 `LAMBDA`로 재작성 |

알 수 없는 식별자 → `#NAME?`. `RAND`/`NOW`/`TODAY`/`RANDBETWEEN`는 forced calculate.

---

## 3. Interpreter

후위 순회. `node.isAsync()`면 `executeAsync`.

지연 `IF`/`IFERROR`: 조건이 비배열 스칼라면 선택 분기만 실행.

값 계층:

| 종류 | 클래스 |
| --- | --- |
| number/string/boolean/null | `NumberValueObject` / `StringValueObject` / `BooleanValueObject` / `NullValueObject` |
| error | `ErrorValueObject` (LRU) |
| array / cube / lambda | `ArrayValueObject` / `CubeValueObject` / `LambdaValueObjectObject` |
| reference | Cell/Range/Row/Column/Table/MultiArea |
| async | `AsyncObject` / `AsyncArrayObject` |

셀 기록 (`objectValueToCellValue`): error→STRING, number→NUMBER, boolean→0\|1 BOOLEAN, 에러처럼 보이는 문자열→FORCE_STRING.

### 에러 코드 (`basics/error-type.ts:17-47`)

`#DIV/0!` `#NAME?` `#VALUE!` `#NUM!` `#N/A` `#CYCLE!` `#REF!` `#SPILL!` `#CALC!` `#ERROR!` `#GETTING_DATA` `#NULL!`.

`#CYCLE!`은 정의되어 있으나 순환 그래프에 자동으로 잘 안 쓴다. `#NULL!`은 공백 교차용 주석.

---

## 4. Dirty / 의존성

1. 시트 뮤테이션을 `ActiveDirtyController`가 본다. 스타일만 바꾼 `SetRangeValues`는 스킵.
2. `FormulaCalculationTriggerService`가 커맨드 실행을 **10ms debounce**로 합친다. 진행 중 계산과 dirty가 겹치면 stop mutation 후 재큐.
3. `formula.mutation.set-formula-calculation-start` → `CalculateFormulaService`.
4. 결과를 `SetRangeValuesMutation`으로 셀에 쓴다.

`FormulaDataModel`: shared formula id 맵, array formula range/값, IMAGE 수식. 셀 아이템 `{ f, x?, y?, si? }` — `x`/`y`는 shared-formula 오프셋.

배열 수식은 `ft`/`ref`/`fd`. spill 막히면 `#SPILL!`.

---

## 5. Worker / RPC

브라우저: `UniverRPCMainThreadPlugin` ↔ worker `UniverRPCWorkerThreadPlugin` + `UniverRemoteSheetsFormulaPlugin`. Node: `child_process.fork` (worker_threads 아님).

채널:

| 이름 | 역할 |
| --- | --- |
| `rpc.remote-sync.service` | replica → primary |
| `univer.remote-instance.service` | primary → replica |
| `sheets-formula.remote-register-function.service` | 커스텀 함수. **역직렬화는 throw** (“unsafe”) |
| `sheets-filter.generate-filter-values.service` | 필터 값 생성 |
| `univer.docs-layout-worker` | Docs 레이아웃 (수식 아님) |

DataSync는 **MUTATION + 유닛 allowlist + mutation allowlist + `fromSync` 아님**. `onlyLocal`은 안 본다. Replica는 수식 결과 MUTATION을 되돌려 보낸다.

워커 preset `onlyRegisterFormulaRelatedMutations: true` — 워커는 수식 관련 핸들러만 등록.

커스텀 함수 Facade `registerFunction`은 메인에서 돈다. 워커로 함수 소스를 실어 보내는 경로는 막혀 있다.

---

## 6. 수식 관련 MUTATION ID

`formula.mutation.*` 28개. 계산 제어: `set-formula-calculation-start|stop|result|notification`. 데이터: `set-formula-data`, `set-array-formula-data`, `set-defined-name`, `set-super-table`, `register-function`, query/cell dependency 쌍.

에이전트가 직접 부를 일은 거의 없고, `FRange.setFormula` → `sheet.command.set-range-values` → dirty → 위 뮤테이션이다.

---

## 7. 기타

- Date system은 현재 유닛 (`Date1900`/`Date1904`).
- `tests/formula-integration/` — Node에서 엔진+시트를 붙여 Excel 호환을 검증하는 통합 스위트.
- 함수 구현 패턴: `BaseFunction` 서브클래스 + `ArrayValueObject`. `SUM`/`VLOOKUP`/`IF`가 그 예.
- LAMBDA/LET는 파서·렉서에 있다. spill `#`는 stub.
