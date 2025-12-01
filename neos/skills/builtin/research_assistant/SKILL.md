# Research Assistant Skill

## Description
리서치 작업을 보조하는 스킬입니다. 소스 분석, 요약, 참고문헌 정리 등을 수행합니다.

## Capabilities
- 소스 품질 평가
- 텍스트 요약
- 참고문헌 추출 및 정리
- 핵심 인사이트 도출
- 리서치 메모 작성

## Usage
이 스킬은 HyperDeepResearchAgent와 함께 사용되어 리서치 품질을 향상시킵니다.

### Parameters
- `action`: 수행할 작업 ("analyze_source", "summarize", "extract_references")
- `content`: 분석할 내용
- `options`: 추가 옵션

### Example
```python
# 소스 분석
params = {
    "action": "analyze_source",
    "content": "...",
    "options": {
        "check_credibility": True,
        "extract_key_points": True
    }
}

# 텍스트 요약
params = {
    "action": "summarize",
    "content": "...",
    "options": {
        "max_length": 500,
        "style": "academic"
    }
}
```

## Integration with HyperDeepResearch
이 스킬은 HyperDeepResearchAgent의 각 단계에서 활용될 수 있습니다:
- Phase 2: 리서치 계획 수립 보조
- Phase 3: 소스 품질 평가
- Phase 4: 심층 분석 보조
- Phase 7: 최종 리포트 작성 지원

## Version
1.0.0
