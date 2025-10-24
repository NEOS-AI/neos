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
            "ko": f"""라운드 {round_num} 분석

주제: {original_query}

초기 데이터 요약:
{data_summary[:1000]}

이전 라운드 인사이트:
{previous_insights[:1000] if previous_insights else 'N/A'}

이번 라운드에서 다음을 분석해주세요:
- 새로운 패턴과 인사이트
- 이전 라운드와의 연결점
- 추가 탐구가 필요한 영역

상세한 분석을 작성해주세요.""",

            "en": f"""Round {round_num} Analysis

Topic: {original_query}

Initial Data Summary:
{data_summary[:1000]}

Previous Round Insights:
{previous_insights[:1000] if previous_insights else 'N/A'}

For this round, analyze the following:
- New patterns and insights
- Connections with previous rounds
- Areas requiring further exploration

Write a detailed analysis.""",

            "ja": f"""ラウンド {round_num} 分析

テーマ: {original_query}

初期データ要約:
{data_summary[:1000]}

前回ラウンドのインサイト:
{previous_insights[:1000] if previous_insights else 'N/A'}

今回のラウンドで以下を分析してください:
- 新しいパターンとインサイト
- 前回ラウンドとの接続点
- さらなる探求が必要な領域

詳細な分析を作成してください。"""
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
