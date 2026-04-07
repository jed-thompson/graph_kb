# Graph KB Tools for Code Exploration

These tools allow you to explore and understand the codebase in depth.

## search_code

Search the repository for code semantically related to your query.

**Parameters:**
- `repo_id` (required): The repository identifier
- `query` (required): Natural language description of what you're looking for
- `top_k` (optional): Maximum number of results to return (uses configured value if omitted)

**Use when:**
- Looking for code that implements a specific feature
- Finding functions related to a concept
- Searching for usage examples
- Broad initial exploration of unfamiliar areas

**Example:**
```json
{
  "repo_id": "owner_repo",
  "query": "authentication middleware that validates JWT tokens",
  "top_k": 10
}
```

---

## get_symbol_info

Get detailed information about a specific code symbol (function, class, or method).

**Parameters:**
- `symbol_name` (required): Name of the function, class, or method to look up
- `repo_id` (required): The repository identifier
- `include_callers` (optional): Include functions that call this symbol (default: false)
- `include_callees` (optional): Include functions called by this symbol (default: false)
- `limit` (optional): Maximum number of callers/callees to return

**Use when:**
- You know the exact name of a function or class and need its definition and context
- Understanding how a symbol is used (include_callers=true)
- Understanding what a symbol depends on (include_callees=true)

**Example:**
```json
{
  "symbol_name": "authenticate_user",
  "repo_id": "owner_repo",
  "include_callers": true,
  "include_callees": true
}
```

---

## trace_call_chain

Trace the call chain from or to a specific function across the codebase.

**Parameters:**
- `symbol_name` (required): Name of the starting function or class
- `repo_id` (required): The repository identifier
- `direction` (optional): `"outgoing"` (what this calls) or `"incoming"` (what calls this) — default: `"outgoing"`
- `max_depth` (optional): Maximum traversal depth (uses configured value if omitted)

**Use when:**
- Tracing execution flow end-to-end
- Finding all callers of a function (incoming)
- Understanding the full call tree from an entry point (outgoing)
- Mapping data flow through the system

**Example:**
```json
{
  "symbol_name": "handle_grpc_request",
  "repo_id": "owner_repo",
  "direction": "outgoing",
  "max_depth": 5
}
```

---

## get_file_content

Retrieve the full content of a source file.

**Parameters:**
- `file_path` (required): Path to the file within the repository
- `repo_id` (required): The repository identifier

**Use when:**
- You need the complete implementation of a file
- Verifying exact implementation details not visible in a code chunk
- Reading configuration, schemas, or small utility files in full

**Example:**
```json
{
  "file_path": "carrier_integrations_platform/carrier_capabilities_facade.py",
  "repo_id": "owner_repo"
}
```

---

## get_related_files

Find files related to a given file through imports or dependencies.

**Parameters:**
- `file_path` (required): Path to the file within the repository
- `repo_id` (required): The repository identifier
- `relationship_type` (optional): `"imports"`, `"imported_by"`, or `"all"` — default: `"all"`

**Use when:**
- Mapping dependencies of a module
- Finding all files that import a given module
- Understanding the dependency graph around a key file

**Example:**
```json
{
  "file_path": "src/auth/middleware.py",
  "repo_id": "owner_repo",
  "relationship_type": "imported_by"
}
```

---

## execute_cypher_query

Execute a custom Cypher query against the Neo4j graph knowledge base for advanced analysis.

**Parameters:**
- `query` (required): Cypher query string
- `repo_id` (required): The repository identifier
- `explanation` (required): Brief description of what this query is looking for

**Use when:**
- Other tools don't cover your specific analysis need
- Querying relationships not exposed by specialized tools
- Finding all symbols of a specific type (e.g., all entry points, all HTTP handlers)
- Complex path queries across multiple relationship types

**Example:**
```json
{
  "query": "MATCH (f:Function)-[:CALLS]->(g:Function) WHERE f.repo_id = $repo_id AND g.name CONTAINS 'error' RETURN f.name, g.name LIMIT 20",
  "repo_id": "owner_repo",
  "explanation": "Find all functions that call error-handling functions"
}
```

---

## websearch

Search the web for external documentation, library references, or best practices.

**Parameters:**
- `query` (required): Search query string
- `max_results` (optional): Number of results to return (default: 5)

**Use when:**
- Looking up official documentation for a library or framework used in the codebase
- Finding best practices or common patterns for a technology
- Researching how other projects solve similar problems

**Example:**
```json
{
  "query": "gRPC Python server interceptors error handling best practices",
  "max_results": 5
}
```

---

## websearch_with_content

Search the web and return the full page content of results (not just summaries).

**Parameters:**
- `query` (required): Search query string
- `max_results` (optional): Number of results to return (default: 3)

**Use when:**
- You need detailed content from documentation pages, not just titles and snippets
- The summary from `websearch` is insufficient and you need the full text

**Example:**
```json
{
  "query": "LangGraph StateGraph conditional edges documentation",
  "max_results": 2
}
```

---

## Best Practices

1. **Start broad, then narrow**: Use `search_code` first to locate relevant areas, then `get_symbol_info` for details
2. **Follow the call chain**: Use `trace_call_chain` with `direction="outgoing"` from entry points to trace data flows
3. **Find all callers**: Use `trace_call_chain` with `direction="incoming"` to understand how a component is used
4. **Read full context**: Use `get_file_content` when a code chunk is insufficient and you need the complete picture
5. **Map dependencies**: Use `get_related_files` to understand module boundaries and import graphs
6. **For architectural questions**: Start with `search_code` for entry points → `trace_call_chain` to follow flows → `get_file_content` for key files
