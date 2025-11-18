#!/bin/bash

# NEOS Redis Backup Script
# Automated Redis backup with RDB snapshots
#
# Usage:
#   ./backup-redis.sh [backup_dir]
#
# Features:
# - RDB snapshot backups
# - Automatic rotation (keeps last 7 days)
# - Timestamped filenames
# - Error handling and logging
# - Docker and local Redis support
# - Backup verification

set -euo pipefail

# Configuration
BACKUP_DIR="${1:-/backups/redis}"
RETENTION_DAYS=7
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="${BACKUP_DIR}/backup.log"

# Redis configuration
REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_PASSWORD="${REDIS_PASSWORD:-}"

# Docker configuration
DOCKER_CONTAINER="${REDIS_CONTAINER:-neos-redis-master}"
USE_DOCKER="${USE_DOCKER:-true}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Logging function
log() {
    local level=$1
    shift
    local message="$@"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    echo "${timestamp} [${level}] ${message}" | tee -a "${LOG_FILE}"

    case $level in
        ERROR)
            echo -e "${RED}[ERROR]${NC} ${message}" >&2
            ;;
        SUCCESS)
            echo -e "${GREEN}[SUCCESS]${NC} ${message}"
            ;;
        WARNING)
            echo -e "${YELLOW}[WARNING]${NC} ${message}"
            ;;
    esac
}

# Create backup directory
create_backup_dir() {
    if [ ! -d "${BACKUP_DIR}" ]; then
        log "INFO" "Creating backup directory: ${BACKUP_DIR}"
        mkdir -p "${BACKUP_DIR}"
    fi
}

# Check if Docker container is running
check_docker_container() {
    if [ "${USE_DOCKER}" = "true" ]; then
        if ! docker ps --format '{{.Names}}' | grep -q "^${DOCKER_CONTAINER}$"; then
            log "ERROR" "Docker container ${DOCKER_CONTAINER} is not running"
            exit 1
        fi
        log "INFO" "Docker container ${DOCKER_CONTAINER} is running"
    fi
}

# Get Redis info
get_redis_info() {
    if [ "${USE_DOCKER}" = "true" ]; then
        docker exec "${DOCKER_CONTAINER}" redis-cli INFO
    else
        if [ -n "${REDIS_PASSWORD}" ]; then
            redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" -a "${REDIS_PASSWORD}" INFO
        else
            redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" INFO
        fi
    fi
}

