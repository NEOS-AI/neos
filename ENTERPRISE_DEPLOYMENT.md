# NEOS Enterprise Deployment Guide

## Overview

This guide covers deploying NEOS as an enterprise-grade, production-ready system with:

- **High Availability**: Multiple backend replicas with load balancing
- **Distributed State Management**: PostgreSQL-backed workflow checkpointing
- **Comprehensive Monitoring**: Prometheus + Grafana + Jaeger + Loki
- **Horizontal Scalability**: Scale backend instances independently
- **Resilience**: Health checks, automatic restarts, graceful degradation

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                       Load Balancer (Nginx)                  │
│                          Port 80/443                         │
└────────┬────────────────────┬────────────────────┬──────────┘
         │                    │                    │
    ┌────▼────┐          ┌────▼────┐         ┌────▼────┐
    │ Backend │          │ Backend │         │ Backend │
    │  #1     │          │  #2     │         │  #3     │
    │ :8518   │          │ :8519   │         │ :8520   │
    └────┬────┘          └────┬────┘         └────┬────┘
         │                    │                    │
         └────────┬───────────┴───────────┬────────┘
                  │                       │
         ┌────────▼─────────┐    ┌────────▼──────────┐
         │   PostgreSQL     │    │   Redis Cluster    │
         │  + pgvector      │    │   (Cache/Session)  │
         │   Primary        │    │                    │
         └──────────────────┘    └────────────────────┘
                  │
         ┌────────▼──────────────────────────────────┐
         │          Monitoring Stack                 │
         │  Prometheus | Grafana | Jaeger | Loki    │
         └───────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Docker 24.0+ and Docker Compose 2.20+
- 16GB RAM minimum (32GB recommended for production)
- 50GB available disk space
- Linux/macOS (Windows with WSL2)

### 1. Environment Setup

Create `.env` file with required secrets:

```bash
# Database
POSTGRES_PASSWORD=your_secure_postgres_password_here

# AI Services
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
TAVILY_API_KEY=tvly-...

# Authentication
JWT_SECRET_KEY=generate_with_openssl_rand_hex_32

# Message Queue
RABBITMQ_PASSWORD=your_secure_rabbitmq_password

# Monitoring
GRAFANA_PASSWORD=your_grafana_admin_password
```

**Generate secure secrets:**
```bash
# JWT Secret
openssl rand -hex 32

# Passwords
openssl rand -base64 32
```

### 2. Deploy Enterprise Stack

```bash
# Start all services
docker-compose -f docker-compose.enterprise.yml up -d

# Check service status
docker-compose -f docker-compose.enterprise.yml ps

# View logs
docker-compose -f docker-compose.enterprise.yml logs -f neos-backend-1

# Scale backend (if needed)
docker-compose -f docker-compose.enterprise.yml up -d --scale neos-backend-1=5
```

### 3. Verify Deployment

```bash
# Health check
curl http://localhost/api/v1/health

# Metrics endpoint
curl http://localhost/metrics

# Test query
curl -X POST http://localhost/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What is machine learning?", "user_id": "test_user"}'
```

### 4. Access Monitoring Dashboards

| Service | URL | Default Credentials |
|---------|-----|---------------------|
| **API** | http://localhost | - |
| **Prometheus** | http://localhost:9090 | - |
| **Grafana** | http://localhost:3001 | admin / (from .env) |
| **Jaeger** | http://localhost:16686 | - |
| **RabbitMQ** | http://localhost:15672 | neos / (from .env) |

## Configuration

### Database Scaling

**Connection Pool Tuning:**

Edit backend environment in `docker-compose.enterprise.yml`:

```yaml
environment:
  - DATABASE_POOL_SIZE=50  # Default: 10
  - DATABASE_MAX_OVERFLOW=100  # Default: 20
```

**Read Replicas:**

Add PostgreSQL read replica:

```yaml
postgres-replica:
  image: pgvector/pgvector:pg16
  environment:
    POSTGRES_USER: neos_user
    POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    POSTGRES_PRIMARY_HOST: postgres-primary
  command: |
    postgres -c 'primary_conninfo=host=postgres-primary port=5432 user=neos_user'
```

### Redis High Availability

Replace single Redis with Sentinel cluster:

```yaml
redis-sentinel-1:
  image: redis:7-alpine
  command: redis-sentinel /etc/redis/sentinel.conf
  # ... sentinel configuration
```

