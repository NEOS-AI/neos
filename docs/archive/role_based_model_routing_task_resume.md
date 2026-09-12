# Role-Based Model Routing — 남은 이슈

> 📦 **보관 문서 (2026-08-04 archive 이동).** 현재 진입점은
> [DEEP_ANALYSIS_HARNESS_ROADMAP.md](../DEEP_ANALYSIS_HARNESS_ROADMAP.md) §8-B다.
> 제목의 "남은 이슈"는 낡았다 — **I1~I6 전부 종결됐다.** 이 문서는 로드맵이
> 압축한 진단 기록(I1~I6 원인 분석, fixture 재설계 상세, 스킬 이름 규칙 근거)을
> 위해 남긴다. 지켜야 할 불변식은 §7이며 로드맵 §4.2에 요약돼 있다.

**갱신일:** 2026-07-26
**작업 위치:** `dev` 브랜치 직접 작업 (워크트리 없음 — 사용자 명시 승인)
**플랜:** `docs/superpowers/plans/2026-07-25-role-based-model-routing.md` (untracked)
**스펙:** `docs/superpowers/specs/2026-07-25-role-based-model-routing-design.md` (`4f76d1ef`)

---

## 0. 한 줄 요약

**플랜 6개 태스크는 전부 완료**(`4f76d1ef..dd36325f`)했다. 아래는 그 과정에서 **드러났지만
플랜 범위 밖이라 손대지 않은 잔여 이슈**들이다. 서로 독립적이므로 원하는 것만 골라 진행하면 된다.

| # | 이슈 | 심각도 | 범위 |
|---|---|---|---|
| ~~I1~~ | ~~`.env.template` 미커밋~~ | ✅ **해결** (`59d98aa6`) | — |
| ~~I2~~ | ~~`api_gateway/config.toml` 시크릿 하드코딩~~ | ✅ **해결** (`e752b16c`) | — |
| ~~I3~~ | ~~전역 `llm.model` 자동 기본값~~ | ✅ **해결** (`e65b765d`) | — |
| ~~I4~~ | ~~크로스 프로바이더 OpenAI 폴백~~ | ✅ **해결** (`e65b765d`) | — |
| ~~I5~~ | ~~프론트엔드 레거시 피커 엔트리 부정확~~ | ✅ **해결** (`48ad7dac`) | — |
| ~~I6~~ | ~~`fast` 티어 · `atomizer_model` 역할 미정~~ | ✅ **결정 확정** (`af5b83ba`) | — |

**남은 이슈 없음.** I1~I6 전부 처리됐다.

**현재 검증 상태:** 백엔드 2234 passed / 16 skipped / 0 failed,
게이트웨이 `cargo test` 5/5 + `cargo build` clean,
프론트엔드 `tsc --noEmit` clean.

---

## 0.1 후속 작업 — 모델 카탈로그 config화 (2026-07-27, `783fe864..88dea3ab`)

이 문서의 여러 서술이 후속 작업으로 **낡았다.** 아래를 먼저 읽어야 한다.

**요약:** 모델에 관한 사실(목록 노출, 추천 티어, thinking 계약, 가격)이
`neos/config/models.yaml` 한 곳으로 모였다. 새 모델 추가가 config 편집으로 끝난다.
운영 문서는 [CONFIGURATION.md](../CONFIGURATION.md)의 **Model Catalog** 절이며,
설계는 [스펙](../superpowers/specs/2026-07-26-model-catalog-config-design.md),
실행은 [플랜](../superpowers/plans/2026-07-26-model-catalog-config.md)에 있다.

이 문서에서 **더 이상 유효하지 않은 서술:**

| 이 문서의 서술 | 현재 상태 |
|---|---|
| `get_recommended_models("openai")["fast"]`가 `gpt-5-mini-2025-08-07` (§0 각주, §6) | **`gpt-5.6-terra`.** gpt-5-mini는 가격 미상이라 은퇴했고 terra가 `fast`+`balanced`를 겸한다 |
| `is_claude_5()`로 Claude 5 요청 계약 판별 | **삭제됨.** 모델별 `thinking: adaptive \| budgeted \| none` 선언으로 대체 |
| `CostCalculator.DEFAULT_PRICING` 하드코딩 가격표 | **삭제됨.** 카탈로그 `pricing`에서 파생 (DB 우선순위는 불변) |
| `list_models()`가 provider마다 하드코딩 목록 | Anthropic·OpenAI는 카탈로그 파생. Gemini는 정적, Ollama는 라이브 서버 조회 유지 |
| §8의 재스캔 명령이 나열한 모델 ID | `claude-sonnet-4-6`, `claude-opus-4-6`, `gpt-5-2025-08-07`, `gpt-5-mini-2025-08-07`은 은퇴 |
| §8의 "1164 passed / 2 failed" | 2234 passed / 0 failed |

**§7의 제약은 전부 그대로 유효하다** — 역할 기본값 4개, 해석 우선순위,
크로스 프로바이더 폴백 금지, Claude 5 adaptive thinking. 카탈로그는 모델
*사실*만 옮겼고 배포 *정책*(`model_routing`, 기능 오버라이드)은 건드리지 않았다.

**부수적으로 잡은 프로덕션 버그 2건:**

- `iterative_refiner.py`가 존재한 적 없는 `metrics_collector.end_collection()`을
  호출했다(실제 이름은 `finalize_collection`). `collect_metrics` 기본값이 `True`이고
  경로에 `try/except`가 없어, HDR 리포트 생성이 **모든 정제 작업을 마친 뒤 마지막
  단계에서** `AttributeError`로 실패했다. 2026-01-11부터.
- provider를 모델명에서 추측(`"gpt" in model`)해서, 이름에 provider가 드러나지
  않는 모델이 기본 provider로 잘못 갔다. `provider_for_model()`이 카탈로그에서
  답하도록 바꿨다.

### 선재 순서 의존 실패 2건 — ✅ 해결 (`4b37a3fe`, `fe425578`)

둘 다 **테스트가 개발자의 `.env`에 의존**하던 문제였다. 프로덕션 동작은 정상이었다.

