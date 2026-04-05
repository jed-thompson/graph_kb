# Graph KB API

REST and WebSocket API for code knowledge graph operations.

## Quick Start

### Local Development

```bash
# Install dependencies
pip install -r requirements.api.txt

# Set environment variables
cp .env.api.example .env.api
# Edit .env.api with your values

# Run the API
uvicorn graph_kb_api.main:app --reload --port 8000
```

### Docker

```bash
# Build and run with Docker Compose
docker-compose -f docker-compose.api.yml up --build

# Or build standalone
docker build -f Dockerfile.api -t graph-kb-api .
docker run -p 8000:8000 graph-kb-api
```

## API Documentation

Once running, visit:

- **Swagger UI**: <http://localhost:8000/docs>
- **ReDoc**: <http://localhost:8000/redoc>

## Endpoints

### REST Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/repos` | List repositories |
| GET | `/api/v1/repos/{id}` | Get repository |
| DELETE | `/api/v1/repos/{id}` | Delete repository |
| GET | `/api/v1/repos/{id}/symbols` | Search symbols |
| GET | `/api/v1/repos/{id}/symbols/{id}` | Get symbol |
| POST | `/api/v1/repos/{id}/search` | Semantic search |
| POST | `/api/v1/repos/{id}/retrieve` | Hybrid retrieval |
| GET | `/api/v1/repos/{id}/stats` | Graph statistics |

### WebSocket Endpoints

| Endpoint | Description |
|----------|-------------|
| `/ws` | Generic workflow endpoint |
| `/ws/ask-code` | Code Q&A workflow |
| `/ws/ingest` | Repository ingestion |

#### WebSocket Protocol

**Client → Server:**

```json
{"type": "start", "payload": {"query": "...", "repo_id": "..."}}
```

**Server → Client:**

```json
{"type": "progress", "workflow_id": "...", "data": {"step": "..."}}
{"type": "complete", "workflow_id": "...", "data": {"response": "..."}}
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GRAPHKB_NEO4J_URI` | Neo4j connection URI | `bolt://localhost:7687` |
| `GRAPHKB_OPENAI_API_KEY` | OpenAI API key | - |
| `GRAPHKB_CHROMA_PATH` | ChromaDB storage path | `./chroma_db` |

See `.env.api.example` for all options.
