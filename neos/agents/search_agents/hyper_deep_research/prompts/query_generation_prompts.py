"""Query generation prompt templates for HyperDeepResearch."""

from typing import Dict, List


class QueryGenerationPrompts:
    """Prompts for generating diverse search queries."""

    @staticmethod
    def get_multi_query_prompt(
        original_query: str,
        research_questions: List[str],
        language: str = "en"
    ) -> str:
        """Get multi-query generation prompt.

        Args:
            original_query: Original research query
            research_questions: List of research questions
            language: Target language code

        Returns:
            Formatted prompt string
        """
        questions_text = '\n'.join(research_questions[:10])

        prompts: Dict[str, str] = {
            "ko": f"""다음 연구 주제에 대해 다양한 관점과 각도에서 검색 쿼리를 생성해주세요:

주제: {original_query}

연구 질문들:
{questions_text}

다음 전략으로 **25개의 다양한 검색 쿼리**를 생성해주세요:

1. 직접 질문 (5개): 주제의 핵심 질문
2. 관련 개념 (5개): 연관 키워드, 유사 주제
3. 특정 측면 (5개): 기술, 시장, 사회, 역사, 미래
4. 비교 및 대조 (5개): A vs B, 장단점, 대안
5. 사례 및 실제 (5개): 사례 연구, 실제 적용, 성공/실패 사례

각 쿼리는 한 줄로, 구체적이고 검색 가능하게 작성하세요.
번호나 카테고리 표시 없이 쿼리만 작성하세요.""",

            "en": f"""Generate diverse search queries from various perspectives and angles for the following research topic:

Topic: {original_query}

Research Questions:
{questions_text}

Generate **25 diverse search queries** using the following strategies:

1. Direct Questions (5): Core questions about the topic
2. Related Concepts (5): Associated keywords, similar topics
3. Specific Aspects (5): Technology, market, society, history, future
4. Comparison and Contrast (5): A vs B, pros and cons, alternatives
5. Cases and Practice (5): Case studies, practical applications, success/failure cases

Write each query on one line, specific and searchable.
Write only the queries without numbers or category labels.""",

            "ja": f"""以下の研究テーマについて、様々な観点と角度から検索クエリを生成してください:

テーマ: {original_query}

研究質問:
{questions_text}

以下の戦略で **25個の多様な検索クエリ** を生成してください:

1. 直接質問 (5個): テーマの核心的な質問
2. 関連概念 (5個): 関連キーワード、類似テーマ
3. 特定側面 (5個): 技術、市場、社会、歴史、未来
4. 比較対照 (5個): A vs B、長所短所、代替案
5. 事例と実践 (5個): ケーススタディ、実際の応用、成功/失敗事例

各クエリは1行で、具体的で検索可能に作成してください。
番号やカテゴリ表示なしで、クエリのみを記述してください。"""
        }

        return prompts.get(language, prompts["en"])

    @staticmethod
    def get_gap_query_prompt(gap: str, language: str = "en") -> str:
        """Get prompt for generating gap-filling queries.

        Args:
            gap: Knowledge gap identified
            language: Target language code

        Returns:
            Formatted prompt string
        """
        prompts: Dict[str, str] = {
            "ko": f"""다음 지식 갭을 메우기 위한 구체적인 검색 쿼리 5개를 생성해주세요:

갭: {gap}

각 쿼리는 한 줄로, 구체적이고 검색 가능하게 작성하세요.""",

            "en": f"""Generate 5 specific search queries to fill the following knowledge gap:

Gap: {gap}

Write each query on one line, specific and searchable.""",

            "ja": f"""以下の知識ギャップを埋めるための具体的な検索クエリを5個生成してください:

ギャップ: {gap}

各クエリは1行で、具体的で検索可能に作成してください。"""
        }

        return prompts.get(language, prompts["en"])
