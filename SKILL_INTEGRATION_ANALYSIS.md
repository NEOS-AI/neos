# 스킬 통합 분석 및 구현 계획

## 현재 상태 분석

### ✅ 확인된 사항

#### 1. 새로운 스킬들이 제대로 등록됨
- **ArXiv Skill**: 학술 논문 검색 (물리학, 수학, CS, AI/ML)
- **PubMed Skill**: 의학/생물학 논문 검색
- **Wikipedia Skill**: 일반 지식 검색
- **Research Assistant Skill**: 기존 스킬 (소스 분석, 요약, 참고문헌 추출)

테스트 결과:
```
Total builtin skills: 7
Skills: ['bigquery', 'docx', 'pdf', 'research_assistant', 'arxiv', 'pubmed', 'wikipedia']

✓ ArXiv available: True
✓ PubMed available: True
✓ Wikipedia available: True
✓ Research Assistant available: True
```

#### 2. SkillBasedToolSelector 존재 확인
- **위치**: `neos/agents/skill_based_tool_selector.py`
- **기능**: LLM 기반 지능형 스킬 및 툴 선택
- **작동 방식**:
  1. 사용 가능한 스킬 목록을 가져옴 (`_get_available_skills()`)
  2. 쿼리와 컨텍스트를 LLM에게 전달
  3. LLM이 필요한 스킬만 선택
  4. `SkillToolSelection` 객체 반환 (selected_skills, selected_tools, reasoning, priority_order)

#### 3. HyperDeepResearchAgent에서의 활용
- **Phase 0**: Skill and Tool Selection
  - `skill_tool_selector.select_skills_and_tools()` 호출
  - 선택된 스킬들을 `self.selected_skills`에 저장
  - 선택 이유를 `self.selection_reasoning`에 저장

**코드 위치**: `neos/agents/search_agents/hyper_deep_research/agent.py:334-347`
```python
selection = await self.skill_tool_selector.select_skills_and_tools(
    query=query,
    context=selection_context,
    session_id=session_id,
    user_id=user_id,
    detected_language=language
)
self.selected_skills = selection.selected_skills
self.selected_tools = selection.selected_tools
```

### ⚠️ 발견된 문제점

#### 1. 선택된 스킬이 실제로 사용되지 않음

**현재 상황**:
- Phase 0에서 스킬 선택은 하지만
- **실제로 선택된 스킬을 사용하는 코드가 없음**
- Research Assistant 스킬만 하드코딩되어 사용됨 (line 1963-1972)

```python
# 현재 코드 (line 1963-1972)
if "research_assistant" in self.skill_manager.registry._skills:
    await self.skill_manager.initialize_skill("research_assistant")
    self.skills_enabled = True
```

**문제**:
- ArXiv, PubMed, Wikipedia 스킬이 선택되어도 사용되지 않음
- Tavily 웹 검색만 사용됨

#### 2. 도메인별 자동 스킬 선택 메커니즘 없음

**요구사항**:
- 과학/공학 관련 → ArXiv 필수
- 의학/생명/바이오 관련 → PubMed 필수

**현재 상황**:
- LLM이 선택하므로 **확률적**으로 선택됨
- **필수 선택을 보장하는 메커니즘 없음**

---

## 요구사항 분석

### 요구사항 1: 서브에이전트 스킬 선택 기능이 새 스킬들에도 유효하게 동작

**현재 달성 가능 여부**: ⚠️ **부분적으로 가능**

**이유**:
1. ✅ SkillBasedToolSelector는 새 스킬들을 볼 수 있음
2. ✅ LLM이 적절한 스킬을 선택할 수 있음
3. ❌ **선택된 스킬을 실제로 사용하는 코드가 없음**

**필요한 구현**:
- 선택된 스킬을 실제로 활용하는 로직 추가

### 요구사항 2: 딥리서치에서 도메인별 필수 스킬 활용

**현재 달성 가능 여부**: ❌ **불가능 (구현 필요)**

**이유**:
1. 현재는 LLM이 확률적으로 선택
2. 필수 스킬을 보장하는 메커니즘 없음
3. 도메인 감지 및 매핑 로직 없음

**필요한 구현**:
- 도메인 감지 로직
- 필수 스킬 매핑
- 스킬 사용 로직

---

## 구현 계획

### Phase 1: 선택된 스킬 실제 활용 (필수)

#### 1.1. HyperDeepResearchAgent에 스킬 사용 메서드 추가

**목표**: Phase 3 (Data Collection)에서 선택된 스킬들을 활용

**구현 위치**: `neos/agents/search_agents/hyper_deep_research/agent.py`

**새로운 메서드**:
```python
async def _collect_data_from_skills(
    self,
    query_variations: List[str],
    topic_analysis: Dict[str, Any],
    session_id: str,
    user_id: str,
    language: str
) -> List[Dict[str, Any]]:
    """Collect data using selected research skills (ArXiv, PubMed, Wikipedia)

    Returns:
        List of skill-based search results
    """
    skill_results = []

    # ArXiv skill usage
    if "arxiv" in self.selected_skills:
        arxiv_results = await self._search_with_arxiv(query_variations)
        skill_results.extend(arxiv_results)

    # PubMed skill usage
    if "pubmed" in self.selected_skills:
        pubmed_results = await self._search_with_pubmed(query_variations)
        skill_results.extend(pubmed_results)

    # Wikipedia skill usage
    if "wikipedia" in self.selected_skills:
        wikipedia_results = await self._search_with_wikipedia(query_variations)
        skill_results.extend(wikipedia_results)

    return skill_results
```

