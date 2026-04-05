# GraphKB Dashboard

React/Next.js dashboard for GraphKB code knowledge graph management.

## Prerequisites

- Node.js 18+
- npm or yarn
- FastAPI backend running on port 8000
- PostgreSQL, Neo4j, and ChromaDB running

## Getting Started

### Installation

```bash
cd graph_kb_dashboard
npm install
```

### Configuration

Copy `.env.local.example` to `.env.local` and configure:

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws
```

### Development

```bash
npm run dev
```

The dashboard will be available at `http://localhost:3000`

### Build

```bash
npm run build
npm run start
```

### Docker

```bash
docker build -t graphkb-dashboard .
docker run -p 3000:3000 -e NEXT_PUBLIC_API_BASE_URL=http://host.docker.internal:8000/api/v1 graphkb-dashboard
```

## Features

- Repository management (list, view, delete)
- Semantic code search
- Symbol exploration with graph relationships
- Real-time workflow updates (WebSocket)
- Architecture overview
- Hotspot analysis

## Project Structure

```
src/
├── app/              # Next.js App Router pages
├── components/       # React components
├── lib/
│   ├── api/        # API client
│   └── types/      # TypeScript types
└── styles/          # Global styles
```
