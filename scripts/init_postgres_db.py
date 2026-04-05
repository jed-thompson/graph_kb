#!/usr/bin/env python3
"""Initialize PostgreSQL database schema.

This script creates all tables in PostgreSQL using the ORM models.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from graph_kb_api.database.base import init_database, close_database, get_engine
from graph_kb_api.database.models import Base


async def main() -> None:
    """Initialize database schema."""
    print("Initializing PostgreSQL database...")

    try:
        # Initialize database connection
        await init_database()

        # Get engine and create all tables
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        print("Database schema created successfully!")
        print("\nTables created:")
        for table_name in Base.metadata.tables.keys():
            print(f"  - {table_name}")

    except Exception as e:
        print(f"Error initializing database: {e}")
        sys.exit(1)
    finally:
        # Close database connection
        await close_database()


if __name__ == "__main__":
    asyncio.run(main())
