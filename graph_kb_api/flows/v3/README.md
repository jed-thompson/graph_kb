# LangGraph v3 Workflows

This directory contains the v3 workflow implementations using LangGraph for sophisticated code analysis.

## Overview

The v3 workflows provide advanced code analysis capabilities with:
- **Deep Agent**: Iterative reasoning with tool calling for complex analysis
- **Natural Language Interface**: Ask questions without slash commands
- **Semantic Retrieval**: Context-aware code search
- **Graph Expansion**: Relationship-based context gathering

## Workflows

### Deep Agent Workflow

The Deep Agent workflow uses the `deepagents` library to perform sophisticated multi-step reasoning about code.

**Features:**
- Iterative tool calling (up to 10 iterations by default)
- Access to multiple code analysis tools:
  - `search_code`: Semantic code search
  - `get_symbol_info`: Symbol details and relationships
  - `trace_call_chain`: Call chain analysis
  - `get_file_content`: File content retrieval
  - `get_related_files`: Related file discovery
  - `execute_cypher_query`: Custom graph queries
- Automatic retry with exponential backoff
- Configurable LLM model

**Usage:**

1. **Via Slash Command:**
   ```
   /deep explain the complete authentication flow from login to token validation
   /deep how does the system handle errors across different layers?
   /deep trace all database queries made during user registration
   ```

2. **Via Natural Language (automatic):**
   ```
   what does the main function do?
   how is authentication implemented?
   explain the payment processing flow
   ```

The natural language handler automatically routes **all** non-slash-command messages to the Deep Agent workflow.

## Architecture

```
src/flows/v3/
├── graphs/                      # Workflow definitions
│   ├── ask_code.py             # Standard AskCode workflow
│   ├── deep_agent.py           # Deep Agent workflow
│   ├── diff.py                 # Diff workflow
│   ├── ingest.py               # Ingestion workflow
│   └── base_workflow_engine.py # Base engine class
├── nodes/                       # Workflow nodes
│   ├── deep_agent.py           # Deep agent node
│   ├── ask_code_nodes.py       # Standard AskCode nodes
│   ├── diff_nodes.py           # Diff nodes
│   ├── ingest_nodes.py         # Ingestion nodes
│   ├── retrieval.py            # Retrieval nodes
│   ├── llm.py                  # LLM nodes
│   ├── formatting.py           # Formatting nodes
│   ├── human.py                # Human interaction nodes
│   ├── validation.py           # Validation nodes
│   ├── tools.py                # Tool execution nodes
│   └── base_node.py            # Base node class
├── state/                       # State definitions
│   ├── ask_code.py             # AskCode state
│   ├── diff.py                 # Diff state
│   ├── ingest.py               # Ingest state
│   ├── common.py               # Common state fields
│   ├── reducers.py             # State reducers
│   └── validation.py           # Validation state
├── tools/                       # Tool implementations
│   ├── graph_kb.py             # Graph KB tools
│   ├── file_access.py          # File access tools
│   └── cypher.py               # Cypher query tool
├── integration/                 # Integration layer
│   └── natural_language_handler.py  # Natural language routing
├── handlers/                    # Command handlers
│   └── ask_code_handler.py     # AskCode command handler
├── utils/                       # Utilities
│   ├── graph_context_formatter.py  # Graph context formatting
│   ├── progress_display.py     # Progress display
│   └── tool_display.py         # Tool display
├── tests/                       # Tests
│   └── test_foundation.py      # Foundation tests
├── docs/                        # Documentation
│   ├── graphkb_schema.md       # GraphKB schema
│   └── DATABASE_CONSOLIDATION_PLAN.md
├── checkpointer.py             # State persistence
├── config.py                   # Configuration
├── exceptions.py               # Custom exceptions
├── feature_flags.py            # Feature flags
├── messaging.py                # Messaging utilities
├── progress_manager.py         # Progress management
└── README.md                   # This file
```

## Configuration

### Deep Agent Model

The deep agent model can be configured when creating the workflow:

```python
workflow = DeepAgentWorkflowEngine(
    llm=llm,
    app_context=app_context,
    model="openai:gpt-4o",  # or "anthropic:claude-3-5-sonnet-20241022" or "openai:gpt-5.2"
    max_iterations=10
)
```

The model parameter uses the format `"provider:model-name"` (e.g., `"openai:gpt-4o"`, `"anthropic:claude-3-5-sonnet-20241022"`).

### Natural Language Detection

The natural language handler routes **all** non-slash-command messages to the Deep Agent workflow. There is no keyword-based detection - any message that doesn't start with `/` is automatically handled by the Deep Agent, which can then determine if it's code-related and respond appropriately.

## Development

### Adding New Tools

1. Create tool in `src/flows/v3/tools/`
2. Add to tool list in `DeepAgentNode.__init__`
3. Document in system prompt

### Adding New Workflows

1. Create workflow in `src/flows/v3/graphs/`
2. Extend `BaseWorkflowEngine`
3. Define nodes and routing logic
4. Create command in `src/commands/`
5. Register command in `src/app.py`

## Testing

Test the deep agent workflow:

```bash
# Via command
/deep what are the main entry points in this codebase?

# Via natural language
how does the authentication system work?
```

## Dependencies

- `langgraph`: Workflow orchestration
- `deepagents`: Deep agent implementation
- `langchain`: LLM integration
- `tenacity`: Retry logic

## Future Enhancements

- [x] Workflow persistence with checkpointing (implemented)
- [ ] Multi-repository analysis
- [ ] Custom tool registration
- [ ] Workflow templates
- [ ] Performance optimization
- [ ] Enhanced error recovery
