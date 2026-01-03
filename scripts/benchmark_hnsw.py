#!/usr/bin/env python3
"""
HNSW Index Performance Benchmark Script

이 스크립트는 pgvector의 IVFFlat과 HNSW 인덱스 성능을 비교합니다.
마이그레이션 전후의 성능 향상을 측정하고 통계를 제공합니다.

Usage:
    python scripts/benchmark_hnsw.py
    python scripts/benchmark_hnsw.py --queries 100 --warmup 10
"""

import asyncio
import time
import statistics
from typing import List, Dict, Tuple
import argparse
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import sys

sys.path.append('.')
sys.path.append('..')

from neos.config.settings import Settings


class HNSWBenchmark:
    """HNSW 인덱스 성능 벤치마크"""

    def __init__(self, database_url: str):
        self.engine = create_async_engine(database_url, echo=False)
        self.async_session = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
        self.results: Dict[str, List[float]] = {
            'ivfflat': [],
            'hnsw': []
        }

    async def check_index_type(self) -> str:
        """현재 사용 중인 인덱스 타입 확인"""
        async with self.async_session() as session:
            query = text("""
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE tablename = 'query_cache'
                AND indexname LIKE '%vector%'
            """)
            result = await session.execute(query)
            indexes = result.fetchall()

            for idx_name, idx_def in indexes:
                if 'hnsw' in idx_def.lower():
                    return 'hnsw'
                elif 'ivfflat' in idx_def.lower():
                    return 'ivfflat'

            return 'unknown'

    async def get_sample_vectors(self, limit: int = 100) -> List[Tuple[int, List[float]]]:
        """캐시에서 샘플 벡터 가져오기"""
        async with self.async_session() as session:
            query = text("""
                SELECT id, query_vector
                FROM query_cache
                WHERE query_vector IS NOT NULL
                ORDER BY RANDOM()
                LIMIT :limit
            """)
            result = await session.execute(query, {"limit": limit})
            rows = result.fetchall()

            # pgvector array to list 변환
            parsed_vectors = []
            for row in rows:
                vector = row[1]
                # pgvector는 다양한 형태로 반환될 수 있음
                if isinstance(vector, str):
                    # 문자열 형태: '[1.0, 2.0, 3.0]'
                    vector = [float(x) for x in vector.strip('[]').split(',')]
                elif hasattr(vector, '__iter__'):
                    # 이미 리스트/배열 형태
                    vector = [float(x) for x in vector]
                else:
                    continue
                parsed_vectors.append((row[0], vector))
            
            return parsed_vectors

    async def benchmark_query(
        self,
        vector: List[float],
        ef_search: int = 40,
        top_k: int = 5
    ) -> Tuple[float, List[int]]:
        """단일 쿼리 성능 측정"""
        async with self.async_session() as session:
            # HNSW 런타임 파라미터 설정
            await session.execute(text(f"SET LOCAL hnsw.ef_search = {ef_search}"))

            start_time = time.perf_counter()

            # 벡터를 PostgreSQL 배열 형식으로 변환 (공백 없이)
            # NaN이나 Inf 값 체크 및 제거
            clean_vector = []
            for v in vector:
                v = float(v)
                if v != v or abs(v) == float('inf'):  # NaN or Inf
                    clean_vector.append(0.0)
                else:
                    clean_vector.append(v)
            vector_str = '[' + ','.join(f'{v:.8f}' for v in clean_vector) + ']'

            # asyncpg의 파라미터 바인딩 문제로 인해 벡터는 직접 포맷팅
            query = text(f"""
                SELECT id, query_vector <=> '{vector_str}'::vector AS distance
                FROM query_cache
                WHERE query_vector IS NOT NULL
                ORDER BY distance
                LIMIT :top_k
            """)

            result = await session.execute(query, {"top_k": top_k})

            rows = result.fetchall()
            latency = (time.perf_counter() - start_time) * 1000  # ms로 변환

            # 결과 ID 리스트 반환
            result_ids = [row[0] for row in rows]

            return latency, result_ids

    async def run_benchmark(
        self,
        num_queries: int = 50,
        warmup_queries: int = 10,
        ef_search_values: List[int] = None
    ) -> Dict[str, any]:
        """벤치마크 실행"""
        if ef_search_values is None:
            ef_search_values = [40]  # 기본값

        print("=" * 70)
        print("HNSW Index Performance Benchmark")
        print("=" * 70)
        print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()

        # 현재 인덱스 타입 확인
        index_type = await self.check_index_type()
        print(f"Current index type: {index_type.upper()}")
        print()

        # 샘플 벡터 가져오기
        print(f"Fetching {num_queries + warmup_queries} sample vectors...")
        sample_vectors = await self.get_sample_vectors(num_queries + warmup_queries)

        if len(sample_vectors) < num_queries + warmup_queries:
            print(f"Warning: Only {len(sample_vectors)} vectors available in cache")
            num_queries = max(1, len(sample_vectors) - warmup_queries)

        print(f"Retrieved {len(sample_vectors)} sample vectors")
        print()

        results = {}

        for ef_search in ef_search_values:
            print(f"Testing with ef_search = {ef_search}")
            print("-" * 70)

            latencies = []

            # Warmup
            print(f"Running {warmup_queries} warmup queries...")
            for i in range(warmup_queries):
                _, vector = sample_vectors[i]
                await self.benchmark_query(vector, ef_search=ef_search)

            # Actual benchmark
            print(f"Running {num_queries} benchmark queries...")
            for i in range(warmup_queries, warmup_queries + num_queries):
                _, vector = sample_vectors[i]
                latency, _ = await self.benchmark_query(vector, ef_search=ef_search)
                latencies.append(latency)

                if (i - warmup_queries + 1) % 10 == 0:
                    print(f"  Progress: {i - warmup_queries + 1}/{num_queries} queries")

            # 통계 계산
            results[f"ef_search_{ef_search}"] = {
                'mean': statistics.mean(latencies),
                'median': statistics.median(latencies),
                'stdev': statistics.stdev(latencies) if len(latencies) > 1 else 0,
                'min': min(latencies),
                'max': max(latencies),
                'p95': self._percentile(latencies, 0.95),
                'p99': self._percentile(latencies, 0.99),
                'latencies': latencies
            }

            print()
            self._print_statistics(results[f"ef_search_{ef_search}"])
            print()

        # 인덱스 정보
        index_info = await self.get_index_info()

        return {
            'index_type': index_type,
            'num_queries': num_queries,
            'results': results,
            'index_info': index_info,
            'timestamp': datetime.now().isoformat()
        }

    def _percentile(self, data: List[float], percentile: float) -> float:
        """백분위수 계산"""
        sorted_data = sorted(data)
        index = int(len(sorted_data) * percentile)
        return sorted_data[min(index, len(sorted_data) - 1)]

    def _print_statistics(self, stats: Dict[str, float]):
        """통계 출력"""
        print(f"  Mean latency:   {stats['mean']:.2f} ms")
        print(f"  Median latency: {stats['median']:.2f} ms")
        print(f"  Std deviation:  {stats['stdev']:.2f} ms")
        print(f"  Min latency:    {stats['min']:.2f} ms")
        print(f"  Max latency:    {stats['max']:.2f} ms")
        print(f"  P95 latency:    {stats['p95']:.2f} ms")
        print(f"  P99 latency:    {stats['p99']:.2f} ms")

    async def get_index_info(self) -> Dict[str, any]:
        """인덱스 정보 조회"""
        async with self.async_session() as session:
            # 인덱스 크기
            size_query = text("""
                SELECT
                    indexname,
                    pg_size_pretty(pg_relation_size(indexname::regclass)) AS index_size,
                    pg_relation_size(indexname::regclass) AS index_size_bytes
                FROM pg_indexes
                WHERE tablename = 'query_cache'
                AND indexname LIKE '%vector%'
            """)
            result = await session.execute(size_query)
            index_sizes = result.fetchall()

            # 테이블 통계
            stats_query = text("""
                SELECT
                    COUNT(*) as total_rows,
                    COUNT(query_vector) as rows_with_vector
                FROM query_cache
            """)
            result = await session.execute(stats_query)
            stats = result.fetchone()

            return {
                'index_sizes': [
                    {'name': row[0], 'size': row[1], 'size_bytes': row[2]}
                    for row in index_sizes
                ],
                'total_rows': stats[0],
                'rows_with_vector': stats[1]
            }

    async def compare_ef_search_values(
        self,
        ef_search_values: List[int],
        num_queries: int = 50
    ):
        """다양한 ef_search 값 비교"""
        print("=" * 70)
        print("HNSW ef_search Parameter Comparison")
        print("=" * 70)
        print()

        results = await self.run_benchmark(
            num_queries=num_queries,
            warmup_queries=10,
            ef_search_values=ef_search_values
        )

        print("\n" + "=" * 70)
        print("SUMMARY: ef_search Comparison")
        print("=" * 70)

        for key, stats in results['results'].items():
            ef_value = key.replace('ef_search_', '')
            print(f"\nef_search = {ef_value}:")
            print(f"  Mean: {stats['mean']:.2f} ms | P95: {stats['p95']:.2f} ms | P99: {stats['p99']:.2f} ms")

        print("\n" + "=" * 70)
        print("Index Information")
        print("=" * 70)
        for idx in results['index_info']['index_sizes']:
            print(f"  {idx['name']}: {idx['size']}")
        print(f"  Total rows: {results['index_info']['total_rows']:,}")
        print(f"  Rows with vector: {results['index_info']['rows_with_vector']:,}")
        print()

    async def close(self):
        """리소스 정리"""
        await self.engine.dispose()


