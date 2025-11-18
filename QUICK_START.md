# NEOS Quick Start Guide

Get NEOS up and running in 5 minutes!

## Prerequisites

- Docker 24.0+ and Docker Compose 2.20+
- 8GB RAM minimum (16GB recommended)
- 20GB available disk space

## Step 1: Clone and Configure (2 minutes)

```bash
# Clone repository
git clone https://github.com/NEOS-AI/neos.git
cd neos

# Copy environment template
cp .env.example .env

# Edit .env and add your API keys
nano .env  # or use your favorite editor
```

**Required API keys:**
- `OPENAI_API_KEY` - Get from https://platform.openai.com/api-keys
- `ANTHROPIC_API_KEY` - Get from https://console.anthropic.com/settings/keys
- `TAVILY_API_KEY` - Get from https://tavily.com/

**Critical security:** Change these in .env:
- `JWT_SECRET_KEY` - Generate with: `openssl rand -hex 32`
- `POSTGRES_PASSWORD` - Generate with: `openssl rand -base64 32`
- `RABBITMQ_PASSWORD` - Generate with: `openssl rand -base64 32`
- `GRAFANA_PASSWORD` - Your choice (for Grafana admin login)

## Step 2: Start NEOS (2 minutes)

```bash
# Start the entire stack
docker-compose -f docker-compose.enterprise.yml up -d

# Check status
docker-compose -f docker-compose.enterprise.yml ps

# View logs
docker-compose -f docker-compose.enterprise.yml logs -f neos-backend-1
```

Wait for all services to be healthy (~1-2 minutes).

## Step 3: Verify Installation (1 minute)

```bash
# Health check
curl http://localhost/api/v1/health

# Test query
curl -X POST http://localhost/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is artificial intelligence?",
    "user_id": "test_user"
  }'
```

## Access Dashboards

| Service | URL | Credentials |
|---------|-----|-------------|
| **API** | http://localhost | - |
| **API Docs** | http://localhost/docs | - |
| **Metrics** | http://localhost/metrics | - |
| **Prometheus** | http://localhost:9090 | - |
| **Grafana** | http://localhost:3001 | admin / (your GRAFANA_PASSWORD) |
| **Jaeger** | http://localhost:16686 | - |
| **RabbitMQ** | http://localhost:15672 | neos / (your RABBITMQ_PASSWORD) |

## What's Included?

✅ **3 Backend Instances** - Load balanced with Nginx
✅ **PostgreSQL** - With pgvector for semantic search
✅ **Redis** - For caching and sessions
✅ **RabbitMQ** - Message queue for async tasks
✅ **Prometheus** - Metrics collection
✅ **Grafana** - Visualization dashboards
✅ **Jaeger** - Distributed tracing
✅ **Loki** - Log aggregation

## Common Tasks

### View Logs

```bash
# All services
docker-compose -f docker-compose.enterprise.yml logs -f

# Specific service
docker-compose -f docker-compose.enterprise.yml logs -f neos-backend-1

# Last 100 lines
docker-compose -f docker-compose.enterprise.yml logs --tail=100
```

### Restart Services

```bash
# Restart everything
docker-compose -f docker-compose.enterprise.yml restart

# Restart specific service
docker-compose -f docker-compose.enterprise.yml restart neos-backend-1
```

### Scale Backend

```bash
# Scale to 5 instances
docker-compose -f docker-compose.enterprise.yml up -d --scale neos-backend-1=5
```

### Stop Everything

```bash
# Stop all services
docker-compose -f docker-compose.enterprise.yml stop

# Stop and remove containers
docker-compose -f docker-compose.enterprise.yml down

# Stop and remove volumes (WARNING: deletes all data!)
docker-compose -f docker-compose.enterprise.yml down -v
```

## Testing

### Manual Test

```bash
# Register user
curl -X POST http://localhost/api/v1/register \
  -H "Content-Type: application/json" \
  -d '{
    "username": "testuser",
    "email": "test@example.com",
    "password": "SecurePass123!"
  }'

# Login
curl -X POST http://localhost/api/v1/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "testuser",
    "password": "SecurePass123!"
  }'

# Query with authentication
curl -X POST http://localhost/api/v1/query \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -d '{
    "query": "Explain neural networks",
    "user_id": "testuser"
  }'
```

