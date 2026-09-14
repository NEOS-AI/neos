# Managed coding sandbox B2 설계 메모 — 2026-09-15

> 정본은 [재검토 문서](MANAGED_SANDBOX_PROVIDER_REVIEW_260914.md) §2·§3·§5·§6·§8과 [PLAN §B2](PLAN_260913.md)다. 이 메모는 문서가 정하지 않은 부분에서 내린 결정만 적는다. B2 gate는 통과하지 않았다.

## 구조

```text
coding loop -> ManagedSandboxProvider (neos/coding/sandbox/managed/provider.py)
                 |-- durable ledger        managed/ledger.py, ledger_sql.py (057)
                 |-- provider client       managed/clients/{e2b,modal}.py (SDK 주입)
                 `-- SandboxdSession       neos/coding/sandboxd/session.py
                          `-- neos-sandboxd  neos/coding/sandboxd/guest.py (이미지에 bake)
```

## 문서가 열어 둔 곳에서 내린 결정

- **식별자.** `SandboxProvider.create()`는 task id를 받지 않으므로 `task_id = owner_id`로 둔다. `sandbox_id = HMAC(owner, task, ordinal)`은 샌드박스 수명 동안 고정된다. `generation`은 **provider object 세대**로, 1에서 시작한다. allocation id, idempotency key, provider name/tag는 `(sandbox_id, generation)`에서 결정적으로 나온다. 입력은 길이 접두 인코딩이라 구분자 충돌이 없다.
- **ownership 키.** `secrets.managed_provider_reference_key`의 바이트를 AES-GCM 봉인과 HMAC에 같이 쓰지 않는다. 라벨 `neos/coding-sandbox/ownership-hmac/v1`로 HMAC 서브키를 파생한다. 새 시크릿은 추가하지 않았다.
- **Modal cold suspend.** snapshot과 terminate가 **확인된 뒤** suspend 시점에 generation을 올리고 다음 key를 원장에 적는다. resume이 도중에 죽어도 재시도는 같은 key로 재발견한다. terminate가 불명확하면 행을 RUNNING으로 두고 실패시킨다. snapshot은 TTL로 사라지는 쓰레기가 된다.
- **snapshot 원장.** 행 컬럼이 아니라 `coding_sandbox_ledger_snapshots` 테이블에 둔다. restore는 snapshot id로 찾는다. cold resume용 snapshot도 결정적 snapshot id로 같은 테이블에서 찾아 checksum을 검증한다.
- **checksum.** guest가 워크스페이스 트리(경로, mode, 크기, 내용 해시, symlink 대상)를 sha256으로 계산한다. restore와 cold resume은 checksum이 다르면 새 object를 파기하고 실패한다(fail closed).
- **sandboxd 연결 모델.** 이미지 안의 `neos-sandboxd serve`가 unix socket에서 계속 돈다. vendor exec을 건너는 것은 고정 argv `neos-sandboxd connect` 하나다. E2B snapshot이 연결을 끊어도 daemon과 journal은 살아 있어 cursor부터 replay한다.
- **bundle digest.** `guest.py` 파일 바이트의 sha256이다. `sandbox.managed.sandboxd_digest`로 고정할 수 있고, 비우면 소스 트리의 guest digest를 요구한다.
- **오류 분류.** timeout, transport, 5xx는 결과를 알 수 없는 실패로 보고 재발견만 한다. 409도 재발견한다. 429처럼 확정된 거절은 행을 `failed`로 둔다. 다음 create는 새 ordinal로 시작한다.
- **revision/cursor commit.** version pin 없이 owner+generation으로만 fence하고, 값은 올라가기만 한다. commit이 실패하면 `managed_revision_commit_ambiguous`로 올린다.
- **`sandbox.managed.provider: docker`.** 이제 코딩 provider로 servable하지 않다. guest daemon이 없기 때문이다. Docker shadow 할당 어댑터는 그대로 두었다.

## 알려진 한계 (hard boundary가 아님)

- 명령이 끝나거나 timeout되면 guest가 process group 전체를 SIGKILL한다. `setsid`로 group을 벗어난 프로세스는 막지 못한다. cgroup이 없고, vendor hard PID 계약도 확인되지 않았다(§5).
- workspace byte guard는 쓰기 단위 cap뿐이다. 전체 quota가 아니다.
- PTY resize는 guest `TIOCSWINSZ`로만 한다.
