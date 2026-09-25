# 05. Network · RPC · Protocol · Collaboration 프리미티브

조사 기준: `/Users/yeonwoosung/Desktop/univer` (Apache-2.0, `@univerjs/*` 1.0.2). 이 클론에는 **실시간 협업 서버가 없다.** README가 협업을 Pro로 명시하고, 워크스페이스에도 collab client/server 패키지가 없다.

핵심 구분:

| 층 | 이 클론에 있는 것 | 이 클론에 없는 것 |
|---|---|---|
| 전송 | HTTP/WebSocket 클라이언트 추상화 (`@univerjs/network`) | 협업 게이트웨이, Comb 룸 서버 |
| 프로세스 간 | 브라우저 Web Worker RPC, Node `child_process` RPC | Node collaboration client, computing delegation 서버 |
| 계약 | changeset/colla-msg/snapshot **타입** (`@univerjs/protocol`). `.proto` 없음. 체크인된 TS + `@grpc/grpc-js` Metadata | 그 타입을 구현하는 gRPC/WS 서버 (`ISnapshotService`, `IAuthzService`, `ICombService`, `IHistoryService`, `ILicenseService` …) |
| OT | Docs `JSONX`/`TextX` (`ot-json1`) — 로컬 문서 변환 | 멀티유저 OT 브로커, changeset replay 툴 |
| 훅 | `fromCollab` / `onMutationExecutedForCollab` / `collaboration?: true` 오버라이드 슬롯 | Pro collab 플러그인이 그 슬롯에 꽂는 구현 |

README 원문:

> Live editing, shared revisions, and Worktree workflows require the corresponding Web SDK and collaboration capabilities; package availability and licensing vary by feature.  
> (`README.md:141`)

> Collaboration server, Node.js collaboration client, SSR services, computing delegation, server-side calculation, and collaboration changeset replay tooling.  
> — Univer Pro / commercial (`README.md:312`)

> The repository does not own Univer Pro's commercial collaboration, import/export, server, or enterprise capabilities  
> (`DREAMNUM.md:15`)

Pro 저장소는 별도 `dream-num/univer-pro`이며, OSS `dev` 푸시 시 `sync-univer` dispatch만 보낸다 (`.github/workflows/dispatch-sync-univer-pro.yml:1-24`). 이 클론 안에 서버 바이너리나 collab 패키지는 없다.

---

## 1. 런타임이 서로 말하는 방식

```
┌──────────────────────────── 브라우저 ────────────────────────────┐
│  Main Univer                                                 │
│   ├─ UniverNetworkPlugin  HTTP (XHR 기본) / Facade WS        │
│   ├─ UniverRPCMainThreadPlugin  ──postMessage──►  Web Worker │
│   │     DataSyncPrimary              IMessageProtocol        │
│   │     채널: rpc.remote-sync.service / univer.remote-instance-service │
│   │           sheets-formula.remote-register-function.service (역직렬화 throw) │
│   │           sheets-filter.generate-filter-values.service    │
│   │     시트 스냅샷 + allowlist MUTATION (`fromSync`로 bounce 방지, onlyLocal은 안 봄) │
│   │                          ◄── 계산 결과 MUTATION ──       │
│   │     UniverRPCWorkerThreadPlugin + 수식 엔진              │
│   └─ UniverDocsLayoutWorkerPlugin ──postMessage──► Layout WW │
│         ChannelService('univer.docs-layout-worker') protocol v5 │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────── Node.js ─────────────────────────┐
│  Main Univer                                                 │
│   ├─ UniverNetworkPlugin  HTTP (fetch 기본)                  │
│   └─ UniverRPCNodeMainPlugin  ──fork+IPC──►  child process   │
│         DataSyncPrimary            process.send / 'message'  │
│                              UniverRPCNodeWorkerPlugin       │
│                              수식 replica                    │
└──────────────────────────────────────────────────────────────┘

Pro (이 클론 밖)
  브라우저/Node collab client ──WS/gRPC──► Collaboration server
  IChangeset / ICollaMsg / ICombService 계약을 실제로 구현
```

Isomorphic 규칙 (`docs/ISOMORPHIC.md:1-34`):

- Node.js 지원 우선순위는 브라우저와 같다 (`docs/ISOMORPHIC.md:3-4`).
- 서버+클라이언트 기능은 로직 플러그인 / UI 플러그인으로 나눈다 (`docs/ISOMORPHIC.md:11-18`). `fs`/`path`/`child_process`는 서버 전용 플러그인 (`docs/ISOMORPHIC.md:20-21`).
- Facade는 서버와 클라이언트 모두에서 동작해야 한다 (`docs/ISOMORPHIC.md:25-29`).
- `MUTATION`은 UI 상태를 읽지 말고 로직 플러그인에 둔다 (`docs/ISOMORPHIC.md:33-34`). 그래서 Worker/Node replica가 같은 mutation을 재실행할 수 있다.

