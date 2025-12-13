"""Topic analysis prompt templates for HyperDeepResearch."""

from typing import Dict


class TopicAnalysisPrompts:
   """Prompts for multi-dimensional topic analysis."""

   @staticmethod
   def get_prompt(query: str, language: str = "en") -> str:
      """Get topic analysis prompt in the specified language.

      Args:
         query: Research topic/query
         language: Target language code ('en', 'ko', 'ja')

      Returns:
         Formatted prompt string
      """
      prompts: Dict[str, str] = {
         "ko": f"""다음 연구 주제를 다차원으로 깊이 있게 분석해주세요:

주제: {query}

다음을 모두 포함하여 분석해주세요:

1. **핵심 개념 분해**
   - 주요 키워드와 그 의미
   - 연관 개념 및 용어
   - 개념 간 관계

2. **다차원 관점**
   - 기술적 관점
   - 경제적/시장적 관점
   - 사회적/문화적 관점
   - 역사적 관점
   - 미래 전망 관점

3. **연구 범위 설정**
   - 지리적 범위 (글로벌/지역)
   - 시간적 범위 (과거/현재/미래)
   - 주제 깊이 (개요/심층)

4. **핵심 연구 질문 (10-15개)**
   - What (무엇): 현상, 정의, 구성요소
   - Why (왜): 원인, 동기, 배경
   - How (어떻게): 메커니즘, 프로세스, 방법
   - Who (누구): 주체, 이해관계자
   - When (언제): 시점, 추세, 변화
   - Where (어디): 지역, 장소, 맥락

5. **잠재적 조사 영역**
   - 데이터가 필요한 영역
   - 전문가 의견이 필요한 영역
   - 사례 연구가 필요한 영역

매우 상세하고 구조화된 분석을 한국어로 작성해주세요.""",

            "en": f"""Conduct a multi-dimensional in-depth analysis of the following research topic:

Topic: {query}

Include all of the following:

1. **Core Concept Decomposition**
   - Key terms and their meanings
   - Related concepts and terminology
   - Relationships between concepts

2. **Multi-Dimensional Perspectives**
   - Technical perspective
   - Economic/market perspective
   - Social/cultural perspective
   - Historical perspective
   - Future outlook perspective

3. **Research Scope Definition**
   - Geographic scope (global/regional)
   - Temporal scope (past/present/future)
   - Topic depth (overview/in-depth)

4. **Core Research Questions (10-15)**
   - What: Phenomena, definitions, components
   - Why: Causes, motivations, background
   - How: Mechanisms, processes, methods
   - Who: Actors, stakeholders
   - When: Timing, trends, changes
   - Where: Regions, locations, contexts

5. **Potential Investigation Areas**
   - Areas requiring data
   - Areas requiring expert opinions
   - Areas requiring case studies

Write a very detailed and structured analysis in English.""",

            "ja": f"""以下の研究テーマについて、多次元的な詳細分析を実施してください:

テーマ: {query}

以下の全てを含めて分析してください:

1. **核心概念の分解**
   - 主要キーワードとその意味
   - 関連概念と用語
   - 概念間の関係

2. **多次元的観点**
   - 技術的観点
   - 経済的/市場的観点
   - 社会的/文化的観点
   - 歴史的観点
   - 将来展望の観点

3. **研究範囲の設定**
   - 地理的範囲（グローバル/地域）
   - 時間的範囲（過去/現在/未来）
   - テーマの深さ（概要/詳細）

4. **核心研究質問（10-15個）**
   - What（何）: 現象、定義、構成要素
   - Why（なぜ）: 原因、動機、背景
   - How（どのように）: メカニズム、プロセス、方法
   - Who（誰）: 主体、利害関係者
   - When（いつ）: 時点、トレンド、変化
   - Where（どこ）: 地域、場所、文脈

5. **潜在的調査領域**
   - データが必要な領域
   - 専門家意見が必要な領域
   - ケーススタディが必要な領域

非常に詳細で構造化された分析を日本語で作成してください。"""
      }

      return prompts.get(language, prompts["en"])