**개별 스킬 메서드**:
```python
async def _search_with_arxiv(self, queries: List[str]) -> List[Dict[str, Any]]:
    """Search ArXiv for academic papers"""
    results = []
    for query in queries[:5]:  # Limit to prevent overuse
        result = await self.skill_manager.execute_skill(
            "arxiv",
            {
                "action": "search",
                "query": query,
                "max_results": 5
            }
        )
        if result.success:
            # Convert to SearchResult format
            for paper in result.data.get("papers", []):
                results.append({
                    "title": paper["title"],
                    "content": paper["summary"],
                    "url": paper["entry_url"],
                    "score": 0.9,  # High quality academic source
                    "source": "arxiv"
                })
    return results

async def _search_with_pubmed(self, queries: List[str]) -> List[Dict[str, Any]]:
    """Search PubMed for medical papers"""
    # Similar implementation

async def _search_with_wikipedia(self, queries: List[str]) -> List[Dict[str, Any]]:
    """Search Wikipedia for background information"""
    # Similar implementation
```

**통합 위치**: `_collect_initial_data()` 메서드 (line 663)
```python
async def _collect_initial_data(...):
    # ... existing code ...

    # Add skill-based search
    if self.selected_skills:
        await self.event_logger.log_status_message(
            f"Collecting data from selected skills: {self.selected_skills}",
            "info"
        )
        skill_results = await self._collect_data_from_skills(
            query_variations, topic_analysis, session_id, user_id, language
        )
        all_results.extend(skill_results)

    # ... rest of existing code ...
```

---

### Phase 2: 도메인별 필수 스킬 보장 (필수)

#### 2.1. 도메인 감지 및 필수 스킬 추가 로직

**목표**: 주제 분석 결과를 바탕으로 필수 스킬 자동 추가

**구현 위치**: `HyperDeepResearchAgent._ensure_required_skills()` (새 메서드)

```python
async def _ensure_required_skills(
    self,
    topic_analysis: Dict[str, Any],
    selected_skills: List[str]
) -> List[str]:
    """Ensure domain-specific required skills are included

    Args:
        topic_analysis: Topic analysis result from Phase 1
        selected_skills: Skills selected by SkillBasedToolSelector

    Returns:
        Updated skills list with required skills
    """
    updated_skills = list(selected_skills)

    # Extract topic keywords and categories
    topic_text = topic_analysis.get("full_analysis", "").lower()
    key_aspects = topic_analysis.get("key_aspects", [])

    # Domain detection keywords
    science_engineering_keywords = [
        "ai", "ml", "machine learning", "deep learning", "neural network",
        "algorithm", "computer science", "physics", "mathematics",
        "engineering", "quantum", "robotics", "nlp", "computer vision",
        "transformer", "llm", "language model"
    ]

    medical_bio_keywords = [
        "medical", "medicine", "disease", "drug", "vaccine", "clinical",
        "patient", "treatment", "therapy", "diagnosis", "hospital",
        "biology", "biomedical", "gene", "protein", "cell", "cancer",
        "virus", "bacteria", "immune", "health", "pharmaceutical"
    ]

    # Check if science/engineering domain
    science_match = any(
        keyword in topic_text or
        any(keyword in aspect.lower() for aspect in key_aspects)
        for keyword in science_engineering_keywords
    )

    # Check if medical/bio domain
    medical_match = any(
        keyword in topic_text or
        any(keyword in aspect.lower() for aspect in key_aspects)
        for keyword in medical_bio_keywords
    )

    # Add required skills
    if science_match and "arxiv" not in updated_skills:
        updated_skills.append("arxiv")
        print("[INFO] 🎓 Science/Engineering topic detected → Adding ArXiv skill")

    if medical_match and "pubmed" not in updated_skills:
        updated_skills.append("pubmed")
        print("[INFO] 🏥 Medical/Bio topic detected → Adding PubMed skill")

    # Always add Wikipedia for background knowledge
    if "wikipedia" not in updated_skills:
        updated_skills.append("wikipedia")
        print("[INFO] 📚 Adding Wikipedia skill for background knowledge")

    return updated_skills
```

**통합 위치**: Phase 1 이후, Phase 2 이전

```python
# After Phase 1: Topic Analysis (line 376)
# Before Phase 2: Research Planning (line 391)

# Ensure required skills based on topic domain
print("\n[INFO] 🎯 Ensuring required skills for topic domain...")
self.selected_skills = await self._ensure_required_skills(
    topic_analysis, self.selected_skills
)
print(f"[INFO] ✅ Final skills: {self.selected_skills}")

# Initialize selected skills
for skill_name in self.selected_skills:
    await self.skill_manager.initialize_skill(skill_name)
```

