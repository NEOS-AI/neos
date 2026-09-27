---
name: canvas
type: content_generation
version: 1.0.0
description: 연구 결과를 구조화된 캔버스(마크다운·차트·다이어그램)로 렌더링
capabilities:
  - render_canvas
  - export_canvas_html
  - generate_chart
  - generate_diagram
dependencies: []
allowed_tools: "Read"
---

# Canvas Skill

## Description
연구 세션 결과를 동적 캔버스 형태로 렌더링하는 스킬입니다.
구조화된 마크다운, 소스 분포 차트(matplotlib), Mermaid 마인드맵을 조합하여
가독성 높은 캔버스를 생성합니다.

## Capabilities
- 연구 결과 구조화된 마크다운 렌더링 (섹션·테이블·인용 포함)
- 소스별 검색 결과 분포 차트 생성 (base64 PNG)
- 인용 소스 관계 Mermaid 마인드맵 생성
- 전체 캔버스 HTML 내보내기 (자급자족 파일)

## Usage

### Parameters
- `session_id` (필수): 렌더링할 연구 세션 ID
- `user_id` (필수): 사용자 ID (권한 확인용)
- `canvas_type` (선택, 기본값 `all`): `markdown` | `chart` | `diagram` | `all`

### Example
```python
params = {
    "session_id": "abc123",
    "user_id": "user-uuid",
    "canvas_type": "all",  # 마크다운 + 차트 + 다이어그램
}
```

## Requirements
- `matplotlib>=3.8.0` (차트 생성용, 선택적 — 없으면 차트 생략)
- Mermaid JS (CDN, 클라이언트 사이드)

## Version
1.0.0
