"""Test database module imports.

Simple test to verify SQLAlchemy models can be imported correctly.
"""


def test_models_import():
    """Test that database models can be imported without errors."""
    # This should succeed - SQLAlchemy 2.0.46 has Mapped
    from graph_kb_api.database.models import Base, Repository

    assert Repository is not None
    assert Base is not None


def test_base_import():
    """Test that database base can be imported."""
    from graph_kb_api.database.base import DatabaseError, get_database_url

    assert get_database_url is not None
    assert DatabaseError is not None
