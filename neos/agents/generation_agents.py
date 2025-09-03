from typing import Dict, Any, List
import httpx

from neos.workflow.state import GenerationResult
from neos.config.settings import settings

from .base import GenerationAgent


class ImageGenerationAgent(GenerationAgent):
    """이미지 생성 에이전트"""
    
    def __init__(self):
        super().__init__(
            name="image_generation",
            generation_type="image",
            role="Image Generator",
            goal="Generate images based on text descriptions and requirements",
            backstory="You are skilled at creating detailed prompts for image generation and understanding visual requirements."
        )
    
    async def execute(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        if not self.validate_input(query, context):
            return {"success": False, "error": "Invalid input"}
        
        try:
            # 이미지 생성 요청인지 확인
            if not self._is_image_request(query):
                return {
                    "success": False, 
                    "error": "Query does not appear to be an image generation request"
                }
            
            # 이미지 생성 실행
            image_result = await self._generate_image(query, context)
            
            return self.format_output(image_result, {"generation_type": "image"})
            
        except Exception as e:
            return {"success": False, "error": str(e), "agent": self.name}
    
    def _is_image_request(self, query: str) -> bool:
        """이미지 생성 요청 확인"""
        image_keywords = [
            "이미지", "그림", "사진", "그려", "만들어", "생성", "이미지 생성",
            "image", "picture", "draw", "create", "generate", "visualization"
        ]
        return any(keyword in query.lower() for keyword in image_keywords)
    
    async def _generate_image(self, query: str, context: Dict[str, Any]) -> GenerationResult:
        """이미지 생성"""
        try:
            # OpenAI DALL-E 3 사용
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.openai.com/v1/images/generations",
                    headers={
                        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "dall-e-3",
                        "prompt": self._enhance_prompt(query),
                        "size": "1024x1024",
                        "quality": "standard",
                        "n": 1
                    },
                    timeout=60.0
                )
            
            if response.status_code == 200:
                result = response.json()
                image_url = result["data"][0]["url"]
                
                return GenerationResult(
                    content_type="image",
                    content={
                        "image_url": image_url,
                        "prompt_used": self._enhance_prompt(query),
                        "model": "dall-e-3"
                    },
                    metadata={
                        "size": "1024x1024",
                        "quality": "standard"
                    }
                )
            else:
                raise Exception(f"Image generation failed: {response.text}")
                
        except Exception as e:
            # 실패 시 플레이스홀더 반환
            return GenerationResult(
                content_type="image",
                content={
                    "error": str(e),
                    "placeholder": "이미지 생성에 실패했습니다."
                }
            )
    
    def _enhance_prompt(self, query: str) -> str:
        """프롬프트 개선"""
        base_prompt = query
        
        # 스타일 및 품질 향상 키워드 추가
        enhancements = [
            "high quality", "detailed", "professional",
            "clear", "well-composed", "aesthetic"
        ]
        
        enhanced = f"{base_prompt}, {', '.join(enhancements)}"
        return enhanced[:1000]  # 프롬프트 길이 제한

