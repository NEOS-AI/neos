# 00. k-skill — 개요

원본 README 한 줄:

> 한국인인가요? 이 스킬 모음집을 다운로드 받아 두세요.

원본은 코딩 에이전트에 한국 공공 API·실생활 표면 레시피를 심는 **마크다운 스킬 팩**이다. FSI/Univer처럼 부모 커널이 아니다. 에이전트 루프는 호스트가 이미 갖고, k-skill은 `SKILL.md` 어댑터 + `instruction.md` + 선택 스크립트다.

조사 기준: 로컬 클론 `/Users/yeonwoosung/Desktop/k-skill` (2026-09-26). README는 “총 125개”라고 쓰지만 디스크·플러그인 매니페스트·런타임 감사 표는 모두 **127**이다.

## 1. 원본이 하는 일

설치:

```bash
npx --yes skills add NomaDamas/k-skill --all -g
npx -y @nomadamas/k-skill@0 update
```

생성된 `SKILL.md`는 워크플로가 아니다. 에이전트에게 CLI를 돌리라고 한다.

```bash
npx -y @nomadamas/k-skill@0 instruct <skill>
npx -y @nomadamas/k-skill@0 exec <skill> scripts/<file> -- ...
npx -y @nomadamas/k-skill@0 read <skill> references/<file>
```

CLI가 `packages/k-skill-cli/templates/*.md` (core/proxy/vault/browser/lookup/…)와 `instruction.md`를 조립한다. 프록시 스킬(~59)은 사용자 API 키 없이 `https://k-skill-proxy.nomadamas.org`를 친다. 브라우저/액션 스킬은 Dolshoi vault + CloakBrowser 또는 로컬 CDP를 가정하고, 결제·전송·최종 제출 직전에 `clarify`를 요구한다.

## 2. 디렉터리 구조

```
k-skill/
  <skill>/
    skill.json          # 소스. name, description, profiles, frontmatter YAML 문자열
    instruction.md      # 소스. 사이트별 워크플로
    SKILL.md            # 생성물. CLI 스텁
    scripts/            # 선택
    references/         # 선택
  packages/
    k-skill-cli/        # @nomadamas/k-skill (MIT)
    k-skill-proxy/      # AGPL-3.0 hosted 무료 API 프록시
    k-skill-browser-runtime/
    <per-skill npm helpers>/
  docs/features/<skill>.md
  .claude-plugin/plugin.json
```

소스 오브 트루스: `skill.json` + `instruction.md`. `SKILL.md`와 `packages/k-skill-cli/skills/`는 생성물이다.

## 3. skill.json

127개 모두 `name`, `description`, `profiles`, `frontmatter`를 가진다. `name`은 디렉터리 이름과 같다.

`frontmatter`는 YAML 문자열이다. 거의 전부 `name` + `description` + `license: MIT` + `metadata.{category,locale: ko-KR,phase}`다. 예외: `korean-jangbu-for` / `korean-privacy-terms`는 Apache-2.0 래퍼. `gongsijiga-search`의 JSON `description`은 `"|"`, 실제 설명은 frontmatter 멀티라인.

구현 유형 (`docs/adding-a-skill.md`):

| 유형 | 수 | 동작 |
|---|---|---|
| instruction 전용 | 34 | curl/node를 본문에 적음 |
| 스킬 디렉터리 `scripts/` | 69 | CLI `exec`로 실행 |
| npm helper `packages/<id>` | ~25 | 별도 패키지 |
| 프록시 경유 | 59 | hosted `/v1/...` |
| 원격 MCP | 4 | 홍익메디케어, 한국일보, 마이리얼트립, 올라포케 역삼 |

## 4. 카테고리 (README 표)

| 영역 | n | 예 |
|---|---|---|
| 이동·교통·여행 | 18 | `railway-timetable`, `korea-weather` 아님 — `seoul-subway-arrival` |
| 부동산·주택 | 8 | `real-estate-search` |
| 법률·공공 | 9 | `korean-law-search` |
| 사업·상권·세무 | 10 | `nts-business-registration` |
| 정부지원·조달 | 7 | `kstartup-search` |
| 채용·일자리 | 4 | `job-posting-match` |
| 금융·투자·경제통계 | 7 | `korean-stock-search`, `k-dart` |
| 건강·의료 | 5 | `emergency-room-beds` |
| 쇼핑·중고거래 | 12 | `coupang-product-search` |
| 먹거리·주류 | 4 | `kamis-food-price` |
| 스포츠·경기 | 5 | `kbo-results` |
| 문화·역사·여가 | 6 | `joseon-sillok-search` |
| 종교 | 1 | `religious-facility-search` |
| 교육·장학·학술 | 4 | `korean-scholarship-search` |
| 뉴스·정보·리서치 | 4 | `naver-news-search` |
| 한국어·글쓰기 | 5 | `korean-spell-check` |
| 날씨·환경 | 4 | `korea-weather` |
| 생활·기타 | 6 | `korean-holiday-calendar` |
| 개발자·문서 도구 | 4 | `hwp`, `rhwp-edit` |
| 운세·작명 | 2 | `saju-fortune` |
| 공통 설정·관리 | 2 | `k-skill-setup`, `k-skill-cleaner` |

전체 id 목록은 스펙 §4.

## 5. Neos에 이미 있는 것과의 관계

| Neos 목록 | 루트 | k-skill을 넣으면 |
|---|---|---|
| 코딩 마크다운 카탈로그 | `neos/coding/skills/` | 125줄을 직접 넣으면 코딩 프롬프트가 비대해진다. 인덱스 한 줄만 허용. |
| 팩 카탈로그 | `fsi_catalog()` / `univer_catalog()` | **이 패턴을 따른다.** |
| BaseSkill HTTP | `neos/skills/builtin/` + `skill.py` | 넣지 않는다. 실행 클래스가 아니다. |
| 웹 UI | 없음 | 프론트 변경 없음. |

이름 충돌: `skills/` 최상위 181개와 k-skill 127개는 **교집합 없음**.

## 6. v0에 옮기지 않는 것

- `packages/k-skill-proxy` (AGPL 서버). 스킬 본문은 호스티드 URL을 그대로 둔다.
- Dolshoi vault, CloakBrowser, `k-skill-browser-runtime`.
- `k-skill-setup`, `k-skill-cleaner`.
- `ParentKind`, kebab leaf, MCP 허브 JSON, slash `aliases.yaml`.
- 생성 `SKILL.md` 스텁을 그대로 벤더하는 일 (Neos `load_skill.v1`이 스텁만 돌려주면 오프라인 본문이 없다).
