#!/bin/bash

# NEOS Complete Backup Script
# Backs up PostgreSQL and Redis together
#
# Usage:
#   ./backup-all.sh [backup_base_dir]
#
# This script orchestrates both database backups

set -euo pipefail

# Configuration
BACKUP_BASE_DIR="${1:-/backups}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="${BACKUP_BASE_DIR}/backup-all.log"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

# Logging
log() {
    local level=$1
    shift
    local message="$@"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    echo "${timestamp} [${level}] ${message}" | tee -a "${LOG_FILE}"
}

# Create backup base directory
mkdir -p "${BACKUP_BASE_DIR}"

log "INFO" "========== NEOS Complete Backup Started =========="
log "INFO" "Timestamp: ${TIMESTAMP}"
log "INFO" "Backup directory: ${BACKUP_BASE_DIR}"

# Track success/failure
POSTGRES_SUCCESS=false
REDIS_SUCCESS=false

# Backup PostgreSQL
log "INFO" "Starting PostgreSQL backup..."
if bash "${SCRIPT_DIR}/backup-postgres.sh" "${BACKUP_BASE_DIR}/postgres"; then
    POSTGRES_SUCCESS=true
    log "SUCCESS" "PostgreSQL backup completed"
else
    log "ERROR" "PostgreSQL backup failed"
fi

# Backup Redis
log "INFO" "Starting Redis backup..."
if bash "${SCRIPT_DIR}/backup-redis.sh" "${BACKUP_BASE_DIR}/redis"; then
    REDIS_SUCCESS=true
    log "SUCCESS" "Redis backup completed"
else
    log "ERROR" "Redis backup failed"
fi

# Summary
log "INFO" "========== Backup Summary =========="
log "INFO" "PostgreSQL: $(${POSTGRES_SUCCESS} && echo 'SUCCESS' || echo 'FAILED')"
log "INFO" "Redis:      $(${REDIS_SUCCESS} && echo 'SUCCESS' || echo 'FAILED')"

if ${POSTGRES_SUCCESS} && ${REDIS_SUCCESS}; then
    echo -e "${GREEN}All backups completed successfully!${NC}"
    log "SUCCESS" "========== All Backups Completed =========="
    exit 0
else
    echo -e "${RED}Some backups failed! Check logs for details.${NC}"
    log "ERROR" "========== Some Backups Failed =========="
    exit 1
fi
