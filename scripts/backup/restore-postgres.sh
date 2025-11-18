#!/bin/bash

# NEOS PostgreSQL Restore Script
# Restore from backup with safety checks
#
# Usage:
#   ./restore-postgres.sh <backup_file>
#   ./restore-postgres.sh latest  # Restore from latest backup
#
# WARNING: This will REPLACE the current database!

set -euo pipefail

# Configuration
BACKUP_DIR="${BACKUP_DIR:-/backups/postgres}"
DB_USER="${POSTGRES_USER:-neos_user}"
DB_NAME="${POSTGRES_DB:-neos_db}"
DOCKER_CONTAINER="${POSTGRES_CONTAINER:-neos-postgres-primary}"
USE_DOCKER="${USE_DOCKER:-true}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Get backup file
if [ $# -eq 0 ]; then
    echo -e "${RED}Error: No backup file specified${NC}"
    echo "Usage: $0 <backup_file|latest>"
    echo ""
    echo "Available backups:"
    ls -lh "${BACKUP_DIR}"/neos_db_*.sql.gz 2>/dev/null || echo "No backups found"
    exit 1
fi

BACKUP_FILE="$1"

# Handle "latest" keyword
if [ "${BACKUP_FILE}" = "latest" ]; then
    BACKUP_FILE="${BACKUP_DIR}/latest.sql.gz"

    if [ ! -f "${BACKUP_FILE}" ]; then
        echo -e "${RED}Error: No latest backup found${NC}"
        exit 1
    fi
fi

# Verify backup file exists
if [ ! -f "${BACKUP_FILE}" ]; then
    echo -e "${RED}Error: Backup file not found: ${BACKUP_FILE}${NC}"
    exit 1
fi

echo -e "${YELLOW}========== NEOS PostgreSQL Restore ==========${NC}"
echo "Backup file: ${BACKUP_FILE}"
echo "Database: ${DB_NAME}"
echo ""
echo -e "${RED}WARNING: This will REPLACE the current database!${NC}"
echo -e "${RED}All existing data will be LOST!${NC}"
echo ""
read -p "Are you sure you want to continue? (yes/no): " -r
echo

if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
    echo "Restore cancelled"
    exit 0
fi

echo "Starting restore..."

# Verify backup integrity
echo "Verifying backup integrity..."
if ! gzip -t "${BACKUP_FILE}"; then
    echo -e "${RED}Error: Backup file is corrupted${NC}"
    exit 1
fi

# Restore
if [ "${USE_DOCKER}" = "true" ]; then
    echo "Restoring via Docker..."

    # Stop application containers to prevent connections
    echo -e "${YELLOW}Stopping application containers...${NC}"
    docker-compose -f docker-compose.enterprise.yml stop neos-backend-1 neos-backend-2 neos-backend-3 2>/dev/null || true

    # Restore database
    if gunzip -c "${BACKUP_FILE}" | docker exec -i "${DOCKER_CONTAINER}" psql -U "${DB_USER}"; then
        echo -e "${GREEN}Restore completed successfully${NC}"

        # Restart application containers
        echo "Restarting application containers..."
        docker-compose -f docker-compose.enterprise.yml up -d neos-backend-1 neos-backend-2 neos-backend-3

        echo -e "${GREEN}========== Restore Complete ==========${NC}"
        exit 0
    else
        echo -e "${RED}Restore failed${NC}"
        exit 1
    fi
else
    # Direct restore
    echo "Restoring directly to PostgreSQL..."

    if gunzip -c "${BACKUP_FILE}" | psql -U "${DB_USER}" -d postgres; then
        echo -e "${GREEN}Restore completed successfully${NC}"
        echo -e "${GREEN}========== Restore Complete ==========${NC}"
        exit 0
    else
        echo -e "${RED}Restore failed${NC}"
        exit 1
    fi
fi
