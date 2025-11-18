#!/bin/bash

# NEOS PostgreSQL Backup Script
# Automated backup with rotation and compression
#
# Usage:
#   ./backup-postgres.sh [backup_dir]
#
# Features:
# - Compressed backups (gzip)
# - Automatic rotation (keeps last 7 days)
# - Timestamped filenames
# - Error handling and logging
# - Docker and local PostgreSQL support
# - Backup verification

set -euo pipefail

# Configuration
BACKUP_DIR="${1:-/backups/postgres}"
RETENTION_DAYS=7
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DATE_ONLY=$(date +%Y%m%d)
LOG_FILE="${BACKUP_DIR}/backup.log"

# Database configuration (from environment or defaults)
DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5432}"
DB_USER="${POSTGRES_USER:-neos_user}"
DB_NAME="${POSTGRES_DB:-neos_db}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-}"

# Docker configuration
DOCKER_CONTAINER="${POSTGRES_CONTAINER:-neos-postgres-primary}"
USE_DOCKER="${USE_DOCKER:-true}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

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

# Create backup directory if it doesn't exist
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

# Perform backup
perform_backup() {
    local backup_file="${BACKUP_DIR}/neos_db_${TIMESTAMP}.sql.gz"
    local temp_file="${BACKUP_DIR}/neos_db_${TIMESTAMP}.sql"

    log "INFO" "Starting PostgreSQL backup..."
    log "INFO" "Database: ${DB_NAME}"
    log "INFO" "Backup file: ${backup_file}"

    if [ "${USE_DOCKER}" = "true" ]; then
        # Docker-based backup
        log "INFO" "Using Docker exec for backup"

        if ! docker exec "${DOCKER_CONTAINER}" pg_dump \
            -U "${DB_USER}" \
            -d "${DB_NAME}" \
            --verbose \
            --clean \
            --create \
            --if-exists \
            2>> "${LOG_FILE}" | gzip > "${backup_file}"; then
            log "ERROR" "Backup failed"
            rm -f "${backup_file}"
            exit 1
        fi
    else
        # Direct PostgreSQL backup
        log "INFO" "Using pg_dump directly"

        if [ -n "${POSTGRES_PASSWORD}" ]; then
            export PGPASSWORD="${POSTGRES_PASSWORD}"
        fi

        if ! pg_dump \
            -h "${DB_HOST}" \
            -p "${DB_PORT}" \
            -U "${DB_USER}" \
            -d "${DB_NAME}" \
            --verbose \
            --clean \
            --create \
            --if-exists \
            2>> "${LOG_FILE}" | gzip > "${backup_file}"; then
            log "ERROR" "Backup failed"
            rm -f "${backup_file}"
            exit 1
        fi

        unset PGPASSWORD
    fi

    # Verify backup file
    if [ ! -f "${backup_file}" ]; then
        log "ERROR" "Backup file was not created"
        exit 1
    fi

    local file_size=$(du -h "${backup_file}" | cut -f1)
    log "SUCCESS" "Backup completed: ${backup_file} (${file_size})"

    # Create a "latest" symlink
    ln -sf "$(basename "${backup_file}")" "${BACKUP_DIR}/latest.sql.gz"

    echo "${backup_file}"
}

# Verify backup integrity
verify_backup() {
    local backup_file=$1

    log "INFO" "Verifying backup integrity..."

    # Test gzip integrity
    if ! gzip -t "${backup_file}" 2>> "${LOG_FILE}"; then
        log "ERROR" "Backup file is corrupted (gzip test failed)"
        return 1
    fi

    # Check if file contains SQL content
    if ! gunzip -c "${backup_file}" | head -n 20 | grep -q "PostgreSQL"; then
        log "ERROR" "Backup file does not appear to contain PostgreSQL dump"
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
    done < <(find "${BACKUP_DIR}" -name "neos_db_*.sql.gz" -mtime +${RETENTION_DAYS} -type f)

    if [ $count -eq 0 ]; then
        log "INFO" "No old backups to delete"
    else
        log "SUCCESS" "Deleted ${count} old backup(s)"
    fi
}

# Calculate and display backup statistics
backup_statistics() {
    local total_backups=$(find "${BACKUP_DIR}" -name "neos_db_*.sql.gz" -type f | wc -l)
    local total_size=$(du -sh "${BACKUP_DIR}" | cut -f1)
    local oldest_backup=$(find "${BACKUP_DIR}" -name "neos_db_*.sql.gz" -type f -printf '%T+ %p\n' | sort | head -n 1 | cut -d' ' -f2-)
    local newest_backup=$(find "${BACKUP_DIR}" -name "neos_db_*.sql.gz" -type f -printf '%T+ %p\n' | sort -r | head -n 1 | cut -d' ' -f2-)

    log "INFO" "Backup Statistics:"
    log "INFO" "  Total backups: ${total_backups}"
    log "INFO" "  Total size: ${total_size}"
    if [ -n "${oldest_backup}" ]; then
        log "INFO" "  Oldest: $(basename "${oldest_backup}")"
    fi
    if [ -n "${newest_backup}" ]; then
        log "INFO" "  Newest: $(basename "${newest_backup}")"
    fi
}

# Send notification (optional, requires configuration)
send_notification() {
    local status=$1
    local message=$2

    # Implement notification logic here
    # Examples:
    # - Email: echo "$message" | mail -s "NEOS Backup ${status}" admin@example.com
    # - Slack: curl -X POST -H 'Content-type: application/json' --data '{"text":"'"$message"'"}' $SLACK_WEBHOOK_URL
    # - Discord, PagerDuty, etc.

    : # No-op for now
}

# Main execution
main() {
    log "INFO" "========== NEOS PostgreSQL Backup Started =========="
    log "INFO" "Timestamp: ${TIMESTAMP}"

    # Pre-flight checks
    create_backup_dir
    check_docker_container

    # Perform backup
    local backup_file=$(perform_backup)

    # Verify backup
    if verify_backup "${backup_file}"; then
        # Rotate old backups
        rotate_backups

        # Show statistics
        backup_statistics

        log "SUCCESS" "========== Backup Completed Successfully =========="
        send_notification "SUCCESS" "PostgreSQL backup completed: $(basename "${backup_file}")"

        exit 0
    else
        log "ERROR" "========== Backup Failed =========="
        send_notification "FAILED" "PostgreSQL backup failed - please check logs"

        exit 1
    fi
}

# Handle interrupts
trap 'log "ERROR" "Backup interrupted"; exit 130' INT TERM

# Run main function
main
