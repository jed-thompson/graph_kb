#!/bin/bash
#
# Backup script for ChromaDB and Neo4j databases
# Creates compressed archives of both database volumes
#

set -e

# Configuration
BACKUP_DIR="${BACKUP_DIR:-./backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
COMPOSE_PROJECT="${COMPOSE_PROJECT_NAME:-$(basename $(pwd) | tr '[:upper:]' '[:lower:]')}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Derive volume names (docker-compose prefixes with project name)
NEO4J_VOLUME="${COMPOSE_PROJECT}_neo4j_data"
CHROMADB_VOLUME="${COMPOSE_PROJECT}_chromadb_data"

log_info "Starting database backup..."
log_info "Backup directory: $BACKUP_DIR"
log_info "Timestamp: $TIMESTAMP"

# Check if containers are running
CONTAINERS_RUNNING=false
if docker compose ps --status running | grep -q "neo4j\|chromadb"; then
    CONTAINERS_RUNNING=true
    log_warn "Containers are running. For consistent backups, consider stopping them first."
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Backup cancelled."
        exit 0
    fi
fi

# Backup Neo4j
log_info "Backing up Neo4j data volume..."
if docker volume inspect "$NEO4J_VOLUME" > /dev/null 2>&1; then
    docker run --rm \
        -v "${NEO4J_VOLUME}:/data:ro" \
        -v "$(pwd)/$BACKUP_DIR:/backup" \
        alpine:latest \
        tar -czf "/backup/neo4j_backup_${TIMESTAMP}.tar.gz" -C /data .
    log_info "Neo4j backup created: $BACKUP_DIR/neo4j_backup_${TIMESTAMP}.tar.gz"
else
    log_warn "Neo4j volume '$NEO4J_VOLUME' not found. Skipping."
fi

# Backup ChromaDB
log_info "Backing up ChromaDB data volume..."
if docker volume inspect "$CHROMADB_VOLUME" > /dev/null 2>&1; then
    docker run --rm \
        -v "${CHROMADB_VOLUME}:/chroma:ro" \
        -v "$(pwd)/$BACKUP_DIR:/backup" \
        alpine:latest \
        tar -czf "/backup/chromadb_backup_${TIMESTAMP}.tar.gz" -C /chroma .
    log_info "ChromaDB backup created: $BACKUP_DIR/chromadb_backup_${TIMESTAMP}.tar.gz"
else
    log_warn "ChromaDB volume '$CHROMADB_VOLUME' not found. Skipping."
fi

# Create a manifest file
MANIFEST_FILE="$BACKUP_DIR/backup_manifest_${TIMESTAMP}.json"
cat > "$MANIFEST_FILE" << EOF
{
    "timestamp": "$TIMESTAMP",
    "date": "$(date -Iseconds)",
    "neo4j_backup": "neo4j_backup_${TIMESTAMP}.tar.gz",
    "chromadb_backup": "chromadb_backup_${TIMESTAMP}.tar.gz",
    "compose_project": "$COMPOSE_PROJECT",
    "neo4j_volume": "$NEO4J_VOLUME",
    "chromadb_volume": "$CHROMADB_VOLUME"
}
EOF

log_info "Backup manifest created: $MANIFEST_FILE"

# Create/update symlinks to latest backups
ln -sf "neo4j_backup_${TIMESTAMP}.tar.gz" "$BACKUP_DIR/neo4j_backup_latest.tar.gz"
ln -sf "chromadb_backup_${TIMESTAMP}.tar.gz" "$BACKUP_DIR/chromadb_backup_latest.tar.gz"
ln -sf "backup_manifest_${TIMESTAMP}.json" "$BACKUP_DIR/backup_manifest_latest.json"

log_info "Backup complete!"
log_info ""
log_info "Backup files:"
ls -lh "$BACKUP_DIR"/*_${TIMESTAMP}* 2>/dev/null || true