---

### Phase 3: 스킬 초기화 로직 개선 (권장)

**현재 문제**:
- Research Assistant만 하드코딩되어 초기화

**개선안**:
```python
async def _initialize_selected_skills(self):
    """Initialize all selected skills"""
    try:
        for skill_name in self.selected_skills:
            if skill_name in self.skill_manager.registry._skills:
                success = await self.skill_manager.initialize_skill(skill_name)
                if success:
                    print(f"[INFO] ✅ {skill_name} skill initialized")
                else:
                    print(f"[WARNING] ❌ {skill_name} skill initialization failed")
    except Exception as e:
        print(f"[WARNING] Failed to initialize skills: {e}")
```

---

## 구현 우선순위

### 🔴 필수 (HIGH)
1. **Phase 1**: 선택된 스킬 실제 활용
   - `_collect_data_from_skills()` 구현
   - `_search_with_arxiv()`, `_search_with_pubmed()`, `_search_with_wikipedia()` 구현
   - `_collect_initial_data()`에 통합

2. **Phase 2**: 도메인별 필수 스킬 보장
   - `_ensure_required_skills()` 구현
   - 도메인 감지 로직
   - Phase 1 이후에 통합

### 🟡 권장 (MEDIUM)
3. **Phase 3**: 스킬 초기화 로직 개선
   - `_initialize_selected_skills()` 구현
   - 기존 하드코딩 제거

### 🟢 선택 (LOW)
4. 스킬 결과 품질 평가 및 가중치
5. 스킬 결과 캐싱 (중복 쿼리 방지)
6. 에러 핸들링 및 폴백 메커니즘

---

## 예상 결과

### 구현 전 (현재)
```
Query: "Explain the latest advances in transformers for NLP"

Phase 0: Skill Selection
  → Selected: ["research_assistant"]  # LLM이 선택했지만...

Phase 3: Data Collection
  → Tavily 웹 검색만 사용
  → ArXiv 논문 검색 없음 ❌
```

### 구현 후 (개선)
```
Query: "Explain the latest advances in transformers for NLP"

Phase 0: Skill Selection
  → Selected by LLM: ["research_assistant"]

Phase 1: Topic Analysis
  → Topic: "Transformers for NLP" (Science/Engineering)
  → Domain Detection: ✅ Computer Science/AI detected
  → Required Skills Added: ["arxiv", "wikipedia"]
  → Final Skills: ["research_assistant", "arxiv", "wikipedia"]

Phase 3: Data Collection
  → Tavily 웹 검색: 20개 쿼리
  → ArXiv 논문 검색: 5개 쿼리 (25개 논문) ✅
  → Wikipedia 배경 검색: 3개 쿼리 ✅
  → 총 소스: 150+ (학술 논문 포함)
```

```
Query: "What are the latest COVID-19 vaccine findings?"

Phase 0: Skill Selection
  → Selected by LLM: ["research_assistant"]

Phase 1: Topic Analysis
  → Topic: "COVID-19 vaccine"
  → Domain Detection: ✅ Medical/Health detected
  → Required Skills Added: ["pubmed", "wikipedia"]
  → Final Skills: ["research_assistant", "pubmed", "wikipedia"]

Phase 3: Data Collection
  → Tavily 웹 검색: 20개 쿼리
  → PubMed 의학 논문 검색: 5개 쿼리 (25개 논문) ✅
  → Wikipedia 배경 검색: 3개 쿼리 ✅
  → 총 소스: 150+ (의학 논문 포함)
```

---

## 결론

### 요구사항 달성 여부

#### ✅ 요구사항 1: 서브에이전트 스킬 선택 기능
**현재 상태**: 부분적으로 작동 (선택은 되지만 사용 안됨)
**필요 구현**: Phase 1 (선택된 스킬 실제 활용)
**달성 가능**: ✅ **가능** (구현 필요)

#### ✅ 요구사항 2: 도메인별 필수 스킬 활용
**현재 상태**: 불가능
**필요 구현**: Phase 2 (도메인별 필수 스킬 보장)
**달성 가능**: ✅ **가능** (구현 필요)

### 추가 구현 필요 사항

**필수**:
1. Phase 1: 선택된 스킬 실제 활용 로직 (`_collect_data_from_skills()` 등)
2. Phase 2: 도메인 감지 및 필수 스킬 추가 로직 (`_ensure_required_skills()`)

**권장**:
3. Phase 3: 스킬 초기화 로직 개선 (`_initialize_selected_skills()`)

### 구현 순서

```
1. Phase 1 구현 (선택된 스킬 활용)
   ↓
2. Phase 2 구현 (필수 스킬 보장)
   ↓
3. Phase 3 구현 (초기화 로직 개선)
   ↓
4. 테스트 및 검증
   ↓
5. 커밋 및 푸시
```

---

## 다음 단계

구현을 진행하시겠습니까?

1. **Phase 1 + Phase 2 구현** (필수 기능만)
2. **Phase 1 + Phase 2 + Phase 3 구현** (모든 개선사항)
3. **분석 내용만 확인** (구현은 나중에)
