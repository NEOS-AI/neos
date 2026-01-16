"""Evaluation prompt templates for section quality assessment.

This module provides language-specific prompts for evaluating section quality
across multiple dimensions: coherence, completeness, and clarity.

Supports Korean (ko), English (en), and Japanese (ja) with culturally
appropriate criteria, examples, and rubrics.
"""

from typing import Dict


class EvaluationPrompts:
    """Prompts for section quality evaluation."""

    @staticmethod
    def get_quality_evaluation_prompt(
        section_title: str,
        content: str,
        language: str = "en"
    ) -> str:
        """Get language-specific section quality evaluation prompt.

        Evaluates three dimensions:
        - Coherence: Logical flow and connection between ideas
        - Completeness: How well section addresses its purpose
        - Clarity: Writing quality and readability

        Args:
            section_title: Section title for context
            content: Section content to evaluate (truncated to 4000 chars)
            language: Target language code ('ko', 'en', 'ja')

        Returns:
            Formatted prompt string with language-specific criteria and examples
        """
        # Truncate content to avoid token limits
        content_preview = content[:4000]

        prompts: Dict[str, str] = {
            "ko": f"""이 섹션의 품질을 세 가지 차원에서 평가해주세요. 각 항목을 0.0에서 1.0 사이로 평가하세요.

섹션 제목: {section_title}

내용:
{content_preview}

─── 평가 기준 ───

**일관성 (Coherence, 0.0-1.0)**: 아이디어 간의 논리적 흐름과 연결
- 0.9-1.0: 매끄러운 전환, 명확한 논증, 모든 아이디어가 자연스럽게 연결됨
- 0.7-0.8: 대부분의 전환이 부드러우며 사소한 간극만 존재, 전반적으로 좋은 흐름
- 0.5-0.6: 일부 아이디어가 단절되어 있으며 전환이 개선 필요
- 0.0-0.4: 단편적이며 논리적 구조가 부족함

**완성도 (Completeness, 0.0-1.0)**: 섹션의 목적을 얼마나 잘 다루는가
- 0.9-1.0: 충분한 깊이로 모든 측면을 철저히 다룸
- 0.7-0.8: 주요 요점을 적절히 다루며 사소한 간극은 허용됨
- 0.5-0.6: 중요한 측면이 누락되었거나 깊이가 부족함
- 0.0-0.4: 심각하게 불완전하며 중요한 간극이 있음

**명료성 (Clarity, 0.0-1.0)**: 작성 품질과 가독성
- 0.9-1.0: 매우 명확하고 간결하며 대상 독자가 이해하기 쉬움
- 0.7-0.8: 대체로 명확하며 사소한 모호함만 존재
- 0.5-0.6: 일부 혼란스러운 부분이 있으며 가독성 문제 존재
- 0.0-0.4: 불명확하고 복잡하며 이해하기 어려움

─── 예시 ───

낮은 품질 섹션 (전체 점수: 0.5):
"AI는 중요합니다. 많은 회사들이 사용합니다. 여러 작업을 수행할 수 있습니다."
→ 일관성: 0.4 (단절된 진술, 논리적 연결 부족)
→ 완성도: 0.3 (깊이와 세부 사항 부족, 피상적)
→ 명료성: 0.7 (간단하지만 너무 모호함)

높은 품질 섹션 (전체 점수: 0.9):
"인공지능은 자동화된 의사결정, 예측 분석, 자연어 처리라는 세 가지 핵심 메커니즘을 통해 현대 비즈니스 운영을 변화시켰습니다. 최근 연구에 따르면 포춘 500대 기업의 78%가 최소 하나의 핵심 비즈니스 기능에 AI를 통합했으며, 고객 서비스와 공급망 최적화가 도입률을 주도하고 있습니다. 이러한 통합은 운영 효율성을 평균 40% 향상시키고 비용을 25% 절감하는 것으로 나타났습니다."
→ 일관성: 0.95 (명확한 흐름, 논리적 구조, 자연스러운 전개)
→ 완성도: 0.90 (상세하며 핵심 요점을 구체적 데이터와 함께 다룸)
→ 명료성: 0.90 (명확하고 구체적이며 잘 작성됨)

─── 평가 결과 ───

다음 정확한 형식으로 점수를 제공하세요 (예: 0.85):
coherence: X.XX
completeness: X.XX
clarity: X.XX""",

            "en": f"""Evaluate this section's quality on three dimensions. Rate each from 0.0 to 1.0.

Section Title: {section_title}

Content:
{content_preview}

─── Evaluation Criteria ───

**Coherence (0.0-1.0)**: Logical flow and connection between ideas
- 0.9-1.0: Seamless transitions, clear argumentation, all ideas connect naturally
- 0.7-0.8: Good flow with minor gaps, most transitions are smooth
- 0.5-0.6: Some disconnected ideas, transitions need improvement
- 0.0-0.4: Fragmented, lacks logical structure

**Completeness (0.0-1.0)**: How well it addresses the section's purpose
- 0.9-1.0: Thoroughly addresses all aspects with sufficient depth
- 0.7-0.8: Covers main points adequately, minor gaps acceptable
- 0.5-0.6: Missing important aspects or lacks depth
- 0.0-0.4: Severely incomplete, critical gaps

**Clarity (0.0-1.0)**: Writing quality and readability
- 0.9-1.0: Crystal clear, concise, accessible to target audience
- 0.7-0.8: Mostly clear with minor ambiguities
- 0.5-0.6: Some confusing parts, readability issues
- 0.0-0.4: Unclear, convoluted, hard to understand

─── Examples ───

Low quality section (Overall: 0.5):
"AI is important. Many companies use it. It can do things."
→ coherence: 0.4 (disconnected statements, lacks logical flow)
→ completeness: 0.3 (lacks depth and details, superficial)
→ clarity: 0.7 (simple but too vague)

High quality section (Overall: 0.9):
"Artificial intelligence has transformed modern business operations through three key mechanisms: automated decision-making, predictive analytics, and natural language processing. Recent studies indicate that 78% of Fortune 500 companies have integrated AI into at least one core business function, with customer service and supply chain optimization leading adoption rates. This integration has resulted in an average 40% improvement in operational efficiency and 25% reduction in costs."
→ coherence: 0.95 (clear flow, logical structure, natural progression)
→ completeness: 0.90 (detailed, addresses key points with specific data)
→ clarity: 0.90 (clear, specific, well-written)

─── Your Evaluation ───

Provide scores in this exact format (e.g., 0.85):
coherence: X.XX
completeness: X.XX
clarity: X.XX""",

            "ja": f"""このセクションの品質を3つの側面から評価してください。それぞれ0.0から1.0で評価してください。

セクションタイトル: {section_title}

内容:
{content_preview}

─── 評価基準 ───

**一貫性 (Coherence, 0.0-1.0)**: アイデア間の論理的な流れと接続
- 0.9-1.0: シームレスな移行、明確な論証、すべてのアイデアが自然につながる
- 0.7-0.8: 小さなギャップはあるが良い流れ、ほとんどの移行がスムーズ
- 0.5-0.6: いくつかの切り離されたアイデア、移行の改善が必要
- 0.0-0.4: 断片的で論理的構造が欠けている

**完全性 (Completeness, 0.0-1.0)**: セクションの目的をどれだけ満たしているか
- 0.9-1.0: 十分な深さですべての側面を徹底的にカバー
- 0.7-0.8: 主要なポイントを適切にカバー、小さなギャップは許容
- 0.5-0.6: 重要な側面が欠けているか深さが不足
- 0.0-0.4: 著しく不完全、重大なギャップ

**明瞭性 (Clarity, 0.0-1.0)**: 文章の質と読みやすさ
- 0.9-1.0: 非常に明確で簡潔、対象読者が理解しやすい
- 0.7-0.8: ほぼ明確で小さな曖昧さのみ
- 0.5-0.6: 混乱する部分があり、読みやすさに問題
- 0.0-0.4: 不明確で複雑、理解が困難

─── 例 ───

低品質セクション (総合: 0.5):
"AIは重要です。多くの企業が使用しています。いろいろなことができます。"
→ 一貫性: 0.4 (切り離された記述、論理的な流れの欠如)
→ 完全性: 0.3 (深さと詳細が欠如、表面的)
→ 明瞭性: 0.7 (シンプルだが曖昧すぎる)

高品質セクション (総合: 0.9):
"人工知能は、自動化された意思決定、予測分析、自然言語処理という3つの主要なメカニズムを通じて、現代のビジネス運営を変革しました。最近の研究によると、フォーチュン500企業の78%が少なくとも1つの中核的なビジネス機能にAIを統合しており、カスタマーサービスとサプライチェーン最適化が採用率をリードしています。この統合により、運用効率が平均40%向上し、コストが25%削減されています。"
→ 一貫性: 0.95 (明確な流れ、論理的構造、自然な展開)
→ 完全性: 0.90 (詳細で主要なポイントを具体的データと共にカバー)
→ 明瞭性: 0.90 (明確で具体的、よく書かれている)

─── 評価結果 ───

次の正確な形式でスコアを提供してください (例: 0.85):
coherence: X.XX
completeness: X.XX
clarity: X.XX"""
        }

        return prompts.get(language, prompts["en"])