**① `test_settings_compat` — 프로세스 env 격리 누락 (`4b37a3fe`)**

`load_app_config`는 `apply_secret_overrides(config_data, process_env)`를 **마지막에**
적용한다(설계상 프로세스 env 최우선). 그런데 `litellm/__init__.py:81`,
`litellm/proxy/proxy_cli.py:27`, `crewai/llm.py:52`가 **import 시점에
`dotenv.load_dotenv()`를 호출**해 저장소 `.env`를 `os.environ`으로 복사한다.
전체 실행에서는 `DATABASE_URL`이 프로세스 env에 들어가 테스트가 지정한 시크릿 파일을 이겼다.
(NEOS 자체 코드는 비변조 `dotenv_values`만 쓴다 — 오염원은 서드파티였다.)

테스트는 `LEGACY_ENV_KEYS`만 지우고 있었는데 `DATABASE_URL`은 `SECRET_ENV_KEYS` 소속이다.
→ `isolated_env` fixture로 양쪽 다 지우도록 수정.

**② `test_query_authorization` — import 순서 경쟁 (`fe425578`)**

`neos/main.py:77`의 `IS_DEBUG = settings.DEBUG`는 **import 시점에 고정**되고,
`_include_router_for_runtime`이 `IS_DEBUG`가 False일 때만 미인증 websocket 라우트를 제거한다.
`.env:249`에 `DEBUG=true`가 있어 앰비언트 `settings.DEBUG`는 True다.

`test_query_authorization.py:13`이 이미 `os.environ["DEBUG"] = "false"`를 하고 있었지만,
**모듈 import 시점**이라 `tests/api`의 다른 모듈이 먼저 `neos.main`을 import하면 이미 늦는다.
→ `tests/conftest.py`(모든 테스트 모듈보다 먼저 import됨)로 올려 경쟁 자체를 제거.
`_load_production_app()`에 전제 조건 단언을 추가해, 환경이 잘못되면 라우트 집합 diff 대신
이유가 찍히게 했다.

**효과:** 전체 스위트 실패 51 → 46건, 대상 2건 포함 총 13건 해소.

### 이어서 진행한 스위트 정리 — 51 → 9~13건

남은 46건을 **"순서 의존"과 "진짜 실패"로 분리**했다(46건만 모아 재실행 → 30건이 여전히 실패).
그 30건은 전부 **선재 실패**였고(이번 세션 이전부터 깨져 있었음), 원인별로 처리했다.

**제품 버그 2건 (테스트가 가려주고 있던 것):**

| 버그 | 영향 | 커밋 |
|---|---|---|
| `SkillMetadataError`가 파서 예외 계층과 끊김 | `auto_discovery`의 `except SkillMetadataError`가 **죽은 코드**였다. 깨진 스킬 하나가 discovery 전체를 중단시켰다 | `f2dd71dd` |
| `SectionIterator`가 없는 `self.quality_threshold` 참조 | 속성이 `default_quality_threshold`로 개명됐는데 완료 조건만 옛 이름을 봤다. quick-skip을 지나면 `AttributeError`로 죽었다 | `61fc62a1` |

**낡은 테스트 (구현이 바뀌었는데 안 따라간 것):**

| 대상 | 내용 | 커밋 |
|---|---|---|
| multimodal 10건 | 라우트가 인증을 요구하게 됐는데 미인증 호출 → 전부 401. 루트 엔드포인트도 더 이상 경로 목록을 노출하지 않음 | `8559d72a` |
| vision 3건 | `models.yaml`의 vision claude가 `claude-sonnet-5`로 갱신됨. 팩토리가 Gemini까지 폴백하므로 "키 없음" 테스트는 `GOOGLE_API_KEY`도 비워야 함 | `4bc52144`, `2ccae4dc` |
| pdf 2건 | PyMuPDF가 주 파서가 되어 PyPDF2만 꺼서는 미설치 경로에 도달 못 함 | `4bc52144` |
| skills 파서 3건 | `extract_frontmatter`가 `(frontmatter, body)` 튜플 반환 | `f2dd71dd` |
| refiner mock 4건 | citation tracker mock에 `parse_citations_from_text` 누락, `str`에 `patch.object(__str__)`, 조기 반환으로 도달 불가한 경로, 템플릿까지 세는 취약한 계수 | `61fc62a1` |
| checkpointer 1건 | `alist`는 async generator인데 `await`함. `Checkpoint`는 TypedDict라 `isinstance` 불가 | (동 커밋) |

**결과:** 전체 스위트 **51 → 9~13건**(2100여 건 통과). 남은 것은 아래 하나의 집단뿐이다.

### 스킬 이름 규칙 확정 — kebab-case (`eade1cc8`)

`SkillMetadataError` 수정으로 예외 처리가 되살아나면서 드러난 문제를 정리했다.

**규칙:** 스킬 이름은 **유니코드 문자·숫자 + 하이픈만**. 언더스코어 금지.
디렉터리 / `SKILL.md`의 `name:` / `skill.py`의 `name=` **세 곳이 모두 일치**해야 한다.

`validator.py:39`가 이미 "Unicode letters plus hyphens"로 의도를 명시하고 있었고,
`research-assistant` 선례와 Agent Skills 관례가 같은 방향이라 이를 채택했다.

**개명한 5개:** `news_api`→`news-api`, `semantic_scholar`→`semantic-scholar`,
`github_search`→`github-search`, `google_scholar`→`google-scholar`, `sec_edgar`→`sec-edgar`.
`research-assistant`의 `skill.py`는 자기 SKILL.md와 어긋난 `research_assistant`를 쓰고 있어 함께 교정했다.

**효과:** 프로덕션 auto-discovery가 **7개 → 9개**를 등록한다
(`news-api`, `semantic-scholar`가 그동안 조용히 누락돼 있었다).

**건드리지 않은 것 (별개 네임스페이스):**

| 대상 | 예 | 이유 |
|---|---|---|
| API 키·설정 키 | `NEWS_API_KEY`, `sec_edgar_user_agent` | 시크릿/설정 키 이름 |
| `SourceType` 열거형 | `SEMANTIC_SCHOLAR = "semantic_scholar"` | `tavily`·`duckduckgo`까지 포함하는 검색 소스 taxonomy. 스킬 레지스트리와 무관 |
| 툴 이름 | `semantic_scholar_search` | 툴 네임스페이스 |

