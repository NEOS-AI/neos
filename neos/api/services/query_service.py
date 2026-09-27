"""헬스 체크 서비스.

레거시 쿼리 API 의 비즈니스 로직(쿼리 실행·이력·트렌드·HyperResearch 리포트
조회)이 여기 있었다. 그 라우트를 걷어 내면서(2026-09-27) 남은 호출자는
`GET /api/v1/health` 하나다. 클래스 이름은 `neos.api.services` 의 지연 export
가 가리키므로 그대로 둔다.
"""

from datetime import datetime
from typing import Any, Dict

from neos.database.connection import db_manager
from neos.utils.cache import cache_manager
from neos.utils.embeddings import embedding_manager


class QueryService:
    """시스템 헬스 체크"""

    @staticmethod
    async def check_system_health() -> Dict[str, Any]:
        """시스템 헬스 체크"""
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

        return {
            "status": overall_status,
            "timestamp": datetime.now().isoformat(),
            "services": services
        }
