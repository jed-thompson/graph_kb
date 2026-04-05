# GraphKB Project (Claude & Antigravity Guidance)

## Steering Documents

This project uses Kiro steering documents for context-aware guidance. Key steering docs in `.kiro/steering/`:

| Document | Inclusion | When Used |
|----------|-----------|-----------|
| [project-architecture.md](.kiro/steering/project-architecture.md) | auto | Always loaded — defines active frontend (Next.js dashboard) and deprecated paths (Chainlit) |
| [websocket-patterns.md](.kiro/steering/websocket-patterns.md) | fileMatch | Loaded when working on `graph_kb_dashboard/**` or WebSocket backend code |
| [mermaid-rendering.md](.kiro/steering/mermaid-rendering.md) | fileMatch | Loaded when working on chat components or LLM prompts that generate diagrams |
| [database-migration-implementation.md](.kiro/steering/database-migration-implementation.md) | manual | Reference for SQLite → PostgreSQL migration work |
| [e2e-testing.md](.kiro/steering/e2e-testing.md) | fileMatch | Loaded when working in `e2e/**` — Playwright test patterns, video recording, approval gate helpers |

## AGENTS.md Hierarchy

This project has AI-readable documentation in `AGENTS.md` files throughout the codebase. These are automatically loaded as context when working in a directory:

| Directory | Key Content |
|-----------|-------------|
| `AGENTS.md` (root) | Project overview, commands, architecture |
| `graph_kb_api/AGENTS.md` | Backend structure, FastAPI patterns |
| `graph_kb_api/flows/v3/AGENTS.md` | LangGraph workflows, state machines |
| `graph_kb_api/flows/v3/nodes/AGENTS.md` | Node implementation patterns |
| `graph_kb_api/flows/v3/state/AGENTS.md` | TypedDict state schemas |
| `graph_kb_api/websocket/AGENTS.md` | WebSocket protocols, ThreadSafeBridge |
| `graph_kb_dashboard/AGENTS.md` | Frontend structure, Next.js patterns |
| `graph_kb_dashboard/src/components/AGENTS.md` | React component organization |
| `graph_kb_dashboard/src/lib/store/AGENTS.md` | Zustand state patterns |
| `graph_kb_dashboard/src/lib/api/AGENTS.md` | API clients, WebSocket singleton |

When working in a subdirectory, Claude and Antigravity read the local AGENTS.md plus all parent AGENTS.md files up to root.

## Quick Reference

- **Frontend**: `graph_kb_dashboard/` (Next.js/React)
- **Backend**: `graph_kb_api/` (FastAPI)
- **Deprecated**: `Chainlit/` — do not modify

## Key Patterns

- Single shared WebSocket connection via singleton in `graph_kb_dashboard/src/lib/api/websocket.ts`
- Thread-safe progress bridge for sync → async event relay in backend
- Mermaid diagrams require sanitization and serial render queue
- Repository pattern for database access with SQLAlchemy async

## Safe Refactoring Protocol

- **Never apply mechanical transformations across multiple files without per-file verification.** After any bulk edit (search-and-replace, import reorganization, pattern migration), run `ruff check` on every modified file individually and fix errors before moving on.
- **Verify imports match usage.** When extracting a function to a new module and updating callers, confirm that every file importing the function actually uses all the symbols it imports. Run `ruff check <file>` after each edit — it catches F821 (undefined name) and F401 (unused import) instantly.
- **Test the changed path, not just the file.** After modifying an agent or node, verify the workflow path that invokes it completes without error. A static check catches syntax/import bugs; only a runtime test catches wiring bugs.

## Linting

- **Always run `ruff check` on modified Python files before committing.** Ruff is configured in `ruff.toml` with rules E, F, I, W — it catches undefined names, unused imports, and import ordering issues at static analysis time.
- Fix auto-fixable issues with `ruff check --fix <file>`, but review the diff before accepting.