**안전성 근거:** 스킬은 `spec_from_file_location`으로 **파일 경로 로드**되므로 디렉터리
개명이 import를 깨지 않는다. 커밋된 YAML에도 스킬 이름 참조가 없었다.

> ⚠️ 로컬 YAML에서 `deep_analysis.discovery_skills`를 직접 오버라이드하고 있다면
> 언더스코어 이름을 하이픈으로 바꿔야 한다. 커밋된 프로파일에는 해당 항목이 없다.

회귀 가드: `tests/test_skills_auto_discovery.py::TestSkillNamingRule` (디렉터리 규칙 +
모든 빌트인 `SKILL.md` 검증). 규칙 본문은 `docs/NEOS_WORKFLOW.md`에 문서화했다.

**여전히 남은 것:** `cron`, `github-search`, `google-scholar`, `openalex`, `reddit`,
`sec-edgar` 6개는 `SKILL.md`가 없어 auto-discovery 대상이 아니다. 이름 규칙은 이제
충족하므로 `SKILL.md`만 추가하면 등록된다.

---

### deep_analysis 오염 — 결정적 원인 1건 해결 (`0cd8bfda`), 잔여는 fixture 설계 문제

**해결: `tests/test_harness_settings_defaults.py`의 `importlib.reload`**

`importlib.reload(neos.config.settings)`는 모듈을 재실행해 `settings` 싱글턴을 **새로 만든다.**
이전에 `from neos.config.settings import settings`로 붙잡은 모듈들은 옛 객체를 계속 쓰므로
둘이 갈라진다. 그 결과 `test_service.py`가 새 객체에 confidence cap을 패치해도
`build_orchestrator`는 옛 객체의 기본값을 읽어 실패했다
(`{1: 0.6, ...}` vs 패치한 `{1: 0.51, ...}`).

`Settings.__init__`이 생성 시점에 설정·env를 읽으므로 reload는 애초에 불필요했다.
**효과: 전체 실패 11~13건 → 7~8건.**

**반증된 가설 — 커넥션 누수 (기록용)**

`db_manager.close()`가 `engine.dispose(close=False)`를 쓰는 것이 커넥션 누수라고 보고
`dispose()`로 바꿔봤다. **결과는 악화(8 → 17건)였고 되돌렸다.**

`close=False`는 실수가 아니라 **테스트별 새 이벤트 루프 설계에 대한 의도적 회피책**이다.
커넥션을 만든 루프가 닫힌 뒤 close를 시도하면 asyncpg가 `attached to a different loop`로
실패한다. 이 이유를 `neos/database/connection.py`에 주석으로 못박아 뒀다 —
같은 실수를 반복하지 않도록.

### ✅ fixture 재설계 — 전체 스위트 green (`c219531d`)

비결정적 DB 실패 7~8건의 근본 원인은 **세 가지가 겹친 fixture 문제**였다.

| 문제 | 내용 |
|---|---|
| 죽은 `event_loop` fixture | pytest-asyncio는 1.0에서 이 훅을 제거했다(현재 1.4). 테스트 실행 루프를 제어하지 못하면서, 쓰이지 않는 루프를 매 테스트 생성하고 `set_event_loop`으로 스레드 루프를 그쪽으로 돌려놨다 |
| 테스트별 엔진 재생성 | `reset_db_manager`가 매 테스트 전후로 엔진을 폐기·재생성 → 테스트마다 새 커넥션 풀 |
| `dispose(close=False)` | 커넥션을 닫지 않고 버린다. 루프가 사라진 커넥션은 닫을 수 없으므로 이 플래그 자체는 필요하다 — 다만 버려진 풀이 누적됐다 |

2000개가 넘는 테스트를 지나며 누적돼 후반부에 커넥션 생성이 간헐 실패했다.
그래서 트레이스백이 단언이 아니라 `pool._do_get()` → `_create_connection()`에서 끝났다.

**적용:**

1. 죽은 `event_loop` fixture 삭제
2. `pytest.ini`에 `asyncio_default_test_loop_scope = session` /
   `asyncio_default_fixture_loop_scope = session` — 세션 전체를 **하나의 루프**에서
3. `reset_db_manager` 제거 → 세션 스코프 `database_engine_lifecycle`로 대체.
   엔진을 **한 번만** 만들고 세션 끝에서 한 번 정리한다.
   생성은 **첫 사용 시점까지 지연**시켜 `no_db` 테스트만 돌릴 때 DB를 요구하지 않게 했다

**결과: 2112 passed / 0 failed.** 3회 연속 + 랜덤 순서 실행에서도 동일하고,
실행 시간도 약 30초 줄었다(268s → 240s 내외). 부분 실행(`tests/config` 113/113,
`tests/workflow/deep_analysis` 353/353)도 정상이다.

> 📌 1단계(죽은 fixture 제거)만 적용했을 때는 오히려 16건으로 악화됐다.
> 세션 스코프 루프와 **함께** 적용해야 효과가 난다. 부분 적용하지 말 것.

### 남은 참고 사항

- `deep_analysis_*` 테이블에 과거 실행 잔여물이 약 1.6만 행 남아 있다.
  `cleanup_test_data`는 이 테이블을 지우지 않는다. 지금은 실패를 유발하지 않지만
  (테스트가 run_id로 스코프하므로) 무한히 쌓인다. 정리 대상으로 남겨둔다.
- `SKILL.md`가 없어 여전히 발견되지 않는 스킬 6개: `cron`, `github-search`,
  `google-scholar`, `openalex`, `reddit`, `sec-edgar`.

<details>
<summary>이전 기록 — 비결정적 DB 실패 7~8건</summary>

```
tests/workflow/deep_analysis/*  (대부분)
tests/tasks/test_deep_analysis_persistence_integration.py
tests/test_auth_api.py::TestAuthAPIEndpoints::test_register_*
```

