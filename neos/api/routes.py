from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
import uuid
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from neos.workflow.graph import multi_agent_workflow
from neos.database.connection import db_manager
from neos.database.models import User, QueryHistory
from neos.utils.cache import cache_manager
from neos.utils.embeddings import embedding_manager


# API 라우터 생성
router = APIRouter()


# 요청/응답 모델들
class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=10000, description="사용자 쿼리")
    user_id: Optional[str] = Field(None, description="사용자 ID")
    session_id: Optional[str] = Field(None, description="세션 ID")
    preferences: Optional[Dict[str, Any]] = Field(default_factory=dict, description="사용자 설정")

class QueryResponse(BaseModel):
    success: bool
    response: str
    session_id: str
    query_id: Optional[int] = None
    metadata: Dict[str, Any]
    execution_time_ms: int
    quality_score: float
    errors: List[str] = Field(default_factory=list)

class HealthCheckResponse(BaseModel):
    status: str
    timestamp: str
    services: Dict[str, bool]

class TrendingQuery(BaseModel):
    query_text: str
    search_count: int
    last_searched: str
    category: Optional[str] = None

class RelatedQuery(BaseModel):
    query_text: str
    similarity_score: float
    relation_type: str

# 의존성 함수들
async def get_or_create_user(user_id: str) -> User:
    """사용자 조회 또는 생성"""
    async with db_manager.get_session() as session:
        # 사용자 조회
        result = await session.execute(
            select(User).where(User.user_id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            # 새 사용자 생성
            user = User(user_id=user_id)
            session.add(user)
            try:
                await session.commit()
                await session.refresh(user)
            except IntegrityError:
                await session.rollback()
                # 동시성 문제로 이미 생성된 경우 재조회
                result = await session.execute(
                    select(User).where(User.user_id == user_id)
                )
                user = result.scalar_one_or_none()
        
        return user

async def save_query_history(
    user_id: str,
    session_id: str, 
    original_query: str,
    query_embedding: List[float],
    query_intent: str,
    search_results: List[Any],
    execution_time_ms: int,
    quality_score: float,
    tools_used: List[str]
) -> int:
    """쿼리 히스토리 저장"""
    async with db_manager.get_session() as session:
        query_history = QueryHistory(
            user_id=user_id,
            original_query=original_query,
            query_vector=query_embedding,
            query_intent=query_intent,
            search_results=search_results,
            response_quality_score=quality_score,
            execution_time_ms=execution_time_ms,
            tools_used=tools_used
        )
        
        session.add(query_history)
        await session.commit()
        await session.refresh(query_history)
        
        return query_history.id

# API 엔드포인트들
@router.post("/query", response_model=QueryResponse)
async def process_query(
    request: QueryRequest,
    background_tasks: BackgroundTasks
):
    """
    메인 쿼리 처리 엔드포인트
    멀티 에이전트 워크플로우를 실행하여 사용자 쿼리에 응답
    """
    try:
        # 세션 ID 생성
        session_id = request.session_id or str(uuid.uuid4())
        user_id = request.user_id or f"anonymous_{uuid.uuid4().hex[:8]}"
        
        # 사용자 생성/조회
        await get_or_create_user(user_id)
        
        # 캐시 키 생성
        cache_key = cache_manager.make_key("query_cache", user_id, request.query)
        
        # 캐시에서 확인
        cached_response = await cache_manager.get(cache_key)
        if cached_response and not request.preferences.get("bypass_cache", False):
            return QueryResponse(**cached_response)
        
        # 워크플로우 실행
        workflow_input = {
            "user_id": user_id,
            "session_id": session_id,
            "query": request.query
        }
        
        start_time = datetime.utcnow()
        result = await multi_agent_workflow.execute_workflow(workflow_input)
        end_time = datetime.utcnow()
        
        execution_time = int((end_time - start_time).total_seconds() * 1000)
        
        if result["success"]:
            # 응답 객체 생성
            response = QueryResponse(
                success=True,
                response=result["response"],
                session_id=session_id,
                metadata=result["metadata"],
                execution_time_ms=result["execution_time_ms"],
                quality_score=result["quality_score"],
                errors=result["errors"]
            )
            
            # 백그라운드에서 쿼리 히스토리 저장
            background_tasks.add_task(
                save_query_history_background,
                user_id=user_id,
                session_id=session_id,
                original_query=request.query,
                result=result,
                execution_time_ms=execution_time
            )
            
            # 성공한 응답 캐싱 (1시간)
            if result["quality_score"] > 0.7:
                await cache_manager.set(cache_key, response.dict(), ttl=3600)
            
            return response
            
        else:
            # 에러 응답
            raise HTTPException(
                status_code=500,
                detail=f"Workflow execution failed: {result.get('error', 'Unknown error')}"
            )
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def save_query_history_background(
    user_id: str,
    session_id: str,
    original_query: str,
    result: Dict[str, Any],
    execution_time_ms: int
):
    """백그라운드에서 쿼리 히스토리 저장"""
    try:
        # 임베딩 생성
        query_embedding = await embedding_manager.get_embedding(original_query)
        
        # 사용된 도구들 추출
        tools_used = []
        if "metadata" in result and "agent_types" in result["metadata"]:
            tools_used = result["metadata"]["agent_types"]
        
        # DB에 저장
        await save_query_history(
            user_id=user_id,
            session_id=session_id,
            original_query=original_query,
            query_embedding=query_embedding,
            query_intent="unknown",  # 실제로는 워크플로우 결과에서 추출
            search_results=result.get("metadata", {}),
            execution_time_ms=execution_time_ms,
            quality_score=result.get("quality_score", 0.0),
            tools_used=tools_used
        )
        
    except Exception as e:
        print(f"Failed to save query history: {e}")


@router.get("/health", response_model=HealthCheckResponse)
async def health_check():
    """시스템 헬스 체크"""
    try:
        # 각 서비스 상태 확인
        db_healthy = await db_manager.health_check()
        cache_healthy = await cache_manager.health_check()
        
        # OpenAI API 간단 체크
        try:
            await embedding_manager.get_embedding("test", use_cache=False)
            openai_healthy = True
        except Exception as e:
            openai_healthy = False
            print(f"OpenAI API health check failed: {e}")

        services = {
            "database": db_healthy,
            "cache": cache_healthy,
            "openai": openai_healthy
        }
        
        overall_status = "healthy" if all(services.values()) else "degraded"
        
        return HealthCheckResponse(
            status=overall_status,
            timestamp=datetime.utcnow().isoformat(),
            services=services
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")

@router.get("/trending", response_model=List[TrendingQuery])
async def get_trending_queries(
    time_period: str = "daily",
    limit: int = 10
):
    """인기 검색어 조회"""
    try:
        async with db_manager.get_session() as session:
            from database.models import TrendingQuery as TrendingQueryModel
            
            result = await session.execute(
                select(TrendingQueryModel)
                .where(TrendingQueryModel.time_period == time_period)
                .order_by(TrendingQueryModel.search_count.desc())
                .limit(limit)
            )
            
            trending_queries = result.scalars().all()
            
            return [
                TrendingQuery(
                    query_text=tq.query_text,
                    search_count=tq.search_count,
                    last_searched=tq.last_searched.isoformat(),
                    category=tq.category
                )
                for tq in trending_queries
            ]
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/related/{query_id}", response_model=List[RelatedQuery])
async def get_related_queries(query_id: int, limit: int = 5):
    """연관 검색어 조회"""
    try:
        async with db_manager.get_session() as session:
            from database.models import RelatedQuery as RelatedQueryModel
            
            # 연관 쿼리 조회
            result = await session.execute(
                select(RelatedQueryModel, QueryHistory)
                .join(QueryHistory, RelatedQueryModel.related_query_id == QueryHistory.id)
                .where(RelatedQueryModel.source_query_id == query_id)
                .order_by(RelatedQueryModel.similarity_score.desc())
                .limit(limit)
            )
            
            rows = result.all()
            
            return [
                RelatedQuery(
                    query_text=row.QueryHistory.original_query,
                    similarity_score=row.RelatedQuery.similarity_score,
                    relation_type=row.RelatedQuery.relation_type
                )
                for row in rows
            ]
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/history/{user_id}")
async def get_user_query_history(
    user_id: str,
    limit: int = 20,
    offset: int = 0
):
    """사용자 쿼리 히스토리 조회"""
    try:
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(QueryHistory)
                .where(QueryHistory.user_id == user_id)
                .order_by(QueryHistory.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
            
            histories = result.scalars().all()
            
            return [
                {
                    "id": h.id,
                    "query": h.original_query,
                    "intent": h.query_intent,
                    "quality_score": h.response_quality_score,
                    "execution_time_ms": h.execution_time_ms,
                    "tools_used": h.tools_used,
                    "created_at": h.created_at.isoformat()
                }
                for h in histories
            ]
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/cache/{cache_key}")
async def clear_cache(cache_key: str):
    """특정 캐시 삭제"""
    try:
        success = await cache_manager.delete(cache_key)
        return {"success": success, "message": f"Cache key '{cache_key}' cleared"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/stats/system")
async def get_system_stats():
    """시스템 통계"""
    try:
        async with db_manager.get_session() as session:
            # 총 쿼리 수
            total_queries = await session.execute(
                select(QueryHistory.id).count()
            )
            total_count = total_queries.scalar()
            
            # 오늘의 쿼리 수
            today = datetime.utcnow().date()
            today_queries = await session.execute(
                select(QueryHistory.id)
                .where(QueryHistory.created_at >= today)
                .count()
            )
            today_count = today_queries.scalar()
            
            # 평균 실행 시간
            avg_execution_time = await session.execute(
                select(QueryHistory.execution_time_ms).avg()
            )
            avg_time = avg_execution_time.scalar() or 0
            
            # 평균 품질 점수
            avg_quality = await session.execute(
                select(QueryHistory.response_quality_score).avg()
            )
            avg_quality_score = avg_quality.scalar() or 0
            
            return {
                "total_queries": total_count,
                "today_queries": today_count,
                "avg_execution_time_ms": round(avg_time, 2),
                "avg_quality_score": round(avg_quality_score, 3),
                "timestamp": datetime.utcnow().isoformat()
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 웹소켓 엔드포인트 (실시간 쿼리 처리)
@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket, session_id: str):
    """실시간 쿼리 처리용 웹소켓"""
    await websocket.accept()
    
    try:
        while True:
            # 클라이언트로부터 메시지 수신
            data = await websocket.receive_json()
            
            if data.get("type") == "query":
                query = data.get("query")
                user_id = data.get("user_id", f"ws_{uuid.uuid4().hex[:8]}")
                
                # 진행 상황 전송
                await websocket.send_json({
                    "type": "status",
                    "message": "쿼리 처리 중...",
                    "progress": 10
                })
                
                # 워크플로우 실행
                try:
                    workflow_input = {
                        "user_id": user_id,
                        "session_id": session_id,
                        "query": query
                    }
                    
                    # 진행 상황 업데이트
                    await websocket.send_json({
                        "type": "status", 
                        "message": "에이전트들이 작업 중...",
                        "progress": 50
                    })
                    
                    result = await multi_agent_workflow.execute_workflow(workflow_input)
                    
                    if result["success"]:
                        await websocket.send_json({
                            "type": "result",
                            "response": result["response"],
                            "metadata": result["metadata"],
                            "quality_score": result["quality_score"]
                        })
                    else:
                        await websocket.send_json({
                            "type": "error",
                            "message": f"처리 실패: {result.get('error', 'Unknown error')}"
                        })
                        
                except Exception as e:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"오류 발생: {str(e)}"
                    })
                    
            elif data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
                
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        await websocket.close()