OSS Runtime 칸 (`README.md:296`, `README.md:312`):

- **OSS:** Browser apps, Node.js headless, Web Worker/RPC patterns, multi-instance, server-oriented automation primitives.
- **Pro:** Collaboration client/server, Node.js collaboration client, SSR, computing delegation, server-side calculation, changeset replay.

---

## 2. `@univerjs/network` — HTTP/WebSocket 클라이언트

패키지 README는 “collaboration-oriented integrations”용 네트워크 추상화라고 쓴다 (`packages/network/README.md:7`). 구현은 **클라이언트 전송 계층**이지 협업 프로토콜이 아니다. 키워드에 `collaboration`이 있지만 (`packages/network/package.json:24`) 서버는 없다.

### 2.1 플러그인 등록

`UniverNetworkPlugin`은 `HTTPService`와 `IHTTPImplementation`만 등록한다 (`packages/network/src/plugin.ts:51-72`).

구현 선택 (`packages/network/src/plugin.ts:62-66`):

| 조건 | 구현 |
|---|---|
| `useFetchImpl: true` | `FetchHTTPImplementation` |
| `typeof window !== 'undefined'` (브라우저 기본) | `XHRHTTPImplementation` |
| 그 외 (Node) | `FetchHTTPImplementation` |

설정 (`packages/network/src/config/config.ts:23-42`):

- `useFetchImpl?: boolean`
- `override?: DependencyOverride` — `HTTPService` / `IHTTPImplementation` 교체
- `forceUseNewInstance?: boolean` — 조상 injector에 이미 `HTTPService`가 있으면 기본은 skip (`packages/network/src/plugin.ts:52-60`)

`WebSocketService`는 플러그인 DI에 **등록되지 않는다.** Facade `createSocket`이 `injector.createInstance(WebSocketService)`로 일회성 인스턴스를 만든다 (`packages/network/src/facade/f-univer.ts:88-96`).

Preset 기본 포함: `UniverSheetsCorePreset` (`presets/packages/preset-sheets-core/src/preset.ts:111`), `UniverDocsCorePreset` (`presets/packages/preset-docs-core/src/preset.ts:54`). Node sheets preset에는 network 플러그인이 없다.

### 2.2 HTTPService

Angular HttpClient 스타일. GET/POST/PUT/DELETE/PATCH + interceptor 체인 (`packages/network/src/services/http/http.service.ts:74-211`).

- `registerHTTPInterceptor({ priority?, interceptor })` — JSDoc은 큰 숫자가 먼저라고 적지만, 구현 정렬은 **오름차순**이라 **낮은 `priority`가 먼저** 돈다. 테스트가 이 동작을 고정한다 (`http.service.spec.ts:44-68`). 내장 interceptor는 플러그인이 기본으로 안 넣고, 앱이 `registerHTTPInterceptor`를 호출해야 한다.
- `request()`는 interceptor 파이프의 첫 이벤트를 `firstValueFrom`으로 받는다 (`packages/network/src/services/http/http.service.ts:154-157`).
- `stream()`은 SSE/progress용 Observable (`packages/network/src/services/http/http.service.ts:168-187`). Facade는 `getSSE()`로 노출 (`packages/network/src/facade/f-network.ts:96-102`).

내장 interceptor factory:

| Factory | 역할 | 위치 |
|---|---|---|
| `AuthInterceptorFactory` | 지정 status에서 `onAuthError()` | `packages/network/src/services/http/interceptors/auth-interceptor.ts:26-42` |
| `RetryInterceptorFactory` | 기본 3회, 1s delay | `packages/network/src/services/http/interceptors/retry-interceptor.ts:21-32` |
| `ThresholdInterceptorFactory` | 동시 요청 상한 (`maxParallel`, 기본 1) | `packages/network/src/services/http/interceptors/threshold-interceptor.ts:29-42` |
| `MergeInterceptorFactory` | 동일 요청 병합 | `packages/network/src/services/http/interceptors/merge-interceptor.ts:46-59` |

구현:

- `FetchHTTPImplementation` — 브라우저+Node. 주석: streaming response 미지원 (2024-05-12) (`packages/network/src/services/http/implementations/fetch.ts:32-35`).
- `XHRHTTPImplementation` — 브라우저. 동기 XHR 없음 (`packages/network/src/services/http/implementations/xhr.ts:32-35`).
- `IHTTPImplementation.send()`는 `Observable<HTTPEvent>` (`packages/network/src/services/http/implementations/implementation.ts:25-32`).

### 2.3 WebSocket

`ISocketService.createSocket(url)` → `ISocket` (`packages/network/src/services/web-socket/web-socket.service.ts:25-49`). 브라우저 `WebSocket`을 Observable `open$`/`close$`/`error$`/`message$`로 감싼다 (`packages/network/src/services/web-socket/web-socket.service.ts:54-96`). Node 전용 WS 구현은 없다.

