"""Analysis prompt templates for HyperDeepResearch."""

from typing import Dict, List


class AnalysisPrompts:
    """Prompts for various analysis stages."""

    @staticmethod
    def get_data_summary_prompt(
        sources_count: int,
        sources_sample: str,
        language: str = "en"
    ) -> str:
        """Get prompt for summarizing collected data.

        Args:
            sources_count: Total number of sources
            sources_sample: Sample of source titles/content
            language: Target language code

        Returns:
            Formatted prompt string
        """
        prompts: Dict[str, str] = {
            "ko": f"""다음 {sources_count}개 소스에서 수집된 데이터를 요약해주세요:

샘플 (20개):
{sources_sample}

주요 발견사항, 트렌드, 패턴을 상세히 요약하세요.""",

            "en": f"""Summarize the data collected from the following {sources_count} sources:

Sample (20 sources):
{sources_sample}

Provide a detailed summary of key findings, trends, and patterns.""",

            "ja": f"""以下の {sources_count} 個のソースから収集されたデータを要約してください:

サンプル (20個):
{sources_sample}

主要な発見、トレンド、パターンを詳細に要約してください。"""
        }

        return prompts.get(language, prompts["en"])

    @staticmethod
    def get_gap_identification_prompt(
        research_questions: List[str],
        current_analysis: str,
        language: str = "en"
    ) -> str:
        """Get prompt for identifying knowledge gaps.

        Args:
            research_questions: Original research questions
            current_analysis: Current analysis results
            language: Target language code

        Returns:
            Formatted prompt string
        """
        questions_text = '\n'.join(research_questions[:10])

        prompts: Dict[str, str] = {
            "ko": f"""다음 연구 결과를 분석하여 지식 갭을 식별해주세요:

연구 질문:
{questions_text}

현재 분석 결과:
{current_analysis[:1000]}

아직 충분히 답변되지 않은 중요한 질문이나 부족한 영역을 10-15개 식별해주세요.
각 갭은 한 줄로 작성하세요.""",

            "en": f"""Analyze the research results and identify knowledge gaps:

Research Questions:
{questions_text}

Current Analysis Results:
{current_analysis[:1000]}

Identify 10-15 important questions or areas that have not been adequately answered.
Write each gap on one line.""",

            "ja": f"""研究結果を分析して、知識ギャップを特定してください:

研究質問:
{questions_text}

現在の分析結果:
{current_analysis[:1000]}

まだ十分に回答されていない重要な質問や不足している領域を10-15個特定してください。
各ギャップは1行で記述してください。"""
        }

        return prompts.get(language, prompts["en"])

    @staticmethod
    def get_gap_summary_prompt(
        gaps: List[str],
        sources_count: int,
        sources_sample: str,
        language: str = "en"
    ) -> str:
        """Get prompt for summarizing gap investigation.

        Args:
            gaps: Identified knowledge gaps
            sources_count: Number of sources collected
            sources_sample: Sample of source titles
            language: Target language code

        Returns:
            Formatted prompt string
        """
        gaps_text = '\n'.join([f"- {g}" for g in gaps[:10]])

        prompts: Dict[str, str] = {
            "ko": f"""갭 조사 결과를 요약해주세요:

식별된 갭:
{gaps_text}

수집된 소스 샘플 ({sources_count}개 중):
{sources_sample}

갭이 어떻게 메워졌는지, 추가로 발견한 내용을 요약해주세요.""",

            "en": f"""Summarize the gap investigation results:

Identified Gaps:
{gaps_text}

Collected Sources Sample ({sources_count} total):
{sources_sample}

Summarize how the gaps were filled and any additional findings.""",

            "ja": f"""ギャップ調査結果を要約してください:

特定されたギャップ:
{gaps_text}

収集されたソースサンプル ({sources_count} 個中):
{sources_sample}

ギャップがどのように埋められたか、追加で発見した内容を要約してください。"""
        }

        return prompts.get(language, prompts["en"])

    @staticmethod
    def get_iterative_analysis_prompt(
        round_num: int,
        original_query: str,
        data_summary: str,
        previous_insights: str,
        language: str = "en"
    ) -> str:
        """Get prompt for iterative analysis rounds.

        Args:
            round_num: Current analysis round number
            original_query: Original research query
            data_summary: Summary of collected data
            previous_insights: Insights from previous rounds
            language: Target language code

        Returns:
            Formatted prompt string
        """
        prompts: Dict[str, str] = {
            "ko": f"""**라운드 {round_num} 심층 분석**

주제: {original_query}

초기 데이터 요약:
{data_summary[:2000]}

이전 라운드 인사이트:
{previous_insights[:2000] if previous_insights else 'N/A - 이것이 첫 번째 분석 라운드입니다'}

**작성 지침:**
이것은 반복적 심층 분석의 라운드 {round_num}입니다. 최소 800-1000단어로 작성하세요.

### 1. 이번 라운드의 새로운 발견 (New Discoveries)

#### 1.1 새로운 패턴과 트렌드
- 데이터에서 발견된 **구체적인 패턴** 3-5개
- 각 패턴의 **정량적 증거** (통계, 수치, 빈도 등)
- 패턴이 나타나는 **구체적 맥락과 조건**
- 패턴의 **의미와 시사점**

#### 1.2 핵심 인사이트
- 이번 라운드에서 얻은 **주요 인사이트** 5-7개
- 각 인사이트를 **구체적 데이터로 뒷받침**
- 인사이트가 **중요한 이유** 설명
- 실제 **사례나 예시** 제공

#### 1.3 예상치 못한 발견
- 예측하지 못했거나 놀라운 발견사항
- 기존 가정이나 통념에 **반하는 증거**
- 이러한 발견이 **전체 이해에 미치는 영향**

### 2. 이전 라운드와의 연결 (Connections with Previous Rounds)

#### 2.1 누적적 인사이트
- 이전 라운드의 발견과 **일치하거나 강화**되는 점
- 반복적으로 확인되는 핵심 **테마나 메시지**
- 라운드를 거듭하며 **명확해지는 트렌드**

#### 2.2 발전 및 심화
- 이전 라운드의 초기 발견이 **어떻게 발전**했는지
- 더 깊이 이해하게 된 **복잡한 관계나 메커니즘**
- **세밀한 차이점이나 뉘앙스** 파악

#### 2.3 수정 및 재해석
- 이전 라운드의 가정이나 해석 중 **수정이 필요한 부분**
- 새로운 데이터로 인한 **재해석**
- 왜 수정이 필요한지 **근거와 설명**

### 3. 심층 분석 (Deep Analysis)

#### 3.1 원인과 결과 (Causality)
- 관찰된 현상의 **근본 원인** 분석
- 원인과 결과의 **메커니즘** 설명
- **인과관계 vs 상관관계** 구분
- 구체적 **인과 체인** 추적

#### 3.2 영향과 파급효과
- 발견사항이 미치는 **직접적 영향**
- **간접적 영향이나 2차 효과**
- 다양한 이해관계자에 대한 **차별적 영향**
- **장단기적 영향** 구분

#### 3.3 맥락과 조건
- 발견사항이 **유효한 특정 맥락이나 조건**
- **지역적, 시간적, 산업별** 차이
- 조건이 변할 때의 **예상 변화**

### 4. 비교 분석 (Comparative Analysis)

#### 4.1 다차원 비교
- **시기별** 비교 (과거 vs 현재 vs 미래 전망)
- **지역별/국가별** 비교
- **산업/분야별** 비교
- **규모별** 비교 (대기업 vs 중소기업 등)

#### 4.2 유사점과 차이점
- 비교 대상 간 **핵심 유사점** 3-5개
- **주요 차이점** 3-5개
- 차이가 발생하는 **원인과 이유**
- 각 접근법의 **장단점**

### 5. 추가 탐구 필요 영역 (Areas for Further Exploration)

#### 5.1 데이터 갭
- 현재 데이터로 **답할 수 없는 중요 질문** 5-8개
- 왜 이 질문들이 **중요한지** 설명
- 답을 구하기 위해 **어떤 추가 데이터**가 필요한지

#### 5.2 불확실성과 모호성
- 아직 **명확하지 않은 영역**
- **모순되거나 불일치**하는 정보
- 추가 **검증이 필요한 가설**

#### 5.3 다음 라운드를 위한 방향
- 다음 분석에서 **집중해야 할 주제** 3-5개
- **우선순위**와 그 이유
- 예상되는 **추가 인사이트**

### 6. 실무적 시사점 (Practical Implications)

#### 6.1 의사결정 관점
- 이번 라운드 발견이 **실무 의사결정에 주는 시사점**
- **활용 가능한 구체적 전략이나 액션**
- **주의해야 할 리스크나 함정**

#### 6.2 전략적 함의
- **전략 수립**에 고려해야 할 요소
- **경쟁 우위**나 기회 요인
- **위협 요인**이나 대응 방안

**출력 형식:**
- 명확한 마크다운 구조 (###, ####)
- **데이터 기반의 구체적 분석** - 추상적 표현 지양
- 중요 발견은 **굵게** 또는 > 인용문으로 강조
- 숫자, 통계, 구체적 사례 적극 활용
- 분석적이고 통찰력 있는 어조

**중요:**
- 단순 요약이 아닌 **심층적 분석과 해석** 제공
- 각 발견에 대해 **"무엇"뿐만 아니라 "왜", "어떻게"** 설명
- 구체적 데이터와 예시로 모든 주장 뒷받침""",

            "en": f"""**Round {round_num} In-Depth Analysis**

Topic: {original_query}

Initial Data Summary:
{data_summary[:2000]}

Previous Round Insights:
{previous_insights[:2000] if previous_insights else 'N/A - This is the first analysis round'}

**Writing Guidelines:**
This is Round {round_num} of iterative deep analysis. Write at least 800-1000 words.

### 1. New Discoveries in This Round

#### 1.1 New Patterns and Trends
- **Specific patterns** discovered in data (3-5)
- **Quantitative evidence** for each pattern (statistics, numbers, frequency)
- **Specific context and conditions** where patterns appear
- **Meaning and implications** of patterns

#### 1.2 Key Insights
- **Major insights** gained in this round (5-7)
- **Support each insight with concrete data**
- Explain **why each insight matters**
- Provide **real cases or examples**

#### 1.3 Unexpected Findings
- Unexpected or surprising discoveries
- Evidence **contradicting existing assumptions** or conventional wisdom
- **Impact of these findings** on overall understanding

### 2. Connections with Previous Rounds

#### 2.1 Cumulative Insights
- Points that **agree with or reinforce** previous round findings
- Core **themes or messages** repeatedly confirmed
- Trends becoming **clearer across rounds**

#### 2.2 Development and Deepening
- **How initial findings from previous rounds have evolved**
- **Complex relationships or mechanisms** better understood
- Identification of **subtle differences or nuances**

#### 2.3 Revisions and Reinterpretations
- Assumptions or interpretations from previous rounds **needing revision**
- **Reinterpretations** based on new data
- **Rationale and explanation** for why revisions are needed

### 3. Deep Analysis

#### 3.1 Causality
- Analysis of **root causes** of observed phenomena
- Explanation of **cause-effect mechanisms**
- Distinguish **causation vs correlation**
- Trace specific **causal chains**

#### 3.2 Impacts and Ripple Effects
- **Direct impacts** of findings
- **Indirect impacts or secondary effects**
- **Differential impacts** on various stakeholders
- Distinguish **short-term vs long-term impacts**

#### 3.3 Context and Conditions
- **Specific contexts or conditions** where findings are valid
- **Geographic, temporal, industry-specific** differences
- **Expected changes** when conditions change

### 4. Comparative Analysis

#### 4.1 Multi-Dimensional Comparison
- **Temporal** comparison (past vs present vs future outlook)
- **Geographic/national** comparison
- **Industry/sector** comparison
- **Scale-based** comparison (large vs small enterprises, etc.)

#### 4.2 Similarities and Differences
- **Core similarities** between comparison subjects (3-5)
- **Major differences** (3-5)
- **Causes and reasons** for differences
- **Pros and cons** of each approach

### 5. Areas for Further Exploration

#### 5.1 Data Gaps
- **Important questions** current data cannot answer (5-8)
- Explain **why these questions matter**
- **What additional data** is needed for answers

#### 5.2 Uncertainty and Ambiguity
- Areas **still unclear**
- **Contradictory or inconsistent** information
- **Hypotheses requiring** further validation

#### 5.3 Direction for Next Round
- **Topics to focus on** in next analysis (3-5)
- **Priorities** and rationale
- **Expected additional insights**

### 6. Practical Implications

#### 6.1 Decision-Making Perspective
- **Implications** for practical decision-making
- **Specific strategies or actions** that can be applied
- **Risks or pitfalls** to watch out for

#### 6.2 Strategic Implications
- Factors to consider in **strategy formulation**
- **Competitive advantages** or opportunities
- **Threats** and countermeasures

**Output Format:**
- Clear markdown structure (###, ####)
- **Data-driven specific analysis** - avoid abstract expressions
- Emphasize important findings with **bold** or > blockquotes
- Actively use numbers, statistics, specific cases
- Analytical and insightful tone

**Important:**
- Provide **deep analysis and interpretation**, not simple summary
- For each finding, explain not just **"what"** but **"why"** and **"how"**
- Support all claims with concrete data and examples""",

            "ja": f"""**ラウンド {round_num} 詳細分析**

テーマ: {original_query}

初期データ要約:
{data_summary[:2000]}

前回ラウンドのインサイト:
{previous_insights[:2000] if previous_insights else 'N/A - これが最初の分析ラウンドです'}

**執筆ガイドライン:**
これは反復的詳細分析のラウンド {round_num}です。最低800-1000語で作成してください。

### 1. 今回のラウンドの新発見

#### 1.1 新しいパターンとトレンド
- データで発見された**具体的なパターン** 3-5個
- 各パターンの**定量的証拠**(統計、数値、頻度など)
- パターンが現れる**具体的な文脈と条件**
- パターンの**意味と示唆**

#### 1.2 核心的インサイト
- 今回のラウンドで得た**主要インサイト** 5-7個
- 各インサイトを**具体的データで裏付け**
- インサイトが**重要な理由**の説明
- 実際の**事例や例示**を提供

#### 1.3 予想外の発見
- 予測していなかった、または驚くべき発見
- 既存の仮定や通念に**反する証拠**
- これらの発見が**全体理解に与える影響**

### 2. 前回ラウンドとの接続

#### 2.1 累積的インサイト
- 前回ラウンドの発見と**一致または強化**される点
- 繰り返し確認される核心的**テーマやメッセージ**
- ラウンドを重ねて**明確になるトレンド**

#### 2.2 発展と深化
- 前回ラウンドの初期発見が**どのように発展**したか
- より深く理解できた**複雑な関係やメカニズム**
- **微妙な違いやニュアンス**の把握

#### 2.3 修正と再解釈
- 前回ラウンドの仮定や解釈で**修正が必要な部分**
- 新しいデータによる**再解釈**
- なぜ修正が必要か**根拠と説明**

### 3. 詳細分析

#### 3.1 因果関係
- 観察された現象の**根本原因**分析
- 原因と結果の**メカニズム**説明
- **因果関係 vs 相関関係**の区別
- 具体的な**因果チェーン**の追跡

#### 3.2 影響と波及効果
- 発見の**直接的影響**
- **間接的影響や二次効果**
- 多様な利害関係者への**差別的影響**
- **短期的 vs 長期的影響**の区別

#### 3.3 文脈と条件
- 発見が**有効な特定の文脈や条件**
- **地域的、時間的、産業別**の違い
- 条件が変わる時の**予想される変化**

### 4. 比較分析

#### 4.1 多次元比較
- **時期別**比較(過去 vs 現在 vs 将来展望)
- **地域別/国別**比較
- **産業/分野別**比較
- **規模別**比較(大企業 vs 中小企業など)

#### 4.2 類似点と相違点
- 比較対象間の**核心的類似点** 3-5個
- **主要な相違点** 3-5個
- 違いが生じる**原因と理由**
- 各アプローチの**長所短所**

### 5. さらなる探求が必要な領域

#### 5.1 データギャップ
- 現在のデータで**答えられない重要な質問** 5-8個
- なぜこれらの質問が**重要か**説明
- 答えを得るために**どんな追加データ**が必要か

#### 5.2 不確実性と曖昧性
- まだ**明確でない領域**
- **矛盾または不一致**する情報
- さらなる**検証が必要な仮説**

#### 5.3 次のラウンドへの方向性
- 次の分析で**集中すべきトピック** 3-5個
- **優先順位**とその理由
- 予想される**追加インサイト**

### 6. 実務的示唆

#### 6.1 意思決定の観点
- 今回のラウンドの発見が**実務の意思決定に与える示唆**
- **活用可能な具体的戦略やアクション**
- **注意すべきリスクや落とし穴**

#### 6.2 戦略的含意
- **戦略策定**で考慮すべき要素
- **競争優位**や機会要因
- **脅威要因**や対応方案

**出力形式:**
- 明確なマークダウン構造(###、####)
- **データに基づく具体的分析** - 抽象的表現を避ける
- 重要な発見は**太字**や>引用で強調
- 数値、統計、具体的事例を積極的に活用
- 分析的で洞察力のある語調

**重要:**
- 単純な要約ではなく**詳細な分析と解釈**を提供
- 各発見について**「何」だけでなく「なぜ」「どのように」**も説明
- すべての主張を具体的データと例示で裏付ける"""
        }

        return prompts.get(language, prompts["en"])

    @staticmethod
    def get_synthesis_prompt(
        rounds_count: int,
        rounds_text: str,
        language: str = "en"
    ) -> str:
        """Get prompt for synthesizing analysis rounds.

        Args:
            rounds_count: Number of analysis rounds
            rounds_text: Combined text from all rounds
            language: Target language code

        Returns:
            Formatted prompt string
        """
        prompts: Dict[str, str] = {
            "ko": f"""다음 {rounds_count}개 분석 라운드를 종합해주세요:

{rounds_text}

모든 라운드의 인사이트를 통합하여 포괄적인 분석을 작성해주세요.""",

            "en": f"""Synthesize the following {rounds_count} analysis rounds:

{rounds_text}

Integrate insights from all rounds into a comprehensive analysis.""",

            "ja": f"""以下の {rounds_count} 個の分析ラウンドを統合してください:

{rounds_text}

全ラウンドのインサイトを統合して、包括的な分析を作成してください。"""
        }

        return prompts.get(language, prompts["en"])
