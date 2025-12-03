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
git clone <repository-url>
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
# Create .env file
cp .env.example .env

# Set required API keys
# - OPENAI_API_KEY: OpenAI API key
# - TAVILY_API_KEY: Tavily search API key
```

### 3. Start Database

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
```

### 5. Test API

```bash
# Health check
curl http://localhost:8518/api/v1/health

# Query test
curl -X POST http://localhost:8518/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Analyze AI trends in 2024"}'
```

## 🎯 Usage Examples

### CLI Commands

```bash
# General query
python -m neos.cli workflow test "Analyze AI trends in 2025"

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

response = requests.post(
    "http://localhost:8518/api/v1/query",
    json={"query": "Compare ChatGPT and Claude"}
)

print(response.json())
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