### Load Test

```bash
# Install k6
# macOS: brew install k6
# Linux: sudo snap install k6

# Run load test
k6 run tests/load/basic-load-test.js

# Custom load test
k6 run --vus 50 --duration 5m tests/load/basic-load-test.js
```

## Monitoring

### View Metrics in Grafana

1. Open http://localhost:3001
2. Login with: admin / (your GRAFANA_PASSWORD)
3. Navigate to Dashboards → NEOS
4. View "NEOS Overview" dashboard

### View Traces in Jaeger

1. Open http://localhost:16686
2. Select service: `neos-backend`
3. Click "Find Traces"

### Prometheus Queries

Open http://localhost:9090 and try these queries:

```promql
# Request rate
sum(rate(neos_http_requests_total[1m]))

# Error rate
sum(rate(neos_http_requests_total{status=~"5.."}[5m]))
/ sum(rate(neos_http_requests_total[5m]))

# P95 response time
histogram_quantile(0.95,
  sum(rate(neos_http_request_duration_seconds_bucket[5m])) by (le)
)

# Active sessions
neos_active_sessions
```

## Backup

### Manual Backup

```bash
# Make scripts executable (first time only)
chmod +x scripts/backup/*.sh

# Backup PostgreSQL
./scripts/backup/backup-postgres.sh /backups/postgres

# Backup Redis
./scripts/backup/backup-redis.sh /backups/redis

# Backup everything
./scripts/backup/backup-all.sh /backups
```

### Automated Backups

Add to crontab (`crontab -e`):

```cron
# Daily backup at 2 AM
0 2 * * * /path/to/neos/scripts/backup/backup-all.sh /backups >> /var/log/neos-backup.log 2>&1
```

## Troubleshooting

### Services Won't Start

```bash
# Check logs
docker-compose -f docker-compose.enterprise.yml logs

# Check disk space
df -h

# Check Docker
docker ps -a
docker system prune -a  # Clean up if needed
```

### Database Connection Errors

```bash
# Check if PostgreSQL is running
docker ps | grep postgres

# View PostgreSQL logs
docker logs neos-postgres-primary

# Restart PostgreSQL
docker-compose -f docker-compose.enterprise.yml restart postgres-primary
```

### High Memory Usage

```bash
# Check memory usage
docker stats

# Reduce backend instances
docker-compose -f docker-compose.enterprise.yml up -d --scale neos-backend-1=1
```

### Port Already in Use

```bash
# Find process using port 80
sudo lsof -i :80

# Kill process or change port in docker-compose.enterprise.yml
```

## Next Steps

1. **Production Deployment**: See [ENTERPRISE_DEPLOYMENT.md](ENTERPRISE_DEPLOYMENT.md)
2. **CI/CD Setup**: Configure GitHub Actions with your secrets
3. **SSL/TLS**: Set up certificates for HTTPS
4. **Backup Strategy**: Configure automated backups
5. **Monitoring**: Set up alerts in Prometheus Alertmanager
6. **Security**: Review [ENTERPRISE_READINESS_CHECKLIST.md](ENTERPRISE_READINESS_CHECKLIST.md)

## Getting Help

- **Documentation**: See docs/ directory
- **Issues**: https://github.com/NEOS-AI/neos/issues
- **Backup Guide**: scripts/backup/README.md
- **Enterprise Deployment**: ENTERPRISE_DEPLOYMENT.md
- **Readiness Checklist**: ENTERPRISE_READINESS_CHECKLIST.md

## Development Mode

For development without the full stack:

```bash
# Start only database and cache
docker-compose -f docker-compose.enterprise.yml up -d postgres-primary redis-master

# Run backend locally
pip install -e .
python -m neos.main

# Run frontend locally (in web/ directory)
npm install
npm run dev
```

---

**You're all set!** 🚀

NEOS is now running with:
- ✅ Multi-agent AI system
- ✅ Load balancing (3 backend instances)
- ✅ High availability PostgreSQL
- ✅ Redis caching
- ✅ Complete monitoring stack
- ✅ Distributed tracing

Enjoy using NEOS!
