"""
Cypher query tool for LangGraph v3 agentic workflows.

This module provides a LangChain tool for executing custom Cypher queries
against the Neo4j graph knowledge base with comprehensive safety constraints.

LangGraph Ref: https://docs.langchain.com/oss/python/langchain/tools
"""

import json
import re
from typing import Optional

from langchain_core.tools import tool

from graph_kb_api.graph_kb.facade import GraphKBFacade
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


def _validate_cypher_safety(query: str, repo_id: str) -> Optional[str]:
    """
    Validate that a Cypher query meets safety constraints.

    Safety rules:
    1. Only SELECT/MATCH queries allowed (no CREATE, DELETE, SET, MERGE, REMOVE)
    2. Must include {repo_id: $repo_id} filter
    3. Max 50 results (enforced with LIMIT)
    4. Max path depth of 10 hops

    Args:
        query: Cypher query string
        repo_id: Repository identifier

    Returns:
        Error message if validation fails, None if valid
    """
    query_upper = query.upper()

    # Check for write operations
    write_operations = ['CREATE', 'DELETE', 'SET', 'MERGE', 'REMOVE', 'DROP']
    for op in write_operations:
        # Use word boundaries to avoid false positives (e.g., "CREATED_AT" field)
        if re.search(rf'\b{op}\b', query_upper):
            return f"Write operation '{op}' not allowed. Only read queries (MATCH, RETURN) are permitted."

    # Check for repo_id filter
    if '$repo_id' not in query.lower() and 'repo_id' not in query.lower():
        return "Query must include repo_id filter. Add WHERE clause with {repo_id: $repo_id}"

    # Check for LIMIT clause
    if 'LIMIT' not in query_upper:
        return "Query must include LIMIT clause. Maximum 50 results allowed."

    # Extract LIMIT value and validate
    limit_match = re.search(r'LIMIT\s+(\d+)', query_upper)
    if limit_match:
        limit_value = int(limit_match.group(1))
        if limit_value > 50:
            return f"LIMIT {limit_value} exceeds maximum of 50 results"

    # Check for excessive path depth (prevent expensive queries)
    # Look for patterns like *1..20 or *..20
    path_depth_match = re.search(r'\*\.\.(\d+)|\*\d+\.\.(\d+)', query)
    if path_depth_match:
        max_depth = int(path_depth_match.group(1) or path_depth_match.group(2))
        if max_depth > 10:
            return f"Path depth {max_depth} exceeds maximum of 10 hops"

    return None


@tool
def execute_cypher_query(query: str, repo_id: str, explanation: str) -> str:
    """Execute a custom Cypher query against Neo4j GraphKB.

    This tool allows executing custom Cypher queries to explore the graph
    knowledge base. Use this for complex queries that aren't covered by
    other tools.

    SAFETY CONSTRAINTS:
    - Only SELECT/MATCH queries allowed (no CREATE, DELETE, SET, MERGE, REMOVE)
    - Must include {repo_id: $repo_id} filter
    - Max 50 results (enforced with LIMIT)
    - Max path depth of 10 hops

    Args:
        query: Cypher query string (must include $repo_id parameter)
        repo_id: Repository identifier
        explanation: Brief explanation of what this query finds

    Returns:
        JSON string with query results

    Example:
        >>> execute_cypher_query(
        ...     "MATCH (f:Function {repo_id: $repo_id})-[:CALLS]->(c:Function) "
        ...     "RETURN f.name, c.name LIMIT 10",
        ...     "my-repo",
        ...     "Find functions and what they call"
        ... )
    """
    try:
        logger.info(
            "Executing execute_cypher_query tool",
            data={
                'repo_id': repo_id,
                'explanation': explanation,
                'query_preview': query[:200]
            }
        )

        # Validate safety constraints
        validation_error = _validate_cypher_safety(query, repo_id)
        if validation_error:
            logger.warning(
                "Cypher query validation failed",
                data={'error': validation_error, 'query': query}
            )
            return json.dumps({
                'error': validation_error,
                'error_type': 'validation_error',
                'query': query
            })

        # Get facade instance
        facade = GraphKBFacade.get_instance()

        if not facade.graph_store:
            return json.dumps({
                'error': 'Graph store not initialized',
                'error_type': 'service_unavailable'
            })

        # Execute query with repo_id parameter
        # Log the full query for debugging
        logger.info(
            "Executing Cypher query",
            data={
                'query': query,
                'repo_id': repo_id,
                'explanation': explanation
            }
        )

        results = facade.graph_store.execute_query(
            query=query,
            parameters={'repo_id': repo_id}
        )

        # Convert results to JSON-serializable format
        formatted_results = []
        for record in results:
            # Convert neo4j Record to dict
            result_dict = dict(record)

            # Convert neo4j Node objects to dicts
            for key, value in result_dict.items():
                if hasattr(value, 'items'):  # Neo4j Node
                    result_dict[key] = dict(value)
                elif hasattr(value, '__iter__') and not isinstance(value, (str, dict)):
                    # Handle lists of nodes
                    result_dict[key] = [
                        dict(item) if hasattr(item, 'items') else item
                        for item in value
                    ]

            formatted_results.append(result_dict)

        result = {
            'explanation': explanation,
            'repo_id': repo_id,
            'result_count': len(formatted_results),
            'results': formatted_results
        }

        logger.info(
            "execute_cypher_query completed",
            data={
                'result_count': len(formatted_results),
                'explanation': explanation
            }
        )

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(
            f"execute_cypher_query failed: {e}",
            data={
                'query': query,
                'repo_id': repo_id,
                'error_type': type(e).__name__
            }
        )
        return json.dumps({
            'error': str(e),
            'error_type': type(e).__name__,
            'query': query
        })
