#!/usr/bin/env python3
"""Neo4j schema migration script.

This script migrates existing Symbol and File nodes to extract properties
from the serialized `attrs` JSON property and store them as top-level
node properties for efficient querying.

Migration Details:
- Symbol nodes: Extracts name, kind, docstring, file_path, start_line, end_line
- File nodes: Extracts file_path, language

The migration is idempotent - safe to run multiple times without corrupting data.
Uses batched processing with APOC procedures to handle large datasets efficiently.
"""

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

# Add project root to path for imports
sys.path.insert(0, ".")

from neo4j import GraphDatabase, Driver
from neo4j.exceptions import Neo4jError

from src.graph_kb.config import Neo4jConfig


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@dataclass
class MigrationStats:
    """Statistics from a migration run."""
    
    symbol_nodes_processed: int = 0
    symbol_nodes_skipped: int = 0
    symbol_nodes_failed: int = 0
    file_nodes_processed: int = 0
    file_nodes_skipped: int = 0
    file_nodes_failed: int = 0
    indexes_created: int = 0
    elapsed_seconds: float = 0.0
    
    def __str__(self) -> str:
        return (
            f"Migration Statistics:\n"
            f"  Symbol nodes processed: {self.symbol_nodes_processed}\n"
            f"  Symbol nodes skipped (already migrated): {self.symbol_nodes_skipped}\n"
            f"  Symbol nodes failed: {self.symbol_nodes_failed}\n"
            f"  File nodes processed: {self.file_nodes_processed}\n"
            f"  File nodes skipped (already migrated): {self.file_nodes_skipped}\n"
            f"  File nodes failed: {self.file_nodes_failed}\n"
            f"  Indexes created: {self.indexes_created}\n"
            f"  Total time: {self.elapsed_seconds:.2f} seconds"
        )


class MigrationError(Exception):
    """Raised when migration fails."""
    pass


class APOCNotAvailableError(MigrationError):
    """Raised when APOC procedures are not available."""
    pass



