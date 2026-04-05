# GraphKB Schema Documentation

This document describes the Neo4j graph schema used by SA-Doc-Generator's GraphKB (Graph Knowledge Base) system. This schema is essential for writing Cypher queries in the `execute_cypher_query` tool.

## Node Types

### Repository
Represents a code repository.

**Labels**: `Repository`

**Properties**:
- `repo_id` (string): Unique repository identifier
- `name` (string): Repository name
- `url` (string): Git repository URL
- `branch` (string): Current branch
- `commit_sha` (string): Current commit SHA
- `status` (string): Repository status (e.g., "indexed", "indexing", "failed")
- `created_at` (datetime): Creation timestamp
- `updated_at` (datetime): Last update timestamp

### Directory
Represents a directory in the repository.

**Labels**: `Directory`

**Properties**:
- `path` (string): Directory path relative to repository root
- `name` (string): Directory name
- `repo_id` (string): Parent repository ID

### File
Represents a source code file.

**Labels**: `File`

**Properties**:
- `path` (string): File path relative to repository root
- `name` (string): File name
- `extension` (string): File extension (e.g., ".py", ".js")
- `language` (string): Programming language
- `size` (integer): File size in bytes
- `line_count` (integer): Number of lines
- `repo_id` (string): Parent repository ID

### Symbol (Abstract)
Base type for all code symbols. Specific symbol types include:

#### Function
Represents a function or method.

**Labels**: `Symbol`, `Function`

**Properties**:
- `id` (string): Unique symbol identifier
- `name` (string): Function name
- `qualified_name` (string): Fully qualified name
- `file_path` (string): File containing the function
- `line_number` (integer): Starting line number
- `end_line_number` (integer): Ending line number
- `docstring` (string): Function documentation
- `parameters` (list[string]): Parameter names
- `return_type` (string): Return type annotation
- `is_async` (boolean): Whether function is async
- `repo_id` (string): Parent repository ID

#### Class
Represents a class definition.

**Labels**: `Symbol`, `Class`

**Properties**:
- `id` (string): Unique symbol identifier
- `name` (string): Class name
- `qualified_name` (string): Fully qualified name
- `file_path` (string): File containing the class
- `line_number` (integer): Starting line number
- `end_line_number` (integer): Ending line number
- `docstring` (string): Class documentation
- `base_classes` (list[string]): Base class names
- `repo_id` (string): Parent repository ID

#### Method
Represents a class method.

**Labels**: `Symbol`, `Method`

**Properties**:
- `id` (string): Unique symbol identifier
- `name` (string): Method name
- `qualified_name` (string): Fully qualified name
- `file_path` (string): File containing the method
- `line_number` (integer): Starting line number
- `end_line_number` (integer): Ending line number
- `docstring` (string): Method documentation
- `parameters` (list[string]): Parameter names
- `return_type` (string): Return type annotation
- `is_static` (boolean): Whether method is static
- `is_class_method` (boolean): Whether method is a class method
- `repo_id` (string): Parent repository ID

#### Variable
Represents a module-level variable or constant.

**Labels**: `Symbol`, `Variable`

**Properties**:
- `id` (string): Unique symbol identifier
- `name` (string): Variable name
- `qualified_name` (string): Fully qualified name
- `file_path` (string): File containing the variable
- `line_number` (integer): Line number
- `type_annotation` (string): Type annotation
- `repo_id` (string): Parent repository ID

### Chunk
Represents a text chunk with embeddings for semantic search.

**Labels**: `Chunk`

**Properties**:
- `id` (string): Unique chunk identifier
- `content` (string): Chunk text content
- `file_path` (string): Source file path
- `start_line` (integer): Starting line number
- `end_line` (integer): Ending line number
- `chunk_type` (string): Type of chunk (e.g., "function", "class", "docstring")
- `embedding` (list[float]): Vector embedding (if stored in Neo4j)
- `repo_id` (string): Parent repository ID

## Relationship Types

### CONTAINS
Hierarchical containment relationships.

**From → To**:
- `Repository → Directory`: Repository contains directories
- `Repository → File`: Repository contains files
- `Directory → Directory`: Directory contains subdirectories
- `Directory → File`: Directory contains files
- `File → Symbol`: File contains symbols
- `Class → Method`: Class contains methods

**Properties**:
- None

### CALLS
Function/method call relationships.

**From → To**:
- `Function → Function`: Function calls another function
- `Method → Function`: Method calls a function
- `Method → Method`: Method calls another method

**Properties**:
- `line_number` (integer): Line where call occurs
- `call_count` (integer): Number of times called (optional)

### IMPORTS
Module import relationships.

**From → To**:
- `File → File`: File imports another file
- `Symbol → Symbol`: Symbol imports another symbol

**Properties**:
- `import_type` (string): Type of import ("module", "from", "relative")
- `alias` (string): Import alias if used

### DEFINES
Definition relationships.