### 2.4 Facade와 “직접 만든 협업” 예시

`FUniver.getNetwork()` → `FNetwork` HTTP 래퍼 (`packages/network/src/facade/f-network.ts:30-86`).

`FUniver.createSocket(url)` JSDoc은 **앱이 mutation을 WS로 브로드캐스트하는 샘플**이다 (`packages/network/src/facade/f-univer.ts:31-78`):

1. `univerAPI.createSocket('wss://…')`
2. `CommandExecuted`에서 로컬 `MUTATION`만 보내고 (`fromCollab`/`onlyLocal`/`doc.mutation.rich-text-editing` 제외)
3. 수신 측 `executeCommand(id, params, { fromCollab: true })`

이건 OSS가 제공하는 **전송 구멍**이지 CRDT/OT 서버가 아니다. 충돌 변환, revision, join/leave, ack/reject가 없다. 샘플 URL `wss://47.100.177.253:8449/ws`는 이 클론의 서버가 아니다 (`packages/network/src/facade/f-univer.ts:39`).

---

## 3. `@univerjs/rpc` — 브라우저 메인 ↔ Worker

브라우저 친화 RPC. 프로세스 간 **같은 Univer 인스턴스 두 개**를 mutation으로 맞춘다. 멀티유저 협업이 아니다 (`packages/rpc/README.md:7`, `packages/rpc/package.json:5`).

README가 가리키는 `examples/src/sheets-mobile/worker.ts`는 이 클론에 없다. 실제 worker preset은 `presets/packages/preset-sheets-core/src/worker.ts`.

### 3.1 메시지 프로토콜과 채널

`IMessageProtocol` (`packages/rpc/src/services/rpc/rpc.service.ts:26-30`):

```ts
{ send(message): void; onMessage: Observable<any> }
```

브라우저 구현 (`packages/rpc/src/services/rpc/implementations/web-worker-rpc.service.ts:24-57`):

- Worker: `postMessage` / `addEventListener('message')`
- Main: `worker.postMessage` / `worker.addEventListener('message')`

`ChannelService`는 한 protocol 위에 `ChannelClient`+`ChannelServer`를 동시에 올린다 (`packages/rpc/src/services/rpc/channel.service.ts:32-52`). 양방향 호출이 된다.

모듈 래핑 (`packages/rpc/src/services/rpc/rpc.service.ts:51-113`):

- `fromModule(service)` — 로컬 메서드/Observable을 `IChannel`로
- `toModule(channel)` — Proxy. 이름이 `$`로 끝나면 `subscribe`, 아니면 `call`

### 3.2 와이어 프로토콜

`RequestType` (`packages/rpc/src/services/rpc/rpc.service.ts:136-156`):

| 값 | 의미 |
|---|---|
| 50 `REQUEST_INITIALIZATION` | 클라이언트가 서버 INITIALIZE를 놓쳤을 때 재요청 |
| 100 `CALL` | Promise RPC |
| 101 `SUBSCRIBE` | remote Observable |
| 102 `UNSUBSCRIBE` | 구독 취소 |

`ResponseType` (`packages/rpc/src/services/rpc/rpc.service.ts:166-180`): `INITIALIZE=0`, `CALL_SUCCESS/FAILURE=201/202`, `SUBSCRIBE_NEXT/ERROR/COMPLETE=300/301/302`.

초기화 레이스 대응: 서버 생성 시 `INITIALIZE`를 보내고, 클라이언트는 즉시 `REQUEST_INITIALIZATION`을 보낸다 (`packages/rpc/src/services/rpc/rpc.service.ts:136-145`, `207-208`, `386-388`, `423-425`). 이미 초기화된 채널은 snapshot이 직렬화 전에 바뀌지 않도록 동기 fast path를 탄다 (`packages/rpc/src/services/rpc/rpc.service.ts:254-259`).

### 3.3 플러그인 부트

`UniverRPCMainThreadPlugin` (`packages/rpc/src/plugin.ts:44-106`):

- `workerURL: string | URL | Worker` 필수 (`packages/rpc/src/config/config.ts:21-23`, `packages/rpc/src/plugin.ts:81-84`)
- 문자열/URL이면 내부에서 `new Worker` 후 dispose 시 `terminate` (`packages/rpc/src/plugin.ts:71-77`, `86-87`)
- 등록: `ChannelService`, `DataSyncPrimaryController`, `RemoteSyncPrimaryService`

`UniverRPCWorkerThreadPlugin` (`packages/rpc/src/plugin.ts:109-149`):

- 등록: `DataSyncReplicaController`, Worker message protocol, `WebWorkerRemoteInstanceService`

