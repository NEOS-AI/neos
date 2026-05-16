# Citation System 사용 가이드

HyperDeepResearch Agent의 고급 Citation Tracking System 사용법입니다.

## 📚 개요

Citation System은 연구 보고서의 모든 주장에 대해 자동으로 출처를 추적하고 참조 목록을 생성합니다.

### 주요 기능

✅ **Inline Citation**: 모든 주장에 자동 [번호] 추가
✅ **Multiple Styles**: APA, Chicago, MLA, Vancouver 지원
✅ **Academic Identifiers**: DOI, arXiv ID, PMID 자동 인식
✅ **Citation Validation**: 유효하지 않은 citation 자동 감지
✅ **Reference List**: 자동 생성 및 포맷팅
✅ **Citation Statistics**: 인용 통계 및 분석

---

## 🚀 기본 사용법

### 1. Citation Tracker 초기화

```python
from neos.agents.search_agents.hyper_deep_research.utils import CitationTracker

# Citation tracker 생성
tracker = CitationTracker()
```

### 2. 소스 등록

```python
# 연구에서 수집한 소스 등록
sources = [
    {
        "url": "https://doi.org/10.1038/nature12345",
        "title": "Quantum Computing Advances",
        "author": "Smith, J.",
        "published_date": "2023-05-15",
        "score": 0.95
    },
    {
        "url": "https://arxiv.org/abs/2301.12345",
        "title": "Neural Network Optimization",
        "author": "Lee, S.",
        "published_date": "2023",
        "score": 0.90
    }
]

# 소스 등록 (각 소스에 번호 할당)
tracker.register_sources(sources)
# Output: Registered 2 sources. Total: 2
```

### 3. LLM Prompt에 소스 목록 포함

```python
# 프롬프트용 소스 목록 생성
source_list = tracker.get_source_list_for_prompt(max_sources=100)

print(source_list)
```

출력:
```
Available Sources for Citation:

[1] ⭐"Quantum Computing Advances" - nature.com (quality: 0.95)
[2] ⭐"Neural Network Optimization" - arxiv.org (quality: 0.90)
```

### 4. LLM 응답에서 Citation 파싱

```python
# LLM이 생성한 섹션 (inline citations 포함)
section_content = """
Quantum computers leverage superposition [1] and entanglement [2]
to achieve exponential speedup [1,2]. Recent advances have enabled
1,000-qubit systems [1], representing a 500% increase from 2020.
"""

# Citation 파싱
citation_contexts = tracker.parse_citations_from_text(
    section_content,
    section_title="Introduction"
)

# 파싱 결과
for ctx in citation_contexts:
    print(f"Claim: {ctx.claim}")
    print(f"Sources: {ctx.source_numbers}")
```

### 5. Reference List 생성

```python
# Reference list 생성 (인용된 소스만)
reference_list = tracker.generate_reference_list(
    style="numbered",  # or "apa", "chicago", "mla", "vancouver"
    only_cited=True
)

print(reference_list)
```

출력:
```markdown
## 📚 References

[1] Smith, J. "Quantum Computing Advances" - nature.com (2023-05-15) [DOI: 10.1038/nature12345] (cited 3x)
[2] Lee, S. "Neural Network Optimization" - arxiv.org (2023) [arXiv:2301.12345] (cited 2x)

**Total Sources: 2** (Cited: 2)
```

---

## 📖 고급 기능

### Multiple Citation Styles

다양한 학술 스타일 지원:

```python
# APA Style (심리학, 사회과학)
reference_apa = tracker.generate_reference_list(style="apa")

# Chicago Style (역사, 인문학)
reference_chicago = tracker.generate_reference_list(style="chicago")

# MLA Style (문학, 예술)
reference_mla = tracker.generate_reference_list(style="mla")

# Vancouver Style (의학, 생명과학)
reference_vancouver = tracker.generate_reference_list(style="vancouver")
```

**출력 예시 비교:**

**APA:**
```
[1] Smith, J. (2023). *Quantum Computing Advances*. nature.com. DOI: 10.1038/nature12345
```

**Chicago:**
```
[1] Smith, J. "Quantum Computing Advances." nature.com. 2023-05-15. DOI: 10.1038/nature12345
```