**From → To**:
- `File → Symbol`: File defines a symbol
- `Class → Method`: Class defines a method

**Properties**:
- None

### REFERENCES
Reference relationships.

**From → To**:
- `Symbol → Symbol`: Symbol references another symbol
- `Function → Variable`: Function references a variable

**Properties**:
- `line_number` (integer): Line where reference occurs
- `reference_type` (string): Type of reference ("read", "write", "call")

### INHERITS
Class inheritance relationships.

**From → To**:
- `Class → Class`: Class inherits from another class

**Properties**:
- `inheritance_order` (integer): Order in base class list

### HAS_CHUNK
Links symbols to their text chunks.

**From → To**:
- `Symbol → Chunk`: Symbol has associated chunk

**Properties**:
- None

## Example Cypher Queries

### Find all functions in a repository
```cypher
MATCH (f:Function)
WHERE f.repo_id = $repo_id
RETURN f.name, f.file_path, f.line_number
LIMIT 50
```

### Find all functions that call a specific function
```cypher
MATCH (caller:Function)-[:CALLS]->(callee:Function {name: $function_name})
WHERE caller.repo_id = $repo_id
RETURN caller.name, caller.file_path
LIMIT 50
```

### Find entry points (functions not called by others)
```cypher
MATCH (f:Function)
WHERE f.repo_id = $repo_id
  AND NOT ()-[:CALLS]->(f)
RETURN f.name, f.file_path, f.line_number
LIMIT 50
```

### Trace call chain from a function
```cypher
MATCH path = (start:Function {name: $function_name})-[:CALLS*1..5]->(end:Function)
WHERE start.repo_id = $repo_id
RETURN path
LIMIT 50
```

### Find all classes and their methods
```cypher
MATCH (c:Class)-[:CONTAINS]->(m:Method)
WHERE c.repo_id = $repo_id
RETURN c.name, collect(m.name) as methods
LIMIT 50
```

### Find files that import a specific module
```cypher
MATCH (f:File)-[:IMPORTS]->(target:File)
WHERE target.path = $module_path
  AND f.repo_id = $repo_id
RETURN f.path
LIMIT 50
```

### Find all symbols in a specific file
```cypher
MATCH (f:File {path: $file_path})-[:DEFINES]->(s:Symbol)
WHERE f.repo_id = $repo_id
RETURN s.name, labels(s), s.line_number
ORDER BY s.line_number
LIMIT 50
```

### Find class hierarchy
```cypher
MATCH path = (c:Class)-[:INHERITS*1..3]->(base:Class)
WHERE c.repo_id = $repo_id
RETURN path
LIMIT 50
```

## Safety Rules for Cypher Queries

When using the `execute_cypher_query` tool, the following safety constraints are enforced:

### Allowed Operations
- `MATCH`: Query nodes and relationships
- `RETURN`: Return query results
- `WHERE`: Filter results
- `WITH`: Chain query parts
- `ORDER BY`: Sort results
- `LIMIT`: Limit result count
- `SKIP`: Skip results
- `UNWIND`: Expand lists
- `OPTIONAL MATCH`: Optional pattern matching

### Prohibited Operations
- `CREATE`: Creating nodes/relationships
- `DELETE`: Deleting nodes/relationships
- `DETACH DELETE`: Deleting with relationships
- `SET`: Modifying properties
- `REMOVE`: Removing properties/labels
- `MERGE`: Creating or matching nodes

### Required Constraints
1. **Repository Filter**: All queries MUST include `repo_id = $repo_id` filter
2. **Result Limit**: Maximum 50 results (enforced with `LIMIT 50`)
3. **Path Depth**: Maximum path depth of 10 hops
4. **Read-Only**: Only SELECT/MATCH queries allowed

### Query Parameters
All queries receive the following parameters:
- `$repo_id`: Repository identifier (automatically injected)

Additional parameters can be passed through the query string using the `$parameter_name` syntax.

## Best Practices

1. **Always filter by repo_id**: Include `WHERE node.repo_id = $repo_id` in all queries
2. **Use LIMIT**: Always include `LIMIT` to prevent large result sets
3. **Index usage**: Queries on `repo_id`, `name`, and `path` are indexed
4. **Path queries**: Limit path depth to avoid expensive traversals
5. **Label specificity**: Use specific labels (e.g., `Function` instead of `Symbol`) for better performance
6. **Property existence**: Check property existence with `WHERE node.property IS NOT NULL`

## Schema Evolution

This schema may evolve over time. Key considerations:

- New node types may be added for additional language constructs
- New relationship types may be added for additional code relationships
- Properties may be added to existing node/relationship types
- Existing properties and relationships will remain backward compatible

## Additional Resources

- Neo4j Cypher documentation: https://neo4j.com/docs/cypher-manual/
- GraphKB implementation: `src/graph_kb/`
- Storage layer: `src/graph_kb/storage/neo4j/`
