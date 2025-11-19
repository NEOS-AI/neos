"""
워크플로우 스케줄러

주기적인 유지보수 작업을 자동으로 실행합니다.
"""
import asyncio
import logging
from typing import Optional
from datetime import datetime

from .checkpointer import get_checkpointer
from ..config.settings import settings

logger = logging.getLogger(__name__)


class WorkflowScheduler:
    """
    워크플로우 유지보수 작업 스케줄러

    - 체크포인트 자동 정리
    - 캐시 정리
    - 통계 수집
    """

    def __init__(
        self,
        cleanup_interval: int = 86400,  # 24시간 (초)
        cleanup_days: int = 30,  # 30일 이상 된 체크포인트 삭제
        enabled: bool = True
    ):
        """
        Args:
            cleanup_interval: 정리 작업 실행 간격 (초)
            cleanup_days: 유지할 체크포인트 기간 (일)
            enabled: 스케줄러 활성화 여부
        """
        self.cleanup_interval = cleanup_interval
        self.cleanup_days = cleanup_days
        self.enabled = enabled
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """스케줄러 시작"""
        if not self.enabled:
            logger.info("워크플로우 스케줄러 비활성화됨")
            return

        if self._running:
            logger.warning("워크플로우 스케줄러가 이미 실행 중입니다")
            return

        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info(
            f"워크플로우 스케줄러 시작: "
            f"정리 간격={self.cleanup_interval}초, "
            f"보관 기간={self.cleanup_days}일"
        )

    async def stop(self):
        """스케줄러 중지"""
        if not self._running:
            return

        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("워크플로우 스케줄러 중지")

    async def _run(self):
        """스케줄러 메인 루프"""
        logger.info("스케줄러 메인 루프 시작")

        while self._running:
            try:
                # 정리 작업 실행
                await self._cleanup_task()

                # 다음 실행까지 대기
                await asyncio.sleep(self.cleanup_interval)

            except asyncio.CancelledError:
                logger.info("스케줄러 취소됨")
                break
            except Exception as e:
                logger.error(f"스케줄러 에러: {e}", exc_info=True)
                # 에러 발생 시 1시간 대기 후 재시도
                await asyncio.sleep(3600)

    async def _cleanup_task(self):
        """정리 작업 실행"""
        try:
            start_time = datetime.utcnow()
            logger.info("=" * 50)
            logger.info("체크포인트 자동 정리 작업 시작")
            logger.info(f"실행 시각: {start_time.isoformat()}")

            # 체크포인트 정리
            checkpointer = await get_checkpointer()

            # 통계 조회 (정리 전)
            stats_before = await checkpointer.get_stats()
            logger.info(
                f"정리 전 통계: "
                f"총 체크포인트={stats_before['total_checkpoints']}, "
                f"고유 스레드={stats_before['unique_threads']}"
            )

            # 오래된 체크포인트 삭제
            deleted_count = await checkpointer.cleanup_old_checkpoints(
                days=self.cleanup_days
            )

            # 통계 조회 (정리 후)
            stats_after = await checkpointer.get_stats()
            logger.info(
                f"정리 후 통계: "
                f"총 체크포인트={stats_after['total_checkpoints']}, "
                f"고유 스레드={stats_after['unique_threads']}"
            )

            # 실행 시간 계산
            execution_time = (datetime.utcnow() - start_time).total_seconds()

            logger.info(
                f"✅ 체크포인트 정리 완료: "
                f"{deleted_count}개 삭제, "
                f"실행 시간={execution_time:.2f}초"
            )
            logger.info("=" * 50)

        except Exception as e:
            logger.error(f"체크포인트 정리 작업 실패: {e}", exc_info=True)

    async def run_now(self):
        """정리 작업 즉시 실행 (테스트용)"""
        logger.info("체크포인트 정리 작업 수동 실행")
        await self._cleanup_task()


# 전역 스케줄러 인스턴스
_scheduler: Optional[WorkflowScheduler] = None


async def get_scheduler() -> WorkflowScheduler:
    """
    전역 스케줄러 인스턴스 가져오기

    Returns:
        WorkflowScheduler: 스케줄러 인스턴스
    """
    global _scheduler

    if _scheduler is None:
        _scheduler = WorkflowScheduler(
            cleanup_interval=86400,  # 24시간
            cleanup_days=30,  # 30일
            enabled=True
        )

    return _scheduler


async def start_scheduler():
    """스케줄러 시작 (애플리케이션 시작 시 호출)"""
    scheduler = await get_scheduler()
    await scheduler.start()


async def stop_scheduler():
    """스케줄러 중지 (애플리케이션 종료 시 호출)"""
    global _scheduler

    if _scheduler:
        await _scheduler.stop()
        _scheduler = None
