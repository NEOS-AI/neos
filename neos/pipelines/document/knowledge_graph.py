"""Knowledge Graph extraction from documents using LLM"""

import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict

from neos.config.settings import settings
from neos.utils.logger import get_logger
from neos.utils.llm_factory import get_llm

logger = get_logger(__name__)


@dataclass
class Entity:
    """엔티티 데이터 클래스"""

    entity_id: str
    entity_type: str
    entity_name: str
    entity_description: Optional[str] = None
    properties: Optional[Dict[str, Any]] = None
    confidence_score: float = 0.0
    occurrences: Optional[List[Dict[str, Any]]] = None


@dataclass
class Relation:
    """관계 데이터 클래스"""

    source_entity_id: str
    target_entity_id: str
    relation_type: str
    confidence_score: float = 0.0
    properties: Optional[Dict[str, Any]] = None


@dataclass
class KnowledgeGraphResult:
    """지식 그래프 추출 결과"""

    entities: List[Entity]
    relations: List[Relation]
    metadata: Optional[Dict[str, Any]] = None


class KnowledgeGraphExtractor:
    """LLM을 사용한 지식 그래프 추출"""

    def __init__(
        self,
        model_name: Optional[str] = None,
        min_confidence: float = None,
    ):
        """
        KnowledgeGraphExtractor 초기화

        Args:
            model_name: LLM 모델 이름
            min_confidence: 최소 신뢰도 임계값
        """
        self.model_name = model_name or settings.KG_EXTRACTION_MODEL
        self.min_confidence = min_confidence or settings.KG_MIN_CONFIDENCE
        self.llm = get_llm(model=self.model_name)

        logger.info(
            f"KnowledgeGraphExtractor initialized: model={self.model_name}, min_confidence={self.min_confidence}"
        )

    async def extract(
        self,
        text: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> KnowledgeGraphResult:
        """
        텍스트에서 지식 그래프 추출

        Args:
            text: 추출할 텍스트
            context: 추가 컨텍스트 정보

        Returns:
            KnowledgeGraphResult
        """
        if not text or not text.strip():
            logger.warning("Empty text provided for knowledge graph extraction")
            return KnowledgeGraphResult(entities=[], relations=[])

        try:
            # LLM 프롬프트 구성
            prompt = self._build_extraction_prompt(text, context)

            # LLM 호출
            response = await self.llm.ainvoke(prompt)

            # 응답 파싱
            kg_result = self._parse_llm_response(response.content)

            # 필터링 (신뢰도 기준)
            kg_result = self._filter_by_confidence(kg_result)

            logger.info(
                f"Extracted {len(kg_result.entities)} entities and {len(kg_result.relations)} relations"
            )

            return kg_result

        except Exception as e:
            logger.error(f"Knowledge graph extraction failed: {e}")
            return KnowledgeGraphResult(entities=[], relations=[])

    def _build_extraction_prompt(
        self, text: str, context: Optional[Dict[str, Any]] = None
    ) -> str:
        """지식 그래프 추출 프롬프트 생성"""
        context_info = ""
        if context:
            context_info = f"\n\nAdditional Context:\n{json.dumps(context, indent=2)}"

        prompt = f"""You are an expert knowledge graph extraction system. Extract entities and relationships from the following text.

Instructions:
1. Identify all important entities (people, organizations, concepts, events, locations, etc.)
2. For each entity, provide:
   - A unique ID (use lowercase, underscore-separated format)
   - Entity type (person, organization, concept, event, location, product, etc.)
   - Entity name
   - Brief description
   - Key properties (as key-value pairs)
   - Confidence score (0.0 to 1.0)

3. Identify relationships between entities
4. For each relationship, provide:
   - Source entity ID
   - Target entity ID
   - Relationship type (works_for, founded, located_in, related_to, causes, etc.)
   - Confidence score (0.0 to 1.0)
   - Additional properties if applicable

5. Return the result in the following JSON format:
{{
  "entities": [
    {{
      "entity_id": "john_doe",
      "entity_type": "person",
      "entity_name": "John Doe",
      "entity_description": "CEO of TechCorp",
      "properties": {{"role": "CEO", "age": "45"}},
      "confidence_score": 0.95
    }}
  ],
  "relations": [
    {{
      "source_entity_id": "john_doe",
      "target_entity_id": "techcorp",
      "relation_type": "works_for",
      "confidence_score": 0.90,
      "properties": {{"position": "CEO", "since": "2015"}}
    }}
  ]
}}

Text to analyze:
{text}
{context_info}

Return ONLY the JSON response, no additional text.
"""
        return prompt

    def _parse_llm_response(self, response_text: str) -> KnowledgeGraphResult:
        """LLM 응답 파싱"""
        try:
            # JSON 추출 (마크다운 코드 블록 제거)
            json_text = response_text.strip()
            if json_text.startswith("```json"):
                json_text = json_text[7:]
            if json_text.startswith("```"):
                json_text = json_text[3:]
            if json_text.endswith("```"):
                json_text = json_text[:-3]

            json_text = json_text.strip()

            # JSON 파싱
            data = json.loads(json_text)

            # Entity 객체 생성
            entities = []
            for entity_data in data.get("entities", []):
                entity = Entity(
                    entity_id=entity_data["entity_id"],
                    entity_type=entity_data["entity_type"],
                    entity_name=entity_data["entity_name"],
                    entity_description=entity_data.get("entity_description"),
                    properties=entity_data.get("properties", {}),
                    confidence_score=entity_data.get("confidence_score", 0.0),
                    occurrences=[],
                )
                entities.append(entity)

            # Relation 객체 생성
            relations = []
            for relation_data in data.get("relations", []):
                relation = Relation(
                    source_entity_id=relation_data["source_entity_id"],
                    target_entity_id=relation_data["target_entity_id"],
                    relation_type=relation_data["relation_type"],
                    confidence_score=relation_data.get("confidence_score", 0.0),
                    properties=relation_data.get("properties", {}),
                )
                relations.append(relation)

            return KnowledgeGraphResult(
                entities=entities,
                relations=relations,
                metadata={"raw_response": response_text},
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            logger.debug(f"Response text: {response_text}")
            return KnowledgeGraphResult(entities=[], relations=[])

        except Exception as e:
            logger.error(f"Error parsing LLM response: {e}")
            return KnowledgeGraphResult(entities=[], relations=[])

    def _filter_by_confidence(
        self, kg_result: KnowledgeGraphResult
    ) -> KnowledgeGraphResult:
        """신뢰도 기준으로 필터링"""
        filtered_entities = [
            e for e in kg_result.entities if e.confidence_score >= self.min_confidence
        ]

        # 필터링된 엔티티 ID 세트
        valid_entity_ids = {e.entity_id for e in filtered_entities}

        # 관계 필터링 (유효한 엔티티 + 신뢰도 기준)
        filtered_relations = [
            r
            for r in kg_result.relations
            if r.confidence_score >= self.min_confidence
            and r.source_entity_id in valid_entity_ids
            and r.target_entity_id in valid_entity_ids
        ]

        logger.info(
            f"Filtered: {len(filtered_entities)}/{len(kg_result.entities)} entities, "
            f"{len(filtered_relations)}/{len(kg_result.relations)} relations"
        )

        return KnowledgeGraphResult(
            entities=filtered_entities,
            relations=filtered_relations,
            metadata=kg_result.metadata,
        )

    async def extract_batch(
        self,
        texts: List[str],
        contexts: Optional[List[Dict[str, Any]]] = None,
    ) -> List[KnowledgeGraphResult]:
        """
        여러 텍스트에서 지식 그래프 추출

        Args:
            texts: 추출할 텍스트 리스트
            contexts: 각 텍스트의 컨텍스트 리스트

        Returns:
            KnowledgeGraphResult 리스트
        """
        import asyncio

        if contexts is None:
            contexts = [None] * len(texts)

        tasks = [self.extract(text, context) for text, context in zip(texts, contexts)]
        results = await asyncio.gather(*tasks)

        return results

    def merge_results(
        self, results: List[KnowledgeGraphResult]
    ) -> KnowledgeGraphResult:
        """
        여러 결과를 하나로 병합 (엔티티 중복 제거 및 관계 통합)

        Args:
            results: KnowledgeGraphResult 리스트

        Returns:
            병합된 KnowledgeGraphResult
        """
        entity_map: Dict[str, Entity] = {}
        all_relations: List[Relation] = []

        # 엔티티 병합 (ID 기준)
        for result in results:
            for entity in result.entities:
                if entity.entity_id in entity_map:
                    # 이미 존재하는 엔티티 - 신뢰도가 더 높은 것 선택
                    existing = entity_map[entity.entity_id]
                    if entity.confidence_score > existing.confidence_score:
                        entity_map[entity.entity_id] = entity
                else:
                    entity_map[entity.entity_id] = entity

            # 관계 수집
            all_relations.extend(result.relations)

        # 관계 중복 제거 (source, target, type 조합 기준)
        relation_map: Dict[tuple, Relation] = {}
        for relation in all_relations:
            key = (
                relation.source_entity_id,
                relation.target_entity_id,
                relation.relation_type,
            )
            if key in relation_map:
                # 이미 존재하는 관계 - 신뢰도가 더 높은 것 선택
                existing = relation_map[key]
                if relation.confidence_score > existing.confidence_score:
                    relation_map[key] = relation
            else:
                relation_map[key] = relation

        merged_result = KnowledgeGraphResult(
            entities=list(entity_map.values()),
            relations=list(relation_map.values()),
            metadata={"merged_from": len(results)},
        )

        logger.info(
            f"Merged {len(results)} results into {len(merged_result.entities)} entities "
            f"and {len(merged_result.relations)} relations"
        )

        return merged_result
