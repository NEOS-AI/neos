"""
Gemini Embedding 2 재임베딩 스크립트

Migration 027 실행 후 NULL이 된 벡터 컬럼을 Gemini Embedding 2로 채웁니다.

사용법:
    python scripts/reembed_to_gemini.py --table all --dry-run
    python scripts/reembed_to_gemini.py --table document_chunks --batch-size 50
    python scripts/reembed_to_gemini.py --table all --batch-size 100

체크포인트: scripts/reembed_checkpoint.json (중단 후 자동 재개)
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncpg
from pgvector.asyncpg import register_vector

from neos.config.settings import settings
from neos.utils.embeddings import EmbeddingManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CHECKPOINT_FILE = Path(__file__).parent / "reembed_checkpoint.json"

# (테이블명, 텍스트 컬럼, 벡터 컬럼, PK 컬럼, 조건부 여부)
TABLE_CONFIGS = [
    ("query_history",          "original_query",      "query_vector",    "id",  False),
    ("trending_queries",       "query_text",          "query_vector",    "id",  False),
    ("document_chunks",        "chunk_text",          "embedding",       "id",  False),
    ("knowledge_graphs",       "entity_description",  "entity_embedding","id",  False),
    ("kg_entities",            "entity_description",  "embedding",       "id",  True),
    ("conversation_embeddings","summary_text",         "summary_embedding","id",  True),
    ("query_cache",            "query_text",          "query_vector",    "id",  False),
    ("tool_registry",          "description",         "embedding",       "id",  False),
    ("long_term_memories",     "content",             "embedding",       "id",  False),
    ("message_embeddings",     "content",             "embedding",       "id",  False),
    ("evidence_claims",        "claim_text",          "embedding",       "id",  True),
]


def load_checkpoint() -> dict:
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE) as f:
            return json.load(f)
    return {}


def save_checkpoint(checkpoint: dict) -> None:
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(checkpoint, f, indent=2)


async def table_exists(conn: asyncpg.Connection, table: str) -> bool:
    result = await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name=$1)", table
    )
    return result


async def reembed_table(
    conn: asyncpg.Connection,
    embedding_manager: EmbeddingManager,
    table: str,
    text_col: str,
    vec_col: str,
    pk_col: str,
    batch_size: int,
    dry_run: bool,
    checkpoint: dict,
) -> int:
    last_id = checkpoint.get(table, 0)
    total_processed = 0

    while True:
        rows = await conn.fetch(
            f"""
            SELECT {pk_col}, {text_col}
            FROM {table}
            WHERE {vec_col} IS NULL
              AND {pk_col} > $1
              AND {text_col} IS NOT NULL
              AND {text_col} != ''
            ORDER BY {pk_col}
            LIMIT $2
            """,
            last_id,
            batch_size,
        )

        if not rows:
            break

        texts = [row[text_col] for row in rows]
        ids = [row[pk_col] for row in rows]

        logger.info(f"[{table}] IDs {ids[0]}~{ids[-1]} 처리 중 ({len(texts)}건)")

        if dry_run:
            logger.info(f"[{table}] dry-run: {len(texts)}건 스킵")
            last_id = ids[-1]
            total_processed += len(texts)
            checkpoint[table] = last_id
            save_checkpoint(checkpoint)
            continue

        embeddings = await embedding_manager.get_embeddings_batch(texts, use_cache=False)

        update_pairs = [
            (emb, row_id)
            for emb, row_id in zip(embeddings, ids)
            if emb is not None
        ]

        if update_pairs:
            await conn.executemany(
                f"UPDATE {table} SET {vec_col} = $1 WHERE {pk_col} = $2",
                [(emb, row_id) for emb, row_id in update_pairs],
            )

        failed = len(texts) - len(update_pairs)
        if failed:
            logger.warning(f"[{table}] {failed}건 임베딩 실패 (None 반환)")

        last_id = ids[-1]
        total_processed += len(texts)
        checkpoint[table] = last_id
        save_checkpoint(checkpoint)
        logger.info(f"[{table}] 누적 {total_processed}건 완료")

    return total_processed


async def main(args: argparse.Namespace) -> None:
    checkpoint = load_checkpoint()

    embedding_manager = EmbeddingManager()
    logger.info(
        f"임베딩 provider: {embedding_manager.provider_name}, "
        f"모델: {embedding_manager.model}, "
        f"차원: {embedding_manager.dimension}"
    )

    db_url = settings.DATABASE_URL
    # asyncpg는 postgresql+asyncpg:// 형식을 지원하지 않으므로 변환
    if db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    elif db_url.startswith("postgresql+psycopg2://"):
        db_url = db_url.replace("postgresql+psycopg2://", "postgresql://", 1)

    conn = await asyncpg.connect(db_url)
    await register_vector(conn)
    try:
        target_tables = TABLE_CONFIGS if args.table == "all" else [
            cfg for cfg in TABLE_CONFIGS if cfg[0] == args.table
        ]

        if not target_tables:
            logger.error(f"알 수 없는 테이블: {args.table}")
            return

        total_all = 0
        for table, text_col, vec_col, pk_col, conditional in target_tables:
            if conditional and not await table_exists(conn, table):
                logger.info(f"[{table}] 테이블 없음, 건너뜀")
                continue

            logger.info(f"=== {table} 재임베딩 시작 ===")
            count = await reembed_table(
                conn, embedding_manager,
                table, text_col, vec_col, pk_col,
                args.batch_size, args.dry_run, checkpoint,
            )
            logger.info(f"=== {table} 완료: {count}건 ===")
            total_all += count

        logger.info(f"\n전체 완료: {total_all}건 처리됨")
        if args.dry_run:
            logger.info("(dry-run 모드: 실제 업데이트 없음)")

    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gemini Embedding 2 재임베딩 스크립트")
    parser.add_argument(
        "--table",
        default="all",
        help="재임베딩할 테이블 이름 또는 'all' (기본값: all)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        dest="batch_size",
        help="배치 크기 (기본값: 100)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="실제 업데이트 없이 시뮬레이션",
    )
    args = parser.parse_args()
    asyncio.run(main(args))
