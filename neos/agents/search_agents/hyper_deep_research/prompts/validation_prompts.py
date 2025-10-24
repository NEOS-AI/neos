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
            "ko": f"""다음 {sources_count}개의 소스를 교차 검증하고 삼각측량(Triangulation)을 수행해주세요:

{sources_text}

다음을 분석해주세요:

1. **일관성 분석**
   - 여러 소스에서 일관되게 확인되는 핵심 사실
   - 신뢰도가 높은 정보 (3개 이상 소스에서 확인)

2. **불일치 분석**
   - 소스 간 상충되는 정보
   - 불일치의 원인 (시점, 관점, 데이터 차이 등)

3. **정보 품질 평가**
   - 고품질 소스 (학술, 공식 기관)
   - 중간 품질 소스 (뉴스, 산업 보고서)
   - 주의 필요 소스 (의견, 블로그)

4. **삼각측량 결과**
   - 다양한 소스에서 교차 확인된 핵심 발견사항
   - 단일 소스에만 있는 정보 (추가 검증 필요)

5. **신뢰도 매트릭스**
   - 높은 신뢰도 정보 목록
   - 중간 신뢰도 정보 목록
   - 낮은 신뢰도 정보 목록

상세한 교차 검증 보고서를 작성해주세요.""",

            "en": f"""Perform cross-validation and triangulation on the following {sources_count} sources:

{sources_text}

Analyze the following:

1. **Consistency Analysis**
   - Core facts consistently confirmed across multiple sources
   - High-confidence information (verified by 3+ sources)

2. **Discrepancy Analysis**
   - Conflicting information between sources
   - Causes of discrepancies (timing, perspective, data differences, etc.)

3. **Information Quality Assessment**
   - High-quality sources (academic, official institutions)
   - Medium-quality sources (news, industry reports)
   - Sources requiring caution (opinions, blogs)

4. **Triangulation Results**
   - Key findings cross-verified from various sources
   - Information from single sources only (requires additional verification)

5. **Reliability Matrix**
   - High-reliability information list
   - Medium-reliability information list
   - Low-reliability information list

Write a detailed cross-validation report.""",

            "ja": f"""以下の {sources_count} 個のソースについて、クロス検証と三角測量(Triangulation)を実施してください:

{sources_text}

以下を分析してください:

1. **一貫性分析**
   - 複数のソースで一貫して確認される核心的な事実
   - 信頼度が高い情報（3個以上のソースで確認）

2. **不一致分析**
   - ソース間で矛盾する情報
   - 不一致の原因（時点、観点、データの違いなど）

3. **情報品質評価**
   - 高品質ソース（学術、公式機関）
   - 中間品質ソース（ニュース、産業レポート）
   - 注意が必要なソース（意見、ブログ）

4. **三角測量結果**
   - 多様なソースでクロス確認された核心的な発見
   - 単一ソースのみの情報（追加検証が必要）

5. **信頼度マトリックス**
   - 高信頼度情報リスト
   - 中信頼度情報リスト
   - 低信頼度情報リスト

詳細なクロス検証レポートを作成してください。"""
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
            "ko": f"""다음 연구 결과를 비판적으로 분석해주세요:

주제: {topic}

심층 분석 결과:
{deep_analysis[:1500]}

교차 검증 결과:
{validation_report[:1500]}

다음 관점에서 비판적으로 분석해주세요:

1. **다양한 관점 분석**
   - 찬성 의견 및 근거
   - 반대 의견 및 근거
   - 중립/회의적 관점

2. **가정과 편향 식별**
   - 암묵적 가정
   - 잠재적 편향 (확증 편향, 선택 편향 등)
   - 누락된 관점

3. **한계점 및 제약사항**
   - 데이터의 한계
   - 방법론적 제약
   - 일반화의 한계

4. **대안적 해석**
   - 다른 방식의 해석 가능성
   - 맥락에 따른 해석 차이

5. **추가 고려사항**
   - 윤리적 고려사항
   - 사회적 영향
   - 장기적 시사점

6. **미해결 질문**
   - 추가 연구가 필요한 영역
   - 답변되지 않은 질문

매우 비판적이고 균형 잡힌 분석을 작성해주세요.""",

            "en": f"""Critically analyze the following research results:

Topic: {topic}

Deep Analysis Results:
{deep_analysis[:1500]}

Cross-Validation Results:
{validation_report[:1500]}

Critically analyze from the following perspectives:

1. **Multi-Perspective Analysis**
   - Supporting opinions and evidence
   - Opposing opinions and evidence
   - Neutral/skeptical perspectives

2. **Assumptions and Bias Identification**
   - Implicit assumptions
   - Potential biases (confirmation bias, selection bias, etc.)
   - Missing perspectives

3. **Limitations and Constraints**
   - Data limitations
   - Methodological constraints
   - Generalization limitations

4. **Alternative Interpretations**
   - Possibility of different interpretations
   - Context-dependent interpretation differences

5. **Additional Considerations**
   - Ethical considerations
   - Social impacts
   - Long-term implications

6. **Unresolved Questions**
   - Areas requiring further research
   - Unanswered questions

Write a highly critical and balanced analysis.""",

            "ja": f"""以下の研究結果を批判的に分析してください:

テーマ: {topic}

詳細分析結果:
{deep_analysis[:1500]}

クロス検証結果:
{validation_report[:1500]}

以下の観点から批判的に分析してください:

1. **多様な観点分析**
   - 賛成意見と根拠
   - 反対意見と根拠
   - 中立/懐疑的観点

2. **仮定とバイアスの特定**
   - 暗黙の仮定
   - 潜在的バイアス（確証バイアス、選択バイアスなど）
   - 欠落した観点

3. **限界と制約**
   - データの限界
   - 方法論的制約
   - 一般化の限界

4. **代替的解釈**
   - 異なる解釈の可能性
   - 文脈による解釈の違い

5. **追加考慮事項**
   - 倫理的考慮事項
   - 社会的影響
   - 長期的示唆

6. **未解決の質問**
   - さらなる研究が必要な領域
   - 回答されていない質問

非常に批判的でバランスの取れた分析を作成してください。"""
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
            "ko": f"""다음 섹션을 작성해주세요:

섹션: {section_title}
목적: {section_purpose}

주제: {topic}

참고 자료:
- 심층 분석: {deep_analysis[:800]}
- 검증 결과: {validation[:800]}
- 비판적 분석: {critical_analysis[:800]}

총 {total_sources}개 소스를 기반으로 이 섹션을 매우 상세하고 전문적으로 작성해주세요.
데이터, 사례, 구체적인 내용을 포함하세요.""",

            "en": f"""Write the following section:

Section: {section_title}
Purpose: {section_purpose}

Topic: {topic}

Reference Materials:
- Deep Analysis: {deep_analysis[:800]}
- Validation Results: {validation[:800]}
- Critical Analysis: {critical_analysis[:800]}

Based on {total_sources} total sources, write this section in a very detailed and professional manner.
Include data, cases, and specific content.""",

            "ja": f"""以下のセクションを作成してください:

セクション: {section_title}
目的: {section_purpose}

テーマ: {topic}

参考資料:
- 詳細分析: {deep_analysis[:800]}
- 検証結果: {validation[:800]}
- 批判的分析: {critical_analysis[:800]}

合計 {total_sources} 個のソースに基づいて、このセクションを非常に詳細かつ専門的に作成してください。
データ、事例、具体的な内容を含めてください。"""
        }

        return prompts.get(language, prompts["en"])
