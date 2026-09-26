# 외교부 해외안전·여행경보 조회

## What this skill does

외교부 `국가·지역별 여행경보 목록 조회(0404 대륙정보)` API를
`k-skill-proxy`의 좁은 read-only route로 조회한다. 국가명 또는 ISO 2자리
코드로 공식 여행경보 단계, 지역 유형, 경보 내용, 작성일과 공식 지도 URL을
확인한다.

이 skill은 자체적인 안전/위험 점수나 여행 허가 판단을 만들지 않는다.
응답된 외교부 공식 경보와 원문 링크를 사실 그대로 요약한다.

## Inputs

- `country_iso_alp2`: ISO 2자리 국가코드(예: `RU`)
- `country_nm`: 한글 국가명(예: `러시아`)
- `page`: 기본 `1`
- `perPage`: 기본 `10`, 최대 `100`

국가명과 ISO 코드는 동시에 주지 않는다.

## Workflow

```bash
BASE="${KSKILL_PROXY_BASE_URL:-https://k-skill-proxy.nomadamas.org}"
curl -fsS --get "$BASE/v1/mofa-travel-safety/travel-alerts" \
  --data-urlencode "country_iso_alp2=RU" \
  --data-urlencode "perPage=10"
```

응답 `items`의 `country_nm`, `country_iso_alp2`, `alarm_lvl`,
`region_ty`, `remark`, `written_dt`, `dang_map_download_url`을 원문 기준으로
요약한다. `alarm_lvl` 숫자의 의미는 답변에서 임의로 재분류하지 말고
외교부 원문/0404 설명을 함께 제시한다.

## Access path and credentials

일반 사용자는 hosted `k-skill-proxy`를 사용하므로 data.go.kr 키가 필요
없다. proxy 운영자는 승인된 `DATA_GO_KR_API_KEY`를 서버 runtime env에
보관한다. 키는 URL, 로그, 저장소, 사용자 응답에 노출하지 않는다.

공식 API:
<https://www.data.go.kr/data/15095500/openapi.do>

실제 upstream:
`https://apis.data.go.kr/1262000/TravelAlarmService0404/getTravelAlarm0404List`

## Fallback and failure modes

- 먼저 proxy route를 사용하고, 실패하면 공식 data.go.kr API 문서와 0404
  원문 링크만 안내한다. 임의의 안전 판정을 대신하지 않는다.
- `400 bad_request`: 잘못된 ISO 코드, 국가명, 페이지 값
- `503 upstream_not_configured`: proxy runtime에 data.go.kr 키 없음
- `502 upstream_error`: 외교부/data.go.kr 인증·quota·상류 장애
- `upstream_invalid_response`: JSON 대신 XML/HTML 오류 응답
- `items: []`: 해당 조건에 맞는 국가/지역 기록 없음

## Done when

- 국가명 또는 ISO 코드와 조회 시각을 답변에 적었다.
- `alarm_lvl`, `region_ty`, `remark`를 공식 필드명과 함께 제시했다.
- 원문 API 문서와 0404 공식 링크를 함께 제공했다.