**단독 실행 시 100% 통과**한다 — `deep_analysis` + `tasks` + `test_auth_api` 합쳐 378/378.
전체 실행에서만 실패하고, **두 번 연속 실행 시 겹치는 실패가 거의 없다**(실행마다 대상이 바뀜).
즉 남은 것은 데이터 오염이 아니라 **비결정성**이다.

증상은 데이터 불일치가 아니라 **커넥션 풀 생성 실패**다(트레이스백이
`db_manager.initialize()` → `pool._do_get()` → `_create_connection()`에서 끝난다).
세션 내내 보이는 `attached to a different loop` / `coroutine 'Connection._cancel' was never
awaited` 로그와 같은 뿌리다.

**근본 원인은 fixture 설계다.** `tests/conftest.py`가

- `event_loop`를 **테스트마다 새로** 만들고
- `reset_db_manager`가 매 테스트 전후로 엔진을 버리고 재생성하며
- 그 버려진 커넥션은 `close=False`라 닫히지 않는다

2100여 테스트를 거치며 이 조합이 누적돼 후반부에 커넥션 생성이 간헐적으로 실패한다.

**고치려면 fixture를 재설계해야 한다** — 세션 스코프 이벤트 루프로 통일하거나,
테스트별 트랜잭션 롤백 방식으로 바꿔 엔진 재생성을 없애는 방향이다.
`close=False`만 바꾸는 식의 부분 수정은 위에서 확인했듯 악화된다.

</details>

---

## 1. ✅ I1 — `.env.template` 미커밋 (해결됨, `59d98aa6`)

워킹트리에 있던 시크릿 전용 템플릿을 커밋했다 (+48 / −716). 실제 시크릿은 들어 있지
않고 전부 빈 값 또는 `CHANGE_THIS_PASSWORD` 플레이스홀더임을 확인한 뒤 커밋했다.
`tests/config/test_env_template_policy.py` 4건이 이제 커밋된 상태에서 통과한다.

<details>
<summary>원래 진단 기록</summary>

### 증상

`tests/config/test_env_template_policy.py` 2건이 **워킹트리 수정본 덕분에만** 통과한다.
`370bfff3`(커밋된 상태)로 되돌리면 즉시 실패한다:

```
FAILED test_env_template_assignment_keys_are_allowlisted
FAILED test_env_template_points_to_yaml_example
```

### 원인

`.env.template`을 시크릿 전용 템플릿으로 재작성하는 작업이 **워킹트리에만 남아 있다**
(`git status`상 ` M .env.template`, +48 / −716). 정책 테스트는 `daea3fd7 feat: Add
migration from dotenv to config file`에서 이미 커밋되었다.

### 조치

이 라우팅 작업이 아니라 **dotenv→config 마이그레이션 작업 맥락에서 커밋**해야 한다.
그때까지는 누구든 워킹트리를 초기화하면 테스트가 깨진다.

> ⚠️ 라우팅 작업 중에는 플랜 Global Constraints("`.env.template`의 무관한 변경을 보존하라")에
> 따라 의도적으로 건드리지 않았다. I2와 함께 처리하는 게 자연스럽다.

</details>

---

## 2. ✅ I2 — 게이트웨이 시크릿 하드코딩 (해결됨, `e752b16c`)

### 적용한 수정

`api_gateway/config.toml`에서 JWT 서명 키와 postgres 비밀번호를 제거하고
(`secret_key = ""`, `password = ""`), 게이트웨이가 읽는 env 오버라이드를 전부 문서화했다.

**중요 — 단순히 비우기만 하면 더 위험했다.** `auth.rs:178`이 `secret_key`를 HS256
디코딩 키로 그대로 쓰기 때문에, 빈 키로 기동하면 **빈 키로 서명된 토큰이 통과**한다.
하드코딩된 개발용 키보다 나쁜 상태다. 그래서 기동 검증을 함께 추가했다:

```rust
// api_gateway/src/config.rs — load_from_path()가 env 오버라이드 후 호출
pub fn validate(&self) -> Result<()> {
    if self.jwt.secret_key.trim().is_empty() {
        anyhow::bail!("jwt.secret_key is empty: set the JWT_SECRET_KEY environment variable");
    }
    Ok(())
}
```

### 검증

- `cargo test` 5/5 (신규 2건: 빈 키 거부 / 정상 키 통과), `cargo build` clean
- 실제 바이너리로 확인: `JWT_SECRET_KEY` 없이 실행 → 위 메시지로 기동 거부.
  키를 넣고 실행 → 설정 로드 통과 후 DB 연결 단계로 진행
- `tests/config/test_gateway_config_policy.py` 3건 통과

### 운영 영향

게이트웨이는 이제 **`JWT_SECRET_KEY` 없이는 기동하지 않는다.** 의도된 동작이다.
현재 `docker-compose.*.yml` 어디에도 게이트웨이 서비스가 없어 깨지는 배포 경로는 없지만,
나중에 compose에 편입할 때 이 환경변수를 반드시 주입해야 한다.

<details>
<summary>원래 진단 기록</summary>

### 증상

```
FAILED tests/config/test_gateway_config_policy.py::test_gateway_config_does_not_ship_secret_defaults
FAILED tests/config/test_gateway_config_policy.py::test_gateway_config_documents_required_production_secret_env
FAILED tests/config/test_gateway_config_policy.py::test_gateway_config_documents_transitional_env_overrides
```

### 원인

정책 테스트는 `daea3fd7`에서 추가됐는데, 대상 파일 `api_gateway/config.toml`은
`c5989ad9 feat: Implement the API gateway in Rust` 이후 **한 번도 갱신되지 않았다**.
마이그레이션이 절반만 적용된 상태다.

현재 파일에 실제로 들어 있는 값:

```toml
# api_gateway/config.toml:29
secret_key = "neos_is_a_multiagent_ai_platform_for_research_and_knowledge_work"
# api_gateway/config.toml:50
password = "postgres"
```

### 조치 — 테스트가 요구하는 것 (`tests/config/test_gateway_config_policy.py`)