### Horizontal Scaling

**Scale backend instances:**

```bash
# Scale to 5 instances
docker-compose -f docker-compose.enterprise.yml up -d \
  --scale neos-backend-1=2 \
  --scale neos-backend-2=2 \
  --scale neos-backend-3=1

# Or directly in compose file
services:
  neos-backend:
    deploy:
      replicas: 5
```

**Resource Allocation:**

```yaml
deploy:
  resources:
    limits:
      cpus: '4'
      memory: 8G
    reservations:
      cpus: '2'
      memory: 4G
```

## Monitoring & Observability

### Prometheus Queries

**Request Rate (QPS):**
```promql
sum(rate(neos_http_requests_total[1m]))
```

**Error Rate:**
```promql
sum(rate(neos_http_requests_total{status=~"5.."}[5m]))
/ sum(rate(neos_http_requests_total[5m]))
```

**P95 Response Time:**
```promql
histogram_quantile(0.95,
  sum(rate(neos_http_request_duration_seconds_bucket[5m])) by (le, endpoint)
)
```

**LLM Cost (hourly):**
```promql
sum(increase(neos_llm_cost_usd[1h]))
```

### Grafana Dashboards

**Import pre-built dashboards:**

1. Navigate to Grafana (http://localhost:3001)
2. Go to Dashboards → Import
3. Upload JSON from `config/grafana/dashboards/`

**Available Dashboards:**

- **NEOS Overview**: System-wide metrics (RED)
- **Workflow Performance**: Agent and workflow execution metrics
- **LLM Monitoring**: API calls, costs, token usage
- **Infrastructure**: Database, Redis, resource utilization

### Alerting

**Configure Alertmanager** (optional):

```yaml
# docker-compose.enterprise.yml
alertmanager:
  image: prom/alertmanager:latest
  volumes:
    - ./config/alertmanager/config.yml:/etc/alertmanager/config.yml
  ports:
    - "9093:9093"
```

**Alert Channels:**

- Slack
- PagerDuty
- Email
- Webhook

### Distributed Tracing

**View traces in Jaeger:**

1. Open http://localhost:16686
2. Select service: `neos-backend`
3. Search by operation, tags, or time range

**Trace workflow execution:**

Each workflow execution generates a trace showing:
- Query classification time
- Agent execution times (parallel visualization)
- LLM API call durations
- Database query times

## Performance Tuning

### Database Optimization

**Indexes:**

Ensure indexes exist on frequently queried columns:

```sql
-- Workflow checkpoints
CREATE INDEX idx_checkpoints_thread_created
  ON langgraph_checkpoints(thread_id, created_at DESC);

-- Query history
CREATE INDEX idx_query_history_user_time
  ON query_history(user_id, created_at DESC);

-- Vector search
CREATE INDEX idx_embeddings_vector
  ON embeddings USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);
```

**Connection Pooling:**

Use PgBouncer for connection pooling:

```yaml
pgbouncer:
  image: edoburu/pgbouncer:latest
  environment:
    DATABASE_URL: postgres://neos_user:password@postgres-primary/neos_db
    POOL_MODE: transaction
    MAX_CLIENT_CONN: 1000
    DEFAULT_POOL_SIZE: 25
```

### Cache Optimization

**Cache Hit Rate Target: >80%**

```bash
# Monitor cache performance
docker exec neos-redis-master redis-cli INFO stats | grep hit_rate

# Tune cache TTLs in .env
WORKFLOW_RESPONSE_CACHE_TTL=86400  # 24 hours
REDIS_TTL=3600  # 1 hour
```

### LLM Cost Optimization

**Strategies:**

1. **Caching**: Enable aggressive caching for repeated queries
2. **Model Selection**: Use cheaper models for simple tasks
3. **Prompt Optimization**: Reduce token usage with efficient prompts
4. **Rate Limiting**: Prevent cost spikes from abuse

**Monitor costs:**

```promql
# Daily cost projection
sum(increase(neos_llm_cost_usd[1d]))

# Cost by model
sum(increase(neos_llm_cost_usd[1h])) by (model)
```

## Backup & Recovery

### Automated Backups

**PostgreSQL Backup:**

```bash
# Backup script (add to cron)
#!/bin/bash
BACKUP_DIR=/backups/postgres
DATE=$(date +%Y%m%d_%H%M%S)

docker exec neos-postgres-primary pg_dump \
  -U neos_user neos_db | gzip > \
  $BACKUP_DIR/neos_db_$DATE.sql.gz

# Retain last 7 days
find $BACKUP_DIR -name "*.sql.gz" -mtime +7 -delete
```

**Redis Backup:**

```bash
# Trigger RDB snapshot
docker exec neos-redis-master redis-cli BGSAVE

# Copy snapshot
docker cp neos-redis-master:/data/dump.rdb \
  /backups/redis/dump_$(date +%Y%m%d).rdb
```

### Disaster Recovery

**Restore from Backup:**

```bash
# Restore PostgreSQL
gunzip < /backups/postgres/neos_db_20250101_120000.sql.gz | \
  docker exec -i neos-postgres-primary psql -U neos_user neos_db

# Restore Redis
docker cp /backups/redis/dump_20250101.rdb neos-redis-master:/data/dump.rdb
docker restart neos-redis-master
```

## Security Hardening

### SSL/TLS Encryption

**Enable HTTPS in Nginx:**

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /etc/nginx/ssl/cert.pem;
    ssl_certificate_key /etc/nginx/ssl/key.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # ... rest of configuration
}
```

**Get SSL certificates** (Let's Encrypt):

```bash
certbot certonly --standalone -d your-domain.com
```

### Network Security

**Isolate services with Docker networks:**

```yaml
networks:
  backend:
    driver: bridge
    internal: true  # No external access
  frontend:
    driver: bridge