class ApiCallAgent(GenerationAgent):
    """API 호출 에이전트"""
    
    def __init__(self):
        super().__init__(
            name="api_call",
            generation_type="api",
            role="API Integration Specialist",
            goal="Make API calls to external services and integrate third-party data",
            backstory="You specialize in integrating with various APIs and handling external service communications."
        )
    
    async def execute(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        if not self.validate_input(query, context):
            return {"success": False, "error": "Invalid input"}
        
        try:
            # API 호출이 필요한지 판단
            api_requirements = self._analyze_api_requirements(query)
            
            if not api_requirements["needs_api"]:
                return {
                    "success": False,
                    "error": "Query does not require API integration"
                }
            
            # API 호출 실행
            api_result = await self._make_api_calls(api_requirements, context)
            
            return self.format_output(api_result, {"generation_type": "api"})
            
        except Exception as e:
            return {"success": False, "error": str(e), "agent": self.name}
    
    def _analyze_api_requirements(self, query: str) -> Dict[str, Any]:
        """API 요구사항 분석"""
        api_indicators = {
            "weather": ["날씨", "기온", "weather", "temperature"],
            "currency": ["환율", "currency", "exchange rate"],
            "stock": ["주식", "stock", "주가", "market"],
            "news": ["뉴스", "news", "최신"],
            "translation": ["번역", "translate", "translation"]
        }
        
        detected_apis = []
        for api_type, keywords in api_indicators.items():
            if any(keyword in query.lower() for keyword in keywords):
                detected_apis.append(api_type)
        
        return {
            "needs_api": len(detected_apis) > 0,
            "api_types": detected_apis,
            "priority": detected_apis[0] if detected_apis else None
        }
    
    async def _make_api_calls(self, requirements: Dict[str, Any], context: Dict[str, Any]) -> GenerationResult:
        """API 호출 실행"""
        results = []
        
        for api_type in requirements["api_types"]:
            try:
                if api_type == "weather":
                    result = await self._call_weather_api(context)
                elif api_type == "currency":
                    result = await self._call_currency_api(context)
                elif api_type == "stock":
                    result = await self._call_stock_api(context)
                else:
                    result = {"error": f"Unsupported API type: {api_type}"}
                
                results.append({
                    "api_type": api_type,
                    "result": result
                })
                
            except Exception as e:
                results.append({
                    "api_type": api_type,
                    "error": str(e)
                })
        
        return GenerationResult(
            content_type="api_data",
            content={"api_calls": results},
            metadata={"total_calls": len(results)}
        )
    
    async def _call_weather_api(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """날씨 API 호출 (예시)"""
        # 실제 구현에서는 OpenWeatherMap 등의 API 사용
        return {
            "location": "Seoul",
            "temperature": "15°C",
            "condition": "Partly Cloudy",
            "note": "This is a mock weather response"
        }
    
    async def _call_currency_api(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """환율 API 호출 (예시)"""
        return {
            "base": "USD",
            "target": "KRW",
            "rate": 1320.50,
            "note": "This is a mock currency response"
        }
    
    async def _call_stock_api(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """주식 API 호출 (예시)"""
        return {
            "symbol": "AAPL",
            "price": 175.25,
            "change": "+2.15",
            "note": "This is a mock stock response"
        }

class FileProcessingAgent(GenerationAgent):
    """파일 처리 에이전트"""
    
    def __init__(self):
        super().__init__(
            name="file_processing",
            generation_type="file",
            role="File Processing Specialist",
            goal="Process, analyze, and manipulate various types of files",
            backstory="You are expert at handling different file formats and extracting meaningful information from documents."
        )
    
    async def execute(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        if not self.validate_input(query, context):
            return {"success": False, "error": "Invalid input"}
        
        try:
            # 파일 처리 요청인지 확인
            file_requirements = self._analyze_file_requirements(query)
            
            if not file_requirements["needs_file_processing"]:
                return {
                    "success": False,
                    "error": "Query does not require file processing"
                }
            
            # 파일 처리 실행
            processing_result = await self._process_files(file_requirements, context)
            
            return self.format_output(processing_result, {"generation_type": "file"})
            
        except Exception as e:
            return {"success": False, "error": str(e), "agent": self.name}
    
    def _analyze_file_requirements(self, query: str) -> Dict[str, Any]:
        """파일 처리 요구사항 분석"""
        file_keywords = [
            "파일", "문서", "엑셀", "pdf", "csv", "분석",
            "file", "document", "excel", "spreadsheet", "analyze"
        ]
        
        processing_types = {
            "analysis": ["분석", "analyze", "analysis", "통계"],
            "conversion": ["변환", "convert", "transformation"],
            "extraction": ["추출", "extract", "parsing"],
            "summary": ["요약", "summary", "summarize"]
        }
        
        needs_processing = any(keyword in query.lower() for keyword in file_keywords)
        
        detected_types = []
        for proc_type, keywords in processing_types.items():
            if any(keyword in query.lower() for keyword in keywords):
                detected_types.append(proc_type)
        
        return {
            "needs_file_processing": needs_processing,
            "processing_types": detected_types,
            "priority": detected_types[0] if detected_types else "analysis"
        }
    
    async def _process_files(self, requirements: Dict[str, Any], context: Dict[str, Any]) -> GenerationResult:
        """파일 처리 실행"""
        # 실제 구현에서는 업로드된 파일을 처리
        # 여기서는 예시 결과 반환
        
        processing_results = []
        
        for proc_type in requirements["processing_types"]:
            if proc_type == "analysis":
                result = {
                    "type": "data_analysis",
                    "summary": "파일 데이터 분석 완료",
                    "statistics": {"rows": 1000, "columns": 15}
                }
            elif proc_type == "extraction":
                result = {
                    "type": "data_extraction",
                    "extracted_data": {"key_fields": ["name", "date", "value"]},
                    "success_rate": 0.95
                }
            else:
                result = {
                    "type": proc_type,
                    "message": f"{proc_type} 처리 완료"
                }
            
            processing_results.append(result)
        
        return GenerationResult(
            content_type="file_processing",
            content={"processing_results": processing_results},
            metadata={
                "total_operations": len(processing_results),
                "processing_types": requirements["processing_types"]
            }
        )

class TaskCreationAgent(GenerationAgent):
    """작업 생성 에이전트"""
    
    def __init__(self):
        super().__init__(
            name="task_creation",
            generation_type="task",
            role="Task Creation Specialist",
            goal="Create structured tasks, workflows, and action plans based on user requirements",
            backstory="You excel at breaking down complex requirements into actionable tasks and creating organized workflows."
        )
    
    async def execute(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        if not self.validate_input(query, context):
            return {"success": False, "error": "Invalid input"}
        
        try:
            # 작업 생성 요청인지 확인
            task_requirements = self._analyze_task_requirements(query)
            
            if not task_requirements["needs_task_creation"]:
                return {
                    "success": False,
                    "error": "Query does not require task creation"
                }
            
            # 작업 생성 실행
            task_result = await self._create_tasks(task_requirements, context)
            
            return self.format_output(task_result, {"generation_type": "task"})
            
        except Exception as e:
            return {"success": False, "error": str(e), "agent": self.name}
    
    def _analyze_task_requirements(self, query: str) -> Dict[str, Any]:
        """작업 생성 요구사항 분석"""
        task_keywords = [
            "작업", "계획", "할일", "단계", "프로세스",
            "task", "plan", "todo", "step", "process", "workflow"
        ]
        
        task_types = {
            "project": ["프로젝트", "project"],
            "research": ["연구", "조사", "research", "study"],
            "analysis": ["분석", "analysis", "analyze"],
            "development": ["개발", "development", "build", "create"]
        }
        
        needs_tasks = any(keyword in query.lower() for keyword in task_keywords)
        
        detected_types = []
        for task_type, keywords in task_types.items():
            if any(keyword in query.lower() for keyword in keywords):
                detected_types.append(task_type)
        
        return {
            "needs_task_creation": needs_tasks,
            "task_types": detected_types,
            "complexity": self._assess_complexity(query)
        }
    
    def _assess_complexity(self, query: str) -> str:
        """작업 복잡도 평가"""
        complex_indicators = ["복잡", "상세", "완전", "comprehensive", "detailed", "complex"]
        simple_indicators = ["간단", "빠른", "기본", "simple", "quick", "basic"]
        
        if any(indicator in query.lower() for indicator in complex_indicators):
            return "high"
        elif any(indicator in query.lower() for indicator in simple_indicators):
            return "low"
        else:
            return "medium"
    
    async def _create_tasks(self, requirements: Dict[str, Any], context: Dict[str, Any]) -> GenerationResult:
        """작업 생성 실행"""
        complexity = requirements["complexity"]
        task_types = requirements["task_types"]
        
        # 복잡도에 따른 작업 생성
        if complexity == "high":
            tasks = self._generate_detailed_tasks(task_types)
        elif complexity == "low":
            tasks = self._generate_simple_tasks(task_types)
        else:
            tasks = self._generate_standard_tasks(task_types)
        
        return GenerationResult(
            content_type="task_list",
            content={
                "tasks": tasks,
                "total_tasks": len(tasks),
                "estimated_duration": self._estimate_duration(tasks)
            },
            metadata={
                "complexity": complexity,
                "task_types": task_types
            }
        )
    
    def _generate_detailed_tasks(self, task_types: List[str]) -> List[Dict[str, Any]]:
        """상세 작업 목록 생성"""
        return [
            {
                "id": 1,
                "title": "요구사항 분석 및 정의",
                "description": "프로젝트의 상세 요구사항을 분석하고 명확히 정의합니다.",
                "priority": "high",
                "estimated_hours": 8,
                "dependencies": []
            },
            {
                "id": 2,
                "title": "리서치 및 조사",
                "description": "관련 기술, 도구, 방법론에 대한 심층 조사를 진행합니다.",
                "priority": "high", 
                "estimated_hours": 16,
                "dependencies": [1]
            },
            {
                "id": 3,
                "title": "설계 및 계획 수립",
                "description": "전체 시스템 설계와 구현 계획을 수립합니다.",
                "priority": "medium",
                "estimated_hours": 12,
                "dependencies": [1, 2]
            }
        ]
    
    def _generate_simple_tasks(self, task_types: List[str]) -> List[Dict[str, Any]]:
        """간단한 작업 목록 생성"""
        return [
            {
                "id": 1,
                "title": "기본 조사",
                "description": "필요한 정보를 빠르게 조사합니다.",
                "priority": "medium",
                "estimated_hours": 2,
                "dependencies": []
            },
            {
                "id": 2,
                "title": "실행 및 완료",
                "description": "조사한 내용을 바탕으로 작업을 실행합니다.",
                "priority": "high",
                "estimated_hours": 4,
                "dependencies": [1]
            }
        ]
    
    def _generate_standard_tasks(self, task_types: List[str]) -> List[Dict[str, Any]]:
        """표준 작업 목록 생성"""
        return [
            {
                "id": 1,
                "title": "계획 수립",
                "description": "작업 계획을 수립합니다.",
                "priority": "high",
                "estimated_hours": 4,
                "dependencies": []
            },
            {
                "id": 2,
                "title": "자료 수집",
                "description": "필요한 자료와 정보를 수집합니다.",
                "priority": "medium",
                "estimated_hours": 6,
                "dependencies": [1]
            },
            {
                "id": 3,
                "title": "분석 및 실행",
                "description": "수집한 자료를 분석하고 작업을 실행합니다.",
                "priority": "high",
                "estimated_hours": 8,
                "dependencies": [2]
            }
        ]
    
    def _estimate_duration(self, tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """소요 시간 추정"""
        total_hours = sum(task.get("estimated_hours", 0) for task in tasks)
        
        return {
            "total_hours": total_hours,
            "total_days": total_hours // 8,
            "working_weeks": total_hours // 40
        }