### 3.4 Data sync — 수식 오프로드

Primary(메인)이 replica(Worker)에 시트 스냅샷과 mutation을 밀어 넣고, replica가 계산 mutation을 돌려보낸다.

**Primary** (`packages/rpc/src/controllers/data-sync/data-sync-primary.controller.ts:40-45`):

- 기본 동기화 대상은 **spreadsheet만** (`packages/rpc/src/controllers/data-sync/data-sync-primary.controller.ts:44-45`).
- 시트 생성/폐기를 replica `createInstance`/`disposeInstance`에 미러 (`packages/rpc/src/controllers/data-sync/data-sync-primary.controller.ts:144-162`).
- 다른 문서 타입은 `syncUnit(unitId)`로 수동. SHEET 또는 BASE만 (`packages/rpc/src/controllers/data-sync/data-sync-primary.controller.ts:79-89`).
- mutation은 `registerSyncingMutations`에 등록된 id만, `fromSync`가 아니고 unit이 syncing set에 있을 때 (`packages/rpc/src/controllers/data-sync/data-sync-primary.controller.ts:164-181`).
- 전송은 Promise 큐로 직렬화 (`packages/rpc/src/controllers/data-sync/data-sync-primary.controller.ts:115-122`).

시트가 등록하는 mutation 예: `SetRangeValuesMutation`, merge/row/col, `SetNumfmtMutation`, filter dirty 등 (`packages/sheets/src/controllers/basic-worksheet.controller.ts:210-233`). Worker 쪽은 `onlyRegisterFormulaRelatedMutations: true`로 수식 무관 mutation을 생략한다 (`packages/sheets/src/controllers/basic-worksheet.controller.ts:235-239`, `presets/packages/preset-sheets-core/src/worker.ts:38`).

**Replica** (`packages/rpc/src/controllers/data-sync/data-sync-replica.controller.ts:29-70`): 로컬 `MUTATION`이 `fromSync`가 아니면 `IRemoteSyncService.syncMutation`으로 메인에 되돌린다.

적용 시 `fromCollab`은 버리고 `onlyLocal: true`, `fromSync: true`를 붙인다 (`packages/rpc/src/services/remote-instance/remote-instance.service.ts:40-47`, `121-128`). Worker 미러와 협업 피어 적용은 플래그가 다르다.

Replica가 만들 수 있는 유닛: `UNIVER_SHEET`, `UNIVER_BASE`. Docs/Slides는 throw (`packages/rpc/src/services/remote-instance/remote-instance.service.ts:95-106`).

채널 이름:

- `rpc.remote-sync.service` — replica → primary (`packages/rpc/src/services/remote-instance/remote-instance.service.ts:25-31`)
- `univer.remote-instance-service` — primary → replica (`packages/rpc/src/services/remote-instance/remote-instance.service.ts:50-57`)

### 3.5 수식 플러그인이 RPC를 쓰는 법

메인에서 `notExecuteFormula: true`이면 `UniverSheetsFormulaPlugin`이 `IRemoteRegisterFunctionService`를 Worker 채널 프록시로 붙인다 (`packages/sheets-formula/src/plugin.ts:135-142`).

Worker는 `UniverRemoteSheetsFormulaPlugin`이 `RemoteRegisterFunctionService`를 같은 채널에 등록한다 (`packages/sheets-formula/src/plugin.ts:85-90`).

Preset 조립 (`presets/packages/preset-sheets-core/src/preset.ts:107-160`):

```
workerURL 있음
  → UniverRPCMainThreadPlugin
  → FormulaEngine / Sheets / SheetsFormula 모두 notExecuteFormula: true
```

Worker preset (`presets/packages/preset-sheets-core/src/worker.ts:36-41`):

```
UniverSheetsPlugin({ onlyRegisterFormulaRelatedMutations: true })
UniverFormulaEnginePlugin
UniverRPCWorkerThreadPlugin
UniverRemoteSheetsFormulaPlugin
```

---

## 4. `@univerjs/rpc-node` — Node 메인 ↔ child process

브라우저 RPC와 **같은 DataSync 컨트롤러**를 `child_process.fork` IPC에 얹는다 (`packages/rpc-node/README.md:7`, `packages/rpc-node/src/plugin.ts:24-33`).

README의 `examples/src/node/sdk/worker.ts`는 이 클론에 없다. 실제는 `presets/packages/preset-sheets-node-core/src/worker.ts`.

`UniverRPCNodeMainPlugin` (`packages/rpc-node/src/plugin.ts:38-96`):

- `workerSrc: string` 필수 (`packages/rpc-node/src/config/config.ts:21-23`, `packages/rpc-node/src/plugin.ts:62-65`)
- `fork(path)` 후 `child.send` / `child.on('message')` (`packages/rpc-node/src/plugin.ts:133-154`)
- dispose 시 `child.kill()` (`packages/rpc-node/src/plugin.ts:84-94`)

