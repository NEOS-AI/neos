# NEOS

> 🤖 Multi-Agent AI Search, Analysis & Coding System

NEOS is a multi-agent AI system built on FastAPI and LangGraph. Specialized agents collaborate to search, analyze and verify information, and a sandboxed coding agent runs long tasks with human approval gates. A Next.js frontend (`web/`) streams responses from the backend.

[![Python Version](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## ✨ Key Features

### 🔍 Search & Research
- **Knowledge / Realtime Search**: knowledge-base search plus web search via the Tavily API
- **WebLookUp Agent**: direct URL extraction and analysis, with optional Playwright rendering for JavaScript/SPA pages
- **Multi-Query Search**: multi-angle decomposition of complex queries
- **Deep Research / HyperDeepResearch**: long-form research reports; HyperDeep uses recursive (ROMA) decomposition with a refinement loop
- **Research skills**: built-in skill sources such as arXiv, Semantic Scholar, OpenAlex, PubMed, SEC EDGAR, Wikipedia, Reddit and GitHub (`neos/skills/builtin/`)

### 🧪 Verified Deep Analysis
- Budgeted round loop that only puts **verified claims** in the report (`neos/workflow/deep_analysis/`)
- Deterministic graders check evidence presence, live sources, quote matches and confidence inflation
- Append-only event log with record/replay cassettes and an analytics API (`/api/v1/deep-analysis/...`)

### 💻 Coding Agent
- Durable coding loop with checkpoints, resume, and human approval for risky tool calls (`neos/coding/`)
- Sandboxes: in-memory, Docker, or managed providers (E2B, Modal)
- Subagents, a credential broker (`secret://` references), MCP client connectors, and a device bridge — all **behind feature flags, off by default**

### 🛰️ Standing Agents (experimental, flag-gated)
- Long-lived per-user agents that run background tasks from webhooks, channels (Telegram/Discord/Slack) or schedules
- Monthly budget envelopes, monitor-driven pause and human resume, standing questions that report only new verified/refuted claims

### 🎨 Generation & Tools
- **Image Generation** (OpenAI DALL-E 3), **API Call** agent (weather, exchange rates, stock data)
- **File Processing**: PDF, Word, Excel, PowerPoint parsing; chat attachments reach the model
- **Scheduled tasks** via Celery Beat

### 🧭 Model Routing & Platform
- Role-based model routing (user → conversation → feature override → role default) over Anthropic, OpenAI, Gemini and Ollama providers
- Model facts live in one catalog: `neos/config/models.yaml`
- Chat streaming over SSE (OpenResponses events + `neos:*` extensions)
- Observability: OpenTelemetry, Prometheus/Grafana, Arize Phoenix

## 🚀 Quick Start

### 1. Installation

NEOS uses [uv](https://docs.astral.sh/uv/) (`pyproject.toml` + `uv.lock`).

```bash
git clone https://github.com/NEOS-AI/neos.git
cd neos

# Create .venv and install dependencies (including the dev group)
uv sync

# Optional extras: reranker, sandbox, channels, ollama
uv sync --extra channels

# Playwright browser (for dynamic page rendering)
uv run playwright install chromium
```

### 2. Configuration

Secrets go in `.env`; non-secret runtime settings go in a YAML overlay.

```bash
cp .env.template .env
cp config/neos.example.yaml config/neos.local.yaml
```

In `.env`, set at least:

```dotenv
NEOS_CONFIG_PATH=config/neos.local.yaml
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/neos
REDIS_URL=redis://localhost:6379/0
JWT_SECRET_KEY=<random string>

# LLM / search keys (set the providers you use)
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
TAVILY_API_KEY=...
```

YAML loads as `config/neos.default.yaml` → `config/neos.<NEOS_ENV>.yaml` (default `development`) → `NEOS_CONFIG_PATH`; secrets come from `.env` (or `NEOS_SECRETS_PATH`), with real process env winning. See [docs/CONFIGURATION.md](./docs/CONFIGURATION.md) and [docs/CONFIG_INVENTORY.md](./docs/CONFIG_INVENTORY.md).

### 3. Database and Redis

The database image (PostgreSQL 16 + pgvector) and schema bootstrap are driven by `make`:

```bash
make image-build     # build the neos-paradedb image
make db-up           # start the container and wait for pg_isready
make db-bootstrap    # apply the schema in canonical order (creates the DB if missing)

# Redis-compatible cache/broker
docker run --name neos-valkey -p 6379:6379 -d valkey/valkey
```

The schema order is defined by [db/BOOTSTRAP_ORDER.txt](./db/BOOTSTRAP_ORDER.txt). Run `make help` for all targets (`db-reset`, `db-shell`, `db-verify`, ...) and see [db/README.md](./db/README.md) for details.

### 4. Run the Backend

```bash
# Development server (port 8518)
uv run python -m neos.main

# Or with uvicorn / Granian
uv run uvicorn neos.main:app --reload --host 0.0.0.0 --port 8518
uv run granian --port 8518 --host 0.0.0.0 neos/main:app
```

Celery workers (queues: `search`, `analysis`, `generation`, `default`) and Flower can be started from `docker-compose.dev.yml` with `--profile celery`.

### 5. Run the Frontend (optional)

```bash
cd web
cp .env.example .env.local   # set BACKEND_URL=http://localhost:8518, auth secrets, etc.
pnpm install
pnpm dev                     # http://localhost:3000
```

### 6. Test the API

```bash
# Health check
curl http://localhost:8518/api/v1/health

# Chat (chat routes need a bearer token)
TOKEN=$(curl -s -X POST http://localhost:8518/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "<password>"}' | jq -r .access_token)
CONV=$(curl -s -X POST http://localhost:8518/api/v1/chat/conversations \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"title": "AI trends"}' | jq -r .conversation_id)
curl -N -X POST "http://localhost:8518/api/v1/chat/conversations/$CONV/messages/stream" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"content": "Analyze AI trends in 2026"}'
```

Interactive API docs: **Swagger UI** at http://localhost:8518/docs, **ReDoc** at http://localhost:8518/redoc.

> In non-debug runtimes the legacy chat/query/workflow WebSocket routes are not mounted; chat uses the SSE stream above. Only the coding WebSocket remains, with ticket authentication.

## 🧪 Running Tests

```bash
# Backend (pytest.ini sets asyncio mode and test paths)
uv run pytest -q

# Frontend
cd web && pnpm test:source && pnpm typecheck
```

Integration tests need a bootstrapped PostgreSQL; `tests/conftest.py` only lets tests touch a database whose name ends in `_test`. Some suites need explicit opt-in:

```bash
# Managed sandbox control plane against a real PostgreSQL
CODING_TEST_DATABASE_URL='postgresql+asyncpg://user:pass@host/db' \
  uv run pytest -q tests/coding/managed/integration -rs

# Vendor sandbox smokes (each creates one sandbox, <=300s, network blocked,
# destroyed in finally)
CODING_TEST_E2B=1 E2B_API_KEY=<key> \
  uv run pytest -q tests/coding/managed/integration/test_e2b_opt_in.py -rs

CODING_TEST_MODAL=1 MODAL_TOKEN_ID=<id> MODAL_TOKEN_SECRET=<secret> \
  uv run pytest -q tests/coding/managed/integration/test_modal_opt_in.py -rs

# Docker sandbox gateway
CODING_TEST_DOCKER=1 \
  CODING_TEST_DOCKER_IMAGE='registry/neos-sandbox@sha256:<digest>' \
  uv run pytest -q tests/coding/integration/test_docker_workspace_gateway.py -rs
```

Skipped suites report the exact variable to set.

## 🎯 Usage Examples

### CLI

> The CLI imports `rich`, which is not yet declared in `pyproject.toml`. Until it is, install it first: `uv pip install rich`.

```bash
uv run python -m neos.cli status

# Full workflow
uv run python -m neos.cli workflow test "Analyze AI trends in 2026"

# URL content analysis (--dynamic renders JavaScript with Playwright)
uv run python -m neos.cli workflow web-lookup https://www.example.com
uv run python -m neos.cli workflow web-lookup https://spa-app.com --dynamic

# Deep Research / HyperDeepResearch
uv run python -m neos.cli workflow deep-research "AI semiconductor market outlook"
uv run python -m neos.cli workflow hyper-deep-research "2026년 글로벌 AI 시장 전망"

# Interactive mode
uv run python -m neos.cli interactive
```

Other groups: `agent`, `mcp`, `dataset`, `config`. See [docs/CLI_GUIDE.md](./docs/CLI_GUIDE.md).

### API (Python)

```python
import requests

BASE = "http://localhost:8518/api/v1"
token = requests.post(
    f"{BASE}/auth/login",
    json={"email": "you@example.com", "password": "<password>"},
).json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

conversation = requests.post(
    f"{BASE}/chat/conversations", json={"title": "Model comparison"}, headers=headers
).json()

# SSE (OpenResponses events + neos:* extensions)
with requests.post(
    f"{BASE}/chat/conversations/{conversation['conversation_id']}/messages/stream",
    json={"content": "Compare ChatGPT and Claude"},
    headers=headers,
    stream=True,
) as response:
    for line in response.iter_lines(decode_unicode=True):
        if line.startswith("data: "):
            print(line[6:])
```

### Agents in Python

```python
from neos.agents.search_agents import WebLookUpAgent

agent = WebLookUpAgent(use_playwright=True)
result = await agent.execute(
    query="Analyze https://example.com",
    context={"session_id": "session_123", "user_id": "user_456"},
)
```

## 🗂️ Project Layout

| Path | Contents |
|---|---|
| `neos/api/` | FastAPI routers and handlers |
| `neos/workflow/` | LangGraph workflow, deep analysis loop, HyperDeep, recursive (ROMA) engine |
| `neos/agents/` | Search, analysis and generation agents |
| `neos/coding/` | Coding agent loop, sandboxes, connectors, secrets, device bridge |
| `neos/standing/` | Standing agents |
| `neos/providers/` | Model provider plugins (Anthropic, OpenAI, Gemini, Ollama) |
| `neos/config/` | Settings schema, loader, model catalog (`models.yaml`) |
| `neos/skills/` | Skill auto-discovery and built-in skills |
| `neos/memory/` | Short-term, episodic and long-term memory |
| `neos/database/` | SQLAlchemy models and connections |
| `neos/observability/` | Metrics and tracing |
| `db/` | SQL schema, migrations, bootstrap order |
| `config/` | Runtime YAML profiles, nginx, Prometheus, Grafana, Loki |
| `web/` | Next.js frontend |

## 🛠️ Tech Stack

- **Backend**: Python 3.12+, FastAPI, Uvicorn/Granian, LangGraph
- **LLMs**: Anthropic Claude, OpenAI, Google Gemini, Ollama (via role-based routing)
- **Data**: PostgreSQL 16 + pgvector, Redis/Valkey (semantic cache, Celery broker)
- **Tasks / Distribution**: Celery 5, Ray (optional, `RAY_ENABLED`)
- **Search & Rendering**: Tavily, Playwright, Trafilatura
- **Observability**: OpenTelemetry, Prometheus, Grafana, Loki, Arize Phoenix
- **Frontend**: Next.js 16, React 19, NextAuth.js v5, Vercel AI SDK

## 📚 Documentation

- **Setup**: [Configuration](./docs/CONFIGURATION.md) · [Config inventory](./docs/CONFIG_INVENTORY.md) · [Google OAuth](./docs/GOOGLE_OAUTH_SETUP.md) · [Database](./db/README.md)
- **Usage**: [CLI Guide](./docs/CLI_GUIDE.md) · [API Integrations](./docs/API_INTEGRATIONS.md) · [OpenResponses spec](./docs/OPEN_RESPONSES_SPEC.md)
- **Design**: [Model catalog](./docs/MODEL_CATALOG_DESIGN.md) · [Deep analysis harness](./docs/DEEP_ANALYSIS_HARNESS_DESIGN.md) · [Subagent runtime](./docs/SUBAGENT_RUNTIME_DESIGN.md) · [Standing agents](./docs/Q13_STANDING_AGENT_DESIGN_260930.md)
- **Roadmap**: [Deep analysis harness roadmap](./docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md) (current track status) · [ROADMAP](./docs/ROADMAP.md)