| 요구 | 내용 |
|---|---|
| 빈 기본값 | `secret_key = ""` 와 `password = ""` 문자열이 **그대로** 존재할 것 |
| 하드코딩 제거 | `neos_is_a_multiagent_...` 와 `password = "postgres"` 부재 |
| 프로덕션 시크릿 문서화 | `JWT_SECRET_KEY`, `DATABASE_URL`, `required in production` 문자열 포함 |
| 과도기 env 오버라이드 문서화 | `DB_HOST` `DB_PORT` `DB_NAME` `DB_USER` `DB_PASSWORD` `GATEWAY_PORT` `UPSTREAM_HOST` `UPSTREAM_PORT` `LOG_LEVEL` 전부 포함 |

전부 **문자열 포함 검사**이므로 주석으로 문서화해도 통과한다. 다만 Rust 게이트웨이가
빈 문자열 시크릿을 실제로 env에서 채우는지 함께 확인할 것 — 테스트는 그것까지 검증하지 않는다.

### 검증

```bash
pytest -q tests/config/test_gateway_config_policy.py
```

</details>

---

## 3. ✅ I3 — 전역 `llm.model` 자동 기본값 (해결됨, `e65b765d`)

### 적용한 수정

**A안 채택.** `llm.model`을 `str | None = None`으로 바꾸고 `LLMFactory._resolve_default_model()`
한 곳에서 provider × everyday 역할로 해석한다. **호출부 47곳은 손대지 않았다.**

조사 중 **같은 결함을 가진 설정 2개를 추가로 발견**해 함께 고쳤다:

| 설정 | 이전 | 현재 |
|---|---|---|
| `llm.model` | `gpt-4-turbo-preview` | `null` → everyday 역할 |
| `knowledge_graph.extraction.model` | `gpt-4-turbo-preview` | `null` → everyday 역할 |
| `context_optimization.tool_result_summarization_model` | `gpt-4-turbo-preview` | `null` → everyday 역할 |

`neos/config/models.yaml`의 `llm_models.gpt4.model_id`는 **의도적 레거시 카탈로그**
(`provider: openai`로 명시된 수동 선택 항목)라 그대로 두었다.

부수 정리:
- `settings.LLM_MODEL`을 직접 넘기던 3곳(`query_refinement_agent`,
  `conversation_context_processor`, `search_orchestrator`)에서 인자를 제거했다 —
  `None`을 명시적으로 넘기면 폴백 가능 여부가 뒤바뀌기 때문.
- `cli.py`의 상태 표시는 신규 `get_default_model()`을 쓴다. `None`을 Rich
  `add_row`에 넘기면 예외가 나므로 필수 수정이었다.

**테스트:** `tests/utils/test_llm_factory_defaults.py`(9건),
`tests/config/test_automatic_model_defaults.py`(3건).

<details>
<summary>원래 진단 기록</summary>

### 증상

```yaml
# config/neos.default.yaml:64-66
llm:
  provider: anthropic
  model: gpt-4-turbo-preview   # ← OpenAI ID인데 provider는 anthropic
```

`gpt-4-turbo-preview`는 **Anthropic·OpenAI 두 카탈로그 어디에도 없다**
(`neos/providers/anthropic.py:56-63`, `neos/providers/openai.py:25-33`).
`neos/config/schema.py:105`의 Pydantic 기본값도 동일하다.

### 전 환경에 적용된다

`neos/config/loader.py:353-354`가 `neos.default.yaml`을 **베이스로 deep-merge**한 뒤
`neos.{env}.yaml`을 덮어쓴다. 그런데 `development` / `staging` / `production` 프로파일에는
**`llm` 블록이 아예 없다.** 따라서 세 환경 모두 위 조합을 그대로 상속한다.
(`config/neos.example.yaml`만 `claude-sonnet-5`로 갱신됨 — `9c7d7519`)

### 영향 범위 — 47개 호출부

```python
# neos/utils/llm_factory.py:93,98
provider_name = provider or settings.LLM_PROVIDER   # → "anthropic"
resolved_model = model or settings.LLM_MODEL        # → "gpt-4-turbo-preview"
```

`model=`을 넘기지 않는 **실호출 47곳**이 이 조합을 받는다 (AST로 집계).
`deep_research.py` 8곳, `hyper_deep_research/` 20곳, `multi_query_search.py` 4곳,
`planning_agent.py`, `response_generator.py`, `fact_check_processor.py`,
`quality_evaluator.py`, `search_result_synthesizer.py` 등:

```python
# neos/agents/planning_agent.py:44 — 대표 예
base_llm = create_llm(temperature=0.3, max_tokens=8000)   # model 없음
```

`settings.LLM_MODEL`을 직접 읽는 곳도 둘 있다 —
`neos/utils/llm_factory.py:154`(OpenAI 폴백, I4 참조),
`neos/workflow/processors/query_refinement_agent.py:36`.

> ℹ️ `neos/services/chat_llm_service.py:170,274`는 `**llm_params`에 `model`을 담아 넘기므로
> **해당 없음**(라우팅된 챗 경로). `llm_factory.py:208-225`의 편의 함수들도 kwargs 패스스루라 제외.
> `neos/utils/llm_wrapper.py`의 `create_llm()`은 **docstring 예시**이며 실호출이 아니다.

즉 **역할 라우팅이 커버하지 못한 마지막 자동 기본값**이자, 잔여 이슈 중 영향 범위가 가장 넓다.

> ❓ 이 상태로 에이전트 계층이 어떻게 동작해 왔는지는 미확인이다. 배포 환경이
> `NEOS_CONFIG_PATH`로 별도 YAML을 물려 덮어쓰고 있을 가능성이 높다.
> **착수 전에 실제 배포 프로파일부터 확인할 것** — 그래야 이게 잠복 버그인지
> 운영상 이미 우회된 것인지 갈린다.

### 왜 Task 6에서 못 잡았나

Step 1 스캔 정규식이 날짜형 레거시 ID만 대상으로 했고 `gpt-4-turbo-preview`가 빠져 있었다.
후속 스캔 시 다음을 추가할 것:

```bash
rg -n 'gpt-4-turbo-preview|gpt-4o|gpt-4\b' neos config web/lib
```

### 조치 후보 (택일 필요)