`UniverRPCNodeWorkerPlugin` (`packages/rpc-node/src/plugin.ts:98-130`): `process.send` / `process.on('message')` (`packages/rpc-node/src/plugin.ts:157-170`).

Node sheets preset (`presets/packages/preset-sheets-node-core/src/preset.ts:64-76`): `workerSrc`가 있으면 메인에 `UniverRPCNodeMainPlugin`을 넣고 수식을 실행하지 않는다. Worker preset은 브라우저와 대칭 (`presets/packages/preset-sheets-node-core/src/worker.ts:42-47`).

`preset-docs-node-core`의 RPC 연결은 주석 처리되어 있다 (`presets/packages/preset-docs-node-core/src/preset.ts:23`, `43`). Docs 수식 오프로드는 OSS에서 켜져 있지 않다.

`rpc-node`는 Node 전용 플러그인이다 (`docs/ISOMORPHIC.md:20-21`의 `child_process` 규칙과 일치). 협업 서버가 아니다.

---

## 5. Docs 레이아웃 Worker — 같은 RPC, 다른 채널

시트 수식 오프로드와 별개로 Docs는 레이아웃을 Web Worker로 보낸다. `@univerjs/rpc`의 `ChannelService`/`toModule`를 재사용한다.

채널 이름 `univer.docs-layout-worker`, 프로토콜 버전 5 (`packages/docs/src/layout-worker/protocol.ts:20-21`).

메인 클라이언트 (`packages/docs/src/layout-worker/index.ts:44-59`, `195-198`): Worker `postMessage`를 `IMessageProtocol`로 감싸 `toModule<IDocsLayoutWorkerRuntime>`을 만든다.

Worker 엔트리: `startDocsLayoutWorker()` (`packages/docs/src/index.ts:69`, `examples/src/docs/worker.ts:1-2`). 예제 마운트 (`examples/src/docs/mount.ts:59-61`):

```ts
univer.registerPlugin(UniverDocsLayoutWorkerPlugin, {
  workerFactory: () => new Worker(new URL('./worker.ts', import.meta.url), { type: 'module' }),
});
```

OffscreenCanvas 텍스트 측정이 없으면 실패한다 (`packages/docs/src/layout-worker/worker.ts:139` 근처). 문서 스냅샷/mutation을 레이아웃에 넘기는 계산 오프로드이며, 사용자 간 동기화가 아니다.

---

## 6. `@univerjs/protocol` — 공유 계약, 구현 없음

“Shared protocol types, generated service interfaces, and data contracts” (`packages/protocol/package.json:5`). 의존성 `@grpc/grpc-js`는 서비스 인터페이스의 `Metadata` 타입용이다 (`packages/protocol/package.json:67`). 이 패키지는 gRPC 서버/클라이언트를 띄우지 않는다.

OSS가 실제로 import하는 값은 주로 권한 enum이다: `UnitAction`, `UnitObject`, `UnitRole`, `ObjectScope` (`packages/protocol/src/index.ts:52-57`). 예: `AuthzIoLocalService` (`packages/core/src/services/authz-io/authz-io-local.service.ts:17-33`), Docs permission commands.

### 6.1 문서 모델 타입 (`ts/univer/`)

| 심볼 | 역할 | 파일 |
|---|---|---|
| `UniverType` | UNKNOWN/DOC/SHEET/SLIDE/PROJECT/BASE/BOARD/PDF | `packages/protocol/src/ts/univer/constants/univer.ts:17-27` |
| `ISnapshot` | unitID + type + rev + workbook/doc/slide/board/pdf | `packages/protocol/src/ts/univer/snapshot.ts:24-34` |
| `IChangeset` | `baseRev`/`revision`/`mutations[]`/`userID`/`memberID`/`sid`/`reqId` | `packages/protocol/src/ts/univer/changeset.ts:35-59` |
| `IMutation` / `ICommand` | `{ id, data: string }` 직렬화 커맨드 | `packages/protocol/src/ts/univer/changeset.ts:20-33` |
| `ICollaMsg` | 실시간 이벤트 유니온 | `packages/protocol/src/ts/univer/colla-msg.ts:20-55` |
| `IWorkbookMeta` 등 | 스냅샷 페이로드 | `packages/protocol/src/ts/univer/workbook.ts` 등 |

`ICollaMsg` 이벤트 (`packages/protocol/src/ts/univer/colla-msg.ts:20-55`):

- 멤버: `joinEvent`, `leaveEvent`, `updateCollaboratorEvent`
- 편집: `newCsEvent`, `csAckEvent`, `csRejEvent`, `csShouldRetryEvent`, `permissionRejEvent`
- 커서: `updateCursorEvent`
- 라이브 셰어: `liveShareRequestHost` / `NewHost` / `Operation` / `Terminate`
- 기타: `commentUpdateEvent`, `updatePermissionObjEvent`, `uniscriptRunEvent`, `shouldCloseConn`, `errorEvent`

