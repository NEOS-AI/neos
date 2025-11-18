# NEOS Backup Scripts

Automated backup and restore scripts for PostgreSQL and Redis.

## Quick Start

### 1. Make Scripts Executable

```bash
chmod +x scripts/backup/*.sh
```

### 2. Test Backups Manually

```bash
# Backup PostgreSQL only
./scripts/backup/backup-postgres.sh /backups/postgres

# Backup Redis only
./scripts/backup/backup-redis.sh /backups/redis

# Backup everything
./scripts/backup/backup-all.sh /backups
```

### 3. Schedule Automated Backups

Add to crontab (`crontab -e`):

```cron
# Daily backups at 2:00 AM
0 2 * * * /path/to/neos/scripts/backup/backup-all.sh /backups >> /var/log/neos-backup.log 2>&1

# Or separate schedules:
# PostgreSQL every 6 hours
0 */6 * * * /path/to/neos/scripts/backup/backup-postgres.sh /backups/postgres

# Redis every 4 hours
0 */4 * * * /path/to/neos/scripts/backup/backup-redis.sh /backups/redis
```

## Configuration

### Environment Variables

Set these before running scripts:

```bash
# PostgreSQL
export POSTGRES_USER=neos_user
export POSTGRES_DB=neos_db
export POSTGRES_PASSWORD=your_password
export POSTGRES_CONTAINER=neos-postgres-primary

# Redis
export REDIS_HOST=localhost
export REDIS_PORT=6379
export REDIS_CONTAINER=neos-redis-master

# Docker
export USE_DOCKER=true  # or false for local databases
```

### Configuration Files

Create a config file (optional):

```bash
# /etc/neos/backup.conf
POSTGRES_USER=neos_user
POSTGRES_DB=neos_db
POSTGRES_PASSWORD=secure_password
BACKUP_RETENTION_DAYS=7
USE_DOCKER=true
```

Source it in your crontab:

```cron
0 2 * * * source /etc/neos/backup.conf && /path/to/scripts/backup/backup-all.sh
```

## Restore from Backup

### Restore PostgreSQL

```bash
# List available backups
ls -lh /backups/postgres/

# Restore from specific backup
./scripts/backup/restore-postgres.sh /backups/postgres/neos_db_20250101_020000.sql.gz

# Restore from latest backup
./scripts/backup/restore-postgres.sh latest
```

**⚠️ WARNING**: Restore will REPLACE the current database!

### Restore Redis

```bash
# Stop Redis
docker stop neos-redis-master

# Copy backup to Redis data directory
docker cp /backups/redis/dump_20250101_020000.rdb.gz neos-redis-master:/data/dump.rdb.gz
docker exec neos-redis-master gunzip /data/dump.rdb.gz

# Start Redis
docker start neos-redis-master
```

## Backup Features

### PostgreSQL Backup

- **Compressed backups** (gzip)
- **Full database dumps** with schema and data
- **7-day retention** (configurable)
- **Integrity verification**
- **Detailed logging**
- **Docker and native support**

### Redis Backup

- **RDB snapshot backups**
- **Background saves** (non-blocking)
- **Compressed storage**
- **7-day retention** (configurable)
- **Integrity verification**

## Backup Locations

Default backup structure:

```
/backups/
├── postgres/
│   ├── neos_db_20250101_020000.sql.gz
│   ├── neos_db_20250102_020000.sql.gz
│   ├── latest.sql.gz -> neos_db_20250102_020000.sql.gz
│   └── backup.log
├── redis/
│   ├── dump_20250101_020000.rdb.gz
│   ├── dump_20250102_020000.rdb.gz
│   ├── latest.rdb.gz -> dump_20250102_020000.rdb.gz
│   └── backup.log
└── backup-all.log
```

## Monitoring Backups

### Check Backup Status

```bash
# View recent backups
ls -lht /backups/postgres/ | head -10
ls -lht /backups/redis/ | head -10

# Check backup logs
tail -f /backups/postgres/backup.log
tail -f /backups/redis/backup.log
```

