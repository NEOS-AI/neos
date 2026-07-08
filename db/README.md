# DB

## Docker setup

```bash
cd ..

# 이미지 빌드
docker build --network=host -t neos-paradedb -f docker/Dockerfile.psql .

# 컨테이너 실행
docker run --name neos-paradedb -e POSTGRES_PASSWORD=password -p 5432:5432 -d neos-paradedb
```

Running valkey:
```bash
docker pull valkey/valkey

docker run --name neos-valkey -p 6379:6379 -d valkey/valkey
```

Running rustfs:
```bash
# Using latest version
docker run --name neos-rustfs -d -p 9000:9000 -p 9001:9001 rustfs/rustfs:latest
```

Running jaeger for OpenTelemetry tracing:
```bash
docker run -d --name neos-jaeger -p 16686:16686 \
    -e LOG_LEVEL=info \
    -e COLLECTOR_OTLP_ENABLED=true \
    jaegertracing/all-in-one:latest
```

## Connecting to the database

```bash
psql postgres --host localhost --port 5432 --user postgres
```

## Publish the database image to docker hub

```bash
# ParadeDB
docker tag neos-paradedb neos960518/neos-paradedb:latest
docker push neos960518/neos-paradedb:latest

# Valkey
docker tag valkey/valkey neos960518/neos-valkey:latest
docker push neos960518/neos-valkey:latest
```

## Migrate database schema

Pre-requisite: `CREATE DATABASE neos;` in PostgreSQL

```bash
# add schemas for initial setup
psql -U postgres -d neos --port 5432 --host localhost -f db/init.sql

# add schemas for hyper-deep-research
psql -U postgres -d neos --port 5432 --host localhost -f db/hyper_deep_research.sql

# add schemas for web search logging
psql -U postgres -d neos --port 5432 --host localhost -f db/web_search_log.sql
# add schemas for web search analytics
psql -U postgres -d neos --port 5432 --host localhost -f db/web_search_analytics.sql

# add schemas for workflow builder
psql -U postgres -d neos --port 5432 --host localhost -f db/add_workflow_tables.sql

# add schemas for chat system
psql -U postgres -d neos --port 5432 --host localhost -f db/chat_system.sql
psql -U postgres -d neos --port 5432 --host localhost -f db/chat_similarity_search.sql
psql -U postgres -d neos --port 5432 --host localhost -f db/chat_cost_tracking.sql

# add anonymous user for web interface
psql -U postgres -d neos --port 5432 --host localhost -f db/add_anonymous_user.sql

# Migrate conversation to deep research workflow
psql -U postgres -d neos --port 5432 --host localhost -f db/migrations/001_add_conversation_to_deep_research.sql

# Add deep research events table for real-time progress tracking
psql -U postgres -d neos --port 5432 --host localhost -f db/migrations/002_add_deep_research_events.sql

# Add smart cache table
psql -U postgres -d neos --port 5432 --host localhost -f db/migrations/003_add_smart_cache_tables.sql

# Add migrations for Google OAuth2 and enterprise users
psql -U postgres -d neos --port 5432 --host localhost -f db/migrations/004_add_auth_tables.sql
psql -U postgres -d neos --port 5432 --host localhost -f db/migrations/005_add_oauth_and_enterprise.sql

# Add migrations for changing index type
psql -U postgres -d neos --port 5432 --host localhost -f db/migrations/006_upgrade_to_hnsw.sql

# Add document_chunk table
psql -U postgres -d neos --port 5432 --host localhost -f db/migrations/028_create_document_chunks.sql

# Add documents table
psql -U postgres -d neos --port 5432 --host localhost -f db/migrations/029_create_documents.sql


# Add migrations for Google Gemini API support
psql -U postgres -d neos -h localhost -f db/migrations/007_add_embedding_provider_metadata.sql

# Add visibility column to conversations
psql -U postgres -d neos -h localhost -f db/migrations/008_add_visibility_to_conversations.sql

# Add support for hybrid search
psql -U postgres -d neos -h localhost -f db/migrations/009_add_knowledge_hybrid_search.sql

# Add support for research sessions
psql -U postgres -d neos -h localhost -f db/migrations/010_add_research_session_branches.sql
psql -U postgres -d neos -h localhost -f db/migrations/011_add_research_sessions.sql

# Add 3-tier memory architecture tables
psql -U postgres -d neos -h localhost -f db/migrations/012_add_memory_tables.sql

# Add feedback system
psql -U postgres -d neos -h localhost -f db/migrations/013_add_feedback_system.sql

# Add parent chunk support for better context retrieval
psql -U postgres -d neos -h localhost -f db/migrations/014_add_parent_chunk_support.sql

# Add knowledge graph support
psql -U postgres -d neos -h localhost -f db/migrations/015_add_knowledge_graph.sql
psql -U postgres -d neos -h localhost -f db/migrations/016_add_evidence_graph.sql
psql -U postgres -d neos -h localhost -f db/migrations/017_add_refinement_tables.sql

# Active Contradiction Resolution
psql -U postgres -d neos -h localhost -f db/migrations/018_add_contradiction_resolution.sql

# Add Tool Registry tables
psql -U postgres -d neos -h localhost -f db/migrations/019_add_tool_registry.sql

# Add contextual retrieval tables
psql -U postgres -d neos -h localhost -f db/migrations/020_add_contextual_retrieval.sql

# Add channel source columns to query_history
psql -U postgres -d neos -h localhost -f db/migrations/021_add_channel_source.sql

# Add tool approval allowlist table
psql -U postgres -d neos -h localhost -f db/migrations/022_add_tool_approval_allowlist.sql

# Add scheduled_tasks table
psql -U postgres -d neos -h localhost -f db/migrations/023_add_scheduled_tasks.sql

# UI 폼 세션 저장 테이블
# UIFrameGenerator가 생성한 frame_id → (original_query, conversation_id) 매핑
# POST /api/v1/ui/submit 수신 시 원본 쿼리 복원에 사용
psql -U postgres -d neos -h localhost -f db/migrations/024_add_ui_frame_sessions.sql
psql -U postgres -d neos -h localhost -f db/migrations/025_add_submitted_at.sql

# Execution Approval 타임아웃 추적 테이블 추가
psql -U postgres -d neos -h localhost -f db/migrations/026_add_pending_approvals.sql

# Add gemini embedding dimension support
psql -U postgres -d neos --port 5432 --host localhost -f db/migrations/027_gemini_embedding_dimension.sql

# Add support for agent control slider
psql -U postgres -d neos --port 5432 --host localhost -f db/migrations/030_add_autonomy_preferences.sql

# Add Mission Runtime audit tables
psql -U postgres -d neos --port 5432 --host localhost -f db/migrations/031_add_mission_runtime_tables.sql

# Add research harness tables
psql -U postgres -d neos --port 5432 --host localhost -f db/migrations/032_add_research_harness_tables.sql

# Features for thinking engine and reasoning items
psql -U postgres -d neos --port 5432 --host localhost -f db/migrations/033_add_thinking_engine_tables.sql
psql -U postgres -d neos --port 5432 --host localhost -f db/migrations/034_add_bitemporal_evidence_claims.sql

# Align API key metadata column with the current SQLAlchemy model
psql -U postgres -d neos --port 5432 --host localhost -f db/migrations/035_add_api_key_metadata_column.sql
```
