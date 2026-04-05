# Graph KB Tools for Code Exploration

These tools allow you to explore and understand the codebase in depth.

## search_repo

Search the repository for code semantically related to your query.

**Parameters:**
- `repo_id` (required): The repository identifier
- `query` (required): Natural language description of what you're looking for
- `max_results` (optional): Maximum number of results to return (default: 10)

**Use when:**
- Looking for code that implements a specific feature
- Finding functions related to a concept
- Searching for usage examples

**Example:**
```json
{
  "repo_id": "owner_repo",
  "query": "authentication middleware that validates JWT tokens",
  "max_results": 5
}
```

---

## get_file_snippet

Get the exact code content from a specific file and line range.

**Parameters:**
- `repo_id` (required): The repository identifier
- `file_path` (required): Path to the file within the repository
- `start_line` (required): Starting line number (1-indexed)
- `end_line` (required): Ending line number (inclusive)

**Use when:**
- You need to see more context around a code snippet
- Verifying exact implementation details
- Getting code that wasn't included in the initial context

**Example:**
```json
{
  "repo_id": "owner_repo",
  "file_path": "src/auth/middleware.py",
  "start_line": 45,
  "end_line": 80
}
```

---

## get_flow_between_symbols

Trace the call or import path between two symbols (functions, classes, etc.).

**Parameters:**
- `repo_id` (required): The repository identifier
- `from_symbol` (required): Name of the starting symbol
- `to_symbol` (required): Name of the target symbol

**Use when:**
- Understanding how data flows through the system
- Tracing function call chains
- Finding how two components are connected

**Example:**
```json
{
  "repo_id": "owner_repo",
  "from_symbol": "handle_request",
  "to_symbol": "save_to_database"
}
```

---

## get_architecture_overview

Get a high-level overview of the repository's architecture.

**Parameters:**
- `repo_id` (required): The repository identifier

**Use when:**
- Understanding the overall structure of the codebase
- Identifying main modules and their relationships
- Getting oriented in an unfamiliar repository

**Example:**
```json
{
  "repo_id": "owner_repo"
}
```

---

## Best Practices

1. **Start broad, then narrow**: Use `search_repo` first, then `get_file_snippet` for details
2. **Follow the flow**: Use `get_flow_between_symbols` to understand how components interact
3. **Get the big picture**: Use `get_architecture_overview` when exploring a new repository
4. **Be specific**: Provide clear, descriptive queries for better search results
