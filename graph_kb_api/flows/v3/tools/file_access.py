"""
File access tools for LangGraph v3 agentic workflows.

This module provides LangChain tools for retrieving file content and
finding related files through imports and dependencies.

LangGraph Ref: https://docs.langchain.com/oss/python/langchain/tools
"""

import json
import os

from langchain_core.tools import tool

from graph_kb_api.graph_kb.facade import GraphKBFacade
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


@tool
def get_file_content(file_path: str, repo_id: str) -> str:
    """Retrieve the full content of a source file.

    This tool reads the complete content of a file from the repository.
    Use this when you need to see the full implementation of a file or
    understand the complete context.

    Args:
        file_path: Path to file relative to repo root
        repo_id: Repository identifier

    Returns:
        File content as string, or error message if file not found

    Example:
        >>> get_file_content("src/auth/login.py", "my-repo")
        >>> # Returns the complete content of login.py
    """
    try:
        logger.info(
            "Executing get_file_content tool",
            data={'file_path': file_path, 'repo_id': repo_id}
        )

        # Get facade instance
        facade = GraphKBFacade.get_instance()

        # Get repository path from metadata
        repo_info = facade.metadata_store.get_repo(repo_id)

        if not repo_info:
            return json.dumps({
                'error': f"Repository '{repo_id}' not found",
                'repo_id': repo_id
            })

        repo_path = repo_info.local_path
        if not repo_path:
            return json.dumps({
                'error': f"Repository path not found for '{repo_id}'",
                'repo_id': repo_id
            })

        # Construct full file path
        full_path = os.path.join(repo_path, file_path)

        # Security check: ensure path is within repo
        full_path = os.path.abspath(full_path)
        repo_path = os.path.abspath(repo_path)

        if not full_path.startswith(repo_path):
            return json.dumps({
                'error': 'Access denied: path outside repository',
                'file_path': file_path
            })

        # Check if file exists
        if not os.path.exists(full_path):
            return json.dumps({
                'error': f"File not found: {file_path}",
                'file_path': file_path,
                'repo_id': repo_id
            })

        # Check if it's a file (not directory)
        if not os.path.isfile(full_path):
            return json.dumps({
                'error': f"Path is not a file: {file_path}",
                'file_path': file_path
            })

        # Read file content
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError:
            # Try with different encoding
            with open(full_path, 'r', encoding='latin-1') as f:
                content = f.read()

        # Limit content size (max 100KB)
        max_size = 100 * 1024
        if len(content) > max_size:
            content = content[:max_size] + "\n\n[Content truncated - file too large]"

        result = {
            'file_path': file_path,
            'repo_id': repo_id,
            'content': content,
            'size_bytes': len(content),
            'lines': content.count('\n') + 1
        }

        logger.info(
            "get_file_content completed",
            data={'size_bytes': len(content), 'lines': result['lines']}
        )

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(f"get_file_content failed: {e}")
        return json.dumps({
            'error': str(e),
            'error_type': type(e).__name__,
            'file_path': file_path
        })


@tool
def get_related_files(
    file_path: str,
    repo_id: str,
    relationship_type: str = "all"
) -> str:
    """Find files related through imports or dependencies.

    This tool finds files that are related to the given file through
    import statements or dependency relationships. Use this to understand
    the context and dependencies of a file.

    Args:
        file_path: Source file path
        repo_id: Repository identifier
        relationship_type: "imports", "imported_by", or "all"

    Returns:
        JSON string with related file paths and relationship types

    Example:
        >>> get_related_files("src/auth/login.py", "my-repo", "imports")
        >>> # Returns files that login.py imports
    """
    try:
        logger.info(
            "Executing get_related_files tool",
            data={
                'file_path': file_path,
                'repo_id': repo_id,
                'relationship_type': relationship_type
            }
        )

        # Validate relationship_type
        valid_types = ["imports", "imported_by", "all"]
        if relationship_type not in valid_types:
            return json.dumps({
                'error': f"Invalid relationship_type '{relationship_type}'",
                'valid_types': valid_types
            })

        # Get facade instance
        facade = GraphKBFacade.get_instance()

        # Query for file node
        file_nodes = facade.query_service.find_file_by_path(
            repo_id=repo_id,
            file_path=file_path
        )

        if not file_nodes:
            return json.dumps({
                'error': f"File '{file_path}' not found in repository '{repo_id}'",
                'file_path': file_path,
                'repo_id': repo_id
            })

        file_id = file_nodes[0].get('id')

        related_files = []

        # Get imports (files this file imports)
        if relationship_type in ["imports", "all"]:
            imports = facade.query_service.get_file_imports(
                repo_id=repo_id,
                file_id=file_id
            )
            for imp in imports[:50]:  # Limit to 50
                related_files.append({
                    'file_path': imp.get('file_path'),
                    'relationship': 'imports',
                    'import_statement': imp.get('import_statement')
                })

        # Get imported_by (files that import this file)
        if relationship_type in ["imported_by", "all"]:
            imported_by = facade.query_service.get_file_imported_by(
                repo_id=repo_id,
                file_id=file_id
            )
            for imp in imported_by[:50]:  # Limit to 50
                related_files.append({
                    'file_path': imp.get('file_path'),
                    'relationship': 'imported_by',
                    'import_statement': imp.get('import_statement')
                })

        result = {
            'source_file': file_path,
            'repo_id': repo_id,
            'relationship_type': relationship_type,
            'related_file_count': len(related_files),
            'related_files': related_files
        }

        logger.info(
            "get_related_files completed",
            data={'related_file_count': len(related_files)}
        )

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(f"get_related_files failed: {e}")
        return json.dumps({
            'error': str(e),
            'error_type': type(e).__name__,
            'file_path': file_path
        })