| 안 | 내용 | 트레이드오프 |
|---|---|---|
| A | `LLMConfig.model`을 `str \| None = None`으로 바꾸고 `llm_factory.py:98`에서 everyday 역할로 해석 | Task 3의 "`None` = 역할 기본값" 관례와 일치. **47개 호출부를 건드리지 않고 한 곳에서 해결**. `settings.LLM_MODEL` 직접 참조 2곳만 별도 처리 |
| B | `neos.default.yaml`과 `schema.py:105` 값만 `claude-sonnet-5`로 교체 | 최소 변경. 단 정책 밖의 별도 기본값이 그대로 남아 다음에 또 낡는다 |

**A 권장.** 이 작업의 핵심 계약(`None` = 역할 기본값)을 마지막 구멍에도 적용하는 것이고,
호출부 47곳을 수정할 필요가 없다.

착수 시 TDD 순서: `tests/config/test_model_routing.py` 또는 신규
`tests/utils/test_llm_factory_defaults.py`에 "`model=None`이면 `claude-sonnet-5`" 단언을 먼저 쓰고
RED 확인 → `llm_factory` 수정.

> ⚠️ `llm.fast_model`(`claude-haiku-4-5-20251001`)은 현행이므로 함께 건드릴 필요 없다.
> `provider: anthropic`도 유지 — 바꿔야 할 건 `model`뿐이다.

</details>

---

## 4. ✅ I4 — 크로스 프로바이더 폴백 (해결됨, `e65b765d`)

### 적용한 수정 — "명시 선택 시에만 비활성화"

폴백 자체는 유지하되, **호출자가 `provider=` 또는 `model=`을 하나라도 넘겼으면
폴백하지 않고 예외를 전파**한다. 폴백 대상 모델도 `settings.LLM_MODEL`이 아니라
OpenAI `everyday` 역할(`gpt-5.6-terra`)로 해석한다.

| 호출 | 프로바이더 생성 실패 시 |
|---|---|
| `create_llm(temperature=0.3)` | OpenAI everyday(`gpt-5.6-terra`)로 폴백 |
| `create_llm(model="claude-opus-5")` | **raise** — 명시한 모델은 대체되지 않음 |
| `create_llm(provider="anthropic")` | **raise** — 명시한 프로바이더는 대체되지 않음 |
| `provider="ollama"` | raise (기존 동작 유지) |

폴백은 `OpenAIProvider`를 직접 인스턴스화하던 것에서 **레지스트리(`_providers["openai"]`)
경유**로 바꿨다 — 등록된 프로바이더 교체가 폴백에도 반영된다.

이로써 해석 우선순위 1순위(user)가 실제로 지켜진다: 사용자가 고른 모델이
조용히 다른 프로바이더로 넘어가는 경로가 사라졌다.

<details>
<summary>원래 진단 기록</summary>

### 증상

```python
# neos/utils/llm_factory.py:146-158
if provider_name != "openai" and settings.OPENAI_API_KEY:
    logger.error("FALLING BACK to OpenAI from %s — check provider configuration", provider_name)
    fallback = OpenAIProvider()
    return fallback.create_llm(model=settings.LLM_MODEL, ...)
```

Anthropic 생성이 실패하면 **조용히 OpenAI로 넘어간다**. 게다가 넘기는 모델은 I3의
`gpt-4-turbo-preview`다.

### 왜 이슈인가

플랜 Global Constraints에 **"크로스 프로바이더 fallback 추가 금지"** 가 명시돼 있다.
이 코드는 라우팅 작업 **이전부터 존재**했으므로 "추가"는 아니지만, 사용자가 Anthropic을
명시적으로 골랐는데 OpenAI로 응답이 나갈 수 있다 — 해석 우선순위 1순위(user)를 사실상 무력화한다.

### 조치

선재 동작이라 이번 작업에서 제거하지 않았다. **제품 결정이 필요하다:**

- 폴백 제거 → 명시적 선택 보존이 엄격해지지만 가용성 하락
- 유지하되 사용자 명시 선택 시에만 비활성화
- 유지하되 폴백 모델을 역할 기본값으로 해석

</details>

---

## 5. ✅ I5 — 프론트엔드 레거시 피커 (해결됨, `48ad7dac`)

### 핵심 발견 — 라벨 문제가 아니라 실행 불가였다

`chat_llm_service._extract_provider_from_model`은 **`gpt`→openai, `claude`→anthropic만
인식하고 나머지는 전부 `default_provider`(anthropic)로 폴백**한다. 따라서 Google·xAI
피커 항목은 "라벨이 부정확한" 수준이 아니라, 고르면 Gemini/Grok 모델명을 Anthropic에
보내 **요청 시점에 실패**하는 죽은 항목이었다.

### 적용한 수정

| 조치 | 대상 |
|---|---|
| **제거** | `google/gemini-2.5-flash-lite`, `google/gemini-3-pro-preview`, `xai/grok-4.1-fast-non-reasoning`, `xai/grok-code-fast-1-thinking` |
| **실제 모델에 맞게 개명** | `openai/gpt-4.1` → `openai/gpt-4o` "GPT-4o", `openai/gpt-4.1-mini` → `openai/gpt-4o-mini` "GPT-4o Mini", `anthropic/claude-3.7-sonnet-thinking` → `anthropic/claude-sonnet-4.5-thinking` "Claude Sonnet 4.5 (Thinking)" |

매핑 테이블을 `MODEL_MAP`(현행 피커)과 `RETIRED_MODEL_MAP`(퇴역 ID)으로 분리했다.
퇴역 ID를 남기는 이유는 `chat-model` 쿠키가 검증 없이 그대로 전달되기 때문이다.
**애초에 동작하지 않던 Google·xAI ID는 기본 모델(`claude-sonnet-5`)로 퇴역**시켰다 —
피커에서 사라진 항목은 UI상 기본 모델로 표시되므로 표시와 동작이 일치한다.

> ⚠️ 개명 시 `thinking` 부분 문자열을 유지해야 한다. `web/lib/ai/prompts.ts:64`가
> `selectedChatModel.includes("thinking")`으로 reasoning 프롬프트를 분기한다.
> 회귀 가드: `keeps the reasoning entry detectable by prompt selection`.

