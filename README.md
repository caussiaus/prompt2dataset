# AI-Augmented Web Scraper Platform

**A production-ready, self-hosted web scraping platform with AI-powered extraction, vision processing, and workflow automation.**

Deploy once on Coolify, customize forever with n8n workflows.

---

## ⚡ Quick Start (5 Minutes)

```bash
# Clone and setup
git clone <your-repo> ai-scraper && cd ai-scraper
bash setup.sh

# Select: 1) Quick Start
# Wait 5-10 minutes for models to download

# Access your services
open http://localhost:8000/docs
open http://localhost:5678
```

**That's it!** Full documentation below.

[📖 See QUICKSTART.md for detailed quick start guide](QUICKSTART.md)

---

## 🎯 What is This?

This is a **complete web scraping infrastructure** that you deploy once and then customize through n8n workflows. The platform handles:

- 🤖 **AI Model Management** - Automatic download and management of SOTA AI models
- 🌐 **Browser Automation** - Anti-detection browser rendering with Camoufox
- 👁️ **Vision Processing** - OCR, image analysis, and screenshot understanding
- 🔍 **Discovery** - Intelligent web crawling and URL discovery
- 📊 **Data Extraction** - AI-powered structured data extraction
- 🔄 **Workflow Automation** - n8n for custom scraping workflows

**The Magic**: You don't write code for scraping projects. You create n8n workflows that orchestrate the agents.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────┐
│                    n8n Workflows                     │
│          (Your Custom Scraping Logic Here)          │
└────────────────────┬────────────────────────────────┘
                     │
         ┌───────────┴───────────┐
         │   Agent Gateway       │
         │   (Orchestrator)      │
         └───────────┬───────────┘
                     │
    ┏━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━┓
    ┃                              ┃
┌───▼────┐  ┌──────▼─┐  ┌────▼────┐  ┌────▼────┐
│Discovery│  │Camoufox│  │ Vision  │  │Extraction│
│ Agent  │  │ Agent  │  │  Agent  │  │  Agent  │
└────────┘  └────────┘  └─────────┘  └─────────┘
                          │
                    ┌─────▼──────┐
                    │   Ollama   │
                    │ (AI Models)│
                    └────────────┘
```

---

## 🚀 Quick Start (Coolify Deployment)

### Prerequisites
- [Coolify](https://coolify.io/) installed on your server
- Docker & Docker Compose
- (Optional) NVIDIA GPU for faster AI processing

### Step 1: Clone & Configure

```bash
# Clone this repository in Coolify's project directory
git clone <your-repo-url> ai-web-scraper
cd ai-web-scraper

# Create environment file
cp .env.example .env
nano .env  # Edit with your settings
```

**Important**: Change `MONGO_PASSWORD` to a secure password!

### Step 2: Select AI Models

Edit `models.config` to select which AI models to download:

```bash
nano models.config
```

Remove/comment out models you don't need. Smaller setups can use:
- `llama3.1` (general LLM, ~4GB)
- `llava` (vision, ~4GB)
- `bge-m3` (embeddings, ~2GB)

Full setup with all models requires ~50GB+ disk space.

### Step 3: Deploy on Coolify

1. **In Coolify UI**:
   - Create new project: "AI Web Scraper"
   - Add resource → Docker Compose
   - Point to this repository
   - Set compose file: `docker-compose.yml`

2. **Environment Variables** (Set in Coolify):
   ```
   MONGO_PASSWORD=your_secure_password
   DATA_PATH=/data
   ```

3. **Deploy**:
   - Click "Deploy"
   - First deployment will download AI models (takes 10-30 minutes)
   - Monitor logs to see model download progress

### Step 4: Access Services

After deployment, access:

- **API Gateway**: `http://your-domain:8000`
- **API Docs**: `http://your-domain:8000/docs`
- **n8n Workflow Builder**: `http://your-domain:5678`
- **MongoDB**: `mongodb://your-domain:27017`

---

## 📦 What Gets Deployed

| Service | Port | Description |
|---------|------|-------------|
| **agent-gateway** | 8000 | Main API orchestrator |
| **agent-discovery** | 8001 | Web crawling & URL discovery |
| **agent-camoufox** | 8002 | Anti-detection browser |
| **agent-vision** | 8003 | OCR & image analysis |
| **agent-extraction** | 8004 | AI data extraction |
| **ollama** | 11434 | AI model server |
| **mongodb** | 27017 | Data persistence |
| **n8n** | 5678 | Workflow automation |

---

## 🎨 Creating Scraping Workflows

### Method 1: Use the API Directly

```bash
# Start a scraping job
curl -X POST http://your-domain:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "strategy": "full",
    "use_vision": true
  }'

# Check job status
curl http://your-domain:8000/jobs/{job_id}
```

### Method 2: Create n8n Workflows (Recommended)

1. **Access n8n**: `http://your-domain:5678`
2. **Import workflow** from `n8n-workflows/examples/`
3. **Customize** the workflow for your needs
4. **Activate** and run

See `n8n-workflows/README.md` for example workflows.

