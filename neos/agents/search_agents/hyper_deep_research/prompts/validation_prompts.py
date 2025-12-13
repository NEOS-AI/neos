"""Validation and critical analysis prompt templates."""

from typing import Dict


class ValidationPrompts:
   """Prompts for cross-validation and critical thinking."""

   @staticmethod
   def get_cross_validation_prompt(
      sources_count: int,
      sources_text: str,
      language: str = "en"
   ) -> str:
      """Get cross-validation prompt.

      Args:
         sources_count: Number of sources to validate
         sources_text: Sample of sources content
         language: Target language code

      Returns:
         Formatted prompt string
      """
      prompts: Dict[str, str] = {
         "ko": f"""다음 {sources_count}개의 소스를 **전문적이고 체계적으로** 교차 검증하고 삼각측량(Triangulation)을 수행해주세요:

{sources_text}

**작성 지침:**
이것은 연구 보고서의 중요한 검증 섹션입니다. 최소 600-800단어로 작성하세요.

다음을 **구체적이고 상세하게** 분석해주세요:

### 1. 일관성 분석 (Consistency Analysis)

#### 1.1 핵심 사실 확인
- 여러 소스(3개 이상)에서 일관되게 확인되는 핵심 사실을 **구체적으로** 나열
- 각 사실에 대해 어떤 소스들이 확인했는지 명시
- 일치도 수준 (완전 일치, 부분 일치, 유사 일치) 표시
- 예시: "5개 소스에서 공통적으로 확인된 사실: [구체적 내용]"

#### 1.2 신뢰도 높은 정보
- 복수의 독립적 소스에서 검증된 정보 목록
- 각 정보의 신뢰도 근거 설명
- 데이터의 일치성 정도 (정량적 표현)

### 2. 불일치 분석 (Discrepancy Analysis)

#### 2.1 상충 정보 식별
- 소스 간 상충되는 정보를 **구체적으로** 기술
- 각 불일치 사항에 대한 상세한 비교
- 수치나 주장이 다른 경우, 정확한 차이 명시

#### 2.2 불일치 원인 분석
- 시간적 차이: 데이터 수집 시점의 차이
- 관점의 차이: 분석 프레임워크나 접근법의 차이
- 방법론적 차이: 조사 방법, 샘플링 등의 차이
- 데이터 출처 차이: 1차/2차 자료, 지역별 차이
- 각 원인에 대한 구체적 설명과 예시

### 3. 정보 품질 평가 (Source Quality Assessment)

#### 3.1 고품질 소스 (Tier 1)
- 학술 논문, 공식 기관, 정부 보고서
- 각 소스의 구체적 평가 (저자, 기관, 출판 연도)
- 왜 신뢰할 수 있는지 근거 제시

#### 3.2 중간 품질 소스 (Tier 2)
- 뉴스 매체, 산업 보고서, 전문가 인터뷰
- 편향성이나 제한사항 분석
- 신뢰도와 활용 시 주의점

#### 3.3 주의 필요 소스 (Tier 3)
- 의견 기사, 블로그, SNS 등
- 어떤 부분을 주의해야 하는지 구체적 지적
- 부분적 활용 가능성 검토

### 4. 삼각측량 결과 (Triangulation Results)

#### 4.1 교차 확인된 핵심 발견사항
- 다양한 독립적 소스에서 확인된 사항 (10-15개)
- 각 발견사항마다 확인된 소스 수와 유형 명시
- 발견사항의 중요도와 신뢰도 평가

#### 4.2 단일 소스 정보
- 한 곳에서만 확인된 중요 정보 목록
- 추가 검증이 필요한 이유
- 잠재적 가치와 위험성 평가

#### 4.3 소스 간 보완 관계
- 서로 다른 소스들이 어떻게 보완적 정보를 제공하는지
- 종합적으로 어떤 그림이 그려지는지

### 5. 신뢰도 매트릭스 (Reliability Matrix)

#### 5.1 높은 신뢰도 정보 (>80%)
- 구체적 정보 항목과 확인 소스 수
- 신뢰도 점수와 근거

#### 5.2 중간 신뢰도 정보 (50-80%)
- 부분적으로 확인된 정보
- 추가 검증이 필요한 영역

#### 5.3 낮은 신뢰도 정보 (<50%)
- 단일 소스 또는 모순된 정보
- 활용 시 주의사항

### 6. 종합 평가 및 권고사항

#### 6.1 전체 데이터 품질 평가
- 수집된 소스의 전반적 신뢰도
- 데이터 커버리지의 완성도
- 주요 강점과 약점

#### 6.2 추가 검증 필요 영역
- 더 많은 소스가 필요한 주제
- 상충되는 정보에 대한 해결 방안

**출력 형식:**
- 마크다운 헤딩(###, ####)으로 명확히 구조화
- 중요 발견사항은 **굵게** 또는 > 인용문으로 강조
- 구체적 수치와 예시 포함
- 표나 목록을 활용하여 가독성 향상

**중요:** 단순 나열이 아닌, 각 항목에 대한 **심층적 분석과 해석**을 포함하세요.""",

            "en": f"""Perform **professional and systematic** cross-validation and triangulation on the following {sources_count} sources:

{sources_text}

**Writing Guidelines:**
This is a critical validation section of the research report. Write at least 600-800 words.

Analyze the following **specifically and in detail**:

### 1. Consistency Analysis

#### 1.1 Core Fact Verification
- **Specifically** list core facts consistently confirmed across multiple sources (3+)
- Indicate which sources confirmed each fact
- Show agreement level (complete match, partial match, similar match)
- Example: "Fact confirmed by 5 sources: [specific content]"

#### 1.2 High-Confidence Information
- List of information verified by multiple independent sources
- Explain the basis for each information's reliability
- Degree of data consistency (quantitative expression)

### 2. Discrepancy Analysis

#### 2.1 Identifying Conflicting Information
- **Specifically** describe conflicting information between sources
- Detailed comparison for each discrepancy
- When numbers or claims differ, specify exact differences

#### 2.2 Analyzing Causes of Discrepancies
- Temporal differences: Differences in data collection timing
- Perspective differences: Differences in analytical frameworks or approaches
- Methodological differences: Differences in research methods, sampling, etc.
- Data source differences: Primary/secondary sources, regional differences
- Specific explanations and examples for each cause

### 3. Source Quality Assessment

#### 3.1 High-Quality Sources (Tier 1)
- Academic papers, official institutions, government reports
- Specific evaluation of each source (author, institution, publication year)
- Evidence for why they are trustworthy

#### 3.2 Medium-Quality Sources (Tier 2)
- News media, industry reports, expert interviews
- Analysis of bias or limitations
- Reliability and precautions when using

#### 3.3 Caution-Required Sources (Tier 3)
- Opinion articles, blogs, SNS, etc.
- Specific points to be cautious about
- Examination of partial usability

### 4. Triangulation Results

#### 4.1 Cross-Verified Key Findings
- Items confirmed by various independent sources (10-15)
- For each finding, specify number and types of confirming sources
- Evaluate importance and reliability of findings

#### 4.2 Single-Source Information
- List of important information confirmed by only one source
- Reasons why additional verification is needed
- Assessment of potential value and risks

#### 4.3 Complementary Relationships Between Sources
- How different sources provide complementary information
- What overall picture emerges when combined

### 5. Reliability Matrix

#### 5.1 High-Reliability Information (>80%)
- Specific information items and number of confirming sources
- Reliability score and rationale

#### 5.2 Medium-Reliability Information (50-80%)
- Partially confirmed information
- Areas requiring additional verification

#### 5.3 Low-Reliability Information (<50%)
- Single-source or contradictory information
- Precautions when using

### 6. Overall Assessment and Recommendations

#### 6.1 Overall Data Quality Assessment
- Overall reliability of collected sources
- Completeness of data coverage
- Key strengths and weaknesses

#### 6.2 Areas Requiring Additional Verification
- Topics needing more sources
- Solutions for conflicting information

**Output Format:**
- Clearly structure with markdown headings (###, ####)
- Emphasize important findings with **bold** or > blockquotes
- Include specific numbers and examples
- Use tables or lists to improve readability

**Important:** Include **in-depth analysis and interpretation** for each item, not just simple listing.""",

            "ja": f"""以下の{sources_count}個のソースについて、**専門的かつ体系的に**クロス検証と三角測量(Triangulation)を実施してください:

{sources_text}

**執筆ガイドライン:**
これは研究レポートの重要な検証セクションです。最低600-800語で作成してください。

以下を**具体的かつ詳細に**分析してください:

### 1. 一貫性分析

#### 1.1 核心的事実の確認
- 複数のソース(3個以上)で一貫して確認される核心的事実を**具体的に**列挙
- 各事実について、どのソースが確認したか明示
- 一致度レベル(完全一致、部分一致、類似一致)を表示
- 例: "5個のソースで共通して確認された事実: [具体的内容]"

#### 1.2 信頼度の高い情報
- 複数の独立したソースで検証された情報リスト
- 各情報の信頼性の根拠を説明
- データの一致性の度合い(定量的表現)

### 2. 不一致分析

#### 2.1 矛盾情報の特定
- ソース間で矛盾する情報を**具体的に**記述
- 各不一致事項についての詳細な比較
- 数値や主張が異なる場合、正確な差異を明示

#### 2.2 不一致の原因分析
- 時間的差異: データ収集時点の違い
- 観点の差異: 分析フレームワークやアプローチの違い
- 方法論的差異: 調査方法、サンプリングなどの違い
- データソースの差異: 1次/2次資料、地域別の違い
- 各原因についての具体的説明と例示

### 3. 情報品質評価

#### 3.1 高品質ソース (Tier 1)
- 学術論文、公式機関、政府レポート
- 各ソースの具体的評価(著者、機関、出版年)
- なぜ信頼できるかの根拠提示

#### 3.2 中間品質ソース (Tier 2)
- ニュースメディア、産業レポート、専門家インタビュー
- バイアスや制約の分析
- 信頼性と活用時の注意点

#### 3.3 注意が必要なソース (Tier 3)
- 意見記事、ブログ、SNSなど
- どの部分に注意すべきか具体的指摘
- 部分的活用可能性の検討

### 4. 三角測量結果

#### 4.1 クロス確認された核心的発見
- 多様な独立したソースで確認された事項(10-15個)
- 各発見について確認されたソース数と種類を明示
- 発見の重要度と信頼度を評価

#### 4.2 単一ソース情報
- 1箇所でのみ確認された重要情報のリスト
- 追加検証が必要な理由
- 潜在的価値とリスクの評価

#### 4.3 ソース間の補完関係
- 異なるソースがどのように補完的情報を提供するか
- 総合的にどのような全体像が描かれるか

### 5. 信頼度マトリックス

#### 5.1 高信頼度情報 (>80%)
- 具体的情報項目と確認ソース数
- 信頼度スコアと根拠

#### 5.2 中信頼度情報 (50-80%)
- 部分的に確認された情報
- 追加検証が必要な領域

#### 5.3 低信頼度情報 (<50%)
- 単一ソースまたは矛盾する情報
- 活用時の注意事項

### 6. 総合評価と提言

#### 6.1 全体データ品質評価
- 収集されたソースの全般的信頼度
- データカバレッジの完成度
- 主要な強みと弱み

#### 6.2 追加検証必要領域
- より多くのソースが必要なトピック
- 矛盾する情報に対する解決方案

**出力形式:**
- マークダウンヘディング(###、####)で明確に構造化
- 重要な発見は**太字**や>引用で強調
- 具体的な数値と例示を含む
- 表やリストを活用して可読性向上

**重要:** 単純な列挙ではなく、各項目についての**深い分析と解釈**を含めてください。"""
      }

      return prompts.get(language, prompts["en"])

   @staticmethod
   def get_critical_thinking_prompt(
      topic: str,
      deep_analysis: str,
      validation_report: str,
      language: str = "en"
   ) -> str:
      """Get critical thinking analysis prompt.

      Args:
         topic: Research topic
         deep_analysis: Deep analysis results
         validation_report: Validation report
         language: Target language code

      Returns:
         Formatted prompt string
      """
      prompts: Dict[str, str] = {
         "ko": f"""다음 연구 결과를 **깊이 있고 균형 잡힌 방식으로** 비판적으로 분석해주세요:

주제: {topic}

심층 분석 결과:
{deep_analysis[:2500]}

교차 검증 결과:
{validation_report[:2500]}

**작성 지침:**
이것은 연구 보고서의 핵심 비판적 분석 섹션입니다. 최소 800-1000단어로 작성하세요.

다음 관점에서 **구체적이고 상세하게** 비판적으로 분석해주세요:

### 1. 다양한 관점 분석 (Multi-Perspective Analysis)

#### 1.1 찬성 입장
- 주요 찬성 의견과 **구체적 근거** (데이터, 사례 포함)
- 각 찬성 의견을 지지하는 이론적/실증적 증거
- 찬성 입장의 강점과 설득력 있는 논리
- 실제 사례와 성공 스토리 (최소 3-5개)

#### 1.2 반대 입장
- 주요 반대 의견과 **구체적 비판** (데이터, 사례 포함)
- 각 반대 의견의 근거와 논리
- 반대 입장에서 제기하는 우려사항
- 실패 사례나 부정적 결과 (최소 3-5개)

#### 1.3 중립/회의적 관점
- 균형 잡힌 관점에서의 평가
- 양측 주장의 타당성 검토
- 맥락에 따라 달라질 수 있는 요소들
- 아직 충분히 검증되지 않은 영역

#### 1.4 관점 간 비교 분석
- 각 관점의 강점과 약점 비교
- 왜 이런 다양한 관점이 존재하는지 분석
- 합의 가능한 영역과 논쟁적 영역 구분

### 2. 가정과 편향 식별 (Assumptions and Bias Identification)

#### 2.1 암묵적 가정
- 연구나 분석에 내재된 숨겨진 가정들 (5-7개)
- 각 가정이 결과에 미치는 영향 분석
- 가정이 타당한지, 검증 가능한지 평가
- 대안적 가정 제시

#### 2.2 잠재적 편향
- **확증 편향**: 기존 신념을 확인하려는 경향
- **선택 편향**: 특정 데이터나 소스만 선별적 활용
- **생존자 편향**: 성공 사례만 과다 대표
- **시간적 편향**: 최신 데이터 편중 또는 과거 데이터 무시
- **지역/문화적 편향**: 특정 지역/문화 중심의 시각
- 각 편향의 **구체적 사례**와 영향

#### 2.3 누락된 관점
- 과소 대표된 이해관계자나 그룹
- 고려되지 않은 대안적 프레임워크
- 간과된 중요한 변수나 요인
- 누락으로 인한 분석의 불완전성

### 3. 한계점 및 제약사항 (Limitations and Constraints)

#### 3.1 데이터의 한계
- 데이터 품질 문제 (정확성, 완전성, 최신성)
- 샘플 크기나 범위의 제약
- 데이터 수집 방법의 한계
- 누락된 중요 데이터
- **구체적 예시**: "X 데이터는 2020년까지만 available하여..."

#### 3.2 방법론적 제약
- 연구 설계의 한계
- 인과관계 vs 상관관계의 혼동 가능성
- 통제되지 않은 변수들
- 측정 도구나 지표의 한계
- 재현성이나 일반화 가능성의 문제

#### 3.3 일반화의 한계
- 연구 결과가 적용 가능한 범위
- 특수한 조건이나 맥락의 영향
- 시간적/공간적 일반화의 제약
- 다른 산업/분야로의 전이 가능성

### 4. 대안적 해석 (Alternative Interpretations)

#### 4.1 다른 방식의 해석 가능성
- 동일한 데이터에 대한 2-3가지 대안적 해석
- 각 해석의 논리와 근거
- 어떤 해석이 더 타당한지 비교 평가

#### 4.2 맥락에 따른 해석 차이
- 문화적 맥락에 따른 차이
- 산업/분야별 차이
- 시기에 따른 해석의 변화
- 이해관계자별 해석의 차이

#### 4.3 복잡성과 불확실성
- 단순화할 수 없는 복잡한 요소들
- 예측 불가능한 변수들
- 불확실성의 정도와 영향

### 5. 추가 고려사항 (Additional Considerations)

#### 5.1 윤리적 고려사항
- 윤리적 딜레마나 논란의 여지
- 이해관계 충돌 가능성
- 공정성과 형평성 문제
- 투명성과 책임성 이슈
- **구체적 시나리오**와 윤리적 판단

#### 5.2 사회적 영향
- 다양한 이해관계자에 대한 영향 (긍정/부정)
- 불평등이나 격차 심화/완화 가능성
- 사회적 수용성과 저항
- 의도하지 않은 부작용
- **실제 사례** 기반 영향 분석

#### 5.3 장기적 시사점
- 5-10년 후 예상되는 변화
- 지속 가능성 관점에서의 평가
- 장기적 리스크와 기회
- 미래 세대에 대한 영향

### 6. 미해결 질문 (Unresolved Questions)

#### 6.1 추가 연구가 필요한 영역
- 현재 데이터로 답할 수 없는 중요한 질문 (10-15개)
- 각 질문이 중요한 이유
- 답을 구하기 위한 연구 방향 제안
- 우선순위가 높은 연구 주제

#### 6.2 답변되지 않은 핵심 질문
- 근본적이지만 아직 해결되지 않은 문제
- 논쟁이 지속되는 이유
- 합의 도출을 위해 필요한 것

### 7. 종합 평가 (Overall Critical Assessment)

#### 7.1 연구의 신뢰도와 타당성
- 전반적인 연구 품질 평가 (1-10점 척도)
- 주요 강점 3-5가지
- 주요 약점 3-5가지
- 개선이 필요한 영역

#### 7.2 실무적 함의
- 의사결정에 활용 시 주의사항
- 적용 가능한 영역과 제한적 영역
- 실무 적용을 위한 추가 고려사항

**출력 형식:**
- 명확한 마크다운 구조 (###, ####)
- **굵은 글씨**로 핵심 포인트 강조
- > 인용문으로 중요한 비판이나 통찰 강조
- 구체적 예시와 데이터 포함
- 객관적이고 균형 잡힌 어조 유지

**중요:**
1. 단순히 문제점을 나열하는 것이 아니라, **왜** 그것이 문제인지, **어떤** 영향을 미치는지 깊이 있게 분석
2. 비판을 위한 비판이 아닌, 건설적이고 균형 잡힌 관점 제시
3. 구체적 사례와 데이터로 주장을 뒷받침""",

            "en": f"""Critically analyze the following research results in a **deep and balanced manner**:

Topic: {topic}

Deep Analysis Results:
{deep_analysis[:2500]}

Cross-Validation Results:
{validation_report[:2500]}

**Writing Guidelines:**
This is the core critical analysis section of the research report. Write at least 800-1000 words.

Analyze **specifically and in detail** from the following perspectives:

### 1. Multi-Perspective Analysis

#### 1.1 Supporting Position
- Main supporting opinions with **specific evidence** (data, cases)
- Theoretical/empirical evidence supporting each position
- Strengths and persuasive logic of supporting positions
- Real cases and success stories (minimum 3-5)

#### 1.2 Opposing Position
- Main opposing opinions with **specific criticisms** (data, cases)
- Rationale and logic of each opposing opinion
- Concerns raised by opposing positions
- Failure cases or negative outcomes (minimum 3-5)

#### 1.3 Neutral/Skeptical Perspective
- Balanced evaluation
- Examination of validity of both arguments
- Context-dependent variables
- Areas not yet sufficiently verified

#### 1.4 Comparative Analysis Between Perspectives
- Compare strengths and weaknesses of each perspective
- Analyze why these diverse perspectives exist
- Distinguish areas of consensus from contentious areas

### 2. Assumptions and Bias Identification

#### 2.1 Implicit Assumptions
- Hidden assumptions inherent in research/analysis (5-7)
- Analyze impact of each assumption on results
- Evaluate if assumptions are valid and verifiable
- Propose alternative assumptions

#### 2.2 Potential Biases
- **Confirmation bias**: Tendency to confirm existing beliefs
- **Selection bias**: Selective use of specific data or sources
- **Survivorship bias**: Over-representation of success cases
- **Temporal bias**: Overemphasis on recent data or ignoring historical data
- **Geographic/cultural bias**: Specific region/culture-centric view
- **Specific examples** and impact of each bias

#### 2.3 Missing Perspectives
- Under-represented stakeholders or groups
- Unconsidered alternative frameworks
- Overlooked important variables or factors
- Analysis incompleteness due to omissions

### 3. Limitations and Constraints

#### 3.1 Data Limitations
- Data quality issues (accuracy, completeness, currency)
- Sample size or scope constraints
- Data collection method limitations
- Missing critical data
- **Specific example**: "X data only available until 2020..."

#### 3.2 Methodological Constraints
- Research design limitations
- Possible confusion between causation and correlation
- Uncontrolled variables
- Measurement tool or metric limitations
- Reproducibility or generalizability issues

#### 3.3 Generalization Limitations
- Scope of applicability of research results
- Impact of special conditions or contexts
- Temporal/spatial generalization constraints
- Transferability to other industries/fields

### 4. Alternative Interpretations

#### 4.1 Different Interpretation Possibilities
- 2-3 alternative interpretations of same data
- Logic and rationale for each interpretation
- Comparative evaluation of which interpretation is more valid

#### 4.2 Context-Dependent Interpretation Differences
- Differences by cultural context
- Industry/field-specific differences
- Changes in interpretation over time
- Stakeholder-specific interpretation differences

#### 4.3 Complexity and Uncertainty
- Complex elements that cannot be simplified
- Unpredictable variables
- Degree and impact of uncertainty

### 5. Additional Considerations

#### 5.1 Ethical Considerations
- Ethical dilemmas or controversies
- Potential conflicts of interest
- Fairness and equity issues
- Transparency and accountability issues
- **Specific scenarios** and ethical judgments

#### 5.2 Social Impacts
- Impacts on various stakeholders (positive/negative)
- Potential for exacerbating/mitigating inequality or gaps
- Social acceptability and resistance
- Unintended side effects
- Impact analysis based on **real cases**

#### 5.3 Long-Term Implications
- Expected changes in 5-10 years
- Evaluation from sustainability perspective
- Long-term risks and opportunities
- Impact on future generations

### 6. Unresolved Questions

#### 6.1 Areas Requiring Further Research
- Important questions unanswerable with current data (10-15)
- Why each question is important
- Proposed research directions for answers
- High-priority research topics

#### 6.2 Unanswered Core Questions
- Fundamental but unresolved issues
- Reasons for ongoing debate
- What's needed to reach consensus

### 7. Overall Critical Assessment

#### 7.1 Research Reliability and Validity
- Overall research quality rating (1-10 scale)
- 3-5 major strengths
- 3-5 major weaknesses
- Areas needing improvement

#### 7.2 Practical Implications
- Precautions when using for decision-making
- Applicable areas and limited areas
- Additional considerations for practical application

**Output Format:**
- Clear markdown structure (###, ####)
- Emphasize key points with **bold**
- Highlight important critiques or insights with > blockquotes
- Include specific examples and data
- Maintain objective and balanced tone

**Important:**
1. Not just listing problems, but deeply analyzing **why** it's a problem and **what** impact it has
2. Present constructive and balanced perspectives, not criticism for criticism's sake
3. Support arguments with specific cases and data""",

            "ja": f"""以下の研究結果を**深く、バランスの取れた方法で**批判的に分析してください:

テーマ: {topic}

詳細分析結果:
{deep_analysis[:2500]}

クロス検証結果:
{validation_report[:2500]}

**執筆ガイドライン:**
これは研究レポートの核心的批判的分析セクションです。最低800-1000語で作成してください。

以下の観点から**具体的かつ詳細に**批判的に分析してください:

### 1. 多様な観点分析

#### 1.1 賛成の立場
- 主要な賛成意見と**具体的根拠**(データ、事例を含む)
- 各立場を支持する理論的/実証的証拠
- 賛成立場の強みと説得力のある論理
- 実際の事例と成功ストーリー(最低3-5個)

#### 1.2 反対の立場
- 主要な反対意見と**具体的批判**(データ、事例を含む)
- 各反対意見の根拠と論理
- 反対立場が提起する懸念事項
- 失敗事例や否定的結果(最低3-5個)

#### 1.3 中立/懐疑的観点
- バランスの取れた評価
- 両側の主張の妥当性検討
- 文脈によって変わりうる要素
- まだ十分に検証されていない領域

#### 1.4 観点間の比較分析
- 各観点の強みと弱みの比較
- なぜこのような多様な観点が存在するか分析
- 合意可能な領域と論争的領域の区別

### 2. 仮定とバイアスの特定

#### 2.1 暗黙の仮定
- 研究や分析に内在する隠れた仮定(5-7個)
- 各仮定が結果に与える影響の分析
- 仮定が妥当か、検証可能かの評価
- 代替的仮定の提示

#### 2.2 潜在的バイアス
- **確証バイアス**: 既存の信念を確認しようとする傾向
- **選択バイアス**: 特定のデータやソースのみ選択的に活用
- **生存者バイアス**: 成功事例のみの過度な代表
- **時間的バイアス**: 最新データの偏重または過去データの無視
- **地域/文化的バイアス**: 特定地域/文化中心の視点
- 各バイアスの**具体的事例**と影響

#### 2.3 欠落した観点
- 過少代表された利害関係者やグループ
- 考慮されていない代替的フレームワーク
- 見過ごされた重要な変数や要因
- 欠落による分析の不完全性

### 3. 限界と制約

#### 3.1 データの限界
- データ品質の問題(正確性、完全性、最新性)
- サンプルサイズや範囲の制約
- データ収集方法の限界
- 欠落した重要データ
- **具体例**: "Xデータは2020年までしか利用できず..."

#### 3.2 方法論的制約
- 研究設計の限界
- 因果関係と相関関係の混同の可能性
- 制御されていない変数
- 測定ツールや指標の限界
- 再現性や一般化可能性の問題

#### 3.3 一般化の限界
- 研究結果の適用可能範囲
- 特殊な条件や文脈の影響
- 時間的/空間的一般化の制約
- 他の産業/分野への転用可能性

### 4. 代替的解釈

#### 4.1 異なる解釈の可能性
- 同じデータに対する2-3の代替的解釈
- 各解釈の論理と根拠
- どの解釈がより妥当か比較評価

#### 4.2 文脈による解釈の違い
- 文化的文脈による違い
- 産業/分野別の違い
- 時期による解釈の変化
- 利害関係者別の解釈の違い

#### 4.3 複雑性と不確実性
- 単純化できない複雑な要素
- 予測不可能な変数
- 不確実性の程度と影響

### 5. 追加考慮事項

#### 5.1 倫理的考慮事項
- 倫理的ジレンマや論争の余地
- 利益相反の可能性
- 公平性と衡平性の問題
- 透明性と責任性の課題
- **具体的シナリオ**と倫理的判断

#### 5.2 社会的影響
- 多様な利害関係者への影響(肯定/否定)
- 不平等や格差の拡大/緩和の可能性
- 社会的受容性と抵抗
- 意図しない副作用
- **実際の事例**に基づく影響分析

#### 5.3 長期的示唆
- 5-10年後に予想される変化
- 持続可能性の観点からの評価
- 長期的リスクと機会
- 将来世代への影響

### 6. 未解決の質問

#### 6.1 さらなる研究が必要な領域
- 現在のデータでは答えられない重要な質問(10-15個)
- 各質問が重要な理由
- 答えを得るための研究方向の提案
- 優先度の高い研究トピック

#### 6.2 回答されていない核心的質問
- 根本的だがまだ解決されていない問題
- 論争が続く理由
- 合意形成に必要なこと

### 7. 総合評価

#### 7.1 研究の信頼性と妥当性
- 全般的な研究品質の評価(1-10点スケール)
- 主要な強み3-5点
- 主要な弱み3-5点
- 改善が必要な領域

#### 7.2 実務的含意
- 意思決定に活用する際の注意事項
- 適用可能な領域と制限的領域
- 実務適用のための追加考慮事項

**出力形式:**
- 明確なマークダウン構造(###、####)
- **太字**で核心ポイントを強調
- >引用で重要な批判や洞察を強調
- 具体的例示とデータを含む
- 客観的でバランスの取れた語調を維持

**重要:**
1. 単に問題点を列挙するのではなく、**なぜ**それが問題で、**どんな**影響があるかを深く分析
2. 批判のための批判ではなく、建設的でバランスの取れた観点を提示
3. 具体的事例とデータで主張を裏付ける"""
      }

      return prompts.get(language, prompts["en"])

   @staticmethod
   def get_report_structure_prompt(topic: str, language: str = "en") -> str:
      """Get final report structure planning prompt.

      Args:
         topic: Research topic
         language: Target language code

      Returns:
         Formatted prompt string
      """
      prompts: Dict[str, str] = {
         "ko": f"""다음 주제에 대한 최종 보고서 구조를 설계해주세요:

주제: {topic}

8-12개의 주요 섹션으로 구조화하세요.
각 섹션을 다음 형식으로 제시:
섹션명 | 목적 | 주요 내용

한 줄에 하나씩 작성하세요.""",

            "en": f"""Design the final report structure for the following topic:

Topic: {topic}

Structure it into 8-12 major sections.
Present each section in the following format:
Section Name | Purpose | Key Content

Write one section per line.""",

            "ja": f"""以下のテーマについて、最終レポート構造を設計してください:

テーマ: {topic}

8-12個の主要セクションに構造化してください。
各セクションを以下の形式で提示:
セクション名 | 目的 | 主要内容

1行に1つずつ記述してください。"""
      }

      return prompts.get(language, prompts["en"])


   @staticmethod
   def get_final_section_prompt(
      section_title: str,
      section_purpose: str,
      topic: str,
      deep_analysis: str,
      validation: str,
      critical_analysis: str,
      total_sources: int,
      language: str = "en"
   ) -> str:
      """Get prompt for generating final report sections.

      Args:
         section_title: Section title
         section_purpose: Section purpose
         topic: Research topic
         deep_analysis: Deep analysis summary
         validation: Validation summary
         critical_analysis: Critical analysis summary
         total_sources: Total number of sources
         language: Target language code

      Returns:
         Formatted prompt string
      """
      prompts: Dict[str, str] = {
         "ko": f"""다음 섹션을 **전문 보고서 수준**으로 작성해주세요:

섹션: {section_title}
목적: {section_purpose}

주제: {topic}

참고 자료:
- 심층 분석: {deep_analysis[:2000]}
- 검증 결과: {validation[:2000]}
- 비판적 분석: {critical_analysis[:2000]}

총 {total_sources}개의 신뢰할 수 있는 소스를 기반으로 한 연구입니다.

**작성 지침:**

이 섹션은 전문 연구 보고서의 일부입니다. 다음 기준을 충족해야 합니다:

1. **구조와 깊이**
   - 최소 800-1200단어 분량으로 작성
   - 명확한 서론, 본론, 결론 구조
   - 각 주요 포인트마다 구체적인 설명과 예시 제공
   - 하위 섹션으로 체계적으로 구성 (###, #### 사용)

2. **내용의 전문성**
   - 구체적인 데이터, 통계, 수치 포함
   - 실제 사례와 예시를 상세히 기술
   - 전문 용어 사용 시 명확한 설명 추가
   - 다양한 관점과 의견 제시
   - 인용 가능한 핵심 정보 강조

3. **분석의 깊이**
   - 단순 나열이 아닌 심층적인 분석과 해석
   - 원인과 결과, 상관관계 설명
   - 트렌드와 패턴 파악
   - 시사점과 의미 도출
   - 구체적인 근거와 논리적 전개

4. **보고서 스타일**
   - 객관적이고 전문적인 어조
   - 명확하고 설득력 있는 문장
   - 적절한 마크다운 서식 사용
   - 목록, 표, 강조 등으로 가독성 향상
   - 중요한 발견사항은 **굵게** 또는 > 인용문으로 강조

5. **구체성과 실용성**
   - 추상적 개념보다 구체적 사실 우선
   - 실무적 시사점 제공
   - 비교 분석 (국가별, 시기별, 유형별 등)
   - 도전과제와 해결방안 제시
   - 향후 전망 및 예측

**예시 구조:**

### {section_title}

#### 개요
[이 섹션의 핵심 내용을 2-3문단으로 소개]

#### 주요 발견사항
[구체적인 데이터와 사례를 포함한 3-5개의 하위 주제]

##### 발견사항 1: [제목]
- 구체적 설명 (200-300단어)
- 데이터/통계
- 실제 사례

##### 발견사항 2: [제목]
...

#### 심층 분석
[원인, 영향, 의미에 대한 분석]

#### 시사점
[실무적/전략적 시사점]

#### 향후 전망
[트렌드와 예측]

**중요:** 요약본이 아닌 완전한 보고서 섹션을 작성하세요. 독자가 이 섹션만 읽어도 해당 주제에 대해 깊이 있게 이해할 수 있어야 합니다.""",

            "en": f"""Write the following section at **professional report quality**:

Section: {section_title}
Purpose: {section_purpose}

Topic: {topic}

Reference Materials:
- Deep Analysis: {deep_analysis[:2000]}
- Validation Results: {validation[:2000]}
- Critical Analysis: {critical_analysis[:2000]}

This research is based on {total_sources} credible sources.

**Writing Guidelines:**

This section is part of a professional research report. It must meet the following criteria:

1. **Structure and Depth**
   - Write at least 800-1200 words
   - Clear introduction, body, and conclusion structure
   - Provide specific explanations and examples for each major point
   - Organize systematically with subsections (using ###, ####)

2. **Professional Content**
   - Include specific data, statistics, and figures
   - Describe real cases and examples in detail
   - Add clear explanations when using technical terms
   - Present diverse perspectives and opinions
   - Emphasize key citable information

3. **Analytical Depth**
   - Deep analysis and interpretation, not just listing
   - Explain causes and effects, correlations
   - Identify trends and patterns
   - Derive implications and meanings
   - Develop with concrete evidence and logic

4. **Report Style**
   - Objective and professional tone
   - Clear and persuasive sentences
   - Use appropriate markdown formatting
   - Improve readability with lists, tables, emphasis
   - Highlight important findings with **bold** or > blockquotes

5. **Specificity and Practicality**
   - Prioritize concrete facts over abstract concepts
   - Provide practical implications
   - Comparative analysis (by country, period, type, etc.)
   - Present challenges and solutions
   - Future outlook and predictions

**Example Structure:**

### {section_title}

#### Overview
[Introduce the core content of this section in 2-3 paragraphs]

#### Key Findings
[3-5 subtopics with specific data and cases]

##### Finding 1: [Title]
- Detailed explanation (200-300 words)
- Data/statistics
- Real-world examples

##### Finding 2: [Title]
...

#### In-Depth Analysis
[Analysis of causes, impacts, and implications]

#### Implications
[Practical/strategic implications]

#### Future Outlook
[Trends and predictions]

**Important:** Write a complete report section, not a summary. Readers should gain deep understanding of the topic from this section alone.""",

            "ja": f"""次のセクションを**プロフェッショナルレポート品質**で作成してください:

セクション: {section_title}
目的: {section_purpose}

テーマ: {topic}

参考資料:
- 詳細分析: {deep_analysis[:2000]}
- 検証結果: {validation[:2000]}
- 批判的分析: {critical_analysis[:2000]}

この研究は{total_sources}個の信頼できるソースに基づいています。

**執筆ガイドライン:**

このセクションはプロフェッショナルな研究レポートの一部です。以下の基準を満たす必要があります:

1. **構造と深さ**
   - 最低800-1200語で作成
   - 明確な序論、本論、結論の構造
   - 各主要ポイントに具体的な説明と例を提供
   - サブセクションで体系的に構成(###、####を使用)

2. **専門的な内容**
   - 具体的なデータ、統計、数値を含める
   - 実際の事例と例を詳細に記述
   - 専門用語使用時は明確な説明を追加
   - 多様な観点と意見を提示
   - 引用可能な核心情報を強調

3. **分析の深さ**
   - 単純な列挙ではなく深い分析と解釈
   - 原因と結果、相関関係を説明
   - トレンドとパターンを把握
   - 示唆と意味を導出
   - 具体的な根拠と論理的展開

4. **レポートスタイル**
   - 客観的で専門的な語調
   - 明確で説得力のある文章
   - 適切なマークダウン書式を使用
   - リスト、表、強調で可読性向上
   - 重要な発見は**太字**や>引用で強調

5. **具体性と実用性**
   - 抽象的概念より具体的事実を優先
   - 実務的示唆を提供
   - 比較分析(国別、時期別、タイプ別など)
   - 課題と解決策を提示
   - 今後の展望と予測

**例示構造:**

### {section_title}

#### 概要
[このセクションの核心内容を2-3段落で紹介]

#### 主要発見事項
[具体的なデータと事例を含む3-5個のサブトピック]

##### 発見1: [タイトル]
- 詳細説明(200-300語)
- データ/統計
- 実際の事例

##### 発見2: [タイトル]
...

#### 詳細分析
[原因、影響、意味の分析]

#### 示唆
[実務的/戦略的示唆]

#### 今後の展望
[トレンドと予測]

**重要:** 要約ではなく完全なレポートセクションを作成してください。読者がこのセクションだけを読んでも、そのテーマについて深く理解できる必要があります。"""
      }

      return prompts.get(language, prompts["en"])
