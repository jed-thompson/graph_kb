"""
Web search tool using DuckDuckGo for LangGraph v3 workflows.

This module provides a LangChain tool for web search capabilities using DuckDuckGo.
No API key required - free and privacy-focused.

LangGraph Ref: https://docs.langchain.com/oss/python/langchain/tools
"""

import asyncio
import json

from langchain_core.tools import tool

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)

# Check if duckduckgo-search is available
try:
    from duckduckgo_search import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    DDGS_AVAILABLE = False
    logger.warning("duckduckgo-search not installed. Web search will return empty results.")


@tool
async def websearch(
    query: str,
    max_results: int = 5
) -> str:
    """Search the web using DuckDuckGo for information relevant to the query.

    This tool performs web searches to find documentation, examples, tutorials,
    or other information relevant to the specification being created.

    Use this when you need to:
    - Find documentation for libraries or frameworks
    - Search for best practices or patterns
    - Look up API references or examples
    - Find technical specifications or standards

    Args:
        query: The search query string
        max_results: Maximum number of results to return (default 5)

    Returns:
        JSON string with search results including title, url, and snippet

    Example:
        >>> websearch("FastAPI authentication best practices")
        >>> # Returns top 5 results with titles, URLs, and snippets
    """
    if not DDGS_AVAILABLE:
        return json.dumps({
            'error': 'duckduckgo-search package not installed. Install with: pip install duckduckgo-search>=4.0.0',
            'results': []
        })

    try:
        logger.info(
            "Executing websearch tool",
            data={'query': query, 'max_results': max_results}
        )

        # Run DuckDuckGo search in thread pool (it's sync)
        loop = asyncio.get_event_loop()

        def _search():
            results = []
            with DDGS() as ddgs:
                try:
                    for r in ddgs.text(query, max_results=max_results):
                        results.append({
                            'title': r.get('title', ''),
                            'url': r.get('href', ''),
                            'snippet': r.get('body', '')
                        })
                except Exception as e:
                    logger.error(f"DDGS search error: {e}")
            return results

        results = await loop.run_in_executor(None, _search)

        logger.info(
            "websearch completed",
            data={'result_count': len(results), 'query': query}
        )

        return json.dumps(results, indent=2)

    except Exception as e:
        logger.error(f"websearch failed: {e}")
        return json.dumps({
            'error': str(e),
            'error_type': type(e).__name__,
            'results': []
        })


@tool
async def websearch_with_content(
    query: str,
    max_results: int = 3
) -> str:
    """Search the web and retrieve full content from top results.

    This tool performs a web search and attempts to fetch the full content
    from the resulting URLs. Use this when you need detailed information
    from specific pages, not just snippets.

    Args:
        query: The search query string
        max_results: Maximum number of results to fetch content from (default 3)

    Returns:
        JSON string with search results including title, url, snippet, and full content
    """
    if not DDGS_AVAILABLE:
        return json.dumps({
            'error': 'duckduckgo-search package not installed. Install with: pip install duckduckgo-search>=4.0.0',
            'results': []
        })

    try:
        logger.info(
            "Executing websearch_with_content tool",
            data={'query': query, 'max_results': max_results}
        )

        # First get search results
        search_results_json = await websearch.ainvoke({'query': query, 'max_results': max_results})
        search_results = json.loads(search_results_json)

        if 'error' in search_results and 'results' not in search_results:
            return json.dumps(search_results)

        # Fetch content for each URL
        results = []
        for r in search_results:
            url = r.get('url', '')
            if url:
                try:
                    content = await fetch_url_content(url)
                    results.append({
                        'title': r.get('title', ''),
                        'url': url,
                        'snippet': r.get('snippet', ''),
                        'content': content[:5000] if content else ''  # Limit content size
                    })
                except Exception as e:
                    logger.warning(f"Failed to fetch content for {url}: {e}")
                    results.append({
                        'title': r.get('title', ''),
                        'url': url,
                        'snippet': r.get('snippet', ''),
                        'content': '',
                        'fetch_error': str(e)
                    })

        logger.info(
            "websearch_with_content completed",
            data={'result_count': len(results), 'query': query}
        )

        return json.dumps(results, indent=2)

    except Exception as e:
        logger.error(f"websearch_with_content failed: {e}")
        return json.dumps({
            'error': str(e),
            'error_type': type(e).__name__,
            'results': []
        })


async def fetch_url_content(url: str) -> str:
    """Fetch content from a URL using httpx.

    Args:
        url: URL to fetch content from

    Returns:
        Extracted text content from the page
    """
    import httpx

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, follow_redirects=True)
        response.raise_for_status()

        # Basic text extraction - strip HTML tags
        content = response.text

        # Simple cleanup - remove extra whitespace
        import re
        content = re.sub(r'<[^>]+>', ' ', content)  # Remove HTML tags
        content = re.sub(r'\s+', ' ', content).strip()

        return content
