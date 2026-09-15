# Managed coding sandbox B2 설계 메모 — 2026-09-15

> 정본은 [재검토 문서](MANAGED_SANDBOX_PROVIDER_REVIEW_260914.md) §2·§3·§5·§6·§8과 [PLAN §B2](PLAN_260913.md)다. 이 메모는 문서가 정하지 않은 부분에서 내린 결정만 적는다. **B2 gate는 통과하지 않았다.**
>
> 2026-09-15 개정: 코딩 provider를 **관리형 할당 평면 위로** 옮겼다. 첫 구현은 vendor object를 직접 만들고 자체 원장을 두었는데, 이는 사실상 두 번째 할당 원장이었다. 계획서 브랜치(`feature/b2-managed-sandbox`)와 비교한 결과, dev 구현을 기준으로 두고 할당 평면 연결과 계획서의 ownership 키 설계를 가져오기로 결정했다.

## 구조

```text
admission -> prepare_coding_intent()  (managed/adapter.py)
          -> ManagedSandboxAllocationService.advance()        (기존, 불변)
               `-- ManagedCodingAllocationAdapter             (managed/adapter.py)
                     `-- provider client (managed/clients/{e2b,modal}.py, SDK 주입)
                           `-- vendor object + neos-sandboxd   (neos/coding/sandboxd/)
coding loop -> SandboxBindingService --for_lease--> ManagedSandboxProvider (managed/provider.py)
                                                      |-- runtime ledger (managed/ledger.py, ledger_sql.py, 057)
                                                      `-- SandboxdSession -> neos-sandboxd
cleanup     -> ManagedSandboxCleanupService (기존, 불변) -> ManagedCodingAllocationAdapter.destroy
```

## 결정

- **누가 vendor object를 만드나.** 할당 평면만 만든다. 할당 평면이 admission, 쿼터, kill switch, cleanup SLO를 소유한다. 코딩 provider의 `create(owner_id=task_id)`는 그 태스크의 살아 있는 allocation과 코딩 intent를 찾아 **붙기만** 한다. allocation이 없으면 `managed_allocation_required`로 거절하고, 스스로 할당하지 않는다. 할당 프로토콜(`ManagedSandboxAdapter`)은 바꾸지 않았다. 새 어댑터가 같은 계약을 코딩 client 위에 구현한다. 기존 `adapters/e2b.py`·`modal.py`와 그 capability 상수는 건드리지 않았다.
- **코딩 intent.** `coding_managed_runtime` 행은 할당 **전에** `intent` 상태로 기록한다. 이 행이 profile, image, guest digest, 자원 한도, region, expiry를 담는다. 어댑터는 intent가 없거나 할당 요청과 다르면 vendor를 부르지 않는다. 자원은 cpu, memory, pids, workspace 네 가지만 대조한다. 명령별 timeout과 출력 cap은 sandboxd가 강제한다.
- **식별자 세 층.**
  - 할당 `generation`은 admission 세대다.
  - `incarnation`은 vendor object 교체 횟수다. Modal cold resume이 올린다.
  - `stream_epoch`은 PTY/watcher를 끊는 기준이고, incarnation과 함께 올라간다.
  - 논리 샌드박스 id는 `HMAC("sandbox", allocation_id)`다. allocation 하나에 정확히 하나다.
  - incarnation 1은 admission의 idempotency key를 쓰고, 2 이상은 `neos-coding-sbx:v1:{sandbox}:{incarnation}`을 쓴다.
- **ownership 키 (계획서 방식).**
  - 물리 digest는 `secrets.managed_coding_ownership_key`(base64, 정확히 32바이트)로 만든 HMAC-SHA256이다.
  - 입력은 tenant, task, allocation, generation, sandbox, incarnation, profile, image, region, expiry를 담은 canonical JSON이다.
  - 참조 봉인 키와 같은 값이면 설정 검증이 기동을 막는다.
  - vendor metadata에는 레거시 `neos_ownership_digest`(sha256)와 `neos_coding_ownership`(HMAC)을 **둘 다** 싣는다. 붙기, 재발견, 정리 전에 둘 다 검증한다. 레거시 digest는 키가 없으므로 혼자서는 증거가 되지 못한다.
- **실행 lease fence.** `SandboxBindingService`가 `provider.for_lease(lease)` view를 쓴다. memory와 Docker provider에는 이 메서드가 없어 동작이 그대로다.
  - view의 mutation은 guest에 닿기 **전에** `coding_run_leases` 행(run, worker, fencing token, 만료)을 확인한다. revision과 cursor를 커밋할 때는 그 행을 `FOR SHARE`로 잡는다.
  - lease를 잃은 worker의 쓰기는 `sandbox_fence_stale`로 거절되고 guest 파일도 바뀌지 않는다.