async def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(description='HNSW Index Performance Benchmark')
    parser.add_argument(
        '--queries',
        type=int,
        default=50,
        help='Number of queries to benchmark (default: 50)'
    )
    parser.add_argument(
        '--warmup',
        type=int,
        default=10,
        help='Number of warmup queries (default: 10)'
    )
    parser.add_argument(
        '--ef-search',
        type=str,
        default='40',
        help='Comma-separated ef_search values to test (default: 40)'
    )
    parser.add_argument(
        '--compare',
        action='store_true',
        help='Compare multiple ef_search values (uses --ef-search)'
    )

    args = parser.parse_args()

    # ef_search 값 파싱
    ef_search_values = [int(x.strip()) for x in args.ef_search.split(',')]

    # Settings에서 데이터베이스 URL 가져오기
    settings = Settings()

    benchmark = HNSWBenchmark(settings.DATABASE_URL)

    try:
        if args.compare:
            await benchmark.compare_ef_search_values(
                ef_search_values=ef_search_values,
                num_queries=args.queries
            )
        else:
            results = await benchmark.run_benchmark(
                num_queries=args.queries,
                warmup_queries=args.warmup,
                ef_search_values=ef_search_values
            )

            # 최종 요약
            print("=" * 70)
            print("FINAL SUMMARY")
            print("=" * 70)
            print(f"Index type: {results['index_type'].upper()}")
            print(f"Total queries: {results['num_queries']}")
            print(f"Timestamp: {results['timestamp']}")
            print()

            print("Index Information:")
            for idx in results['index_info']['index_sizes']:
                print(f"  {idx['name']}: {idx['size']}")
            print(f"  Total rows: {results['index_info']['total_rows']:,}")
            print(f"  Rows with vector: {results['index_info']['rows_with_vector']:,}")
            print()

            print("Performance:")
            for key, stats in results['results'].items():
                ef_value = key.replace('ef_search_', '')
                print(f"  ef_search={ef_value}: {stats['mean']:.2f} ms (mean), {stats['p95']:.2f} ms (p95)")
            print()

    finally:
        await benchmark.close()


if __name__ == '__main__':
    asyncio.run(main())