이 클론에서 `ICollaMsg`를 보내거나 받는 코드는 `packages/protocol` export 외에는 없다.

### 6.2 Universer 서비스 인터페이스 (`ts/universer/v1/`)

메서드가 `Observable<…>` + `Metadata?`인 gRPC 스타일 계약. 구현체는 없다.

| 서비스 | 하는 일 | 파일 |
|---|---|---|
| `ICombService` | `NewChanges`, `Broadcast`. CombCmd: HELLO/JOIN/LEAVE/INGEST/HEARTBEAT/RECV | `packages/protocol/src/ts/universer/v1/comb.ts:27-46`, `127-130` |
| `ISnapshotService` | unit CRUD, `SaveChangeset`, `FetchMissingChangesets`, `SaveSnapshot`, `DirectWrite`, `GetUnitOnRev`, sheet block, fork | `packages/protocol/src/ts/universer/v1/snapshot.ts:379-438` |
| `IAuthzService` | collaborator/permission point | `packages/protocol/src/ts/universer/v1/authz.ts` |
| `IHistoryService` | revision 구간 히스토리 | `packages/protocol/src/ts/universer/v1/history.ts` |
| `IFileService` | 업로드/서명 URL | `packages/protocol/src/ts/universer/v1/file.ts` |
| `ILicenseService` | 라이선스 + 수식 태스크 한도 (같은 파일) | `packages/protocol/src/ts/universer/v1/license.ts` |
| comment / user / access-key | 스레드 댓글, 유저, 키 | `packages/protocol/src/ts/universer/v1/` |

Comb 룸 에러 코드에 “global live collaboration rooms count exceeds”가 있다 (`packages/protocol/src/ts/universer/v1/comb.ts:61-62`). 서버 구현은 이 클론에 없다.

`isError()`는 Universer HTTP가 `error.code`를 문자열 `'OK'`로 주는 케이스를 흡수한다 (`packages/protocol/src/utils.ts:26-34`).

### 6.3 Univer Pro 계약 (`ts/univerpro/v1/`)

| 심볼 | 역할 | 파일 |
|---|---|---|
| `IApplyRequest` | changeset apply + `fastForward[]` | `packages/protocol/src/ts/univerpro/v1/apply.ts:92-101` |
| `IDirectWriteRequest` | command 또는 mutation 직접 기록 | `packages/protocol/src/ts/univerpro/v1/apply.ts:111-126` |
| `ICollaborationHelperService` | 백그라운드 스냅샷, `EnsureSnapshot` | `packages/protocol/src/ts/univerpro/v1/helper.ts:32-43` |
| SSC `IComputeRequest` | 서버 사이드 시트 계산 | `packages/protocol/src/ts/univerpro/v1/ssc.ts:62-80` |
| SSR `IGetSSRResponse` | 서브유닛 PNG base64 | `packages/protocol/src/ts/univerpro/v1/ssr.ts:20-33` |

README Pro 칸의 “server-side calculation / SSR / changeset replay”가 가리키는 계약이다. 클라이언트/서버 구현은 없다.

시트 블록 역직렬화 타입은 `packages/protocol/src/other/sheet-block.ts:19-30`. `id` 주석: “generate by backend server”.

---

## 7. OT — `ot-json1` in core

`@univerjs/core` 의존성 `ot-json1@^1.0.2` (`packages/core/package.json:88`). 사용처는 Docs JSON 문서 모델이다. 시트 셀 OT가 아니다.

`JSONX`는 `ot-json1` 래퍼 (`packages/core/src/docs/data-model/json-x/json-x.ts:22-73`):

- `apply` / `compose` / `transform` / `invertWithDoc` / `isNoop`
- `insertOp` / `removeOp` / `replaceOp` / `moveOp` / `editOp`
- `editOp` 기본 path는 `['body']` — 리치 텍스트가 body에 있기 때문 (`packages/core/src/docs/data-model/json-x/json-x.ts:125-128`)

`TextX`는 json1 subtype. `JSONX.registerSubtype(TextX)` (`packages/core/src/docs/data-model/json-x/json-x.ts:131`). `TextX.id = 'text-x'` (`packages/core/src/docs/data-model/text-x/text-x.ts:102-107`). `name`은 Storybook 때문에 `Object.defineProperty`로 붙인다 (`packages/core/src/docs/data-model/text-x/text-x.ts:617-620`).

`JSONX.transformPosition`은 path가 `['body']`이고 subtype이 TextX일 때만 커서 인덱스를 옮긴다 (`packages/core/src/docs/data-model/json-x/json-x.ts:75-81`). 로컬 협업 커서 변환용 훅이고, 네트워크 전송은 없다.

