# Platform Architecture

Technical architecture and design decisions for the AI Web Scraper Platform.

---

## 🏛️ High-Level Architecture

```
┌─────────────────────────────────────────────────┐
│                  User Layer                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │   API    │  │   n8n    │  │  Direct  │     │
│  │  Calls   │  │ Workflows│  │  Agents  │     │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘     │
└───────┼─────────────┼─────────────┼────────────┘
        │             │             │
        └─────────────┴─────────────┘
                      │
        ┌─────────────▼──────────────┐
        │     Agent Gateway          │
        │  (Orchestration Layer)     │
        └─────────────┬──────────────┘
                      │
    ┌─────────────────┼─────────────────┐
    │                 │                 │
┌───▼────┐   ┌────────▼───┐   ┌────────▼───┐
│Discovery│   │  Camoufox  │   │   Vision   │
│ Agent  │   │   Agent    │   │   Agent    │
└────────┘   └────────────┘   └──────┬─────┘
                                      │
             ┌────────────┐     ┌─────▼──────┐
             │ Extraction │     │   Ollama   │
             │   Agent    │────→│ AI Models  │
             └────────────┘     └────────────┘
                  │                    │
           ┌──────▼────────────────────▼─────┐
           │         MongoDB                 │
           │     (Data Persistence)          │
           └─────────────────────────────────┘
```

---

## 🔧 Component Details

### Agent Gateway
**Purpose**: Central orchestrator for all scraping operations
**Tech**: FastAPI, Python 3.11
**Responsibilities**:
- Request routing
- Job management
- Agent coordination
- Result aggregation
- Status tracking

**Key Files**:
- `agent_gateway.py` - Main gateway service
- `Dockerfile.agent-gateway` - Container definition

**API Endpoints**:
- `POST /scrape` - Create scraping job
- `GET /jobs/{id}` - Get job status
- `GET /jobs` - List all jobs
- `GET /health` - Health check

---

### Agent Discovery
**Purpose**: Web crawling and URL discovery
**Tech**: FastAPI, httpx, BeautifulSoup
**Responsibilities**:
- URL discovery
- Sitemap generation
- Link extraction
- Crawl depth management

**Key Features**:
- Configurable crawl depth
- Pattern matching
- External link filtering
- Concurrent requests

**API Endpoints**:
- `POST /discover` - Start discovery
- `GET /sitemap/{domain}` - Get sitemap

---

### Agent Camoufox
**Purpose**: Anti-detection browser automation
**Tech**: Camoufox (Firefox-based), Playwright
**Responsibilities**:
- JavaScript rendering
- Screenshot capture
- Anti-bot evasion
- Human-like behavior

**Key Features**:
- Fingerprint rotation
- Human mouse movement
- Anti-detection patches
- Full page rendering

**Why Camoufox?**
- Best-in-class stealth (passes Cloudflare, DataDome, etc.)
- Open source
- Fingerprint injection at C++ level
- Active development

**API Endpoints**:
- `POST /render` - Render page
- `POST /screenshot` - Capture screenshot

---

### Agent Vision
**Purpose**: OCR and image analysis
**Tech**: FastAPI, Ollama vision models
**Responsibilities**:
- Text extraction (OCR)
- Image description
- Layout analysis
- Table extraction

**Supported Models**:
- llava (default)
- qwen3-vl
- llama3.2-vision

**API Endpoints**:
- `POST /process` - Process image
- `POST /ocr` - OCR only

---

### Agent Extraction
**Purpose**: AI-powered data extraction
**Tech**: FastAPI, Ollama LLMs
**Responsibilities**:
- Structured data extraction
- Content summarization
- Schema-based extraction
- Embedding generation

**Extraction Types**:
- General content
- Product data
- Article content
- Contact information
- Event details

**API Endpoints**:
- `POST /extract` - Extract structured data
- `POST /summarize` - Summarize content
- `POST /embed` - Generate embeddings

---

### Ollama Service
**Purpose**: AI model serving
**Tech**: Ollama
**Responsibilities**:
- Model management
- Inference serving
- GPU acceleration
- Model caching

**Supported Model Types**:
- Language models (LLMs)
- Vision-language models
- Embedding models
- Code models

---

### MongoDB
**Purpose**: Data persistence
**Tech**: MongoDB 7
**Collections**:
- `jobs` - Scraping jobs
- `discovered_urls` - Crawled URLs
- `results` - Extracted data
- `screenshots` - Image data

---

### n8n
**Purpose**: Workflow automation
**Tech**: n8n
**Use Cases**:
- Custom scraping workflows
- Data pipelines
- Scheduled jobs
- Webhook integrations

---

## 🔄 Data Flow

### Simple Scrape Flow
```
1. User → Gateway: POST /scrape
2. Gateway → MongoDB: Create job
3. Gateway → Camoufox: Render page
4. Camoufox → Gateway: HTML + screenshot
5. Gateway → Extraction: Extract data
6. Extraction → Ollama: LLM inference
7. Ollama → Extraction: Structured data
8. Gateway → MongoDB: Store results
9. Gateway → User: Job ID
```