# Trigger BGSAVE
trigger_bgsave() {
    log "INFO" "Triggering Redis BGSAVE..."

    local result
    if [ "${USE_DOCKER}" = "true" ]; then
        result=$(docker exec "${DOCKER_CONTAINER}" redis-cli BGSAVE)
    else
        if [ -n "${REDIS_PASSWORD}" ]; then
            result=$(redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" -a "${REDIS_PASSWORD}" BGSAVE)
        else
            result=$(redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" BGSAVE)
        fi
    fi

    if [[ "${result}" == "Background saving started" ]]; then
        log "SUCCESS" "BGSAVE triggered successfully"
        return 0
    else
        log "WARNING" "BGSAVE response: ${result}"
        return 1
    fi
}

# Wait for BGSAVE to complete
wait_for_bgsave() {
    log "INFO" "Waiting for BGSAVE to complete..."

    local max_wait=300  # 5 minutes max
    local elapsed=0
    local interval=2

    while [ $elapsed -lt $max_wait ]; do
        local info=$(get_redis_info | grep "rdb_bgsave_in_progress")

        if echo "$info" | grep -q "rdb_bgsave_in_progress:0"; then
            log "SUCCESS" "BGSAVE completed"
            return 0
        fi

        sleep $interval
        elapsed=$((elapsed + interval))

        if [ $((elapsed % 10)) -eq 0 ]; then
            log "INFO" "Still waiting... (${elapsed}s elapsed)"
        fi
    done

    log "ERROR" "BGSAVE timeout after ${max_wait}s"
    return 1
}

# Copy RDB file
copy_rdb_file() {
    local backup_file="${BACKUP_DIR}/dump_${TIMESTAMP}.rdb"

    log "INFO" "Copying RDB file to backup location..."

    if [ "${USE_DOCKER}" = "true" ]; then
        # Get RDB file path from container
        local rdb_path=$(docker exec "${DOCKER_CONTAINER}" redis-cli CONFIG GET dir | tail -n 1)
        local rdb_file=$(docker exec "${DOCKER_CONTAINER}" redis-cli CONFIG GET dbfilename | tail -n 1)

        # Copy from container
        if ! docker cp "${DOCKER_CONTAINER}:${rdb_path}/${rdb_file}" "${backup_file}"; then
            log "ERROR" "Failed to copy RDB file from container"
            return 1
        fi
    else
        # Copy from local Redis
        local rdb_path=$(redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" CONFIG GET dir | tail -n 1)
        local rdb_file=$(redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" CONFIG GET dbfilename | tail -n 1)

        if ! cp "${rdb_path}/${rdb_file}" "${backup_file}"; then
            log "ERROR" "Failed to copy RDB file"
            return 1
        fi
    fi

    # Verify file exists and has size
    if [ ! -f "${backup_file}" ]; then
        log "ERROR" "Backup file was not created"
        return 1
    fi

    local file_size=$(du -h "${backup_file}" | cut -f1)
    log "SUCCESS" "Backup copied: ${backup_file} (${file_size})"

    # Compress the backup
    log "INFO" "Compressing backup..."
    if gzip "${backup_file}"; then
        backup_file="${backup_file}.gz"
        local compressed_size=$(du -h "${backup_file}" | cut -f1)
        log "SUCCESS" "Backup compressed: ${compressed_size}"
    fi

    # Create "latest" symlink
    ln -sf "$(basename "${backup_file}")" "${BACKUP_DIR}/latest.rdb.gz"

    echo "${backup_file}"
}

# Verify backup
verify_backup() {
    local backup_file=$1

    log "INFO" "Verifying backup integrity..."

    # Test gzip integrity
    if ! gzip -t "${backup_file}" 2>> "${LOG_FILE}"; then
        log "ERROR" "Backup file is corrupted (gzip test failed)"
        return 1
    fi

    # Check if file contains RDB header
    if ! gunzip -c "${backup_file}" | head -c 9 | grep -q "REDIS"; then
        log "ERROR" "Backup file does not appear to be a Redis RDB file"
        return 1
    fi

    log "SUCCESS" "Backup integrity verified"
    return 0
}

# Rotate old backups
rotate_backups() {
    log "INFO" "Rotating old backups (keeping last ${RETENTION_DAYS} days)..."

    local count=0
    while IFS= read -r file; do
        log "INFO" "Deleting old backup: $(basename "${file}")"
        rm -f "${file}"
        ((count++))
    done < <(find "${BACKUP_DIR}" -name "dump_*.rdb.gz" -mtime +${RETENTION_DAYS} -type f)

    if [ $count -eq 0 ]; then
        log "INFO" "No old backups to delete"
    else
        log "SUCCESS" "Deleted ${count} old backup(s)"
    fi
}

# Backup statistics
backup_statistics() {
    local total_backups=$(find "${BACKUP_DIR}" -name "dump_*.rdb.gz" -type f | wc -l)
    local total_size=$(du -sh "${BACKUP_DIR}" | cut -f1)

    # Get Redis stats
    local redis_info=$(get_redis_info)
    local db_keys=$(echo "$redis_info" | grep "^db0:" | cut -d: -f2 | cut -d, -f1 | cut -d= -f2)
    local used_memory=$(echo "$redis_info" | grep "^used_memory_human:" | cut -d: -f2 | tr -d '\r')

    log "INFO" "Backup Statistics:"
    log "INFO" "  Total backups: ${total_backups}"
    log "INFO" "  Total size: ${total_size}"
    log "INFO" "Redis Statistics:"
    log "INFO" "  Keys in db0: ${db_keys:-0}"
    log "INFO" "  Memory used: ${used_memory:-N/A}"
}

# Main execution
main() {
    log "INFO" "========== NEOS Redis Backup Started =========="
    log "INFO" "Timestamp: ${TIMESTAMP}"

    # Pre-flight checks
    create_backup_dir
    check_docker_container

    # Trigger backup
    if ! trigger_bgsave; then
        log "ERROR" "Failed to trigger BGSAVE"
        exit 1
    fi

    # Wait for completion
    if ! wait_for_bgsave; then
        log "ERROR" "BGSAVE did not complete"
        exit 1
    fi

    # Copy RDB file
    local backup_file=$(copy_rdb_file)

    # Verify backup
    if verify_backup "${backup_file}"; then
        # Rotate old backups
        rotate_backups

        # Show statistics
        backup_statistics

        log "SUCCESS" "========== Backup Completed Successfully =========="
        exit 0
    else
        log "ERROR" "========== Backup Failed =========="
        exit 1
    fi
}

# Handle interrupts
trap 'log "ERROR" "Backup interrupted"; exit 130' INT TERM

# Run main function
main
