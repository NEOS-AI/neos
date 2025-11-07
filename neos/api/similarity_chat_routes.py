"""
Similarity Chat Routes
유사도 검색 기반 채팅 API 라우터
"""

from neos.api.handlers.similarity_chat_handlers import router

# 핸들러에서 정의된 라우터를 그대로 export
similarity_chat_router = router
