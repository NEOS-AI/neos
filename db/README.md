# DB

## Docker setup

```bash
cd ..

# 이미지 빌드
docker build -t neos-paradedb -f docker/Dockerfile.psql .

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

# Add migrations for Google Gemini API support
psql -U postgres -d neos -h localhost -f db/migrations/006_add_embedding_provider_metadata.sql 
```

### Migrate database schema for backoffice

```bash
psql -U postgres -d neos --port 5432 --host localhost -f backoffice/db/migrations/001_create_analytics_tables.sql
```
