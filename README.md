# NEOS

> 🤖 Intelligent Multi-Agent AI System

A next-generation AI system built with LangGraph, CrewAI, and FastAPI. Multiple specialized agents collaborate to process complex queries and deliver high-quality, integrated responses.

[![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## ✨ Key Features

### 🔍 Intelligent Search Agents
- **Knowledge Search**: Knowledge base-powered search
- **Realtime Search**: Real-time web search via Tavily API
- **WebLookUp Agent**: Direct URL content extraction and analysis
  - 🎭 Playwright dynamic rendering support (JavaScript/SPA)
  - Parallel processing of multiple URLs
  - LLM-based content analysis
- **Multi-Query Search**: Multi-angle analysis of complex queries
- **Deep Research**: Expert-level in-depth research reports (15-30 minutes)
- **HyperDeepResearch**: 200+ source collection, 8-stage systematic process (30-60 minutes)

### 📊 Advanced Analysis Agents
- **Data Analysis**: Statistical analysis and pattern discovery
- **Comparative Analysis**: Multi-source comparative analysis
- **Web Content Analysis**: Web page content analysis

### 🎨 Content Generation Agents
- **Image Generation**: OpenAI DALL-E 3
- **API Call**: Weather, currency exchange, stock market data
- **File Processing**: Document analysis, conversion, summarization
- **Task Creation**: Automated project planning

### 🚀 Intelligent Workflows
- LangGraph-based complex agent orchestration
- Dynamic routing: Automatic selection of optimal agents based on query intent and complexity
- Quality validation: Automatic response quality evaluation and reprocessing
- Real-time processing: WebSocket support

## 🚀 Quick Start

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/NEOS-AI/neos.git
cd neos

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright (optional, for dynamic page rendering)
pip install playwright
playwright install chromium
```

### 2. Configuration

```bash
# Create secret env and local YAML overlay
cp .env.template .env
cp config/neos.example.yaml config/neos.local.yaml

# Set NEOS_CONFIG_PATH=config/neos.local.yaml in .env.
# Put secrets in .env and non-secret runtime settings in YAML.
#
# Required API keys
# - OPENAI_API_KEY: OpenAI API key
# - TAVILY_API_KEY: Tavily search API key
```

For details, see [docs/CONFIGURATION.md](./docs/CONFIGURATION.md).

### 3. Start Database, and Dependency Services

Run PostgreSQL and Redis with Docker:

```bash
cd db
docker-compose up -d
```

For more details, see [db/README.md](./db/README.md).

### 4. Run Application

```bash
# Start development server
python3 -m neos.main

# Or run uvicorn directly
uvicorn neos.main:app --reload --host 0.0.0.0 --port 8518

# Also, you could use Granian for better performance
uv run granian --port 8518 --host 0.0.0.0 neos/main:app
```

### 5. Test API

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
  -d '{"content": "Analyze AI trends in 2024"}'
```

### 6. Optional test suites

Most suites run with no external services. These need explicit opt-in:

```bash
# Managed sandbox control plane against a real PostgreSQL
CODING_TEST_DATABASE_URL='postgresql+asyncpg://user:pass@host/db' \
  .venv/bin/pytest -q tests/coding/managed/integration -rs

# Vendor sandbox smokes (each creates one sandbox, <=300s, network blocked,
# destroyed in finally)
CODING_TEST_E2B=1 E2B_API_KEY=<key> \
  .venv/bin/pytest -q tests/coding/managed/integration/test_e2b_opt_in.py -rs

CODING_TEST_MODAL=1 MODAL_TOKEN_ID=<id> MODAL_TOKEN_SECRET=<secret> \
  .venv/bin/pytest -q tests/coding/managed/integration/test_modal_opt_in.py -rs

# Docker sandbox gateway
CODING_TEST_DOCKER=1 \
  CODING_TEST_DOCKER_IMAGE='registry/neos-sandbox@sha256:<digest>' \
  .venv/bin/pytest -q tests/coding/integration/test_docker_workspace_gateway.py -rs
```

Skipped suites report the exact variable to set. Operations runbook:
[docs/NEOS_CODING.md](docs/NEOS_CODING.md) §24.

## 🎯 Usage Examples

### CLI Commands

```bash
# General query
python -m neos.cli workflow test "Analyze AI trends in 2026"

# Stock price prediction
python -m neos.cli workflow test "nvidia stock price prediction for Q1 2026"

# URL content analysis
python -m neos.cli workflow web-lookup https://www.example.com

# Dynamic page rendering (JavaScript support)
python -m neos.cli workflow web-lookup https://spa-app.com --dynamic

# Deep Research
python -m neos.cli workflow deep-research "AI semiconductor market outlook"

# HyperDeepResearch
python -m neos.cli workflow hyper-deep-research "2025년 글로벌 AI 시장 전망"
```

For more CLI examples, see [docs/CLI_GUIDE.md](./docs/CLI_GUIDE.md).

### API Calls

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

### Python Code

```python
from neos.agents.search_agents import WebLookUpAgent

# Using WebLookUp Agent
agent = WebLookUpAgent(use_playwright=True)
result = await agent.execute(
    query="Analyze https://example.com",
    context={"session_id": "session_123", "user_id": "user_456"}
)
```

## 📚 Documentation

### User Guides
- [CLI Guide](./docs/CLI_GUIDE.md)
- [Playwright Setup](./docs/PLAYWRIGHT_SETUP.md)

### Agents
- [WebLookUp Agent](./docs/WEB_LOOKUP_AGENT.md)
- [API Call Agent](./docs/API_INTEGRATIONS.md)

### Other
- [Roadmap](./docs/ROADMAP.md)
- [Changelog](./changelog.md)

## 🛠️ Tech Stack

- **Frameworks**: FastAPI, LangGraph, CrewAI
- **Databases**: PostgreSQL + pgvector, Redis
- **AI Models**: OpenAI GPT-4, DALL-E 3
- **Search**: Tavily API
- **Rendering**: Playwright, BeautifulSoup4
- **Language**: Python 3.11+

For more details, see [System Architecture](./docs/ARCHITECTURE.md).

## 📊 API Documentation

After running the application, access interactive API documentation at:

- **Swagger UI**: http://localhost:8518/docs
- **ReDoc**: http://localhost:8518/redoc

## 🌟 Highlights

### WebLookUp Agent 🔗
- Automatic URL content extraction and analysis
- Static HTML: Fast processing (1-3 seconds)
- Dynamic rendering: JavaScript/SPA support (10-30 seconds)
- Parallel processing of multiple URLs

### Deep Research 🔬
- 4-stage in-depth exploration process
- 30-50+ source collection
- Expert-level markdown reports
- Automatic gap analysis and validation

### API Integration 🌐
- Real-time weather, currency exchange, stock data
- Automatic natural language parameter extraction
- 160+ currency support
- Financial statement retrieval

## 🗺️ Roadmap

See [ROADMAP.md](./docs/ROADMAP.md) for the complete roadmap.

## 🙏 Acknowledgments

- [LangGraph](https://github.com/langchain-ai/langgraph)
- [CrewAI](https://github.com/crewAIInc/crewAI)
- [FastAPI](https://github.com/fastapi/fastapi)
- [Tavily](https://tavily.com)
- [Playwright](https://playwright.dev)