### Verify Backup Integrity

Backups are automatically verified after creation. Manual verification:

```bash
# Test PostgreSQL backup
gzip -t /backups/postgres/latest.sql.gz
gunzip -c /backups/postgres/latest.sql.gz | head -20

# Test Redis backup
gzip -t /backups/redis/latest.rdb.gz
gunzip -c /backups/redis/latest.rdb.gz | head -c 9
```

### Backup Alerts

Monitor backup logs for errors:

```bash
# Check for failed backups
grep -i "error" /backups/*/backup.log

# Check last backup time
ls -l /backups/postgres/latest.sql.gz
ls -l /backups/redis/latest.rdb.gz
```

## Remote Backup Storage

### Sync to S3

Add to your cron after local backup:

```bash
#!/bin/bash
# Sync to S3 after backup
aws s3 sync /backups/ s3://neos-backups/ \
  --exclude "*.log" \
  --storage-class STANDARD_IA \
  --region us-east-1
```

### Sync to Remote Server

```bash
#!/bin/bash
# Rsync to remote backup server
rsync -avz --delete \
  /backups/ \
  backup-server:/mnt/backups/neos/ \
  --exclude="*.log"
```

## Disaster Recovery

### Complete System Restore

1. **Deploy fresh infrastructure**
   ```bash
   docker-compose -f docker-compose.enterprise.yml up -d postgres-primary redis-master
   ```

2. **Restore PostgreSQL**
   ```bash
   ./scripts/backup/restore-postgres.sh /backups/postgres/latest.sql.gz
   ```

3. **Restore Redis**
   ```bash
   docker stop neos-redis-master
   docker cp /backups/redis/latest.rdb.gz neos-redis-master:/data/dump.rdb.gz
   docker exec neos-redis-master gunzip -f /data/dump.rdb.gz
   docker start neos-redis-master
   ```

4. **Start application**
   ```bash
   docker-compose -f docker-compose.enterprise.yml up -d
   ```

### Recovery Time Objective (RTO)

- **PostgreSQL**: 5-15 minutes (depends on backup size)
- **Redis**: 1-2 minutes
- **Total System**: ~20 minutes

### Recovery Point Objective (RPO)

- **Default**: Up to 24 hours (daily backups)
- **Recommended**: 4-6 hours (configure more frequent backups)

## Troubleshooting

### Backup Fails with Permission Error

```bash
# Ensure scripts are executable
chmod +x scripts/backup/*.sh

# Check Docker permissions
docker ps  # Should work without sudo

# Check backup directory permissions
sudo mkdir -p /backups
sudo chown $USER:$USER /backups
```

### BGSAVE Already in Progress (Redis)

Redis is already running a background save. Wait or check:

```bash
docker exec neos-redis-master redis-cli INFO | grep rdb_bgsave_in_progress
```

### PostgreSQL Connection Refused

Check if container is running:

```bash
docker ps | grep postgres
docker logs neos-postgres-primary
```

### Backup Directory Full

```bash
# Check disk space
df -h /backups

# Clean old backups manually
find /backups -name "*.gz" -mtime +30 -delete

# Or reduce retention days in scripts
```

## Best Practices

1. **Test restores regularly** - Monthly disaster recovery drills
2. **Store backups offsite** - S3, remote server, or cloud storage
3. **Monitor backup jobs** - Set up alerts for failures
4. **Encrypt backups** - Use GPG for sensitive data
5. **Document procedures** - Keep recovery runbooks updated
6. **Verify integrity** - Always check backups can be restored

## Backup Encryption (Optional)

Encrypt sensitive backups:

```bash
# Encrypt PostgreSQL backup
gpg --symmetric --cipher-algo AES256 /backups/postgres/latest.sql.gz

# Decrypt when restoring
gpg --decrypt /backups/postgres/latest.sql.gz.gpg | \
  gunzip -c | psql -U neos_user
```

## Support

For issues or questions:
- Check logs: `/backups/*/backup.log`
- Review this documentation
- Contact DevOps team