Docs 명령/레이아웃이 `JSONX.compose`/`editOp`으로 undo/redo와 Worker 레이아웃 mutation을 만든다 (`packages/docs/src/services/doc-state-change-manager.service.ts:231-243`, `packages/docs/src/services/doc-layout-executor.service.ts:45`, `111`). 같은 OT 타입을 Pro collab이 changeset에 실을 수는 있지만, 그 전송 경로는 이 클론에 없다.

시트 편집은 OT가 아니라 **커맨드/뮤테이션 로그**다. 프로토콜 `IChangeset.mutations[]`가 그 직렬화 형태다 (`packages/protocol/src/ts/univer/changeset.ts:35-42`).

---

## 8. Collaboration 프리미티브 (OSS 훅)

실시간 서버 없이, Pro 클라이언트가 꽂을 수 있는 훅만 있다.

### 8.1 `IExecutionOptions`

`packages/core/src/services/command/command.service.ts:186-198`:

| 플래그 | 의미 |
|---|---|
| `onlyLocal` | 로컬만 실행, replica에 동기화하지 않음 |
| `fromCollab` | 협업 피어에서 온 커맨드 |
| `fromChangeset` | 스냅샷/changeset 로드 |
| `syncOnly` | changeset에는 올리되 로컬 실행은 나중에 `onlyLocal`로 |

RPC replica 적용은 `fromCollab`을 제거하고 `fromSync`+`onlyLocal`을 쓴다 (`packages/rpc/src/services/remote-instance/remote-instance.service.ts:41-46`). `fromCollab`은 사람 간 협업용.

### 8.2 `onMutationExecutedForCollab`

리스너는 **하나**만 등록 가능 (`packages/core/src/services/command/command.service.ts:264-270`, `403-414`). mutation에만 호출되고, `syncOnly`면 일반 `onCommandExecuted`는 건너뛴다 (`packages/core/src/services/command/command.service.ts:449-458`).

이 클론의 프로덕션 플러그인은 이 리스너를 등록하지 않는다. 테스트와 clipboard spec만 사용한다. Pro collab 클라이언트가 여기 붙어 changeset을 만들 자리로 읽힌다.

### 8.3 `createUniver({ collaboration: true })`

`presets/src/preset.ts:45-55`:

```ts
if (collaboration) {
  override.push([IUndoRedoService, null]);
  override.push([IAuthzIoService, null]);
  override.push([IMentionIOService, null]);
}
```

로컬 undo/authz/mention을 **제거**해 Pro가 원격 구현을 넣게 한다. 협업을 켜는 코드가 아니다. Docs/Sheets drawing preset은 `collaboration`이면 `IImageIoService`도 null (`presets/packages/preset-docs-drawing/src/preset.ts:37`, `presets/packages/preset-sheets-drawing/src/preset.ts:42`).

OSS 기본 `AuthzIoLocalService`는 “Do not use the mock implementation in a production environment” (`packages/core/src/services/authz-io/authz-io-local.service.ts:41-55`). 인터페이스는 protocol `IAuthzService`와 같은 요청 타입을 쓴다 (`packages/core/src/services/authz-io/type.ts:40-54`).

### 8.4 `freezeSync`

시트 설정. 기본 `true` — freeze를 실시간 협업 상대에게 동기화 (`packages/sheets/src/config/config.ts:58-62`). `false`면 `SetFrozenMutation`에 `onlyLocal`을 붙인다 (`packages/sheets/src/controllers/freeze-sync.controller.ts:52-75`). 동기화 **정책**이지 전송 구현이 아니다.

### 8.5 필터 등 collab 재실행

`sheets-filter-sync.controller.ts`는 `fromCollab`+`onlyLocal` mutation이 필터 캐시에 영향을 줄 때 로컬 재계산한다. collab 클라이언트가 이미 적용한 mutation을 OSS 기능이 따라가기 위한 훅이다.

---

## 9. `@univerjs/telemetry`

인터페이스만 있다 (`packages/telemetry/README.md:7`, `packages/telemetry/src/services/telemetry.service.ts:19-74`): `init` / `identify` / `capture` / `startTime`/`endTime` / `trackPerformance` / `onPageView`.

구현·플러그인 등록이 없다. `SheetRenderController`가 `@Optional(ITelemetryService)`로 `sheet_render_cost`를 `capture`한다 (`packages/sheets-ui/src/controllers/render-controllers/sheet.render-controller.ts:70`, `226`). 앱이 구현체를 넣지 않으면 no-op.

협업 텔레메트리 백엔드가 아니다.

---

## 10. `@univerjs/action-recorder` — 로컬 매크로