- **destroy 의미.**
  - lease view의 `destroy`는 **자기 handle만** 놓는다. binding CAS에서 진 쪽이 이긴 쪽 샌드박스를 무너뜨리지 못하게 하려는 것이다.
  - lease 없는 `destroy`는 runtime을 `detached`로 적는다.
  - vendor object 삭제는 할당 평면 cleanup이 태스크 종료나 절대 만료 때 한다.
- **Modal cold suspend/resume.**
  - suspend는 snapshot 후 terminate하고, terminate가 **확인된 뒤에만** 옛 physical 행을 `destroyed`로 적는다. 확인되지 않으면 runtime은 RUNNING으로 남는다.
  - resume은 교체 physical 행을 먼저 기록하고 새 object를 만든 뒤, handshake와 checksum을 검증한다. 그다음 한 트랜잭션에서 runtime(incarnation + 1), physical(ACTIVE), 045 allocation의 봉인된 `provider_ref`를 함께 옮긴다. 잠금 순서는 allocation → runtime → physical이다.
  - 커밋 전에 죽으면 재시작한 resume이 idempotency key로 재발견해 채택한다. 두 번째 create는 없다.
- **정리.** 어댑터의 `destroy`는 논리 샌드박스의 **모든** incarnation을 지운다. 원장에 기록이 없거나 소유권을 증명하지 못한 object는 지우지 않는다. 정리 서비스는 그런 object를 `CLEANUP_RETRY`로 남긴다.
- **restore.** 045가 태스크당 살아 있는 allocation을 하나로 강제하므로, source가 살아 있는 동안 같은 태스크에 독립 restore를 만들 수 없다.
  - restore는 준비된 target allocation에만 붙는다. target의 intent가 `source_snapshot_id`를 가지고, 어댑터가 그 snapshot에서 object를 만든다.
  - target이 없으면 `managed_restore_target_required`다.
  - checksum이 다르면 runtime을 `failed`로 적고 서비스하지 않는다.
  - 공유 conformance의 restore 테스트는 managed 쪽에서 이 의미로 대체했다.
- **오류 분류.**
  - timeout, transport, 5xx, 409는 결과를 알 수 없는 실패다. 어댑터가 `ManagedAdapterTimeoutError`로 올리면 할당 서비스가 `RECOVERY_PENDING` 뒤 재발견만 하고, 찾지 못하면 `MANUAL_RECOVERY_REQUIRED`에서 멈춘다.
  - 429 같은 확정 거절은 allocation을 `FAILED`로 만든다.
  - 재발견에서 object가 2개 이상 나오면 runtime을 `quarantined`로 두고 채택하지 않는다.
- **`managed.provider: docker`**는 코딩 provider로 servable하지 않다. guest daemon이 없기 때문이다.
- **마이그레이션 057**은 push 전에 개정했다. 첫 판의 `coding_sandbox_ledger` 테이블은 지금 스키마에 없다.

## 알려진 한계 (hard boundary가 아님)

- 명령이 끝나거나 timeout되면 guest가 process group 전체를 SIGKILL한다. `setsid`로 group을 벗어난 프로세스는 막지 못한다. cgroup이 없고, vendor hard PID 계약도 확인되지 않았다(§5).
- workspace byte guard는 쓰기 단위 cap뿐이다. 전체 quota가 아니다.
- PTY/watcher journal은 guest 메모리에 있다. host 재접속은 견디지만 guest 재시작은 견디지 못한다.
- lease 없는(admin) provider의 revision 커밋은 incarnation과 epoch로만 fence한다.

## 남은 일

- **runtime 배선.** 아래가 들어가기 전까지 factory는 계속 거절한다.
  - `prepare_coding_intent`를 admission 직후에 부르는 호출자
  - `_managed_adapter_registry`에 코딩 어댑터를 등록하는 백엔드 주입
- **portable export.** tar + manifest. 기존 `SessionPortableArchiveBuilder`는 세션 계약만 쓰므로 sandboxd 세션에 연결하면 된다.
- **guest 운영.** guest journal 영속화(SQLite), 그리고 이미지에 `neos-sandboxd`를 넣고 digest를 게시하는 일.
- **operation receipt.** 모호한 mutation의 guest 측 재조회. 지금은 revision CAS와 host 재조회로만 해소한다.
- **외부 조건이 필요한 gate 항목.** 실계정 smoke와 비용 ceiling, region/residency, 보안 검토(§8.2 4·5·7).