**MLA:**
```
[1] Smith, J. "Quantum Computing Advances." *nature.com*, 2023-05-15, DOI: 10.1038/nature12345.
```

**Vancouver:**
```
[1] Smith J. Quantum Computing Advances. nature.com. 2023. DOI: 10.1038/nature12345
```

---

### Academic Identifier 자동 인식

DOI, arXiv ID, PMID 등을 URL에서 자동으로 추출합니다.

```python
from neos.agents.search_agents.hyper_deep_research.utils import AcademicIdentifierExtractor

# URL에서 식별자 추출
identifiers = AcademicIdentifierExtractor.extract_from_url(
    "https://doi.org/10.1038/s41586-019-1666-5"
)

print(identifiers.doi)  # "10.1038/s41586-019-1666-5"
print(identifiers.publisher)  # "Nature"

# arXiv
identifiers = AcademicIdentifierExtractor.extract_from_url(
    "https://arxiv.org/abs/2301.12345"
)
print(identifiers.arxiv_id)  # "2301.12345"

# PubMed
identifiers = AcademicIdentifierExtractor.extract_from_url(
    "https://pubmed.ncbi.nlm.nih.gov/12345678/"
)
print(identifiers.pmid)  # "12345678"
```

---

### Citation Validation

잘못된 citation을 자동으로 감지합니다.

```python
# 검증
validation_result = tracker.validate_citations(section_content)

if not validation_result['valid']:
    print(f"Invalid citations found: {validation_result['invalid_citations']}")
    print(f"Coverage: {validation_result['coverage']:.1%}")
```

출력:
```python
{
    "valid": True,
    "total_citations": 5,
    "valid_citations": 5,
    "invalid_citations": [],
    "coverage": 1.0
}
```

---

### Citation Statistics

인용 통계 및 분석:

```python
stats = tracker.get_citation_statistics()

print(f"Total citations: {stats['total_citations']}")
print(f"Cited sources: {stats['cited_sources']}/{stats['total_sources']}")
print(f"Average citations per source: {stats['average_citations_per_source']:.2f}")

# Most cited sources
for source in stats['most_cited_sources'][:5]:
    print(f"[{source['number']}] {source['title']} (cited {source['cited_count']}x)")
```

출력:
```
Total citations: 245
Cited sources: 87/200
Average citations per source: 2.82

Most Cited Sources:
[1] Quantum Computing Advances (cited 15x)
[3] Machine Learning Fundamentals (cited 12x)
[5] Neural Network Architectures (cited 10x)
...
```

---

## 🎯 실제 사용 예시

### 전체 워크플로우

```python
from neos.agents.search_agents.hyper_deep_research import HyperDeepResearchAgent

# Agent 생성
agent = HyperDeepResearchAgent()

# 연구 실행 (소스 자동 수집 및 citation 추적)
result = await agent.execute(
    query="What are the latest advances in quantum computing?",
    context={
        "user_id": "user_123",
        "session_id": "session_456",
        "citation_style": "apa"  # Optional: APA, Chicago, MLA, Vancouver
    }
)

# Citation 통계 확인
citation_stats = agent.report_generator.citation_tracker.get_citation_statistics()
print(f"Research completed with {citation_stats['total_citations']} citations")
```

### 생성된 보고서 예시

```markdown
# Quantum Computing Advances

## Introduction

Quantum computing has emerged as a transformative technology with potential
to revolutionize computation [1,3,5]. Recent developments have demonstrated
quantum advantage in specific problem domains [2,7], with systems now
achieving over 1,000 qubits [4,9,12].

The field has seen exponential growth, with market size projected to reach
$500B by 2030 [15,18,21]. Key technological breakthroughs include improved
error correction [6,10] and enhanced qubit stability [8,11,14]...

---

## 📚 References

[1] Smith, J. (2023). *Quantum Computing: A New Era*. nature.com. DOI: 10.1038/nature12345 (cited 15x)
[2] Lee, S. (2023). *Quantum Advantage Demonstration*. arxiv.org. arXiv:2301.12345 (cited 12x)
[3] Johnson, A. (2023). *Quantum Algorithms*. science.org. DOI: 10.1126/science.abc123 (cited 10x)
...

**Total Sources: 150** (Cited: 87)

### 🔝 Most Cited Sources
1. [1] Quantum Computing: A New Era (cited 15x)
2. [2] Quantum Advantage Demonstration (cited 12x)
3. [3] Quantum Algorithms (cited 10x)
...
```