class Neo4jSchemaMigrator:
    """Handles Neo4j schema migration from attrs JSON to top-level properties.
    
    This class provides methods to:
    1. Check APOC availability
    2. Migrate Symbol nodes (extract name, kind, docstring, etc.)
    3. Migrate File nodes (extract file_path, language)
    4. Create indexes on new properties
    
    The migration is idempotent - nodes that already have top-level properties
    are skipped.
    """
    
    # Batch size for processing nodes
    DEFAULT_BATCH_SIZE = 1000
    
    # Symbol properties to extract from attrs
    SYMBOL_PROPERTIES = [
        "name", "kind", "docstring", "file_path", 
        "start_line", "end_line"
    ]
    
    # File properties to extract from attrs
    FILE_PROPERTIES = ["file_path", "language"]
    
    def __init__(
        self,
        driver: Driver,
        database: str = "neo4j",
        batch_size: int = DEFAULT_BATCH_SIZE,
    ):
        """Initialize the migrator.
        
        Args:
            driver: Neo4j driver instance.
            database: Database name to migrate.
            batch_size: Number of nodes to process per batch.
        """
        self._driver = driver
        self._database = database
        self._batch_size = batch_size
        self._apoc_available: Optional[bool] = None
    
    def check_apoc_available(self) -> bool:
        """Check if APOC procedures are available.
        
        Returns:
            True if APOC is available, False otherwise.
            
        Raises:
            APOCNotAvailableError: If APOC is not installed.
        """
        if self._apoc_available is not None:
            return self._apoc_available
        
        try:
            with self._driver.session(database=self._database) as session:
                result = session.run("RETURN apoc.version() AS version")
                record = result.single()
                if record is not None:
                    version = record["version"]
                    logger.info(f"APOC version {version} detected")
                    self._apoc_available = True
                    return True
        except Neo4jError as e:
            logger.warning(f"APOC check failed: {e}")
        
        self._apoc_available = False
        raise APOCNotAvailableError(
            "APOC procedures are not available. "
            "Please install APOC to use this migration script. "
            "See: https://neo4j.com/labs/apoc/4.4/installation/"
        )
    
    def count_unmigrated_symbols(self) -> Tuple[int, int]:
        """Count Symbol nodes that need migration.
        
        Returns:
            Tuple of (unmigrated_count, total_count).
        """
        with self._driver.session(database=self._database) as session:
            result = session.run("""
                MATCH (s:Symbol)
                WITH count(s) AS total
                MATCH (s:Symbol) WHERE s.name IS NULL AND s.attrs IS NOT NULL
                RETURN count(s) AS unmigrated, total
            """)
            record = result.single()
            if record:
                return record["unmigrated"], record["total"]
            return 0, 0
    
    def count_unmigrated_files(self) -> Tuple[int, int]:
        """Count File nodes that need migration.
        
        Returns:
            Tuple of (unmigrated_count, total_count).
        """
        with self._driver.session(database=self._database) as session:
            result = session.run("""
                MATCH (f:File)
                WITH count(f) AS total
                MATCH (f:File) WHERE f.file_path IS NULL AND f.attrs IS NOT NULL
                RETURN count(f) AS unmigrated, total
            """)
            record = result.single()
            if record:
                return record["unmigrated"], record["total"]
            return 0, 0
    
    def migrate_symbol_nodes(self, stats: MigrationStats) -> None:
        """Migrate Symbol nodes to extract properties from attrs.
        
        Uses APOC batched processing for efficiency.
        Skips nodes that already have top-level properties (idempotent).
        Logs warnings for nodes with NULL or invalid attrs.
        
        Args:
            stats: MigrationStats object to update with progress.
        """
        logger.info("Starting Symbol node migration...")
        
        unmigrated, total = self.count_unmigrated_symbols()
        logger.info(f"Found {unmigrated} Symbol nodes to migrate (out of {total} total)")
        
        if unmigrated == 0:
            stats.symbol_nodes_skipped = total
            logger.info("All Symbol nodes already migrated, skipping.")
            return
        
        stats.symbol_nodes_skipped = total - unmigrated
        
        # Use APOC batched processing
        migration_query = """
        CALL apoc.periodic.iterate(
            "MATCH (s:Symbol) WHERE s.name IS NULL AND s.attrs IS NOT NULL RETURN s",
            "WITH s, apoc.convert.fromJsonMap(s.attrs) AS attrs
             SET s.name = attrs.name,
                 s.kind = attrs.kind,
                 s.docstring = attrs.docstring,
                 s.file_path = attrs.file_path,
                 s.start_line = attrs.start_line,
                 s.end_line = attrs.end_line",
            {batchSize: $batch_size, parallel: false}
        ) YIELD batches, total, errorMessages
        RETURN batches, total, errorMessages
        """
        
        try:
            with self._driver.session(database=self._database) as session:
                result = session.run(
                    migration_query,
                    batch_size=self._batch_size,
                )
                record = result.single()
                if record:
                    batches = record["batches"]
                    processed = record["total"]
                    errors = record["errorMessages"]
                    
                    stats.symbol_nodes_processed = processed
                    
                    if errors:
                        # Count error messages
                        error_count = len(errors) if isinstance(errors, list) else 1
                        stats.symbol_nodes_failed = error_count
                        for error in (errors if isinstance(errors, list) else [errors]):
                            logger.warning(f"Symbol migration error: {error}")
                    
                    logger.info(
                        f"Symbol migration complete: {processed} nodes in {batches} batches"
                    )
        except Neo4jError as e:
            logger.error(f"Symbol migration failed: {e}")
            raise MigrationError(f"Symbol migration failed: {e}") from e
    
    def migrate_file_nodes(self, stats: MigrationStats) -> None:
        """Migrate File nodes to extract properties from attrs.
        
        Uses APOC batched processing for efficiency.
        Skips nodes that already have top-level properties (idempotent).
        Logs warnings for nodes with NULL or invalid attrs.
        
        Args:
            stats: MigrationStats object to update with progress.
        """
        logger.info("Starting File node migration...")
        
        unmigrated, total = self.count_unmigrated_files()
        logger.info(f"Found {unmigrated} File nodes to migrate (out of {total} total)")
        
        if unmigrated == 0:
            stats.file_nodes_skipped = total
            logger.info("All File nodes already migrated, skipping.")
            return
        
        stats.file_nodes_skipped = total - unmigrated
        
        # Use APOC batched processing
        # Note: File nodes store path as "file_path" in attrs, but we also
        # check for "path" as a fallback for older data
        migration_query = """
        CALL apoc.periodic.iterate(
            "MATCH (f:File) WHERE f.file_path IS NULL AND f.attrs IS NOT NULL RETURN f",
            "WITH f, apoc.convert.fromJsonMap(f.attrs) AS attrs
             SET f.file_path = COALESCE(attrs.file_path, attrs.path),
                 f.language = attrs.language",
            {batchSize: $batch_size, parallel: false}
        ) YIELD batches, total, errorMessages
        RETURN batches, total, errorMessages
        """
        
        try:
            with self._driver.session(database=self._database) as session:
                result = session.run(
                    migration_query,
                    batch_size=self._batch_size,
                )
                record = result.single()
                if record:
                    batches = record["batches"]
                    processed = record["total"]
                    errors = record["errorMessages"]
                    
                    stats.file_nodes_processed = processed
                    
                    if errors:
                        error_count = len(errors) if isinstance(errors, list) else 1
                        stats.file_nodes_failed = error_count
                        for error in (errors if isinstance(errors, list) else [errors]):
                            logger.warning(f"File migration error: {error}")
                    
                    logger.info(
                        f"File migration complete: {processed} nodes in {batches} batches"
                    )
        except Neo4jError as e:
            logger.error(f"File migration failed: {e}")
            raise MigrationError(f"File migration failed: {e}") from e
    
    def create_indexes(self, stats: MigrationStats) -> None:
        """Create indexes on new top-level properties.
        
        Creates indexes for efficient querying on:
        - Symbol.name
        - Symbol.kind
        - Symbol.file_path
        - File.file_path
        
        Uses IF NOT EXISTS to be idempotent.
        
        Args:
            stats: MigrationStats object to update with progress.
        """
        logger.info("Creating indexes on new properties...")
        
        index_queries = [
            ("symbol_name_index", 
             "CREATE INDEX symbol_name_index IF NOT EXISTS FOR (s:Symbol) ON (s.name)"),
            ("symbol_kind_index",
             "CREATE INDEX symbol_kind_index IF NOT EXISTS FOR (s:Symbol) ON (s.kind)"),
            ("symbol_file_path_index",
             "CREATE INDEX symbol_file_path_index IF NOT EXISTS FOR (s:Symbol) ON (s.file_path)"),
            ("file_file_path_index",
             "CREATE INDEX file_file_path_index IF NOT EXISTS FOR (f:File) ON (f.file_path)"),
        ]
        
        created = 0
        with self._driver.session(database=self._database) as session:
            for index_name, query in index_queries:
                try:
                    session.run(query)
                    logger.info(f"Created/verified index: {index_name}")
                    created += 1
                except Neo4jError as e:
                    logger.warning(f"Failed to create index {index_name}: {e}")
        
        stats.indexes_created = created
        logger.info(f"Index creation complete: {created} indexes")
    
    def run_migration(self, dry_run: bool = False) -> MigrationStats:
        """Run the full migration.
        
        Args:
            dry_run: If True, only report what would be done without making changes.
            
        Returns:
            MigrationStats with results of the migration.
        """
        stats = MigrationStats()
        start_time = time.time()
        
        try:
            # Check APOC availability
            self.check_apoc_available()
            
            if dry_run:
                logger.info("DRY RUN - No changes will be made")
                unmigrated_symbols, total_symbols = self.count_unmigrated_symbols()
                unmigrated_files, total_files = self.count_unmigrated_files()
                logger.info(f"Would migrate {unmigrated_symbols} Symbol nodes (out of {total_symbols})")
                logger.info(f"Would migrate {unmigrated_files} File nodes (out of {total_files})")
                stats.symbol_nodes_processed = unmigrated_symbols
                stats.symbol_nodes_skipped = total_symbols - unmigrated_symbols
                stats.file_nodes_processed = unmigrated_files
                stats.file_nodes_skipped = total_files - unmigrated_files
            else:
                # Run migrations
                self.migrate_symbol_nodes(stats)
                self.migrate_file_nodes(stats)
                self.create_indexes(stats)
            
        except APOCNotAvailableError:
            raise
        except Exception as e:
            logger.error(f"Migration failed: {e}")
            raise MigrationError(f"Migration failed: {e}") from e
        finally:
            stats.elapsed_seconds = time.time() - start_time
        
        return stats
    
    def verify_migration(self) -> Dict[str, Any]:
        """Verify the migration was successful.
        
        Returns:
            Dictionary with verification results.
        """
        results = {}
        
        with self._driver.session(database=self._database) as session:
            # Check Symbol nodes
            symbol_result = session.run("""
                MATCH (s:Symbol)
                WITH count(s) AS total
                MATCH (s:Symbol) WHERE s.name IS NOT NULL
                RETURN count(s) AS migrated, total
            """)
            record = symbol_result.single()
            if record:
                results["symbol_migrated"] = record["migrated"]
                results["symbol_total"] = record["total"]
                results["symbol_percentage"] = (
                    (record["migrated"] / record["total"] * 100)
                    if record["total"] > 0 else 100
                )
            
            # Check File nodes
            file_result = session.run("""
                MATCH (f:File)
                WITH count(f) AS total
                MATCH (f:File) WHERE f.file_path IS NOT NULL
                RETURN count(f) AS migrated, total
            """)
            record = file_result.single()
            if record:
                results["file_migrated"] = record["migrated"]
                results["file_total"] = record["total"]
                results["file_percentage"] = (
                    (record["migrated"] / record["total"] * 100)
                    if record["total"] > 0 else 100
                )
            
            # Check indexes
            index_result = session.run("""
                SHOW INDEXES
                WHERE name IN ['symbol_name_index', 'symbol_kind_index', 
                               'symbol_file_path_index', 'file_file_path_index']
                RETURN name, state
            """)
            results["indexes"] = [
                {"name": r["name"], "state": r["state"]}
                for r in index_result
            ]
        
        return results



