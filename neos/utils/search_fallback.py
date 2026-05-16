from typing import List, Dict, Any, Optional
import difflib
import re
import asyncio
import time
from sqlalchemy import text
from neos.database.connection import db_manager
import logging


logger = logging.getLogger(__name__)


class SearchFallbackDetailed:
    """개선된 검색 fallback 시스템 - 상세 분석 포함"""
    
    def __init__(self):
        # 검색 통계 수집을 위한 카운터
        self.stats = {
            "vector_searches": 0,
            "keyword_searches": 0,
            "hybrid_searches": 0,
            "total_time": 0.0,
            "cache_hits": 0
        }
    
    async def vector_only_search(
        self, 
        query_embedding: List[float], 
        limit: int = 5,
        similarity_threshold: float = 0.4
    ) -> List[Dict[str, Any]]:
        """
        벡터 유사도만 사용한 순수 검색
        
        Args:
            query_embedding: 3072차원 벡터 임베딩
            limit: 최대 결과 수
            similarity_threshold: 유사도 임계값 (0.0~1.0)
        
        Returns:
            검색 결과 리스트 (점수 내림차순)
        
        동작 원리:
        1. 코사인 거리(<=> 연산자) 계산
        2. 거리를 유사도로 변환 (1 - distance)
        3. 임계값 이상의 결과만 필터링
        4. ivfflat 인덱스로 고속 검색
        """
        start_time = time.time()
        self.stats["vector_searches"] += 1
        
        if not query_embedding:
            logger.warning("No query embedding provided for vector search")
            return []
            
        async with db_manager.get_session() as session:
            try:
                # 핵심 SQL: 벡터 유사도 검색
                sql = text("""
                    -- 벡터 검색 쿼리 분석
                    SELECT 
                        original_query,
                        search_results,
                        response_quality_score,
                        created_at,
                        
                        -- 코사인 거리 계산 (0~2 범위, 0이 가장 유사)
                        query_vector::halfvec(3072) <=> :query_vector::halfvec(3072) as distance,
                        
                        -- 유사도로 변환 (0~1 범위 보장, 1이 가장 유사)
                        GREATEST(0, 1 - (query_vector::halfvec(3072) <=> :query_vector::halfvec(3072))) as similarity,
                        
                        -- 벡터 차원 확인 (디버그용)
                        array_length(query_vector, 1) as vector_dimension
                        
                    FROM query_history
                    WHERE 
                        -- 벡터가 존재하는 행만
                        query_vector IS NOT NULL
                        
                        -- 임계값 이상의 유사도만 (성능 최적화)
                        AND 1 - (query_vector::halfvec(3072) <=> :query_vector::halfvec(3072)) > :threshold
                        
                        -- 최근 데이터 우선 (선택적)
                        AND created_at > NOW() - INTERVAL '1 year'
                    
                    -- 가장 유사한 것부터 정렬 (거리 오름차순 = 유사도 내림차순)
                    ORDER BY query_vector::halfvec(3072) <=> :query_vector::halfvec(3072) ASC
                    
                    -- 결과 수 제한
                    LIMIT :limit
                """)
                
                # 파라미터 바인딩
                params = {
                    "query_vector": f"[{','.join(str(x) for x in query_embedding)}]",
                    "threshold": similarity_threshold,
                    "limit": limit
                }
                
                result = await session.execute(sql, params)
                rows = result.fetchall()
                
                # 결과 처리 및 메타데이터 추가
                results = []
                for row in rows:
                    similarity_score = float(row.similarity)
                    distance_score = float(row.distance)
                    
                    # 유사도가 임계값을 만족하는지 재확인
                    if similarity_score >= similarity_threshold:
                        results.append({
                            "title": row.original_query,
                            "content": str(row.search_results) if row.search_results else "",
                            "score": similarity_score,
                            "metadata": {
                                "quality_score": row.response_quality_score,
                                "vector_distance": distance_score,
                                "vector_dimension": row.vector_dimension,
                                "search_method": "vector_only",
                                "created_at": row.created_at.isoformat() if row.created_at else None,
                                "execution_time_ms": (time.time() - start_time) * 1000
                            }
                        })
                
                # 통계 업데이트
                self.stats["total_time"] += time.time() - start_time
                
                logger.info(f"Vector search found {len(results)} results in {(time.time() - start_time)*1000:.1f}ms")
                return results
                
            except Exception as e:
                logger.error(f"Vector search error: {e}")
                return []
    
    async def keyword_based_search(
        self, 
        query: str, 
        limit: int = 5,
        min_keyword_length: int = 2
    ) -> List[Dict[str, Any]]:
        """
        키워드 기반 fallback 검색
        
        동작 원리:
        1. 쿼리에서 의미있는 키워드 추출
        2. 불용어 및 짧은 단어 제거
        3. OR 조건으로 LIKE 패턴 매칭
        4. 키워드 매칭도와 문자열 유사도 결합
        """
        start_time = time.time()
        self.stats["keyword_searches"] += 1
        
        if not query or len(query.strip()) < 2:
            logger.warning("Query too short for keyword search")
            return []
        
        # 1단계: 키워드 추출 및 전처리
        keywords = self._extract_keywords_advanced(query, min_keyword_length)
        if not keywords:
            logger.warning(f"No valid keywords extracted from query: {query}")
            return []
        
        logger.debug(f"Extracted keywords: {keywords}")
        
        async with db_manager.get_session() as session:
            try:
                # 2단계: 동적 SQL 쿼리 생성
                where_conditions = []
                params = {"limit": limit}
                
                # 각 키워드별로 LIKE 조건 생성
                for i, keyword in enumerate(keywords[:5]):  # 최대 5개 키워드 (성능 고려)
                    param_name = f"keyword_{i}"
                    where_conditions.append(f"LOWER(original_query) LIKE LOWER(:{param_name})")
                    params[param_name] = f"%{keyword}%"
                
                # OR 조건으로 결합
                where_clause = " OR ".join(where_conditions)
                
                params["fetch_limit"] = limit * 2

                # 3단계: SQL 실행
                sql = text(f"""
                    SELECT
                        original_query,
                        search_results,
                        response_quality_score,
                        created_at
                    FROM query_history
                    WHERE
                        ({where_clause})
                        AND created_at > NOW() - INTERVAL '2 years'
                    ORDER BY created_at DESC
                    LIMIT :fetch_limit
                """)
                
                result = await session.execute(sql, params)
                rows = result.fetchall()
                
                # 4단계: 유사도 계산 및 정렬
                results = []
                for row in rows:
                    # 키워드 기반 유사도 계산
                    similarity_score = self._calculate_keyword_similarity_advanced(
                        query, row.original_query, keywords
                    )
                    
                    # 매칭된 키워드 식별
                    matched_keywords = [
                        keyword for keyword in keywords 
                        if keyword.lower() in row.original_query.lower()
                    ]
                    
                    results.append({
                        "title": row.original_query,
                        "content": str(row.search_results) if row.search_results else "",
                        "score": similarity_score,
                        "metadata": {
                            "quality_score": row.response_quality_score,
                            "search_method": "keyword_based",
                            "matched_keywords": matched_keywords,
                            "keyword_match_count": len(matched_keywords),
                            "total_keywords": len(keywords),
                            "match_ratio": len(matched_keywords) / len(keywords),
                            "created_at": row.created_at.isoformat() if row.created_at else None,
                            "execution_time_ms": (time.time() - start_time) * 1000
                        }
                    })
                
                # 5단계: 유사도 순으로 정렬 후 제한
                results.sort(key=lambda x: x["score"], reverse=True)
                final_results = results[:limit]
                
                self.stats["total_time"] += time.time() - start_time
                
                logger.info(f"Keyword search found {len(final_results)} results in {(time.time() - start_time)*1000:.1f}ms")
                return final_results
                
            except Exception as e:
                logger.error(f"Keyword search error: {e}")
                return []
    
    def _extract_keywords_advanced(self, query: str, min_length: int = 2) -> List[str]:
        """
        고급 키워드 추출 로직
        
        처리 단계:
        1. 정규식으로 유효한 문자만 추출
        2. 불용어 사전으로 필터링
        3. 최소 길이 적용
        4. 중요도 기반 정렬 (선택적)
        """
        # 확장된 불용어 사전
        stop_words_korean = {
            "그", "그것", "그런", "그러나", "그래서", "그리고", "그때", "그동안",
            "의", "이", "가", "을", "를", "에", "에서", "에게", "로", "으로", "와", "과",
            "는", "은", "도", "만", "부터", "까지", "대해", "대한", "관한", "관련",
            "하는", "한", "할", "했", "해", "하여", "하면", "하지만", "그냥", "좀", "잘"
        }
        
        stop_words_english = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", 
            "of", "with", "by", "from", "up", "about", "into", "through", "during",
            "before", "after", "above", "below", "between", "among", "this", "that",
            "these", "those", "i", "you", "he", "she", "it", "we", "they", "me",
            "him", "her", "us", "them", "my", "your", "his", "her", "its", "our", "their"
        }
        
        stop_words = stop_words_korean.union(stop_words_english)
        
        # 1. 정규식으로 유효한 단어만 추출 (한글, 영문, 숫자, 하이픈 허용)
        pattern = r'[가-힣a-zA-Z0-9\-]+'
        words = re.findall(pattern, query)
        
        # 2. 필터링 및 정규화
        keywords = []
        for word in words:
            # 소문자 변환
            word_lower = word.lower()
            
            # 길이 및 불용어 검사
            if (len(word) >= min_length and 
                word_lower not in stop_words and
                not word.isdigit() and  # 순수 숫자 제외
                not re.match(r'^[0-9\-]+$', word)):  # 날짜 형식 제외
                
                keywords.append(word)
        
        # 3. 중복 제거 (대소문자 구분 없이)
        unique_keywords = []
        seen_lower = set()
        for keyword in keywords:
            if keyword.lower() not in seen_lower:
                unique_keywords.append(keyword)
                seen_lower.add(keyword.lower())
        
        return unique_keywords
    
    def _calculate_keyword_similarity_advanced(
        self, 
        query1: str, 
        query2: str, 
        keywords: List[str]
    ) -> float:
        """
        고급 키워드 유사도 계산
        
        계산 요소:
        1. Jaccard 유사도 (키워드 집합 기반)
        2. 문자열 유사도 (전체 문자열 비교)
        3. 키워드 위치 유사도 (순서 고려)
        4. 길이 유사도 (문장 길이 비교)
        """
        query1_lower = query1.lower()
        query2_lower = query2.lower()
        
        # 1. Jaccard 유사도
        keywords1 = set(self._extract_keywords_advanced(query1_lower))
        keywords2 = set(self._extract_keywords_advanced(query2_lower))
        
        if not keywords1 and not keywords2:
            jaccard_score = 1.0  # 둘 다 키워드가 없으면 동일
        elif not keywords1 or not keywords2:
            jaccard_score = 0.0  # 한쪽만 키워드가 없으면 다름
        else:
            intersection = keywords1.intersection(keywords2)
            union = keywords1.union(keywords2)
            jaccard_score = len(intersection) / len(union)
        
        # 2. 전체 문자열 유사도
        string_similarity = difflib.SequenceMatcher(None, query1_lower, query2_lower).ratio()
        
        # 3. 키워드 위치 유사도 (키워드 순서 고려)
        position_score = self._calculate_position_similarity(query1_lower, query2_lower, keywords)
        
        # 4. 길이 유사도
        len1, len2 = len(query1), len(query2)
        length_similarity = 1.0 - abs(len1 - len2) / max(len1, len2, 1)
        
        # 5. 가중 평균 계산
        weights = {
            "jaccard": 0.4,      # 키워드 매칭이 가장 중요
            "string": 0.3,       # 전체 문자열 유사도
            "position": 0.2,     # 키워드 위치
            "length": 0.1        # 길이 유사도
        }
        
        final_score = (
            jaccard_score * weights["jaccard"] +
            string_similarity * weights["string"] +
            position_score * weights["position"] +
            length_similarity * weights["length"]
        )
        
        return min(1.0, max(0.0, final_score))  # 0-1 범위로 클램핑
    
    def _calculate_position_similarity(self, query1: str, query2: str, keywords: List[str]) -> float:
        """키워드 위치 기반 유사도 계산"""
        if not keywords:
            return 0.0
        
        positions1 = []
        positions2 = []
        
        for keyword in keywords:
            keyword_lower = keyword.lower()
            
            # 각 쿼리에서 키워드 위치 찾기
            pos1 = query1.find(keyword_lower)
            pos2 = query2.find(keyword_lower)
            
            if pos1 != -1 and pos2 != -1:
                # 상대적 위치 계산 (0-1 범위)
                rel_pos1 = pos1 / max(len(query1), 1)
                rel_pos2 = pos2 / max(len(query2), 1)
                
                positions1.append(rel_pos1)
                positions2.append(rel_pos2)
        
        if not positions1:
            return 0.0
        
        # 위치 차이의 평균 계산
        position_diffs = [abs(p1 - p2) for p1, p2 in zip(positions1, positions2)]
        avg_diff = sum(position_diffs) / len(position_diffs)
        
        # 차이를 유사도로 변환 (차이가 작을수록 높은 점수)
        return 1.0 - avg_diff
    
    async def hybrid_search_advanced(
        self,
        query: str,
        query_embedding: Optional[List[float]] = None,
        limit: int = 5,
        vector_weight: float = 0.7,
        keyword_weight: float = 0.3
    ) -> List[Dict[str, Any]]:
        """
        고급 하이브리드 검색

        특징:
        1. 가중치 기반 점수 결합
        2. 다양성 보장 (중복 제거 + 다양한 소스)
        3. 적응적 임계값 (결과 품질에 따라 조정)
        4. 성능 모니터링
        """
        start_time = time.time()
        self.stats["hybrid_searches"] += 1

        vector_results = []
        keyword_results = []
        
        # 1단계: 병렬 검색 실행
        search_tasks = []

        if query_embedding:
            search_tasks.append(self.vector_only_search(query_embedding, limit=limit))

        search_tasks.append(self.keyword_based_search(query, limit=limit))

        try:
            search_results = await asyncio.gather(*search_tasks, return_exceptions=True)
            
            # 결과 분류
            if query_embedding and len(search_results) >= 2:
                vector_results = search_results[0] if not isinstance(search_results[0], Exception) else []
                keyword_results = search_results[1] if not isinstance(search_results[1], Exception) else []
            elif len(search_results) >= 1:
                keyword_results = search_results[0] if not isinstance(search_results[0], Exception) else []
            
        except Exception as e:
            logger.error(f"Parallel search execution failed: {e}")
        
        # 2단계: 점수 정규화 및 가중치 적용
        normalized_results = []
        
        # 벡터 결과 처리
        if vector_results:
            max_vector_score = max(r["score"] for r in vector_results) if vector_results else 1.0
            for result in vector_results:
                normalized_score = (result["score"] / max_vector_score) * vector_weight
                result_copy = result.copy()
                result_copy["score"] = normalized_score
                result_copy["metadata"]["score_type"] = "vector_weighted"
                result_copy["metadata"]["original_score"] = result["score"]
                normalized_results.append(result_copy)
        
        # 키워드 결과 처리
        if keyword_results:
            max_keyword_score = max(r["score"] for r in keyword_results) if keyword_results else 1.0
            for result in keyword_results:
                normalized_score = (result["score"] / max_keyword_score) * keyword_weight
                result_copy = result.copy()
                result_copy["score"] = normalized_score
                result_copy["metadata"]["score_type"] = "keyword_weighted"
                result_copy["metadata"]["original_score"] = result["score"]
                normalized_results.append(result_copy)
        
        # 3단계: 중복 제거 및 점수 결합
        unique_results = {}
        for result in normalized_results:
            query_text = result["title"]
            
            if query_text in unique_results:
                # 기존 결과와 결합 (더 높은 점수 또는 점수 합산)
                existing = unique_results[query_text]
                combined_score = max(existing["score"], result["score"])  # 또는 점수 합산
                
                # 메타데이터 결합
                existing["score"] = combined_score
                existing["metadata"]["combined_from"] = existing["metadata"].get("combined_from", []) + [result["metadata"]["score_type"]]
            else:
                unique_results[query_text] = result
        
        # 4단계: 최종 정렬 및 다양성 보장
        final_results = list(unique_results.values())
        final_results.sort(key=lambda x: x["score"], reverse=True)
        
        # 다양성 확보 (같은 소스가 너무 많이 나오지 않도록)
        diverse_results = self._ensure_diversity(final_results, limit)
        
        # 5단계: 통계 업데이트
        execution_time = time.time() - start_time
        self.stats["total_time"] += execution_time
        
        # 결과에 통계 정보 추가
        for result in diverse_results:
            result["metadata"]["hybrid_execution_time_ms"] = execution_time * 1000
            result["metadata"]["vector_results_count"] = len(vector_results)
            result["metadata"]["keyword_results_count"] = len(keyword_results)
        
        logger.info(f"Hybrid search completed: {len(diverse_results)} results in {execution_time*1000:.1f}ms")
        return diverse_results
    
    def _ensure_diversity(self, results: List[Dict], limit: int) -> List[Dict]:
        """결과 다양성 보장"""
        if len(results) <= limit:
            return results
        
        # 간단한 다양성 알고리즘: 연속된 비슷한 결과 방지
        diverse = [results[0]]  # 첫 번째는 항상 포함
        
        for result in results[1:]:
            if len(diverse) >= limit:
                break
            
            # 마지막 추가된 결과와 너무 비슷한지 확인
            last_result = diverse[-1]
            similarity = difflib.SequenceMatcher(
                None, 
                result["title"].lower(), 
                last_result["title"].lower()
            ).ratio()
            
            # 유사도가 0.8 미만이면 추가 (다양성 확보)
            if similarity < 0.8:
                diverse.append(result)
        
        # 공간이 남으면 나머지도 추가
        remaining_slots = limit - len(diverse)
        if remaining_slots > 0:
            for result in results:
                if result not in diverse and remaining_slots > 0:
                    diverse.append(result)
                    remaining_slots -= 1
        
        return diverse
    
    def get_search_statistics(self) -> Dict[str, Any]:
        """검색 통계 반환"""
        total_searches = (
            self.stats["vector_searches"] + 
            self.stats["keyword_searches"] + 
            self.stats["hybrid_searches"]
        )
        
        return {
            **self.stats,
            "total_searches": total_searches,
            "avg_time_per_search": self.stats["total_time"] / max(total_searches, 1),
            "cache_hit_rate": self.stats["cache_hits"] / max(total_searches, 1)
        }
    
    def reset_statistics(self):
        """통계 초기화"""
        self.stats = {
            "vector_searches": 0,
            "keyword_searches": 0, 
            "hybrid_searches": 0,
            "total_time": 0.0,
            "cache_hits": 0
        }


# 전역 인스턴스 (개선된 버전)
search_fallback_detailed = SearchFallbackDetailed()