---

## ⚙️ Configuration

### Citation Style 설정

config.py에서 기본 citation style 설정:

```python
class ResearchConfig:
    citation_style: str = "numbered"  # or "apa", "chicago", "mla", "vancouver"
    citation_density: float = 0.3  # 평균 citation per sentence
    min_citations_per_section: int = 15
```

### ReportGenerator에서 사용

```python
# ReportGenerator에서 style 지정
reference_list = self.citation_tracker.generate_reference_list(
    style=config.citation_style,
    only_cited=True
)
```

---

## 📊 Citation Quality Best Practices

### High-Quality Citations

✅ **DO:**
- 모든 사실적 주장에 citation 추가
- 여러 소스로 중요한 주장 뒷받침 [1,3,5]
- 학술 소스 우선 사용 (⭐ 표시)
- DOI/arXiv ID 포함된 소스 선호

❌ **DON'T:**
- 일반적 지식에 불필요한 citation
- 존재하지 않는 번호 사용
- 단일 소스만으로 중요 주장 지지

### Citation Density 가이드

| 섹션 타입 | 권장 Citation 밀도 | 최소 Citations |
|----------|-----------------|----------------|
| Introduction | 낮음 (0.2/sentence) | 5-10 |
| Literature Review | 높음 (0.5/sentence) | 30-50 |
| Methods | 중간 (0.3/sentence) | 10-20 |
| Results | 높음 (0.4/sentence) | 20-40 |
| Discussion | 중간 (0.3/sentence) | 15-30 |

---

## 🐛 문제 해결

### Citation이 파싱되지 않는 경우

```python
# 문제: Citation 형식 불일치
bad_citation = "Reference 1"  # ❌
good_citation = "[1]"  # ✅

# 해결: 정규표현식 패턴 확인
CitationTracker.citation_pattern  # \[(\d+(?:,\s*\d+)*)\]
```

### 유효하지 않은 Citation 번호

```python
# 문제: 소스 목록에 없는 번호 사용
validation = tracker.validate_citations(text)
if not validation['valid']:
    print(f"Invalid: {validation['invalid_citations']}")
    # Fix: 소스 등록 또는 번호 수정
```

### Academic Identifier 인식 실패

```python
# 문제: 비표준 URL 형식
url = "https://custom-domain.com/article/12345"

# 해결: 텍스트에서 추출 시도
identifiers = AcademicIdentifierExtractor.extract_from_text(
    "DOI: 10.1234/example.5678"
)
```

---

## 🔄 Integration with Main Agent

agent.py에서 통합:

```python
# Phase 8: Final Report Generation
final_report = await self.report_generator.synthesize_final_report(
    topic_analysis=topic_analysis,
    methodology=methodology,
    deep_analysis=deep_analysis,
    validation=validation,
    critical_analysis=critical_analysis,
    session_id=session_id,
    user_id=user_id,
    language=language,
    report_id=report_id,
    metadata=self.research_metadata,
    all_sources=self.all_collected_sources  # ★ Citation tracking
)
```

---

## 📈 성능 고려사항

### 메모리 사용

- 소스 200개: ~10MB
- Citation contexts: ~1MB
- Total: ~11MB per research

### 처리 시간

- 소스 등록: O(n) - 200 sources in ~10ms
- Citation 파싱: O(m) - 1000 lines in ~50ms
- Reference list 생성: O(n) - 200 sources in ~20ms

### 최적화 팁

```python
# Tip 1: Limit sources in prompt
source_list = tracker.get_source_list_for_prompt(max_sources=100)

# Tip 2: Use only_cited for reference list
reference_list = tracker.generate_reference_list(only_cited=True)

# Tip 3: Clear tracker after each research
tracker.clear()
```

---

## 📚 추가 자료

- [APA Citation Guide](https://apastyle.apa.org/)
- [Chicago Manual of Style](https://www.chicagomanualofstyle.org/)
- [MLA Handbook](https://www.mla.org/MLA-Style)
- [DOI Handbook](https://www.doi.org/the-identifier/resources/handbook)

---

**Version**: 1.0
**Last Updated**: 2026-01-04
**Author**: HyperDeepResearch Team
