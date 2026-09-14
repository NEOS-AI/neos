# Managed sandbox provider 재검토 — 2026-09-14

> 범위: `neos/coding/sandbox/base.py`의 코딩 `SandboxProvider` 계약을 E2B, Modal, Daytona의 **공식 공개 문서**와 대조한다.
> 결론: B2의 제한된 prototype 대상은 **E2B + Modal**이다. Daytona는 reserve다. 세 공급자 모두 production 승인 상태가 아니다.
> 판정 기준: `native`는 공개된 안정/지원 API가 NEOS 의미를 직접 제공, `helper`는 vendor 실행·파일 API 위에 NEOS guest helper가 의미를 보강, `missing`은 공개 API로 안전하게 만들 수 없거나 production 경계에 필요한 보장이 확인되지 않음을 뜻한다. Alpha/Beta는 따로 표시한다.

## 1. 결정

E2B와 Modal로 B2 prototype을 각각 하나씩 만든다. 목적은 공급자 우열을 미리 확정하는 것이 아니라 동일한 NEOS 계약과 failure semantics를 실제 계정에서 검증하는 것이다.

- **E2B prototype:** 전용 Firecracker microVM, pause/resume, filesystem+memory snapshot이 코딩 세션 중단/재개와 잘 맞는다. E2B는 sandbox마다 자체 kernel을 가지며 다른 고객 sandbox와 filesystem/memory를 공유하지 않는다고 명시한다. managed cloud는 Google Cloud에서 동작하고 at-rest는 Google Cloud 기본 암호화, transit은 TLS다. ([Security](https://e2b.dev/security), [Persistence](https://docs.e2b.dev/sandbox/persistence), [Snapshots](https://docs.e2b.dev/sandbox/snapshots))
- **Modal prototype:** gVisor 격리, argv 기반 `exec`, filesystem API와 watcher, `block_network`, CIDR/domain allowlist가 강점이다. 기본 outbound는 열려 있으므로 NEOS가 create 시 명시적으로 닫아야 한다. Domain allowlist는 Beta이고 SNI/domain-fronting 한계가 문서화돼 있다. ([Networking and security](https://modal.com/docs/guide/sandbox-networking), [Sandbox SDK](https://modal.com/docs/sdk/py/latest/Sandbox))
- **Daytona reserve:** lifecycle, filesystem/search/Git, 완전한 PTY, snapshot, VM pause/resume 표면은 좋다. 그러나 Daytona 공식 인증 문서는 sandbox runtime/toolbox 접근이 grantable scope가 아니며, **조직에 유효한 API key는 선택한 key permission이 없어도 그 조직의 실행 sandbox에서 process/file/terminal을 조작할 수 있다**고 명시한다. NEOS가 요구하는 task/owner별 credential blast radius보다 넓으므로 이 경계가 계약·별도 조직·전용 배포로 좁혀지기 전 B2 대상에서 제외한다. ([Authentication — Permissions & Scopes](https://www.daytona.io/docs/api-keys))

이 결정은 production 승인이 아니다. 두 prototype 모두 §8의 conformance/security gate를 통과하고 보안 검토가 끝날 때까지 factory 기본값은 기존 `memory/off` 그대로이며, allowlist 밖 사용자·조직·repo에는 노출하지 않는다.

## 2. `SandboxProvider` capability matrix

표의 `helper`는 vendor SDK를 흉내 낸다는 뜻이 아니다. 이미지에 고정된 immutable `neos-sandboxd`와 host의 durable NEOS ledger가 공개된 vendor primitive를 조합해 정확한 NEOS 의미를 만든다는 뜻이다.

### 2.1 Provider lifecycle

| NEOS 계약 | E2B | Modal | Daytona | 판정 메모 |
|---|---|---|---|---|
| `create` | native | native | native | 세 공급자 모두 이미지/template/snapshot에서 생성한다. E2B는 metadata, Modal은 name/tags, Daytona는 name/labels를 받을 수 있다. ([E2B lifecycle](https://docs.e2b.dev/sandbox), [Modal Sandboxes](https://modal.com/docs/guide/sandboxes), [Daytona Sandboxes](https://www.daytona.io/docs/sandboxes)) |
| `get` / 재접속 | native | native | native | E2B `get_info`/`connect`, Modal `from_id`, Daytona `get`. 단, 이것은 NEOS owner 인가를 대신하지 않는다. ([E2B SDK](https://e2b.dev/docs/sdk-reference/python-sdk/v2.5.0/sandbox_sync), [Modal SDK](https://modal.com/docs/sdk/py/latest/Sandbox), [Daytona SDK](https://www.daytona.io/docs/en/typescript-sdk/sandbox/)) |
| `suspend` | native | missing vendor → helper: cold snapshot+terminate | native: VM / helper: container stop | E2B pause는 filesystem+memory를 보존한다. Modal 공개 lifecycle은 finished/terminate이며 suspend/resume가 없으므로 filesystem snapshot과 logical NEOS ID를 써서 cold suspend만 보강한다. Daytona container의 stop은 filesystem만, Linux VM/Windows pause는 memory도 보존한다. ([E2B persistence](https://docs.e2b.dev/sandbox/persistence), [Modal lifecycle](https://modal.com/docs/guide/sandboxes#lifecycle), [Daytona persistence](https://www.daytona.io/docs/en/persistence/)) |
| `resume` | native (`connect`) | missing vendor → helper: snapshot에서 재생성 | native: VM / helper: container start | Modal helper는 같은 logical NEOS sandbox ID 아래 provider generation/ref를 교체하며 process/memory 연속성은 주장하지 않는다. 해당 연속성이 필요한 profile은 `capability_unsupported`로 닫는다. |
| `snapshot` | native | native: filesystem; Alpha: memory | native: cold; VM hot도 지원 | E2B snapshot은 filesystem+memory를 캡처하며 원 sandbox는 다시 running이 되지만 PTY/command/WebSocket 연결은 끊긴다. Modal filesystem snapshot은 Image이며 기본 TTL 30일, memory snapshot은 Alpha다. Daytona container cold snapshot은 stopped 상태, VM hot snapshot은 started 상태를 요구한다. ([E2B snapshots](https://docs.e2b.dev/sandbox/snapshots), [Modal snapshots](https://modal.com/docs/guide/sandbox-snapshots), [Daytona snapshots](https://www.daytona.io/docs/snapshots/)) |
| `restore` | native: snapshot에서 create | native: Image에서 create | native: snapshot에서 create | provider snapshot ID와 NEOS checksum/owner/generation은 별도 원장에 둔다. snapshot을 portable archive라고 간주하지 않는다. |
| `destroy` | native (`kill`) | native (`terminate`) | native (`delete`) | NEOS는 provider 호출 전에 owner digest와 generation을 대조한다. not-found는 반복 cleanup에서 성공으로 정규화하되 mismatch는 절대 삭제하지 않는다. |
| `open_session` / `close` | native connect + client close | native attach/detach | native SDK handle | Modal은 detach 뒤 기존 object 동작을 보장하지 않고 `from_id` 재접속을 요구한다. ([Modal connection cleanup](https://modal.com/docs/guide/sandboxes#cleaning-up-client-side-connections)) |
| idle/absolute timeout | native timeout/auto-pause | native `timeout`/`idle_timeout` | native auto-stop/auto-pause/TTL | 공급자 timer는 방어층일 뿐 SoT가 아니다. NEOS ledger의 absolute expiry와 reaper가 이긴다. E2B running 상한은 Hobby 1h/Pro 24h, Modal sandbox 상한은 24h다. Daytona의 기본 auto-stop은 background process만으로 갱신되지 않는다. ([E2B limits](https://docs.e2b.dev/billing), [Modal timeouts](https://modal.com/docs/guide/sandboxes#timeouts), [Daytona lifecycle](https://www.daytona.io/docs/sandboxes)) |

### 2.2 Session, files, commands, PTY, watcher

| `SandboxSession` 계약 | E2B | Modal | Daytona | B2 구현 규칙 |
|---|---|---|---|---|
| `workspace_revision` | helper | helper | helper | vendor file API에 NEOS 전역 revision/CAS 의미가 없다. `neos-sandboxd`가 단조 revision을 관리하고 host ledger에 결과를 commit한다. |
| `list_tree`, `stat`, `read_file`, `write_file`, `mkdir`, `rm` | native | native | native | 경로 정규화, symlink 탈출 차단, byte cap은 vendor API 앞에서 NEOS가 다시 적용한다. ([E2B Filesystem](https://e2b.dev/docs/sdk-reference/python-sdk/v2.5.0/sandbox_async), [Modal filesystem](https://modal.com/docs/guide/sandbox-files), [Daytona filesystem](https://www.daytona.io/docs/file-system-operations/)) |
| `mv`, `chmod` | native/helper | helper | native | SDK별 표면 차이는 guest RPC로 흡수한다. shell 문자열 조합으로 보강하지 않는다. |
| `write_file_if_revision` | helper | helper | helper | `expected_revision` 검증과 write/rename을 guest daemon 한 transaction으로 수행한다. provider object tag/label은 CAS가 아니다. |
| `search_text` | helper | helper | native + helper | Daytona는 content search를 공개한다. 그래도 `.gitignore`, byte/column/head cap, multiline/context/output mode의 NEOS 의미는 공통 helper를 사용한다. E2B/Modal도 동일한 pinned `rg` helper를 사용한다. |
| `glob_files` | helper | helper | helper | `paths.py`/`ignore.py` 규칙을 guest bundle과 같은 버전으로 실행한다. provider 고유 glob 의미를 노출하지 않는다. |
| `git_status`, `git_diff`, `git_log` | helper (`git` argv) | helper (`git` argv) | native Git facade + helper | 출력 cap·timeout·경로 정책을 맞추기 위해 공통 RPC를 거친다. managed implement worktree는 계속 `policy_worktree_unavailable`; host-git worktree만 허용한다. |
| `execute(CommandRequest)` | helper | native transport + helper policy | helper | Modal `exec`는 argv를 직접 받는다. E2B/Daytona의 문서화된 고수준 command 표면은 문자열 중심이므로, 세 provider 모두 최종적으로 sandboxd의 length-prefixed argv RPC를 호출해 shell 재파싱을 없앤다. ([E2B commands](https://docs.e2b.dev/), [Modal `exec`](https://modal.com/docs/sdk/py/latest/Sandbox), [Daytona process](https://www.daytona.io/docs/en/typescript-sdk/process/)) |
| command timeout/stdin/output cap | helper | native + helper cap | native timeout + helper cap | timeout 시 process group 전체를 종료하고 stdout/stderr 각각 cap과 truncation bit를 남긴다. provider SDK timeout만 믿지 않는다. |
| PTY create/write/kill | native + journal helper | helper | native + journal helper | E2B는 SDK에 PTY module, Daytona는 create/connect/input/kill을 공개한다. Modal은 `exec(..., pty=True)`와 stdin은 있으나 NEOS의 addressable PTY session 전체 의미는 helper가 맡는다. ([E2B PTY](https://docs.e2b.dev/sandbox/pty), [Modal PTY](https://modal.com/docs/sdk/py/latest/Sandbox), [Daytona PTY](https://www.daytona.io/docs/en/pty/)) |
| PTY resize | native | missing → helper | native | Modal 공개 API에서 runtime resize 계약을 확인하지 못했으므로 guest daemon의 `ioctl(TIOCSWINSZ)`만 사용한다. 확인 전 vendor 내부/deprecated `pty_info`에 의존하지 않는다. Daytona는 SIGWINCH resize를 명시한다. ([Daytona PTY SDK](https://www.daytona.io/docs/en/typescript-sdk/process/)) |
| `watch_files(after_cursor)` live events | native | native | missing → helper | E2B `watch_dir`, Modal `filesystem.watch`는 live event를 준다. Daytona 공개 filesystem 문서에는 file watcher가 확인되지 않았다. ([E2B watcher](https://e2b.dev/docs/sdk-reference/python-sdk/v2.5.0/sandbox_async), [Modal watcher](https://modal.com/docs/sdk/py/latest/Sandbox)) |
| watcher replay/gap/close | helper | helper | helper | 어느 vendor live watcher도 NEOS의 durable cursor/replay 계약은 아니다. sandboxd journal + host cursor가 재접속을 견디고, 보존 범위 밖 cursor는 `ReplayGap`으로 닫는다. |

## 3. 보안, 소유권, 네트워크

| 항목 | E2B | Modal | Daytona |
|---|---|---|---|
| 격리 단위 | sandbox마다 자체 kernel인 Firecracker microVM. ([Security](https://e2b.dev/security)) | gVisor sandboxed container; 기본적으로 다른 Modal workspace resource 권한이 없다. ([Security model](https://modal.com/docs/guide/sandbox-networking#security-model)) | 제품 문서는 전용 kernel/filesystem/network stack과 runner의 전용 resource를 설명한다. 배포 class별 경계는 security review에서 다시 확인한다. ([Docs](https://www.daytona.io/docs/), [Architecture](https://www.daytona.io/docs/en/architecture/)) |
| 공급자 측 식별 | metadata로 list/filter 가능 | App-scoped unique running name + tags/list filter | name + labels/list filter |
| NEOS 소유권 | metadata는 ACL이 아니다. `owner_id`, allocation id, generation, ownership digest를 host ledger에서 검증한 뒤 provider ID를 사용한다. | name/tag는 ACL/CAS가 아니다. deterministic name 충돌을 create idempotency 보조로만 쓴다. | labels는 ACL이 아니다. 게다가 유효 org key의 toolbox 범위가 조직 전체라 현재 탈락 사유다. |
| outbound 기본 | SDK 공개 create 기본은 internet 허용이므로 `allow_internet_access=False`를 명시한다. stable per-domain allowlist는 B2에서 가정하지 않는다. ([E2B SDK](https://e2b.dev/docs/sdk-reference/python-sdk/v2.5.0/sandbox_sync)) | 기본 public outbound 허용. `block_network=True`를 명시한다. 필요한 profile만 CIDR/domain allowlist를 별도 opt-in하며 Beta domain 제약을 기록한다. ([Networking](https://modal.com/docs/guide/sandbox-networking)) | tier별 기본이 다르다. Tier 3/4는 `networkBlockAll`/CIDR/domain allowlist가 strict하고 runtime 갱신도 지원한다. prototype 제외 상태에서도 기본은 block-all이어야 한다. ([Network limits](https://www.daytona.io/docs/en/network-limits/)) |
| inbound | 공개 URL/포트는 profile에 없으면 생성하지 않는다. | 기본 inbound accept와 Modal resource 접근은 없고, tunnel/connect token은 명시 opt-in이다. | `public`/preview는 명시 opt-in만 허용한다. |
| credential | host provider client에만 둔다. sandbox env/HOME/PATH로 복사하지 않는다. | host client에만 둔다. Modal Secret/OIDC도 profile 허용 없이는 주입하지 않는다. | 조직 유효 key의 toolbox 전역 접근 때문에 reserve. Secret proxy 자체는 plaintext를 guest에 넣지 않지만 이 문제를 해소하지 않는다. ([Secrets](https://www.daytona.io/docs/en/secrets/), [API keys](https://www.daytona.io/docs/api-keys)) |

네트워크 정책의 NEOS 기본은 세 provider 모두 **deny**다. “provider 기본값”은 NEOS 기본값이 아니다. 지원되는 named profile만 accept하고, 예를 들면 `offline-v1`은 outbound/inbound 모두 닫고, 향후 `package-read-v1`은 검증된 목적지와 프로토콜만 연다. provider가 profile을 정확히 표현하지 못하거나 적용 여부를 읽어 확인할 수 없으면 생성 전에 `profile_unsupported`로 거절한다. 넓은 인터넷으로의 fallback은 없다.

## 4. Region과 data residency

- **E2B:** E2B Cloud data plane은 US/EU/APAC, BYOC는 AWS/GCP의 고객 region을 사용한다고 공개한다. managed cloud storage는 Google Cloud 기본 암호화이며 E2B 자체 key layer는 없다고 명시한다. B2는 account가 실제로 허용하는 region을 시작 때 조회/검증하고, 요청 region과 실제 placement를 확인할 수 없으면 실패한다. regulated production은 BYOC 계약과 control-plane/data-path를 별도 검토한다. ([Enterprise deployment comparison](https://e2b.dev/enterprise), [Security](https://e2b.dev/security))
- **Modal:** Sandbox `region=`은 broad `us/eu/ap`와 narrow subregion을 지원하고 pinning은 strict하다. 다만 container region을 지정하면 broad 1.15x, narrow 1.75x 요금 배수가 붙는다. 가장 중요한 예외는 **sandbox filesystem/memory snapshot이 workload region과 무관하게 미국에 저장**된다는 점이다. 따라서 EU residency profile에서는 snapshot을 금지하거나 별도 승인을 요구한다. ([Region selection](https://modal.com/docs/guide/region-selection), [Data residency](https://modal.com/docs/guide/data-residency))
- **Daytona:** shared region target은 `us`, `eu`; dedicated region과 고객 compute의 custom/BYOC region도 문서화돼 있다. snapshot은 region별 publish/capacity 영향을 받는다. reserve 재검토 때 region 계약과 조직 credential 경계를 함께 검증한다. ([Regions](https://www.daytona.io/docs/regions), [Troubleshooting](https://www.daytona.io/docs/en/troubleshooting/))

## 5. Resource limits와 hard gap

`SandboxLimits`는 CPU, memory, PIDs, workspace bytes, command timeout, output bytes, stdin bytes를 모두 **강제**하는 계약이다.

- **E2B:** plan은 최대 vCPU/memory/disk, runtime, concurrency, create rate를 공개하며 CPU/RAM은 template build 설정이다. 그러나 공개 create 계약에서 sandbox별 `pids` hard limit과 NEOS workspace directory의 `workspace_bytes` hard quota를 지정·검증하는 표면은 확인되지 않았다. plan disk size는 NEOS workspace quota와 같은 계약이 아니다. ([Billing & limits](https://docs.e2b.dev/billing))
- **Modal:** create는 CPU와 memory request/limit, 전체 sandbox lifetime/idle timeout을 지원한다. 그러나 공개 Sandbox API에서 `pids` hard limit과 특정 NEOS workspace의 `workspace_bytes` hard quota를 지정·검증하는 표면은 확인되지 않았다. VM root image 최대 512 GiB 같은 platform ceiling도 workspace quota가 아니다. ([Resources](https://modal.com/docs/guide/resources), [VM Sandbox limitations](https://modal.com/docs/guide/vm-sandboxes))
- **Daytona:** 기본 1 vCPU/1 GiB/3 GiB, 공개 기본 per-sandbox 최대 4 vCPU/8 GiB/10 GiB와 organization tier pool/rate limit을 문서화한다. disk resource는 만들 때 지정할 수 있지만 PIDs hard limit은 공개 문서에서 확인되지 않았다. ([Sandbox resources](https://www.daytona.io/docs/sandboxes), [Limits](https://www.daytona.io/docs/limits))

따라서 **E2B와 Modal에는 현재 hard PID/workspace quota gap이 있다.** sandboxd의 process-group accounting, `setrlimit`/cgroup 관측, workspace preflight/usage guard는 blast radius를 줄이지만 검증된 provider hard boundary를 발명하지는 못한다. `strict-pids-v1` 또는 `strict-workspace-quota-v1`처럼 이 보장을 요구하는 profile은 두 provider에서 **fail closed**한다. B2 prototype은 bounded test repository, 낮은 NEOS exec slot, 작은 absolute lifetime/output/stdin cap, 별도 cost ceiling에서만 허용한다. hard limit을 vendor 계약·API·실측 conformance로 증명하기 전 production 승인하지 않는다.

## 6. Idempotency와 recovery

공급자의 create가 timeout난 뒤 “실제로는 만들어졌는가”가 가장 위험한 구간이다. vendor object를 SoT로 삼지 않는다.

1. Host의 durable NEOS ledger가 `(owner_id, task_id, generation)`에서 allocation id, idempotency key, expected provider, image digest, profile, region, expiry를 먼저 기록한다.
2. provider 식별자는 deterministic하게 만든다. Modal은 deployed App 안의 unique running name과 tags를 사용하고, E2B는 metadata를 사용한다. Daytona reserve는 name/labels를 쓸 수 있다. ([Modal named sandboxes and tags](https://modal.com/docs/guide/sandboxes#named-sandboxes), [E2B metadata/list query](https://e2b.dev/docs/sdk-reference/python-sdk/v2.5.0/sandbox_sync), [Daytona labels](https://www.daytona.io/docs/en/python-sdk/sync/sandbox/))
3. retry 전 list/get으로 같은 idempotency key를 재발견한다. 0개면 create, 1개면 ledger에 adopt, 2개 이상이면 격리하고 신규 작업을 차단한다. 공급자 tag/metadata가 NEOS의 원자적 idempotency token이라고 주장하지 않는다.
4. 모든 mutate는 owner digest + generation + expected revision을 대조한다. 오래된 callback/webhook/PTY/watcher는 새 generation에 기록하지 못한다.
5. snapshot 중 연결이 끊기는 E2B는 command/PTY/watcher를 reconnect하고 journal cursor부터 replay한다. E2B pause가 503/`ServiceBusy`로 거절되면 sandbox가 running임을 기록하고 bounded retry한다. ([E2B snapshot connection behavior](https://docs.e2b.dev/sandbox/snapshots), [E2B pause refusal](https://docs.e2b.dev/sandbox/persistence))
6. Modal filesystem snapshot ID는 직접 추적한다. 공식 문서는 snapshot list API가 없고 기본 TTL 이후 `NotFound`가 될 수 있음을 명시한다. ledger가 ID/TTL/checksum을 보관하고 restore 전 존재를 검증한다. ([Modal snapshot retention](https://modal.com/docs/guide/sandbox-snapshots))
7. destroy는 ownership 확인 후 실행하고, 결과가 불명확하면 `destroy_pending`으로 남겨 reaper가 재확인한다. “요청 전송”을 “삭제 확인”으로 기록하지 않는다.

## 7. 가격과 SDK churn

가격은 2026-09-14 공개 list price이며 계약 할인, 세금, egress, snapshot/보관 부대비용을 포함하지 않는다.

| 공급자 | 공개 가격/한도 요약 | churn risk |
|---|---|---|
| E2B | Hobby $0, Pro $150/month + 사용량. 1 vCPU `$0.000014/s`, RAM 1 GiB `$0.0000045/s`; Hobby 20 concurrent/1h, Pro 100–1,100 concurrent/24h. storage는 Hobby 10 GiB, Pro 20 GiB 항목이 무료로 표시된다. ([Pricing](https://e2b.dev/pricing), [Limits](https://docs.e2b.dev/billing)) | pause/snapshot 문서는 최근 stable 명칭과 별도 lifecycle semantics를 갖지만 SDK reference 버전별로 `beta_pause` 등 예전 명칭이 남아 있다. exact version pin + adapter contract test가 필요하다. |
| Modal | Sandbox/Notebook CPU physical core(2 vCPU) `$0.00003942/core/s`, memory `$0.00000667/GiB/s`; Starter $30/month credit, Team $250/month + compute. region pin은 1.15x/1.75x. ([Pricing](https://modal.com/pricing), [Region pricing](https://modal.com/docs/guide/region-selection#pricing)) | 2026년에 Sandbox filesystem 구 API가 연속 deprecated됐고 새 namespace/API 최소 SDK 버전이 있다. filesystem snapshot 기본 TTL도 Python v1.5 / JS·Go v0.8.0에서 30일로 바뀌었다. ([Filesystem migration](https://modal.com/docs/guide/migrate-sandbox-filesystem), [Snapshot retention](https://modal.com/docs/guide/sandbox-snapshots#snapshot-retention)) |
| Daytona | vCPU `$0.0504/h`, RAM `$0.0162/GiB/h`, storage `$0.000108/GiB/h`(첫 5 GiB 무료), 초 단위 과금. lifecycle state에 따라 stopped/paused는 CPU/RAM 대신 disk만 과금된다. ([Pricing](https://www.daytona.io/pricing), [Billing](https://www.daytona.io/docs/billing)) | 다중 언어 SDK 표면이 크고 sandbox snapshot의 `_experimental_create_snapshot`이 `createSnapshot`으로 deprecate되는 전환이 보인다. reserve여도 version pin과 generated/client compatibility test가 필요하다. ([Sandbox SDK](https://www.daytona.io/docs/en/java-sdk/sandbox/)) |

B2는 vendor SDK를 core loop나 tool executor에 직접 import하지 않는다. provider client implementation 한 곳에 pin하고, sanitized exception mapping과 capability probe를 거친다. lockfile 업데이트는 conformance replay와 changelog 검토가 동반되어야 한다.

## 8. 공유 adapter architecture와 승인 gate

현재 `neos/coding/managed/adapters/e2b.py`와 `modal.py`는 allocation/admission benchmark용 좁은 protocol이며 vendor SDK binding도 의도적으로 비워 두었다. 그 capability 상수는 작성 당시의 보수적 underclaim이다. 예를 들어 현재 공식 문서는 E2B의 filesystem+memory snapshot과 Modal의 CIDR/domain allowlist를 새로 명시한다. 반대로 E2B snapshot 뒤 원 sandbox 상태를 `SUSPENDED`로 보는 기존 adapter 설명은 현재 문서의 “brief pause 뒤 RUNNING, 연결은 drop” 의미와 다르다. B2는 이 allocation adapter를 고치거나 복사하지 않고, 현재 문서·실계정 probe로 coding capability를 별도 협상한다.

### 8.1 구조

```text
coding loop / tools
        |
SandboxProvider (NEOS contract)
        |
provider adapter ---- durable NEOS ledger (owner/generation/revision/idempotency)
        |
narrow provider client (SDK pin, lifecycle, transport only)
        |
immutable neos-sandboxd (argv/files/CAS/limits/PTY/watcher journal)
        |
workspace + portable export
```

- **Provider client:** SDK import, credential loading, retry/error mapping은 provider별 좁은 module 하나에만 둔다. 기존 `neos/coding/managed/adapters/` allocation/admission plane은 재작성하지 않고, coding `SandboxProvider` adapter가 그 결과의 `provider_ref`를 소비한다.
- **Immutable guest `neos-sandboxd`:** versioned digest로 image에 bake한다. 런타임 다운로드·self-update 금지. handshake에서 protocol version, binary digest, capabilities를 확인하고 다르면 세션을 열지 않는다.
- **Durable ledger:** sandbox/owner/provider/generation/image/profile/region/expiry, provider refs, workspace revision, snapshot checksum, command/PTY/watcher cursors, destroy confirmation을 host DB에 저장한다. vendor metadata/tag는 recovery index일 뿐 SoT가 아니다.
- **Named profiles:** 코드에 등록된 immutable profile만 허용한다. provider capability probe와 정확히 match하지 않으면 reject한다. 기본은 network deny이며, host PATH/HOME/credential을 복사하지 않는다.
- **Deterministic ownership/generation:** allocation id와 provider name/tag/metadata를 deterministic하게 만들고 HMAC ownership digest를 넣는다. 모든 attach/mutate/destroy가 owner와 generation을 먼저 검증한다.
- **Revision/CAS:** filesystem mutate는 sandboxd의 단조 revision을 반환한다. `write_file_if_revision`은 guest 내 atomic compare+replace이며, host ledger commit이 실패하면 결과를 ambiguous로 두고 재조회한다.
- **Process/output:** task별 exec slot, command/absolute timeout, stdin cap, stdout/stderr cap, process group kill을 공통 구현한다. provider timeout은 추가 방어층이다.
- **PTY/watcher journal:** live stream은 cursor가 있는 bounded journal에 기록한다. reconnect는 last committed cursor부터 replay하고 evicted cursor는 `ReplayGap`; generation change는 기존 stream을 닫는다.
- **Portable export:** snapshot과 별도로 normalized tar stream + manifest(protocol/image/profile/revision/checksum)을 export한다. symlink/hardlink/device/path traversal을 거절하고 byte/file-count cap을 적용한다. 이 archive가 provider 간 exit path이며 vendor memory snapshot은 portable하다고 부르지 않는다.

### 8.2 B2 prototype gate

다음이 **두 provider 각각** 통과하기 전 production 승인, default 변경, broad allowlist를 금지한다.

1. 기존 `SandboxProvider` conformance 전 항목: lifecycle, file/search/git/command, snapshot/restore, PTY, watcher replay/gap, close.
2. security suite: traversal/symlink/hardlink/device, ownership/generation mismatch, stale stream, shell-string injection, env/secret leak, output/stdin bomb, timeout 후 descendant 생존, network deny 증명.
3. recovery suite: create-success/response-timeout, duplicate create, process restart, lost response, provider 404/409/429/5xx, snapshot expiry, destroy ambiguity, region outage.
4. 실계정 opt-in smoke와 비용 ceiling: sandbox 수/exec slot/absolute lifetime을 낮게 고정하고 cleanup SLO와 orphan 0을 확인한다.
5. region/residency 검증: 요청/실제 placement, snapshot 저장 위치, log/metadata/control-plane data flow를 security가 승인한다.
6. E2B/Modal의 PID/workspace hard quota gap이 남아 있으면 strict profile을 계속 거절한다. production profile은 vendor hard enforcement 증거 또는 별도 승인된 보상 통제가 있어야 한다.
7. 보안 검토가 provider credential scope, image provenance/digest, encryption, incident/exit 절차를 승인한다.

## 9. B1 closeout

B1은 **2026-09-14 CLOSED**다. 후보가 두 개 이상이며 E2B + Modal을 제한된 B2 prototype 대상으로 선정했다. Daytona는 조직 전체 toolbox credential 경계 때문에 reserve다. 이 결론은 공개 문서 기반의 착수 승인일 뿐, 세 공급자 어느 것도 production-approved가 아니다. 가격·region·SDK·보안 계약은 B2 canary 직전에 다시 확인한다.
