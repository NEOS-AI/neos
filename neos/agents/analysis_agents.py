from typing import Dict, Any, List
import pandas as pd
import re
import numpy as np

from neos.workflow.state import AnalysisResult

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
            
            # 데이터 분석 수행
            analysis_results = await self._perform_data_analysis(extracted_data, query)
            
            return self.format_output(analysis_results, {"analysis_type": "data"})
            
        except Exception as e:
            return {"success": False, "error": str(e), "agent": self.name}
    
    async def _extract_data_from_results(self, search_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """검색 결과에서 데이터 추출"""
        extracted_data = {
            "numerical_data": [],
            "categorical_data": [],
            "temporal_data": [],
            "text_data": []
        }
        
        for result in search_results:
            content = result.get("content", "")
            
            # 숫자 데이터 추출
            numbers = re.findall(r'\d+\.?\d*%?|\$\d+\.?\d*', content)
            extracted_data["numerical_data"].extend(numbers)
            
            # 날짜 데이터 추출
            dates = re.findall(r'\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}', content)
            extracted_data["temporal_data"].extend(dates)
            
            # 텍스트 데이터 저장
            extracted_data["text_data"].append({
                "source": result.get("source", ""),
                "content": content,
                "metadata": result.get("metadata", {})
            })
        
        return extracted_data
    
    async def _perform_data_analysis(self, data: Dict[str, Any], query: str) -> AnalysisResult:
        """데이터 분석 수행"""
        insights = []
        confidence = 0.0
        
        # 숫자 데이터 분석
        numerical_data = data.get("numerical_data", [])
        if numerical_data:
            numeric_values = self._clean_numeric_data(numerical_data)
            if numeric_values:
                stats = self._calculate_statistics(numeric_values)
                insights.append(f"발견된 수치 데이터: 평균 {stats['mean']:.2f}, 중간값 {stats['median']:.2f}")
                confidence += 0.3
        
        # 텍스트 패턴 분석
        text_data = data.get("text_data", [])
        if text_data:
            patterns = self._analyze_text_patterns(text_data, query)
            insights.extend(patterns)
            confidence += 0.4
        
        # 시간적 트렌드 분석
        temporal_data = data.get("temporal_data", [])
        if temporal_data:
            trend_insights = self._analyze_temporal_trends(temporal_data)
            insights.extend(trend_insights)
            confidence += 0.3
        
        return AnalysisResult(
            analysis_type="data_analysis",
            data=data,
            confidence=min(1.0, confidence),
            insights=insights
        )
    
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
            
            return self.format_output(comparison_result, {"analysis_type": "comparative"})
            
        except Exception as e:
            return {"success": False, "error": str(e), "agent": self.name}
    
    async def _perform_comparative_analysis(self, search_results: List[Dict[str, Any]], query: str) -> AnalysisResult:
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
    
    def _analyze_by_sources(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """소스별 분석"""
        source_groups = {}
        
        for result in results:
            source = result.get("source", "unknown")
            if source not in source_groups:
                source_groups[source] = []
            source_groups[source].append(result)
        
        insights = []
        insights.append(f"총 {len(source_groups)}개의 서로 다른 소스에서 정보 수집")
        
        for source, items in source_groups.items():
            avg_score = np.mean([item.get("score", 0) for item in items])
            insights.append(f"{source}: {len(items)}개 결과, 평균 점수 {avg_score:.2f}")
        
        return {
            "source_groups": source_groups,
            "insights": insights
        }
    
    def _analyze_content_similarity(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """콘텐츠 유사성 분석"""
        insights = []
        
        # 단어 집합 기반 유사성 계산
        contents = [result.get("content", "") for result in results]
        
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
    
    def _analyze_by_scores(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """점수 기반 분석"""
        scores = [result.get("score", 0) for result in results]
        insights = []
        
        if scores:
            max_score = max(scores)
            min_score = min(scores)
            avg_score = np.mean(scores)
            
            insights.append(f"점수 범위: {min_score:.2f} ~ {max_score:.2f} (평균: {avg_score:.2f})")
            
            # 최고 점수 결과 식별
            best_result = max(results, key=lambda x: x.get("score", 0))
            insights.append(f"최고 점수 결과: {best_result.get('title', '제목 없음')[:50]}...")
        
        return {
            "scores": scores,
            "statistics": {
                "max": max_score if scores else 0,
                "min": min_score if scores else 0,
                "mean": avg_score if scores else 0
            },
            "insights": insights
        }
    
    def _analyze_metadata(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """메타데이터 분석"""
        insights = []
        metadata_summary = {}
        
        for result in results:
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
