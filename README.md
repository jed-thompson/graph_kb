# GraphKB — Code Knowledge Graph Agent

An AI-powered agent that ingests GitHub repositories, builds a semantic knowledge graph, and answers questions about codebases using RAG (Retrieval-Augmented Generation).

## Overview

GraphKB combines vector embeddings (ChromaDB) with a graph knowledge base (Neo4j) to provide deep code understanding. It can:

- Ingest and index GitHub repositories with AST parsing
- Build relationship graphs (imports, calls, contains) for code navigation
- Answer questions about codebases via a chat interface
- Generate technical specifications and documentation from templates
- Visualize code architecture and call graphs as Mermaid diagrams
- Run multi-step agentic research workflows via LangGraph

The application exposes a **FastAPI backend** with REST and WebSocket endpoints, and a **Next.js dashboard** as the primary UI.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Next.js Dashboard  :3000                                   │
│  Chat · Repositories · Visualize · Plan · Documents        │
└─────────────────────┬───────────────────────────────────────┘
                      │  REST + WebSocket
┌─────────────────────▼───────────────────────────────────────┐
│  FastAPI + LangGraph  :8000                                 │
│  /api/v1/* · /ws · /ws/ask-code · /ws/ingest               │
└──────┬──────────┬──────────────┬──────────────┬────────────┘
       │          │              │              │
  ┌────▼───┐ ┌───▼────┐  ┌──────▼─────┐ ┌─────▼─────┐
  │ Neo4j  │ │ChromaDB│  │ PostgreSQL │ │   MinIO   │
  │ :7688  │ │ :8091  │  │   :5432    │ │   :9010   │
  │ Graph  │ │Vectors │  │  Metadata  │ │  Blobs/S3 │
  └────────┘ └────────┘  └────────────┘ └───────────┘
```

---

## Quick Start

### Prerequisites

- **Python 3.11+**
- **Node.js 18+**
- **Docker and Docker Compose**
- **OpenAI API key**
- (Optional) GitHub token for private repositories
- (Optional) Hugging Face token for embedding model downloads

### 1. Clone and Configure

```bash
git clone <repo-url>
cd GraphKB-TaskAgent

cp .env.example .env
```

Edit `.env` with your credentials — at minimum set:

```bash
OPENAI_API_KEY=sk-your-key-here
GITHUB_TOKEN=ghp-your-token-here   # optional, for private repos
HF_TOKEN=hf_your-token-here        # for Jina embeddings
```

### 2. Start All Services

```bash
docker compose up -d
```

This starts the API, dashboard, Neo4j, ChromaDB, PostgreSQL, and MinIO.

### 3. Access the UI

| Interface | URL |
|-----------|-----|
| **Dashboard** | http://localhost:3000 |
| **API Docs (Swagger)** | http://localhost:8000/docs |
| **Neo4j Browser** | http://localhost:7475 (user: `neo4j`, password: `password`) |
| **MinIO Console** | http://localhost:9011 (user: `minioadmin`, password: `minioadmin`) |

---

## Services

| Service | Host Port | Description |
|---------|-----------|-------------|
| `api` | 8000 | FastAPI backend + WebSocket server |
| `dashboard` | 3000 | Next.js frontend |
| `postgres` | 5432 | PostgreSQL — workflow state, metadata |
| `neo4j-api` | 7475 / 7688 | Neo4j graph database |
| `chromadb` | 8091 | ChromaDB vector store |
| `minio` | 9010 / 9011 | S3-compatible blob storage |

---

## Using the Dashboard

The Next.js dashboard is the primary way to interact with GraphKB.

### Ingesting a Repository

1. Navigate to **Repositories** and click **Add Repository**
2. Enter a GitHub URL and start ingestion
3. Monitor progress in real time via the WebSocket stream

### Asking Questions

Use the **Chat** page to ask natural language questions about any indexed repository. The agent uses hybrid retrieval (vector + graph traversal) to find relevant context before generating an answer.

### Visualizing Code

The **Visualize** page generates Mermaid diagrams for:
- `architecture` — directory structure and file organization
- `calls` — function/method call relationships
- `dependencies` — import/dependency graph
- `call_chain` — trace calls from/to a specific symbol
- `hotspots` — most-connected symbols (refactoring targets)

### Other Pages

| Page | Description |
|------|-------------|
| **Plan** | Generate technical specifications via multi-step agent |
| **Documents** | Upload and manage supporting documents (PDF, etc.) |
| **Sources** | Manage steering documents that guide LLM generation |
| **Graph Stats** | Explore node/edge counts and graph metrics |
| **Settings** | Configure LLM model, retrieval depth, and other options |

---

## API

### REST Endpoints (`/api/v1`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/repos` | List repositories |
| GET | `/repos/{id}` | Get repository details |
| DELETE | `/repos/{id}` | Delete repository |
| GET | `/repos/{id}/symbols` | Search symbols |
| POST | `/repos/{id}/search` | Semantic search |
| POST | `/repos/{id}/retrieve` | Hybrid retrieval |
| GET | `/repos/{id}/stats` | Graph statistics |
| GET | `/documents` | List documents |
| POST | `/documents` | Upload a document |
| GET | `/templates` | List generation templates |
| GET | `/steering` | List steering documents |
| GET | `/health` | Service health check |

Full interactive documentation at http://localhost:8000/docs.

### WebSocket Endpoints

| Endpoint | Description |
|----------|-------------|
| `/ws` | Generic workflow endpoint |
| `/ws/ask-code` | Code Q&A workflow |
| `/ws/ingest` | Repository ingestion workflow |

**Client → Server:**
```json
{"type": "start", "payload": {"query": "...", "repo_id": "..."}}
```

**Server → Client:**
```json
{"type": "progress", "workflow_id": "...", "data": {"step": "..."}}
{"type": "complete", "workflow_id": "...", "data": {"response": "..."}}
```

---

## Development

### Local API (without Docker)

```bash
# Install API dependencies
pip install -r requirements.api.txt

# Copy and configure environment
cp .env.example .env

# Start infrastructure only (Neo4j, ChromaDB, Postgres, MinIO)
make infra-up

# Run database migrations
make db-migrate

# Start the API with hot-reload
uvicorn graph_kb_api.main:app --reload --port 8000
```

### Local Dashboard (without Docker)

```bash
cd graph_kb_dashboard
npm install
npm run dev
```

Dashboard will be available at http://localhost:3000.

### Common Make Targets

```bash
make help            # Show all available targets

# Docker
make docker-up       # Start all services
make docker-down     # Stop all services
make docker-logs     # Tail all logs
make docker-rebuild  # Rebuild images without cache
make docker-status   # Show container status

# Infrastructure only
make infra-up        # Start Neo4j + ChromaDB + Postgres + MinIO
make infra-down      # Stop infrastructure

# Database
make db-migrate      # Apply pending Alembic migrations
make db-status       # Show current migration revision

# Linting
make ruff            # Run ruff checks
make ruff-fix        # Auto-fix ruff issues

# Testing
make test            # Run all tests
make test-unit       # Unit tests only
make test-integration  # Integration tests only
make test-fast       # Unit + property tests (skips slow)
make test-cov        # Tests with coverage report

# E2E Tests (Playwright)
make e2e-test        # Run E2E tests (live LLM calls)
make e2e-mock        # Run E2E tests with pre-recorded responses
make e2e-record      # Record LLM responses for mock mode
```

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | OpenAI API key |
| `OPENAI_MODEL` | No | Model name (default: `gpt-5.2`) |
| `GITHUB_TOKEN` | No | GitHub token for private repos |
| `HF_TOKEN` | No | Hugging Face token for embedding model |
| `DATABASE_URL` | No | PostgreSQL URL (default: local Docker) |
| `NEO4J_URI` | No | Neo4j Bolt URI (default: `bolt://localhost:7688`) |
| `NEO4J_PASSWORD` | No | Neo4j password (default: `password`) |
| `CHROMA_SERVER_HOST` | No | ChromaDB host (default: `localhost`) |
| `CHROMA_SERVER_PORT` | No | ChromaDB port (default: `8091`) |
| `EMBEDDING_MODEL` | No | Embedding model (default: `jinaai/jina-embeddings-v3`) |
| `LANGGRAPH_V3_ENABLED` | No | Enable LangGraph v3 workflows (default: `true`) |
| `MAX_DEPTH` | No | Max graph traversal depth (default: `25`) |
| `LLM_RECORDING_MODE` | No | `off` / `record` / `replay` for E2E testing |

See `.env.example` for the full list with descriptions.

---

## Project Structure

```
GraphKB-TaskAgent/
├── graph_kb_api/              # FastAPI backend
│   ├── main.py                # App entry point, router registration
│   ├── config.py              # Settings (Pydantic)
│   ├── dependencies.py        # FastAPI dependency injection
│   ├── routers/               # REST route handlers
│   │   ├── chat.py            # Chat/ask-code endpoints
│   │   ├── repos.py           # Repository management
│   │   ├── search.py          # Semantic + hybrid search
│   │   ├── visualization.py   # Graph visualization
│   │   ├── documents.py       # Document management
│   │   ├── steering.py        # Steering documents
│   │   ├── templates.py       # Generation templates
│   │   └── plan.py            # Plan session endpoints
│   ├── flows/v3/              # LangGraph agentic workflows
│   │   ├── agents/            # Specialized agent nodes
│   │   ├── graphs/            # LangGraph graph definitions
│   │   ├── nodes/             # Individual workflow nodes
│   │   ├── state/             # TypedDict state schemas
│   │   └── tools/             # Agent tools
│   ├── graph_kb/              # Knowledge graph core
│   │   ├── ingestion/         # Repository ingestion (AST parsing)
│   │   ├── retrieval/         # Graph traversal and hybrid search
│   │   ├── storage/           # Neo4j and ChromaDB adapters
│   │   ├── visualization/     # Mermaid diagram generation
│   │   └── models/            # Domain models
│   ├── websocket/             # WebSocket connection manager
│   ├── database/              # PostgreSQL + SQLAlchemy setup
│   └── services/              # Application services
│
├── graph_kb_dashboard/        # Next.js frontend
│   └── src/
│       ├── app/               # Next.js app router pages
│       │   ├── chat/          # Chat interface
│       │   ├── repositories/  # Repository management
│       │   ├── visualize/     # Code visualization
│       │   ├── plan/          # Spec generation
│       │   ├── documents/     # Document management
│       │   ├── sources/       # Steering documents
│       │   ├── graph-stats/   # Graph metrics
│       │   └── settings/      # App settings
│       ├── components/        # React components
│       ├── hooks/             # Custom React hooks
│       ├── lib/               # Stores, API clients, WebSocket
│       └── context/           # React context providers
│
├── tests/                     # API unit and integration tests
├── e2e/                       # Playwright end-to-end tests
├── alembic/                   # Database migrations
├── scripts/                   # Backup/restore and utility scripts
├── docker-compose.yml         # Full stack configuration
├── Dockerfile.api.optimized   # Production API image
├── requirements.api.txt       # Python dependencies
├── ruff.toml                  # Python linter config
└── .env.example               # Environment variable template
```

---

## Database Backup & Restore

```bash
# Create a backup (stops containers for consistency)
docker compose down
./scripts/backup_databases.sh
docker compose up -d

# Restore latest backup
./scripts/restore_databases.sh

# Restore specific timestamp
./scripts/restore_databases.sh --timestamp 20241226_143000

# Options
./scripts/restore_databases.sh --neo4j-only
./scripts/restore_databases.sh --chromadb-only
./scripts/restore_databases.sh --list
```

---

## How It Works

### Ingestion Pipeline

1. **Clone** — repository is cloned to local storage
2. **AST Parsing** — Python/JS files parsed to extract functions, classes, imports
3. **Chunking** — code split into semantic chunks
4. **Embedding** — chunks embedded using Jina AI (`jina-embeddings-v3`)
5. **Dual Write** — ChromaDB (vector search) + Neo4j (graph relationships: CALLS, IMPORTS, CONTAINS)

### Retrieval Pipeline

1. **Vector Search** — query embedded and matched against ChromaDB
2. **Graph Expansion** — initial matches expanded via Neo4j relationships (up to N hops)
3. **Ranking** — results ranked by vector similarity + graph distance
4. **Token Pruning** — context trimmed to fit LLM context window

### Agentic Workflows (LangGraph v3)

Multi-step workflows run as LangGraph state machines, persisted in PostgreSQL via a checkpointer. Workflows include:
- **ask-code** — multi-hop question answering over indexed code
- **ingest** — repository indexing with progress streaming
- **research** — deep research with context synthesis
- **plan** — specification generation from templates