사용자 커맨드를 JSON으로 기록하고 같은 머신에서 재생한다 (`packages/action-recorder/README.md:7`, `packages/action-recorder/src/plugin.ts:27-30`). Pro의 “collaboration changeset replay tooling” (`README.md:312`)과 다르다.

동작:

- mutation은 기록 불가 (`packages/action-recorder/src/services/action-recorder.service.ts:56-58`).
- 등록된 COMMAND/OPERATION만 `onCommandExecuted`로 수집 (`packages/action-recorder/src/services/action-recorder.service.ts:67-104`).
- 완료 시 `recorded-commands.json` 다운로드 (`packages/action-recorder/src/services/action-recorder.service.ts:119-124`).
- replay는 focused unit의 `unitId`를 덮어쓰고 `executeCommand`를 순차 실행 (`packages/action-recorder/src/services/replay.service.ts:68-110`). delay 모드 200–1000ms (`packages/action-recorder/src/services/replay.service.ts:117-141`, `148-150`).
- `replayOnly: true`면 recorder UI 없이 replay 서비스만 (`packages/action-recorder/src/plugin.ts:60-65`, `packages/action-recorder/src/config/config.ts:23-26`).

시트 커맨드(값/스타일/merge/filter/paste 등)는 등록되어 있다 (`packages/action-recorder/src/controllers/action-recorder.controller.ts:118-193`). Docs는 `// TODO` (`packages/action-recorder/src/controllers/action-recorder.controller.ts:196-198`).

네트워크 없이 디버그/데모/자동화 재현용이다.

---

## 11. OSS-ready vs Pro collab

README 표 (`README.md:290-312`)를 이 클론 코드에 대응하면:

| 능력 | OSS (이 클론) | Pro (이 클론 밖) |
|---|---|---|
| HTTP 클라이언트 | `@univerjs/network` HTTPService | 인증/테넌트 인터셉터를 Pro 서버에 연결 |
| WebSocket 클라이언트 | `WebSocketService` + Facade 샘플 | collab 클라이언트가 `ICollaMsg` 프레임을 주고받음 |
| 메인↔Worker 수식 | `@univerjs/rpc` DataSync | computing delegation / SSC (`IComputeRequest`) |
| 메인↔Node child 수식 | `@univerjs/rpc-node` | Node collaboration client |
| Docs 레이아웃 Worker | `UniverDocsLayoutWorkerPlugin` | 해당 없음 (로컬 렌더 오프로드) |
| 권한 타입 | `UnitAction` 등 + `AuthzIoLocalService` mock | `IAuthzService` 원격 + collaborator 실시간 이벤트 |
| 문서 OT | `JSONX`/`TextX` 로컬 apply/transform | changeset에 실어 Comb으로 브로드캐스트 |
| mutation 동기화 훅 | `onMutationExecutedForCollab`, `fromCollab` | 그 훅에서 `IChangeset` 생성·ack/reject |
| undo | 로컬 `IUndoRedoService` | `collaboration: true`로 null → 서버 히스토리 |
| 스냅샷/히스토리 | 유닛 스냅샷 메모리 모델 | `ISnapshotService` / `IHistoryService` |
| SSR 이미지 | 없음 | `IGetSSRResponse.imageEncoded` |
| 액션 리플레이 | `@univerjs/action-recorder` 로컬 JSON | changeset replay tooling |
| 텔레메트리 | `ITelemetryService` 슬롯 | 구현체는 앱/Pro |

명시적으로 **없는 것**:

- `packages/` 아래 collab/collaboration/universer/comb 서버 패키지 없음.
- `ICombService` / `ISnapshotService` / `ICollaborationHelperService` 구현 없음 (grep 결과 protocol 정의만).
- `onMutationExecutedForCollab` 프로덕션 구독자 없음.
- `examples/`에 협업 데모 없음. Docs worker는 레이아웃 전용 (`examples/src/docs/worker.ts:1-2`).
- Facade WS 예시는 외부 URL을 가정한다 (`packages/network/src/facade/f-univer.ts:39`).

OSS 경계 원칙 (`README.md:316-321`): Pro 전용 능력을 `@univerjs/*`에 있는 것처럼 쓰면 안 된다. 이 클론의 network/rpc/protocol은 **연결 구멍과 계약**이고, 협업 제품은 Pro Web/Server SDK다 (`README.md:329-330`).

---

## 12. 한 줄 요약

브라우저와 Node는 같은 커맨드/뮤테이션 런타임을 공유한다 (`docs/ISOMORPHIC.md:3-4`). OSS는 (1) HTTP/WS **클라이언트**, (2) 프로세스 안 **RPC replica**(수식·Docs 레이아웃), (3) Pro가 구현할 **프로토콜 타입**, (4) mutation/OT/undo를 collab 클라이언트에 넘길 **훅**을 준다. 멀티유저 룸, changeset ack, 히스토리 서버, SSR, 서버 계산은 이 저장소에 없다.
