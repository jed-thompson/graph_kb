# Frontend-Backend Gap Analysis

## Executive Summary

The Next.js dashboard migration has left the frontend and backend disconnected. This document outlines all identified gaps and the required fixes.

---

## Critical Issues

### 1. Port Mismatch (BLOCKING)

**Problem:** Frontend and backend are configured for different ports.

| Component | Current Config | Expected |
|-----------|---------------|----------|
| Frontend API Client | `http://localhost:8000/api/v1` | Should match backend |
| Frontend WebSocket | `ws://localhost:8000/ws` | Should match backend |
| Backend CORS | `http://localhost:8092` | Frontend's port |

**Impact:** All API calls fail with CORS errors.

**Fix:** Update backend CORS to include port 3000 (Next.js default) or update frontend to use port 8092.

---

## Feature Gap Analysis

### Chainlit Commands vs Next.js Implementation

| Command | Chainlit | Next.js | Status |
|---------|----------|---------|--------|
| `/help` | ✅ HelpCommand | ❌ Missing | **Not implemented** |
| `/generate` | ✅ GenerateCommand | ❌ Missing | **Not implemented** |
| `/prompts` | ✅ PromptsCommand | ❌ Missing | **Not implemented** |
| `/ingest` | ✅ IngestCommand + IngestV3Command | ⚠️ Partial | **WebSocket not streaming** |
| `/diff` | ✅ DiffCommand + DiffV3Command | ❌ Missing | **Not implemented** |
| `/status` | ✅ StatusCommand | ❌ Missing | **Not implemented** |
| `/list` | ✅ ListReposCommand | ❌ Missing | **Not implemented** |
| `/ask` | ✅ AskCodeCommand + AskCodeV3Command | ⚠️ Simulated | **Not using real workflow** |
| `/deep` | ✅ DeepCommand | ❌ Missing | **Not implemented** |
| `/search` | ✅ SearchRepoCommand | ✅ Working | **Uses REST API** |
| `/architecture` | ✅ GetArchitectureCommand | ⚠️ Page exists | **Not wired to chat** |
| `/visualize` | ✅ VisualizeCommand | ⚠️ Page exists | **Not wired to chat** |
| `/graph-stats` | ✅ GraphStatsCommand | ⚠️ Page exists | **Not wired to chat** |
| `/debug-graph` | ✅ DebugGraphCommand | ❌ Missing | **Not implemented** |
| `/docs` | ✅ ListDocsCommand | ⚠️ Page exists | **Not wired to chat** |
| `/view-doc` | ✅ ViewDocCommand | ❌ Missing | **Not implemented** |
| `/upload` | ✅ UploadCommand | ❌ Missing | **Not implemented** |
| `/add-template` | ✅ AddTemplateCommand | ❌ Missing | **Not implemented** |
| `/delete-doc` | ✅ DeleteDocCommand | ❌ Missing | **Not implemented** |
| `/add-steering` | ✅ AddSteeringCommand | ❌ Missing | **Not implemented** |
| `/list-steering` | ✅ ListSteeringCommand | ❌ Missing | **Not implemented** |
| `/remove-steering` | ✅ RemoveSteeringCommand | ❌ Missing | **Not implemented** |
| `/attachments` | ✅ ListAttachmentsCommand | ❌ Missing | **Not implemented** |
| `/clear-attachments` | ✅ ClearAttachmentsCommand | ❌ Missing | **Not implemented** |
| `/menu` | ✅ MenuCommand | ❌ Missing | **Not implemented** |

**Summary:** 3 of 25 commands are functional (12%).

---

## Architecture Issues

### 2. WebSocket Not Properly Integrated

**Location:** `graph_kb_dashboard/src/app/api/chat/route.ts:107-236`

**Problem:** The ingest command creates a WebSocket but:
- Messages are logged to console instead of streamed to client
- SSE stream completes before WebSocket responses arrive
- No proper message forwarding from WebSocket to SSE

**Fix:** Implement proper WebSocket-to-SSE bridge that forwards all events.

### 3. No Real LLM Integration

**Location:** `graph_kb_dashboard/src/app/api/chat/route.ts:156-189`

**Problem:** The `/ask` command simulates AI responses with hardcoded text:
```typescript
const answer = `Based on the retrieved code snippets, here's what I found...`;
// Character-by-character streaming simulation
for (let i = 0; i < answer.length; i++) {
  yield { type: 'content', content: answer[i] };
}
```

**Fix:** Connect to actual LangGraph workflows via WebSocket.

### 4. Multi-Agent Workflow Not Connected

**Backend:** `graph_kb_api/flows/v3/graphs/multi_agent.py` exists
**Frontend:** `graph_kb_dashboard/src/lib/api/websocket.ts` has `startMultiAgentWorkflow()`
**Missing:** No chat command or UI to trigger multi-agent workflow

**Fix:** Add `/multi-agent` command to chat route.

---

## Backend API Reference

### REST Endpoints (Working)
- `GET /api/v1/repos` - List repositories
- `GET /api/v1/repos/{repo_id}/symbols` - List symbols
- `POST /api/v1/repos/{repo_id}/search` - Search code
- `POST /api/v1/repos/{repo_id}/retrieve` - Retrieve with context
- `GET /api/v1/repos/{repo_id}/architecture` - Get architecture
- `GET /api/v1/repos/{repo_id}/stats` - Get graph stats

### WebSocket Endpoints (Available)
- `/ws` - Main workflow endpoint
- `/ws/ask-code` - Ask-code workflow
- `/ws/ingest` - Ingest workflow

### WebSocket Events
- `progress` - Progress updates
- `tool_call` - Tool execution
- `clarification` - User clarification needed
- `partial` - Partial response (streaming)
- `complete` - Workflow complete
- `error` - Error occurred

---

## Fix Priority

### P0 - Critical (Blocking)
1. Fix port mismatch - align CORS and frontend config

### P1 - High (Core functionality)
2. Fix WebSocket-to-SSE integration for ingest
3. Connect `/ask` to real LangGraph workflow
4. Add `/deep` command for multi-agent workflow

### P2 - Medium (Feature parity)
5. Implement remaining slash commands
6. Wire existing pages (visualize, stats, docs) to chat

### P3 - Low (Nice to have)
7. Add action callbacks for interactive responses
8. Add file upload handling

---

## Implementation Plan

### Phase 1: Fix Critical Issues
- [ ] Update CORS configuration
- [ ] Update frontend environment config
- [ ] Test basic API connectivity

### Phase 2: Fix WebSocket Integration
- [ ] Implement WebSocket-to-SSE bridge
- [ ] Fix ingest workflow streaming
- [ ] Add proper error handling

### Phase 3: Connect Real Workflows
- [ ] Wire `/ask` to ask-code workflow
- [ ] Wire `/deep` to multi-agent workflow
- [ ] Add streaming responses

### Phase 4: Feature Parity
- [ ] Implement missing commands
- [ ] Wire pages to chat
- [ ] Add action callbacks

---

## Files to Modify

1. `graph_kb_api/main.py` - Update CORS
2. `graph_kb_dashboard/.env.local` - Update API URLs
3. `graph_kb_dashboard/src/app/api/chat/route.ts` - Fix WebSocket integration
4. `graph_kb_dashboard/src/lib/api/websocket.ts` - Add workflow handlers
5. `graph_kb_dashboard/src/lib/types/api.ts` - Add missing types