### Full Pipeline Flow
```
1. User → Gateway: POST /scrape (strategy=full)
2. Gateway → Discovery: Find URLs
3. Discovery → Gateway: URL list
4. Gateway → Camoufox: Render each page
5. Camoufox → Gateway: HTML + screenshots
6. Gateway → Vision: Analyze screenshots
7. Vision → Ollama: Vision model
8. Gateway → Extraction: Extract data
9. Extraction → Ollama: LLM
10. Gateway → MongoDB: Store all results
11. Gateway → User: Aggregated results
```

---

## 🔐 Security Architecture

### Network Isolation
```
Public Network
    ↓
[Gateway:8000] [n8n:5678]
    ↓
Internal Network
    ↓
[Discovery] [Camoufox] [Vision] [Extraction]
    ↓
[Ollama] [MongoDB]
```

### Authentication
- **Gateway**: API key middleware (optional)
- **MongoDB**: Username/password
- **n8n**: User accounts
- **Internal**: No auth (internal network)

### Data Security
- Credentials in `.env` (gitignored)
- MongoDB authentication required
- No hardcoded secrets
- Volume encryption supported

---

## 📊 Scalability

### Horizontal Scaling
**Stateless Services** (can scale):
- Agent Camoufox (most beneficial)
- Agent Discovery
- Agent Extraction
- Agent Vision

**Stateful Services** (harder to scale):
- MongoDB (requires replication)
- Ollama (model caching issues)

### Vertical Scaling
**Memory-Intensive**:
- Ollama (AI models)
- Camoufox (browser instances)

**CPU-Intensive**:
- Extraction (LLM inference)
- Discovery (concurrent requests)

**Disk-Intensive**:
- MongoDB
- Ollama (model storage)

---

## 🚀 Deployment Models

### 1. Single Server (Recommended for Start)
All services on one machine
- **Pros**: Simple, easy to manage
- **Cons**: Resource limited
- **Minimum**: 16GB RAM, 100GB disk

### 2. Multi-Server
Split by resource type
- Server 1: Gateway, n8n, MongoDB
- Server 2: Ollama (GPU server)
- Server 3+: Camoufox replicas

### 3. Kubernetes (Future)
Full container orchestration
- Auto-scaling
- High availability
- Complex setup

---

## 🔧 Technology Choices

### Why FastAPI?
- Modern async Python
- Auto-generated docs
- High performance
- Easy to extend

### Why MongoDB?
- Flexible schema (scraping varies)
- Good performance
- Easy horizontal scaling
- JSON-native

### Why Ollama?
- Local AI (no API costs)
- Easy model management
- GPU support
- Active community

### Why Camoufox?
- Best stealth capabilities
- Open source
- Well-maintained
- Passes major WAFs

### Why n8n?
- Visual workflow builder
- Self-hosted
- Extensible
- Large integration library

---

## 📈 Performance Characteristics

### Throughput
- **Discovery**: 10-50 pages/second
- **Camoufox**: 1-5 pages/second (bottleneck)
- **Extraction**: 5-20 pages/second
- **Vision**: 2-10 images/second

### Latency
- **Simple scrape**: 5-30 seconds
- **Full pipeline**: 30-120 seconds
- **Vision processing**: 10-60 seconds per image

### Resource Usage
- **Gateway**: 100-500MB RAM
- **Discovery**: 200-500MB RAM
- **Camoufox**: 1-4GB RAM per instance
- **Vision**: 500MB-2GB RAM
- **Extraction**: 500MB-2GB RAM
- **Ollama**: 4-16GB RAM (model dependent)
- **MongoDB**: 1-10GB RAM (data dependent)

---

## 🔄 Future Architecture

### Planned Improvements
1. **Queue System**: Redis/RabbitMQ for job queue
2. **Caching**: Redis for rendered pages
3. **Proxy Rotation**: Built-in proxy management
4. **Rate Limiting**: Per-domain rate limits
5. **Retry Logic**: Intelligent retry strategies
6. **Result Streaming**: Real-time result streaming
7. **Multi-tenancy**: Isolated workspaces
8. **Analytics**: Built-in usage analytics

### Potential Additions
- **Agent Browser**: Web UI for job management
- **Agent Scheduler**: Advanced scheduling
- **Agent Validator**: Data quality checks
- **Agent Deduplicator**: Content deduplication
- **Agent Indexer**: Full-text search

---

## 📚 Design Patterns

### Microservices
Each agent is independent
- **Pros**: Scalable, isolated
- **Cons**: Network overhead

### Gateway Pattern
Single entry point
- **Pros**: Simple API, centralized
- **Cons**: Single point of failure

### Job Queue (Planned)
Async job processing
- **Pros**: Better throughput
- **Cons**: More complex

### Plugin Architecture (n8n)
Extensibility through workflows
- **Pros**: No code changes needed
- **Cons**: Learning curve

---

## 🤝 Contributing

### Adding New Agents
1. Create `agent_name.py`
2. Create `Dockerfile.agent-name`
3. Add to `docker-compose.yml`
4. Update gateway routing
5. Document API

### Adding AI Models
1. Add to `models.config`
2. Update agent to use model
3. Document model purpose
4. Test inference

### Adding Workflows
1. Create workflow in n8n
2. Export to JSON
3. Add to `n8n-workflows/examples/`
4. Document usage

---

**This architecture enables scalable, maintainable, and extensible web scraping at any scale.**
