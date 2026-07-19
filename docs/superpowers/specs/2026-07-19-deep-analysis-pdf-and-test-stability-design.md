# Deep Analysis PDF Fetch and Test Stability Design

## 목적

deep-analysis가 PDF 소스를 HTML로 오인하지 않고 텍스트를 검증 자료로 사용할 수 있게 한다.
동시에 전체 workflow/API handler 테스트에서 확인된 PostgreSQL 실행환경 실패와 telemetry
전역 stub 오염을 분리하고, 실제 코드·테스트 결함을 수정한다.

## 범위

이 작업은 세 부분으로 구성한다.

1. `deep_analysis.fetch`의 PDF 감지·텍스트 추출
2. workflow graph 테스트의 telemetry module 격리
3. PostgreSQL 의존 테스트를 CI와 같은 연결 조건에서 재실행하고 실제 실패만 수정

PDF의 표·이미지·OCR 추출, PDF 저장, UI 변경, DB 테스트 skip은 범위에 포함하지 않는다.

## PDF 감지와 추출

### 감지

2xx 응답에 대해서만 본문 형식을 판별한다.

- `Content-Type`의 media type이 `application/pdf`이면 PDF다.
- 헤더가 없거나 잘못됐어도 body가 공백 뒤 `%PDF-`로 시작하면 PDF다.
- 그 외 응답은 기존 HTML 텍스트 추출을 유지한다.
- non-2xx 응답은 형식과 관계없이 기존처럼 빈 본문으로 저장한다.

HTTP fake와 실제 `httpx.Response`를 모두 지원하도록 `response.headers`와
`response.content`만 요구한다. 기존 단순 fake가 이 속성을 제공하지 않으면 HTML 경로로
동작해 기존 테스트 호환성을 유지한다.

### 추출

`neos/workflow/deep_analysis/pdf_text.py`에 작은 어댑터를 둔다.

- `pdf_bytes_to_text(content: bytes) -> str`
- PyMuPDF(`fitz`)를 함수 안에서 lazy import한다.
- 모든 페이지의 `page.get_text()` 결과를 순서대로 결합한다.
- HTML과 같은 NFC 및 공백 축약 정규화를 적용한다.
- 문서는 `finally`에서 항상 닫는다.
- import 실패, 잘못된 PDF, 암호화/파싱 오류는 `PDFExtractionError`로 변환한다.

PyMuPDF는 이미 `pyproject.toml`과 lockfile의 직접 의존성이므로 새 패키지는 추가하지 않는다.
기존 `pipelines.PDFParser`는 표·이미지·메타데이터까지 추출하고 오류를 결과 dict로 숨기므로
deep-analysis의 좁은 fetch 계약에 재사용하지 않는다.

### 실패 경계

한 PDF의 파싱 실패가 전체 worker를 중단하지 않게 한다. `Worker`의 URL fetch loop는
`PDFExtractionError`만 잡아 URL과 예외 유형을 payload 없이 경고하고 해당 소스를 건너뛴다.
네트워크 오류와 다른 프로그래밍 오류는 기존처럼 상위로 전파한다.

성공한 PDF는 추출된 텍스트로 content hash를 계산하므로 HTML mirror와 같은 텍스트면 동일
blob으로 deduplicate된다. 텍스트가 없는 정상 PDF는 URL/status 기반 empty hash 규칙을
그대로 따른다.

## Telemetry 테스트 격리

다음 테스트 모듈은 collection 시점에 `sys.modules["neos.workflow.telemetry"]`를 stub으로
교체해 이후 production app import를 깨뜨린다.

- `tests/workflow/test_harness_graph_repair.py`
- `tests/workflow/test_harness_graph_routing.py`
- `tests/workflow/test_thinking_engine_finalization.py`

이 전역 telemetry stub을 제거하고 실제 `neos.workflow.telemetry`를 사용한다. 테스트 대상은
순수 routing 함수이며 telemetry 호출을 실행하지 않으므로 stub이 필요하지 않다. 다른 선택적
외부 모듈 stub은 이번 범위에서 유지한다.

회귀 테스트는 문제의 세 workflow 모듈 다음에
`tests/api/handlers/test_query_authorization.py`를 같은 pytest 프로세스에서 실행해 순서
독립성을 증명한다.

## PostgreSQL 테스트 처리

앞서 실패한 deep-analysis 44개는 sandbox가 localhost PostgreSQL socket 연결을 차단해
발생했다. 이를 unit test로 바꾸거나 skip하지 않는다.

1. CI와 같은 `DATABASE_URL` 및 PostgreSQL 접근 권한으로 실패 파일들을 재실행한다.
2. 연결 후 통과하면 환경 실패로 확정하고 코드 변경을 하지 않는다.
3. 연결 후 assertion/schema/cleanup 실패가 남으면 그 실패에 대해서만 systematic debugging과
   TDD로 수정한다.
4. 최종 workflow/API handler 전체 실행 결과를 기록한다.

DB가 실제로 실행 중이지 않으면 새 인프라를 임의로 설치하거나 생성하지 않고 해당 외부
전제조건을 명시한다. GitHub Actions에는 이미 pgvector PostgreSQL service가 구성되어 있다.

## 테스트 전략

### PDF 단위 테스트

- `application/pdf` 응답이 추출기를 사용한다.
- 잘못된 content-type이어도 `%PDF-` body를 감지한다.
- 일반 HTML과 non-2xx 동작이 회귀하지 않는다.
- 여러 페이지 텍스트의 순서·Unicode·공백 정규화를 검증한다.
- PDF 문서가 성공·실패 모두 닫힌다.
- PDF 파싱 실패 시 worker는 그 소스만 건너뛴다.

테스트 PDF는 PyMuPDF로 메모리에서 최소 문서를 생성하거나 parser protocol fake를 사용하며
저장소에 바이너리 fixture를 추가하지 않는다.

### 테스트 안정성 회귀

- telemetry 오염 재현 순서가 한 pytest 프로세스에서 통과한다.
- PostgreSQL 실패 파일을 DB 접근 가능한 조건에서 실행한다.
- `tests/workflow tests/api/handlers` 전체를 실행한다.
- 변경 파일 Ruff와 `git diff --check`를 실행한다.

## 완료 조건

- PDF 응답이 읽을 수 있는 정규화 텍스트의 `ProposedBlob`을 만든다.
- PDF 파싱 실패가 HTML 쓰레기나 `E_QUOTE_MISMATCH` 입력으로 바뀌지 않고 해당 소스만
  격리된다.
- telemetry 테스트가 production import를 오염시키지 않는다.
- PostgreSQL 실패가 환경 제약인지 실제 결함인지 재검증되고 결과가 문서화된다.
- 관련 집중 테스트와 가능한 전체 suite, Ruff가 통과한다.
- `docs/TODO_260729.md`의 §6 및 다음 우선순위가 검증 근거와 함께 갱신된다.