```

**Firewall rules:**

```bash
# Allow only necessary ports
ufw allow 80/tcp
ufw allow 443/tcp
ufw deny 5432/tcp  # Database should not be public
ufw enable
```

### Secrets Management

**Use Docker Secrets (Swarm) or Kubernetes Secrets:**

```yaml
secrets:
  postgres_password:
    external: true
  jwt_secret:
    external: true

services:
  neos-backend:
    secrets:
      - postgres_password
      - jwt_secret
```

## Troubleshooting

### Common Issues

**1. High Memory Usage**

```bash
# Check container memory
docker stats neos-backend-1

# Solution: Increase memory limit or optimize code
docker-compose -f docker-compose.enterprise.yml up -d \
  --scale neos-backend-1=1  # Reduce replicas temporarily
```

**2. Database Connection Errors**

```bash
# Check connection pool
docker exec neos-postgres-primary psql -U neos_user -d neos_db \
  -c "SELECT count(*) FROM pg_stat_activity;"

# Solution: Increase pool size or add PgBouncer
```

**3. Slow Workflow Execution**

```bash
# Check agent performance in Grafana
# Identify bottleneck with distributed tracing in Jaeger

# Optimize:
# - Enable result caching
# - Reduce agent timeouts
# - Scale backend replicas
```

### Logs

**Centralized Logging with Loki:**

```bash
# Query logs via LogCLI
logcli query '{container="neos-backend-1"}' --since=1h

# Or in Grafana Explore with Loki datasource
```

**Direct container logs:**

```bash
# Follow logs
docker-compose -f docker-compose.enterprise.yml logs -f --tail=100 neos-backend-1

# Search logs
docker-compose -f docker-compose.enterprise.yml logs | grep ERROR
```

## Production Checklist

### Before Deployment

- [ ] Change all default passwords in `.env`
- [ ] Generate strong JWT secret key
- [ ] Configure SSL/TLS certificates
- [ ] Set up automated backups
- [ ] Configure monitoring alerts
- [ ] Test disaster recovery procedure
- [ ] Review and tune resource limits
- [ ] Enable firewall rules
- [ ] Set up log retention policies
- [ ] Configure rate limiting
- [ ] Test load balancer failover

### Post-Deployment

- [ ] Verify all health checks pass
- [ ] Test API endpoints
- [ ] Confirm metrics are being collected
- [ ] Verify backup jobs run successfully
- [ ] Test alert notifications
- [ ] Load test the system
- [ ] Document runbooks
- [ ] Train operations team

## Support & Resources

- **Documentation**: https://docs.neos.ai
- **GitHub Issues**: https://github.com/NEOS-AI/neos/issues
- **Slack Community**: https://neos-ai.slack.com
- **Enterprise Support**: enterprise@neos.ai

## License

NEOS is licensed under the MIT License. See LICENSE file for details.
