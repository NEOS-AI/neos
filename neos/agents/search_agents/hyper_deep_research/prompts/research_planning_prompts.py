"""Research planning prompt templates for HyperDeepResearch."""

from typing import Dict


class ResearchPlanningPrompts:
   """Prompts for advanced research methodology planning."""

   @staticmethod
   def get_prompt(topic_analysis_text: str, language: str = "en") -> str:
      """Get research planning prompt in the specified language.

      Args:
         topic_analysis_text: Previous topic analysis result
         language: Target language code ('en', 'ko', 'ja')

      Returns:
         Formatted prompt string
      """
      prompts: Dict[str, str] = {
         "ko": f"""다음 주제 분석을 바탕으로 포괄적인 연구 계획을 수립해주세요:

주제 분석:
{topic_analysis_text[:1500]}

다음을 모두 포함한 상세한 연구 계획을 작성해주세요:

1. **연구 방법론**
   - 탐색적 조사 (Exploratory Research)
   - 설명적 조사 (Descriptive Research)
   - 인과적 조사 (Causal Research)
   - 각 방법론의 적용 영역

2. **이론적 프레임워크**
   - 관련 이론 및 모델
   - 분석 프레임워크
   - 평가 기준

3. **다층 조사 전략**
   - Layer 1: 기본 정보 수집 (정의, 개념, 현황)
   - Layer 2: 심층 분석 (메커니즘, 원인, 영향)
   - Layer 3: 비교 분석 (사례, 대안, 국제 비교)
   - Layer 4: 미래 전망 (트렌드, 예측, 시나리오)

4. **데이터 수집 계획**
   - 1차 데이터 유형: 통계, 사례, 전문가 의견
   - 2차 데이터 유형: 학술 논문, 산업 보고서, 뉴스
   - 검색 키워드 전략 (20개 이상)
   - 소스 다양화 전략

5. **품질 관리 전략**
   - 소스 신뢰성 평가 기준
   - 교차 검증 방법
   - 편향 방지 전략

매우 상세하고 실행 가능한 계획을 한국어로 작성해주세요.""",

            "en": f"""Based on the following topic analysis, create a comprehensive research plan:

Topic Analysis:
{topic_analysis_text[:1500]}

Create a detailed research plan including:

1. **Research Methodology**
   - Exploratory Research
   - Descriptive Research
   - Causal Research
   - Application areas for each

2. **Theoretical Framework**
   - Relevant theories and models
   - Analytical frameworks
   - Evaluation criteria

3. **Multi-Layer Investigation Strategy**
   - Layer 1: Basic information (definitions, concepts, status)
   - Layer 2: Deep analysis (mechanisms, causes, impacts)
   - Layer 3: Comparative analysis (cases, alternatives, international comparison)
   - Layer 4: Future outlook (trends, predictions, scenarios)

4. **Data Collection Plan**
   - Primary data types: statistics, cases, expert opinions
   - Secondary data types: academic papers, industry reports, news
   - Search keyword strategy (20+ keywords)
   - Source diversification strategy

5. **Quality Control Strategy**
   - Source credibility criteria
   - Cross-validation methods
   - Bias prevention strategies

Write a very detailed and actionable plan in English.""",

            "ja": f"""以下のテーマ分析に基づいて、包括的な研究計画を作成してください:

テーマ分析:
{topic_analysis_text[:1500]}

以下を含む詳細な研究計画を作成してください:

1. **研究方法論**
   - 探索的調査 (Exploratory Research)
   - 記述的調査 (Descriptive Research)
   - 因果的調査 (Causal Research)
   - 各方法論の適用領域

2. **理論的フレームワーク**
   - 関連理論とモデル
   - 分析フレームワーク
   - 評価基準

3. **多層調査戦略**
   - Layer 1: 基本情報収集（定義、概念、現状）
   - Layer 2: 詳細分析（メカニズム、原因、影響）
   - Layer 3: 比較分析（事例、代替案、国際比較）
   - Layer 4: 将来展望（トレンド、予測、シナリオ）

4. **データ収集計画**
   - 1次データタイプ: 統計、事例、専門家意見
   - 2次データタイプ: 学術論文、産業レポート、ニュース
   - 検索キーワード戦略(20個以上)
   - ソース多様化戦略

5. **品質管理戦略**
   - ソース信頼性評価基準
   - クロス検証方法
   - バイアス防止戦略

非常に詳細で実行可能な計画を日本語で作成してください。"""
      }

      return prompts.get(language, prompts["en"])