## Bug-Fix Principles

- **Fix the root cause, never paper over it.** If a function receives wrong-type data, trace back to where the bad data originates and fix the producer — do not add `isinstance` guards or `try/except` to silently skip it.
- **Respect typed state schemas.** LangGraph state fields are typed (e.g. `artifacts: Dict[str, ArtifactRef]`). Only put values matching the declared type into that key. Metadata belongs in its own state key.
- **Always ask before executing.** When a code review or analysis identifies issues, present the findings to the user and ask for approval before making any edits. Never auto-apply fixes from a review without explicit user consent.

## Code Style

- **Prefer encapsulation**: Group related functions, constants, and registries within classes rather than as module-level helpers. Use `@staticmethod` or instance methods to keep behavior with the type that owns it. Module-level functions should be reserved for truly standalone utilities.

### Python Type Hints

- **Never use `Any` when a proper type exists**: If there's a class, interface, or protocol that describes the value, use it. Search the codebase for existing types before falling back to `Any`.
- **Never use `# type: ignore` comments**: Fix the underlying type issue instead. If the type stubs are incorrect or incomplete, use `cast()` from `typing` to explicitly annotate the expected type.
- **Use `from __future__ import annotations`** for forward references instead of quoted strings. This enables unquoted forward references and defers annotation evaluation.
- **Prefer `TYPE_CHECKING` imports** for types only needed at type-check time to avoid circular imports:

  ```python
  from __future__ import annotations

  from typing import TYPE_CHECKING, Optional

  if TYPE_CHECKING:
      from graph_kb_api.context import AppContext

  class MyClass:
      def method(self, ctx: Optional[AppContext]) -> None:
          ...
  ```

### Token Estimation

- **Always use `TokenEstimator` from `graph_kb_api.flows.v3.utils.token_estimation`** for counting tokens. Never use word-count approximations like `len(text.split()) * 1.33`.
- The `get_token_estimator()` singleton provides `count_tokens(text: str)` for accurate tiktoken-based counting with automatic fallback.
- For multimodal content (`str | list[str | dict]`), always convert to string before counting:

  ```python
  from graph_kb_api.flows.v3.utils.token_estimation import get_token_estimator

  # Handle AIMessage.content which can be str | list[str | dict]
  output_content: str
  if hasattr(response, "content"):
      raw_content = response.content
      output_content = str(raw_content) if not isinstance(raw_content, str) else raw_content
  else:
      output_content = str(response)

  estimated_tokens = get_token_estimator().count_tokens(output_content)
  ```

## React/Next.js Best Practices

### Component Size & Structure

- **Keep components under 150 lines**. If larger, extract sub-components.
- **One component per file**. Use barrel exports (`index.ts`) for related components.
- **Separate hooks into `hooks/` directory**. Never define hooks inside component files.

### Component Composition

- **Prefer composition over monoliths**. Break UI into reusable pieces:

  ```text
  ResearchResultsPanel.tsx       # Main container (~70 lines)
  ├── ResearchFindingsSummary.tsx  # Findings card
  ├── RiskCard.tsx                 # Individual risk display
  └── ResearchTabContent.tsx       # Tab content wrappers
  ```

- **Use shared wrappers** for repeated patterns (empty states, scroll containers).
- **Extract presentational components** that receive props and emit events.

### Hooks

- **Custom hooks in `src/hooks/`** with `use` prefix.
- **One hook per file** unless tightly coupled.
- **Hooks handle state, effects, and API calls** - components handle rendering.

### File Organization

```text
src/
├── components/
│   └── feature/
│       ├── FeaturePanel.tsx      # Main component
│       ├── FeatureCard.tsx       # Sub-component
│       ├── FeatureEmptyState.tsx # Empty state
│       └── index.ts              # Barrel export
├── hooks/
│   └── useFeature.ts             # Feature logic hook
└── lib/
    └── store/
        └── featureStore.ts       # Zustand store
```