> ℹ️ `lib/ai/providers.ts`의 `getLanguageModel()`은 **호출부가 없는 죽은 코드**다.
> 즉 피커 id는 Vercel 게이트웨이로 나가지 않고 `mapToBackendModelName`만 실제 동작을
> 결정한다. 그래서 id 개명이 안전했다.

**테스트:** `web/tests/source/ai-models.test.ts` 11건 (신규 5건).

<details>
<summary>원래 진단 기록</summary>

### 이번 작업에서 이미 처리한 것 (참고)

- `anthropic/claude-opus-4.5`: 이름이 "Claude Opus 4.6"으로 잘못 라벨링돼 있어 **피커에서 제거**.
  단 `mapToBackendModelName` 매핑은 **남겨뒀다** — `chat-model` 쿠키가
  `web/app/(chat)/chat/[id]/page.tsx:76`에서 그대로 읽히고
  `web/app/(chat)/api/chat/schema.ts:94`가 `z.string()`으로만 검증하므로,
  매핑까지 지우면 게이트웨이 ID 원문이 백엔드로 새어나간다 (`dd36325f`).
- `anthropic/claude-haiku-4.5` 매핑을 백엔드 카탈로그와 맞춰 `claude-haiku-4-5-20251001`로 교정.

> 💡 회귀 가드가 이미 있다: `web/tests/source/ai-models.test.ts`의
> "never returns a gateway-prefixed ID to the backend"가 피커 전 엔트리의 매핑 존재를 강제한다.
> 위 표를 정리할 때 매핑을 지우면 이 테스트가 잡아준다.

</details>

---

## 6. ✅ I6 — `fast` 역할 (도입하지 않기로 확정, `af5b83ba`)

### 결정

**`everyday` / `powerful` 2단계를 유지한다.** 저비용 워크로드는 각자의 명시적 Haiku
설정을 그대로 쓴다:

| 대상 | 현재 값 | 상태 |
|---|---|---|
| `recursive_agent.atomizer_model` (depth > 0) | `claude-haiku-4-5-20251001` | 의도적 제외. `370bfff3`이 고정 |
| 쿼리 분류·확장 등 `*_LLM_MODEL` | `claude-haiku-4-5-20251001` | 의도적 제외 |
| `get_recommended_models()`의 `fast` 티어 | anthropic `claude-haiku-4-5-20251001`, openai `gpt-5.6-terra` (2026-07-27 이전엔 `gpt-5-mini-2025-08-07`) | 라우팅 역할이 아니라 **운영자용 수동 참고 목록** |

이 결정이 실수가 아니라 판단이었음을 테스트로 고정했다:
`tests/config/test_model_routing.py::test_policy_stays_at_two_roles`가
`WorkloadRole == ("everyday", "powerful")`과 `ProviderModelRolesConfig` 필드 집합을 단언한다.

### 나중에 도입하려면

`WorkloadRole` Literal과 `ProviderModelRolesConfig` 필드를 **함께** 확장해야 하고,
그 전에 Haiku 티어 정책 설계가 선행돼야 한다. 위 테스트가 먼저 실패하므로
무심코 절반만 바꾸는 일은 막힌다.

### ~~남은 미확인 사항~~ — 해결됨 (2026-07-27, `5279a8ed`)

> 당시 서술: `get_recommended_models("openai")["fast"]`의 `gpt-5-mini-2025-08-07`을
> 그대로 뒀다. GPT-5.6 세대의 소형 모델이 어디에도 없어 확인되지 않은 모델 ID를
> 지어내지 않았다.

지어내지 않은 판단은 유지하되, **다른 방향으로 해결**했다. `gpt-5-mini-2025-08-07`은
가격이 없는 채로 선택 가능해서 그 비용이 조용히 0으로 집계되고 있었다. 그래서 새
소형 모델 ID를 찾는 대신 **은퇴시키고 `gpt-5.6-terra`가 `fast`를 겸하게** 했다
(`tiers: [fast, balanced]` — Gemini·Ollama가 이미 쓰던 형태).

같은 이유로 은퇴한 모델이 총 6개다. 지금은 **선택 가능한 모델이 전부 가격을
가진다**는 불변식이 테스트로 고정돼 있다
(`test_model_catalog_parity.py::test_every_selectable_model_is_priced`).
`fast` 티어는 여전히 라우팅 역할이 아니라 운영자용 참고값이다 — 위 §6 결정은 유효하다.

---

## 7. 절대 어기면 안 되는 제약 (완료된 작업의 불변식)

- ✅ 해석 우선순위: **user → conversation → feature override → role default**
- ✅ 역할 매핑은 정확히: anthropic `everyday=claude-sonnet-5` / `powerful=claude-opus-5`,
  openai `everyday=gpt-5.6-terra` / `powerful=gpt-5.6-sol`
- ✅ 기존 대화는 저장된 모델 유지 (마이그레이션·재작성 금지)
- ✅ `None` = 역할 기본값, 문자열 = 기능 오버라이드 (`coding_model.model`,
  `recursive_agent.planner_model`, `deep_analysis.models.*`)
- ✅ Claude 5는 adaptive thinking, 비기본 샘플링 파라미터 미전송, 수동 `budget_tokens`는 `ValueError`
- ✅ 경계마다 **한 번만** 해석 (토큰 스트림 루프 안에서 반복 해석 금지)
- ✅ 테스트는 라이브 프로바이더 크리덴셜 불필요
- ❌ 크로스 프로바이더 fallback **추가** 금지 (기존 것은 I4 참조)
- ❌ 요청마다 LLM으로 난이도 분류하는 방식 금지 (설계에서 기각 — 지연·비용·비결정성)
- ❌ Claude Fable 5 / Mythos 5 / GPT-5.6 Luna는 자동 라우팅 대상 아님
- ❌ Gemini / xAI / 임베딩 / 리랭킹 / 비전 전용 모델은 정책 범위 밖
- ✅ 기존 untracked 7월 11일 문서는 **보존**

---

## 8. 검증 명령

