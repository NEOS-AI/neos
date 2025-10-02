from typing import Dict, Any, List
import pandas as pd
import re
import numpy as np
from dataclasses import asdict

from neos.workflow.state import AnalysisResult
from neos.utils.llm_factory import create_llm
from neos.utils.llm_wrapper import create_tracked_llm
from langchain_core.messages import HumanMessage

from .base import AnalysisAgent


class DataAnalysisAgent(AnalysisAgent):
    """데이터 분석 에이전트"""
    
    def __init__(self):
        super().__init__(
            name="data_analysis",
            analysis_type="data",
            role="Data Analyst",
            goal="Analyze data patterns, trends, and provide statistical insights",
            backstory="You are a skilled data analyst who can extract meaningful insights from structured and unstructured data."
        )
    
    async def execute(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        if not self.validate_input(query, context):
            return {"success": False, "error": "Invalid input"}

        try:
            # 검색 결과에서 데이터 추출
            search_results = context.get("search_results", [])
            extracted_data = await self._extract_data_from_results(search_results)

            # Extract session and user info from context
            session_id = context.get("session_id", "") if context else ""
            user_id = context.get("user_id", "") if context else ""

            # 데이터 분석 수행 (LLM 사용)
            analysis_results = await self._perform_data_analysis(extracted_data, query, session_id, user_id)

            return self.format_output(asdict(analysis_results), {"analysis_type": "data"})

        except Exception as e:
            return {"success": False, "error": str(e), "agent": self.name}
    
    async def _extract_data_from_results(self, search_results: List) -> Dict[str, Any]:
        """검색 결과에서 데이터 추출"""
        extracted_data = {
            "numerical_data": [],
            "categorical_data": [],
            "temporal_data": [],
            "text_data": []
        }

        for result in search_results:
            # SearchResult 객체 또는 dict 둘 다 지원
            if hasattr(result, 'content'):
                content = result.content
                source = result.source
                metadata = result.metadata if hasattr(result, 'metadata') else {}
            else:
                content = result.get("content", "")
                source = result.get("source", "")
                metadata = result.get("metadata", {})

            # 숫자 데이터 추출 (퍼센트, 달러 포함)
            numbers = re.findall(r'\d+\.?\d*%?|\$\d+\.?\d*[BMK]?', content)
            extracted_data["numerical_data"].extend(numbers)

            # 날짜 데이터 추출
            dates = re.findall(r'\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}', content)
            extracted_data["temporal_data"].extend(dates)

            # 텍스트 데이터 저장
            extracted_data["text_data"].append({
                "source": source,
                "content": content,
                "metadata": metadata
            })

        return extracted_data
    
    async def _perform_data_analysis(self, data: Dict[str, Any], query: str, session_id: str = "", user_id: str = "") -> AnalysisResult:
        """데이터 분석 수행 (LLM 기반 심층 분석 포함)"""
        insights = []
        confidence = 0.0

        # 1. 기본 통계 분석
        numerical_data = data.get("numerical_data", [])
        stats_summary = ""
        if numerical_data:
            numeric_values = self._clean_numeric_data(numerical_data)
            if numeric_values:
                stats = self._calculate_statistics(numeric_values)
                stats_summary = f"수치 통계: 평균 {stats['mean']:.2f}, 중간값 {stats['median']:.2f}, 최소 {stats['min']:.2f}, 최대 {stats['max']:.2f}, 표준편차 {stats['std']:.2f}"
                insights.append(stats_summary)
                confidence += 0.2

        # 2. 텍스트 패턴 분석
        text_data = data.get("text_data", [])
        if text_data:
            patterns = self._analyze_text_patterns(text_data, query)
            insights.extend(patterns)
            confidence += 0.2

        # 3. 시간적 트렌드 분석
        temporal_data = data.get("temporal_data", [])
        if temporal_data:
            trend_insights = self._analyze_temporal_trends(temporal_data)
            insights.extend(trend_insights)
            confidence += 0.2

        # 4. LLM 기반 심층 분석 (핵심 추가!)
        llm_insights = await self._generate_llm_insights(data, query, stats_summary, session_id, user_id)
        if llm_insights:
            insights.extend(llm_insights)
            confidence += 0.4

        return AnalysisResult(
            analysis_type="data_analysis",
            data=data,
            confidence=min(1.0, confidence),
            insights=insights
        )

    async def _generate_llm_insights(self, data: Dict[str, Any], query: str, stats_summary: str, session_id: str = "", user_id: str = "") -> List[str]:
        """LLM을 사용한 심층 인사이트 생성"""
        try:
            # 텍스트 데이터 요약
            text_data = data.get("text_data", [])
            if not text_data:
                return []

            text_content = "\n\n".join([
                f"출처: {item['source']}\n내용: {item['content'][:300]}"
                for item in text_data[:3]  # 최대 3개 소스만
            ])

            # LLM 생성 및 추적
            base_llm = create_llm(temperature=0.3, max_tokens=800)
            llm = create_tracked_llm(
                llm=base_llm,
                session_id=session_id,
                user_id=user_id,
                workflow_step="data_analysis",
                agent_name=self.name,
                tags=["insight_generation", "analysis"]
            )

            prompt = f"""사용자 쿼리: {query}

수집된 데이터 요약:
{stats_summary}

텍스트 정보:
{text_content}

위 데이터를 분석하여 3-5개의 핵심 인사이트를 생성해주세요. 각 인사이트는:
1. 데이터에서 발견된 구체적인 패턴이나 트렌드
2. 실질적인 의미와 시사점
3. 데이터 기반의 객관적 분석

각 인사이트는 한 문장으로 작성하고, 번호 없이 작성해주세요."""

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            insights_text = response.content.strip()

            # 인사이트를 줄 단위로 분리 (빈 줄 제거)
            insights = [line.strip() for line in insights_text.split('\n') if line.strip() and not line.strip().startswith('#')]

            print(f"[DEBUG] LLM generated {len(insights)} insights for data analysis")
            return insights[:5]  # 최대 5개

        except Exception as e:
            print(f"[WARNING] Failed to generate LLM insights: {e}")
            return []
    
    def _clean_numeric_data(self, raw_numbers: List[str]) -> List[float]:
        """숫자 데이터 정제"""
        clean_numbers = []
        for num_str in raw_numbers:
            try:
                # % 기호 제거
                if '%' in num_str:
                    clean_num = float(num_str.replace('%', ''))
                # $ 기호 제거
                elif '$' in num_str:
                    clean_num = float(num_str.replace('$', '').replace(',', ''))
                else:
                    clean_num = float(num_str.replace(',', ''))
                clean_numbers.append(clean_num)
            except ValueError:
                continue
        return clean_numbers
    
    def _calculate_statistics(self, numbers: List[float]) -> Dict[str, float]:
        """기본 통계 계산"""
        if not numbers:
            return {}
        
        return {
            "mean": np.mean(numbers),
            "median": np.median(numbers),
            "std": np.std(numbers),
            "min": np.min(numbers),
            "max": np.max(numbers),
            "count": len(numbers)
        }
    
    def _analyze_text_patterns(self, text_data: List[Dict[str, Any]], query: str) -> List[str]:
        """텍스트 패턴 분석"""
        insights = []
        
        # 키워드 빈도 분석
        all_text = " ".join([item["content"] for item in text_data])
        words = re.findall(r'\b\w+\b', all_text.lower())
        
        # 쿼리 관련 키워드 찾기
        query_words = set(query.lower().split())
        related_words = [word for word in words if any(qw in word for qw in query_words)]
        
        if related_words:
            insights.append(f"쿼리 관련 키워드가 {len(related_words)}회 발견됨")
        
        # 소스별 분석
        sources = {}
        for item in text_data:
            source = item.get("source", "unknown")
            sources[source] = sources.get(source, 0) + 1
        
        if sources:
            main_source = max(sources, key=sources.get)
            insights.append(f"주요 정보 소스: {main_source} ({sources[main_source]}개 결과)")
        
        return insights
    
    def _analyze_temporal_trends(self, dates: List[str]) -> List[str]:
        """시간적 트렌드 분석"""
        insights = []
        
        if dates:
            insights.append(f"시간 관련 데이터 {len(dates)}개 발견")
            
            # 최신 데이터 확인
            try:
                parsed_dates = pd.to_datetime(dates, errors='coerce').dropna()
                if not parsed_dates.empty:
                    latest_date = parsed_dates.max()
                    oldest_date = parsed_dates.min()
                    insights.append(f"데이터 기간: {oldest_date.strftime('%Y-%m-%d')} ~ {latest_date.strftime('%Y-%m-%d')}")
            except Exception as e:
                insights.append(f"시간적 트렌드 분석 중 오류 발생: {str(e)}")

        return insights


class ComparativeAnalysisAgent(AnalysisAgent):
    """비교 분석 에이전트"""
    
    def __init__(self):
        super().__init__(
            name="comparative_analysis",
            analysis_type="comparative",
            role="Comparative Analyst", 
            goal="Compare and contrast different data points, options, or alternatives",
            backstory="You excel at identifying similarities, differences, and relative advantages between different options or datasets."
        )
    
    async def execute(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        if not self.validate_input(query, context):
            return {"success": False, "error": "Invalid input"}
        
        try:
            # 검색 결과 분석
            search_results = context.get("search_results", [])
            comparison_result = await self._perform_comparative_analysis(search_results, query)

            return self.format_output(asdict(comparison_result), {"analysis_type": "comparative"})
            
        except Exception as e:
            return {"success": False, "error": str(e), "agent": self.name}
    
    async def _perform_comparative_analysis(self, search_results: List, query: str) -> AnalysisResult:
        """비교 분석 수행"""
        insights = []
        confidence = 0.0
        
        if len(search_results) < 2:
            return AnalysisResult(
                analysis_type="comparative_analysis",
                data={"message": "비교를 위한 충분한 데이터가 없습니다."},
                confidence=0.1,
                insights=["비교 분석을 위해서는 최소 2개 이상의 데이터 소스가 필요합니다."]
            )
        
        # 소스별 분류
        sources_analysis = self._analyze_by_sources(search_results)
        insights.extend(sources_analysis["insights"])
        confidence += 0.3
        
        # 콘텐츠 유사성 분석
        similarity_analysis = self._analyze_content_similarity(search_results)
        insights.extend(similarity_analysis["insights"])
        confidence += 0.3
        
        # 점수 기반 비교
        score_analysis = self._analyze_by_scores(search_results)
        insights.extend(score_analysis["insights"])
        confidence += 0.2
        
        # 메타데이터 비교
        metadata_analysis = self._analyze_metadata(search_results)
        insights.extend(metadata_analysis["insights"])
        confidence += 0.2
        
        comparison_data = {
            "sources": sources_analysis,
            "similarity": similarity_analysis,
            "scores": score_analysis,
            "metadata": metadata_analysis,
            "total_results": len(search_results)
        }
        
        return AnalysisResult(
            analysis_type="comparative_analysis",
            data=comparison_data,
            confidence=min(1.0, confidence),
            insights=insights
        )
    
    def _analyze_by_sources(self, results: List) -> Dict[str, Any]:
        """소스별 분석"""
        source_groups = {}

        for result in results:
            # SearchResult 객체 또는 dict 둘 다 지원
            if hasattr(result, 'source'):
                source = result.source
                score = result.score if hasattr(result, 'score') else 0
            else:
                source = result.get("source", "unknown")
                score = result.get("score", 0)

            if source not in source_groups:
                source_groups[source] = []
            source_groups[source].append({"result": result, "score": score})

        insights = []
        insights.append(f"총 {len(source_groups)}개의 서로 다른 소스에서 정보 수집")

        for source, items in source_groups.items():
            avg_score = np.mean([item["score"] for item in items])
            insights.append(f"{source}: {len(items)}개 결과, 평균 점수 {avg_score:.2f}")

        return {
            "source_groups": {k: [item["result"] for item in v] for k, v in source_groups.items()},
            "insights": insights
        }
    
    def _analyze_content_similarity(self, results: List) -> Dict[str, Any]:
        """콘텐츠 유사성 분석"""
        insights = []

        # 단어 집합 기반 유사성 계산
        contents = []
        for result in results:
            if hasattr(result, 'content'):
                contents.append(result.content)
            else:
                contents.append(result.get("content", ""))
        
        if len(contents) >= 2:
            # 간단한 Jaccard 유사도 계산
            similarities = []
            for i in range(len(contents)):
                for j in range(i + 1, len(contents)):
                    sim = self._jaccard_similarity(contents[i], contents[j])
                    similarities.append(sim)
            
            if similarities:
                avg_similarity = np.mean(similarities)
                insights.append(f"콘텐츠 평균 유사도: {avg_similarity:.2f}")
                
                if avg_similarity > 0.7:
                    insights.append("결과들이 매우 유사한 정보를 포함")
                elif avg_similarity > 0.3:
                    insights.append("결과들이 적당히 관련된 정보를 포함")
                else:
                    insights.append("결과들이 다양한 관점의 정보를 포함")
        
        return {
            "similarities": similarities if 'similarities' in locals() else [],
            "insights": insights
        }
    
    def _jaccard_similarity(self, text1: str, text2: str) -> float:
        """Jaccard 유사도 계산"""
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        
        if not union:
            return 0.0
        
        return len(intersection) / len(union)
    
    def _analyze_by_scores(self, results: List) -> Dict[str, Any]:
        """점수 기반 분석"""
        scores = []
        for result in results:
            if hasattr(result, 'score'):
                scores.append(result.score)
            else:
                scores.append(result.get("score", 0))

        insights = []

        if scores:
            max_score = max(scores)
            min_score = min(scores)
            avg_score = np.mean(scores)

            insights.append(f"점수 범위: {min_score:.2f} ~ {max_score:.2f} (평균: {avg_score:.2f})")

            # 최고 점수 결과 식별
            best_result = max(results, key=lambda x: x.score if hasattr(x, 'score') else x.get("score", 0))
            if hasattr(best_result, 'title'):
                title = best_result.title
            else:
                title = best_result.get('title', '제목 없음')
            insights.append(f"최고 점수 결과: {title[:50]}...")

        return {
            "scores": scores,
            "statistics": {
                "max": max_score if scores else 0,
                "min": min_score if scores else 0,
                "mean": avg_score if scores else 0
            },
            "insights": insights
        }
    
    def _analyze_metadata(self, results: List) -> Dict[str, Any]:
        """메타데이터 분석"""
        insights = []
        metadata_summary = {}

        for result in results:
            # SearchResult 객체 또는 dict 둘 다 지원
            if hasattr(result, 'metadata'):
                metadata = result.metadata if result.metadata else {}
            else:
                metadata = result.get("metadata", {})

            for key, value in metadata.items():
                if key not in metadata_summary:
                    metadata_summary[key] = []
                metadata_summary[key].append(value)

        for key, values in metadata_summary.items():
            unique_values = len(set(str(v) for v in values if v is not None))
            insights.append(f"{key}: {unique_values}개의 서로 다른 값")

        return {
            "metadata_summary": metadata_summary,
            "insights": insights
        }
