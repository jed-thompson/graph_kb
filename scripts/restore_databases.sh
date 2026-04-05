#!/bin/bash
# Restore databases from backup

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Database Restore Script${NC}"
echo "======================================"

# Check if backup directory exists
if [ ! -d "backups" ]; then
    echo -e "${RED}Error: backups directory not found${NC}"
    exit 1
fi

# Find the most recent backup
LATEST_BACKUP=$(ls -t backups/backup_manifest_*.json 2>/dev/null | head -1)

if [ -z "$LATEST_BACKUP" ]; then
    echo -e "${RED}Error: No backup manifest found${NC}"
    exit 1
fi

# Extract timestamp from manifest filename
TIMESTAMP=$(basename "$LATEST_BACKUP" | sed 's/backup_manifest_\(.*\)\.json/\1/')
echo -e "${YELLOW}Found backup from: $TIMESTAMP${NC}"

# Backup files
NEO4J_BACKUP="backups/neo4j_backup_${TIMESTAMP}.tar.gz"
CHROMADB_BACKUP="backups/chromadb_backup_${TIMESTAMP}.tar.gz"

# Check if backup files exist
if [ ! -f "$NEO4J_BACKUP" ]; then
    echo -e "${RED}Error: Neo4j backup file not found: $NEO4J_BACKUP${NC}"
    exit 1
fi

if [ ! -f "$CHROMADB_BACKUP" ]; then
    echo -e "${RED}Error: ChromaDB backup file not found: $CHROMADB_BACKUP${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}This will restore databases from backup.${NC}"
echo -e "${YELLOW}Current data will be replaced!${NC}"
echo ""
read -p "Continue? (yes/no): " -r
if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
    echo "Restore cancelled"
    exit 0
fi

# Stop services
echo ""
echo -e "${GREEN}Stopping services...${NC}"
docker-compose down

# Create temporary restore directory
RESTORE_DIR="./restore_temp"
mkdir -p "$RESTORE_DIR"

# Restore Neo4j
echo ""
echo -e "${GREEN}Restoring Neo4j data...${NC}"
NEO4J_RESTORE_DIR="$RESTORE_DIR/neo4j"
mkdir -p "$NEO4J_RESTORE_DIR"
tar -xzf "$NEO4J_BACKUP" -C "$NEO4J_RESTORE_DIR"

# Restore ChromaDB
echo ""
echo -e "${GREEN}Restoring ChromaDB data...${NC}"
CHROMADB_RESTORE_DIR="$RESTORE_DIR/chromadb"
mkdir -p "$CHROMADB_RESTORE_DIR"
tar -xzf "$CHROMADB_BACKUP" -C "$CHROMADB_RESTORE_DIR"

# Remove old volumes
echo ""
echo -e "${GREEN}Removing old volumes...${NC}"
docker volume rm sa-doc-generator_neo4j_data 2>/dev/null || true
docker volume rm sa-doc-generator_chromadb_data 2>/dev/null || true

# Start services to create volumes
echo ""
echo -e "${GREEN}Starting services to create volumes...${NC}"
docker-compose up -d neo4j chromadb

# Wait for containers to be ready
echo "Waiting for containers to initialize..."
sleep 10

# Stop services to copy data
echo ""
echo -e "${GREEN}Stopping services to copy data...${NC}"
docker-compose stop neo4j chromadb

# Copy restored data to volumes
echo ""
echo -e "${GREEN}Copying Neo4j data to volume...${NC}"
docker run --rm \
    -v sa-doc-generator_neo4j_data:/data \
    -v "$(pwd)/$NEO4J_RESTORE_DIR":/backup \
    alpine sh -c "rm -rf /data/* && cp -a /backup/. /data/"

echo -e "${GREEN}Copying ChromaDB data to volume...${NC}"
docker run --rm \
    -v sa-doc-generator_chromadb_data:/chroma/chroma \
    -v "$(pwd)/$CHROMADB_RESTORE_DIR":/backup \
    alpine sh -c "rm -rf /chroma/chroma/* && cp -a /backup/. /chroma/chroma/"

# Clean up temporary directory
echo ""
echo -e "${GREEN}Cleaning up...${NC}"
rm -rf "$RESTORE_DIR"

# Start services
echo ""
echo -e "${GREEN}Starting services...${NC}"
docker-compose up -d

echo ""
echo -e "${GREEN}✓ Restore completed successfully!${NC}"
echo ""
echo "Services are starting up. Check status with: docker-compose ps"
echo "View logs with: docker-compose logs -f"