```bash
# 백엔드 부분 스위트. 전체는 `pytest -q` — 현재 2234 passed / 16 skipped / 0 failed
pytest -q tests/utils tests/config tests/providers \
  tests/services/test_chat_model_resolution.py tests/test_chat_service.py \
  tests/test_chat_llm.py tests/test_cost_calculator.py \
  tests/workflow tests/api tests/database tests/test_pipelines.py -p no:randomly

# Rust 게이트웨이 — 현재 5/5
cd api_gateway && cargo test --offline && cargo build --offline

# 게이트웨이 기동 검증 (JWT_SECRET_KEY 없으면 거부되어야 정상)
env -u JWT_SECRET_KEY CONFIG_PATH=config.toml ./target/debug/neos_api_gateway

# 프론트엔드 — 현재 141/141
pnpm --dir web test:source
pnpm --dir web exec tsc --noEmit   # tsconfig.tsbuildinfo가 더러워지면 git checkout 으로 되돌릴 것

# 낡은 자동 기본값 재스캔 (I3에서 확장한 패턴 포함)
# 주의: 아래 중 claude-sonnet-4-6 / claude-opus-4-6 / gpt-5-2025-08-07 /
# gpt-5-mini-2025-08-07은 2026-07-27에 은퇴했다. 카탈로그에 다시 나타나면
# 가격이 없다는 뜻이므로 test_retired_models_are_gone_from_the_catalog가 잡는다.
rg -n 'claude-sonnet-4-5-20250929|claude-opus-4-5-20251101|claude-sonnet-4-6|claude-opus-4-6|gpt-5-2025-08-07|gpt-5-mini-2025-08-07|gpt-4-turbo-preview|gpt-4o' \
  neos config web/lib docs/CONFIGURATION.md examples

# 모델 카탈로그 자체 검증 (2026-07-27 이후)
pytest -q tests/config/test_model_catalog.py tests/config/test_model_catalog_parity.py
```

**주의 1 — 앰비언트 상태 오염.** 순서 의존 실패가 나오면 이 세 가지를 먼저 의심하라.
셋 다 실제로 이 저장소에서 발생했다:

| 증상 | 원인 | 대응 커밋 |
|---|---|---|
| 전역 `settings` 싱글턴이 바뀐 채 남음 | `reload_settings_for_tests()`가 모듈 전역을 재바인딩 | `d3d3fd96` |
| 프로세스 env가 테스트 지정값을 이김 | litellm·crewai가 import 시 `load_dotenv()`로 `.env`를 `os.environ`에 복사 | `4b37a3fe` |
| import 시점에 고정된 플래그가 어긋남 | `neos/main.py`의 `IS_DEBUG`는 최초 import 때 확정 | `fe425578` |

세 번째가 가장 잡기 어렵다. **모듈 최상단에서 `os.environ[...]`을 설정해 앱 형태를
제어하려는 코드는 신뢰하지 말 것** — 그 모듈이 먼저 import된다는 보장이 없다.
그런 설정은 `tests/conftest.py`에 둬야 한다.

**주의 2 — 전체 스위트는 이제 결정적이다(`c219531d` 이후).** 예전에는 동일 조건에서도
실행마다 60~66건이 오락가락했다. 지금은 `pytest tests/`가 **2112 passed / 0 failed**로
안정적이므로, 실패가 하나라도 보이면 **실제 회귀로 취급**하라.

옛 방식대로 집합 비교가 필요하다면:

```bash
git stash push -u && pytest -q tests/ ... 2>&1 | grep '^FAILED tests/' | sort -u > /tmp/before.txt
git stash pop    && pytest -q tests/ ... 2>&1 | grep '^FAILED tests/' | sort -u > /tmp/after.txt
comm -13 /tmp/before.txt /tmp/after.txt   # 비어 있어야 회귀 없음
```

`grep '^FAILED'`만 쓰면 라이브 로그의 진행 표시(`FAILED  [ 7%]`)까지 걸린다.
반드시 `'^FAILED tests/'`로 걸러라.

---

## 9. 완료된 작업 (참고용 커밋 목록)

| Task | 내용 | 커밋 |
|---|---|---|
| 1 | 중앙 모델 라우팅 계약 (`neos/config/model_routing.py`) | `4f76d1ef..ca72f08b` |
| 2 | 프로바이더 카탈로그 · Claude 5 페이로드 · 가격 | `ca72f08b..7bed37f3` |
| 3 | 백엔드 역할 배정 · 명시적 선택 보존 | `7bed37f3..4d016471` |
| 4 | 재귀 플래너 powerful 역할 | `4d016471..370bfff3` |
| 5 | 프론트엔드 모델 피커 · 매핑 | `547a4ede` |
| 6 | 통합 검증 · 문서 정합 | `d3d3fd96`, `9c7d7519`, `dd36325f` |

Task 6에서 추가로 잡은 자동 기본값 누락 3곳 (`9c7d7519`):
제목 생성(`chat_service.py`), 템플릿 `default_model`(service·repository·API 모델),
`llm.model` 공개 예시(`config/neos.example.yaml`, `docs/CONFIGURATION.md`).
`docs/CONFIGURATION.md`에 `### Model Routing` 절 신규 작성.

### 잔여 이슈 후속 커밋

| 이슈 | 내용 | 커밋 |
|---|---|---|
| I3 · I4 | `create_llm` 기본 모델 역할 라우팅 · 폴백 정책 | `e65b765d` |
| I1 | `.env.template` 시크릿 전용 축소 | `59d98aa6` |
| I2 | 게이트웨이 시크릿 제거 + 기동 검증 | `e752b16c` |
| I5 | 미지원 피커 항목 제거 · 오라벨 교정 | `48ad7dac` |
| I6 | 2단계 역할 정책 확정 (테스트 고정) | `af5b83ba` |

---

## 10. 참조

- 설정 문서: [CONFIGURATION.md](../CONFIGURATION.md) — `### Model Routing` 절
- 관련 재개 문서: [deep_analysis_task_task_resume.md](deep_analysis_task_task_resume.md),
  [coding_agent_task_resume.md](../coding_agent_task_resume.md)
- SDD 원장: `.superpowers/sdd/2026-07-25-role-based-model-routing/`