def main():
    """Main entry point for the migration script."""
    parser = argparse.ArgumentParser(
        description="Migrate Neo4j schema from attrs JSON to top-level properties",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run migration with default settings
  python scripts/migrate_neo4j_schema.py

  # Dry run to see what would be migrated
  python scripts/migrate_neo4j_schema.py --dry-run

  # Custom batch size for large datasets
  python scripts/migrate_neo4j_schema.py --batch-size 5000

  # Verify migration status
  python scripts/migrate_neo4j_schema.py --verify

  # Custom Neo4j connection
  python scripts/migrate_neo4j_schema.py --uri bolt://localhost:7687 --user neo4j --password secret
        """,
    )
    
    parser.add_argument(
        "--uri",
        default=None,
        help="Neo4j URI (default: from NEO4J_URI env var or bolt://localhost:7687)",
    )
    parser.add_argument(
        "--user",
        default=None,
        help="Neo4j username (default: from NEO4J_USER env var or 'neo4j')",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="Neo4j password (default: from NEO4J_PASSWORD env var)",
    )
    parser.add_argument(
        "--database",
        default=None,
        help="Neo4j database (default: from NEO4J_DATABASE env var or 'neo4j')",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Number of nodes to process per batch (default: 1000)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be migrated without making changes",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify migration status without making changes",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Load configuration
    config = Neo4jConfig.from_env()
    
    # Override with command line arguments
    if args.uri:
        config.uri = args.uri
    if args.user:
        config.user = args.user
    if args.password:
        config.password = args.password
    if args.database:
        config.database = args.database
    
    logger.info(f"Connecting to Neo4j at {config.uri} (database: {config.database})")
    
    # Create driver
    try:
        driver = GraphDatabase.driver(
            config.uri,
            auth=(config.user, config.password),
        )
        
        # Test connection
        driver.verify_connectivity()
        logger.info("Connected to Neo4j successfully")
        
    except Exception as e:
        logger.error(f"Failed to connect to Neo4j: {e}")
        sys.exit(1)
    
    try:
        migrator = Neo4jSchemaMigrator(
            driver=driver,
            database=config.database,
            batch_size=args.batch_size,
        )
        
        if args.verify:
            # Just verify migration status
            logger.info("Verifying migration status...")
            results = migrator.verify_migration()
            
            print("\nMigration Verification Results:")
            print(f"  Symbol nodes: {results.get('symbol_migrated', 0)}/{results.get('symbol_total', 0)} "
                  f"({results.get('symbol_percentage', 0):.1f}% migrated)")
            print(f"  File nodes: {results.get('file_migrated', 0)}/{results.get('file_total', 0)} "
                  f"({results.get('file_percentage', 0):.1f}% migrated)")
            print(f"  Indexes: {len(results.get('indexes', []))} found")
            for idx in results.get("indexes", []):
                print(f"    - {idx['name']}: {idx['state']}")
            
        else:
            # Run migration
            stats = migrator.run_migration(dry_run=args.dry_run)
            
            print("\n" + str(stats))
            
            if not args.dry_run:
                # Verify after migration
                logger.info("Verifying migration...")
                results = migrator.verify_migration()
                print(f"\nVerification: {results.get('symbol_percentage', 0):.1f}% Symbol nodes migrated, "
                      f"{results.get('file_percentage', 0):.1f}% File nodes migrated")
        
    except APOCNotAvailableError as e:
        logger.error(str(e))
        sys.exit(2)
    except MigrationError as e:
        logger.error(str(e))
        sys.exit(3)
    finally:
        driver.close()
        logger.info("Disconnected from Neo4j")


if __name__ == "__main__":
    main()