---

## 📚 Example Use Cases

### 1. Product Price Monitoring
```
n8n Trigger (Schedule) 
  → Call Gateway API (product URLs)
  → Extract structured data (price, stock, etc.)
  → Store in MongoDB
  → Send alerts on price changes
```

### 2. News Article Scraping
```
n8n Trigger (Webhook)
  → Discovery Agent (find all articles)
  → Vision Agent (screenshot articles)
  → Extraction Agent (title, author, content)
  → Export to JSON/CSV
```

### 3. Real Estate Data Collection
```
n8n Schedule
  → Discovery (find property listings)
  → Camoufox (render JS-heavy pages)
  → Vision (extract from images)
  → Extraction (structured property data)
  → Database storage
```

---

## 🎛️ Configuration

### AI Models (models.config)

Choose models based on your hardware:

**Minimum Setup** (12GB RAM, no GPU):
```
llama3.1
llava
bge-m3
```

**Recommended Setup** (32GB RAM, GPU):
```
llama3.1
llava
qwen3-vl
deepseek-r1
codellama
bge-m3
```

**Full Setup** (64GB+ RAM, GPU):
All models from `models.config`

### Environment Variables

Key variables to configure in `.env`:

```bash
# Database
MONGO_PASSWORD=change_this_password

# AI Models
VISION_MODEL=llava
EXTRACTION_MODEL=llama3.1
EMBEDDING_MODEL=bge-m3

# Discovery
MAX_CONCURRENT_REQUESTS=10

# Storage
DATA_PATH=./data
```

---

## 🔧 Customization Guide

### Change AI Models

1. Edit `models.config`
2. Redeploy model-manager service
3. Update env vars (VISION_MODEL, EXTRACTION_MODEL, etc.)
4. Restart affected agents

### Add Custom Agents

1. Create new agent file: `agent_custom.py`
2. Add Dockerfile: `Dockerfile.custom-agent`
3. Add to `docker-compose.yml`
4. Rebuild and deploy

### Modify Extraction Logic

Edit prompts in `agent_extraction.py`:
```python
prompts = {
    "product": "Extract product info including...",
    "article": "Extract article info including...",
    # Add your custom types
}
```

---

## 🐛 Troubleshooting

### Models Not Downloading

```bash
# Check Ollama logs
docker logs webscraper-ollama

# Manually trigger model download
docker exec webscraper-model-manager python model_manager.py
```

### Agent Connection Errors

```bash
# Check all services are healthy
docker ps

# Check specific agent logs
docker logs webscraper-gateway
docker logs webscraper-camoufox
```

### Memory Issues

Reduce models in `models.config` or increase Docker memory limits.

### Browser Rendering Fails

Camoufox requires shared memory. Ensure `shm_size: 2gb` in docker-compose.

---

## 📊 Monitoring

### Health Checks

```bash
# Check all services
curl http://your-domain:8000/health

# Individual agents
curl http://your-domain:8001/health  # Discovery
curl http://your-domain:8002/health  # Camoufox
curl http://your-domain:8003/health  # Vision
curl http://your-domain:8004/health  # Extraction
```

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f agent-gateway
```

### Database Queries

```bash
# Connect to MongoDB
docker exec -it webscraper-mongodb mongosh -u admin -p your_password

# View jobs
use webscraper
db.jobs.find().limit(10)
```

---

## 🔐 Security Notes

1. **Change default passwords** in `.env`
2. **Use HTTPS** in production (configure in Coolify)
3. **Restrict ports** - Only expose 8000 and 5678 publicly
4. **API authentication** - Add auth middleware to gateway
5. **Rate limiting** - Configure in gateway or reverse proxy

---

## 📈 Scaling

### Horizontal Scaling

In Coolify, increase replicas for:
- `agent-camoufox` (most resource-intensive)
- `agent-extraction` (parallel processing)
- `agent-discovery` (concurrent crawling)

### Vertical Scaling

Allocate more resources:
- Ollama: More RAM for larger models
- Camoufox: More CPU for rendering
- MongoDB: More disk for data storage

---

## 🤝 Contributing Workflows

Share your n8n workflows:

1. Export workflow from n8n
2. Add to `n8n-workflows/community/`
3. Include README with use case
4. Submit PR

---

## 📄 License

MIT License - See LICENSE file

---

## 🙏 Credits

- **Camoufox** - Anti-detection browser
- **Ollama** - Local AI model serving
- **n8n** - Workflow automation
- **FastAPI** - API framework
- **MongoDB** - Data storage

---

## 📞 Support

- **Issues**: GitHub Issues
- **Discussions**: GitHub Discussions
- **Documentation**: `/docs` folder

---

## 🗺️ Roadmap

- [ ] Web UI for job management
- [ ] Pre-built workflow templates marketplace
- [ ] Proxy rotation support
- [ ] Webhook integrations
- [ ] Data export pipelines
- [ ] Cost tracking & analytics
- [ ] Multi-tenant support

---

**Built for self-hosters who want powerful web scraping without SaaS lock-in.**
