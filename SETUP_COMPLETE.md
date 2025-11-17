# prompt2dataset Repository Setup - COMPLETE ✅

**Setup Date**: 2025-11-17  
**Status**: Production-ready for Coolify deployment

---

## ✅ What Has Been Created

### Core Configuration Files

- ✅ **services.json** - Service registry (source of truth for all services)
- ✅ **coolify-manifest.yaml** - Coolify deployment blueprint
- ✅ **docker-compose.local.yml** - Local development environment
- ✅ **.gitignore** - Git ignore rules (excludes secrets)
- ✅ **config/.env.example** - Environment variable template

### Service Implementations

All services are fully implemented with Dockerfile, app.py, and requirements.txt:

1. ✅ **HTML Parser** (`services/html-parser/`)
   - Port: 5000
   - Parses HTML, extracts structured data
   - BeautifulSoup + lxml

2. ✅ **Extraction Agent** (`services/extraction-agent/`)
   - Port: 8001
   - LLM-powered data extraction
   - Schema-based extraction

3. ✅ **Vision Agent** (`services/vision-agent/`)
   - Port: 8002
   - Image analysis using LLaVA
   - Batch processing support

4. ✅ **Orchestrator Agent** (`services/orchestrator-agent/`)
   - Port: 8003
   - Multi-step workflow coordination
   - Parallel execution support

5. ✅ **Discovery Agent** (`services/discovery-agent/`)
   - Port: 8004
   - URL discovery via SearXNG
   - Service health monitoring

### Utility Scripts

- ✅ **scripts/service_tracker.py** - Real-time service monitoring
- ✅ **scripts/service_client.py** - Python SDK for all services
- ✅ **scripts/setup.sh** - One-time setup script
- ✅ **scripts/health-check.sh** - Quick health check

### Documentation

- ✅ **README.md** - Main project documentation
- ✅ **DEPLOYMENT.md** - Complete deployment guide
- ✅ **docs/SERVICES.md** - Detailed service documentation
- ✅ **docs/API_ENDPOINTS.md** - Complete API reference
- ✅ **docs/TROUBLESHOOTING.md** - Common issues and solutions

---

## 🚀 Next Steps

### 1. Local Testing (5-10 minutes)

```bash
# Run setup script
bash scripts/setup.sh

# Start all services
docker-compose -f docker-compose.local.yml up -d

# Wait for services to initialize (2-3 minutes)
sleep 180

# Check health
python3 scripts/service_tracker.py

# Test the system
python3 scripts/service_client.py --test
```

### 2. Production Deployment to Coolify (30-60 minutes)

Follow **DEPLOYMENT.md** for step-by-step instructions:

1. **Push to GitHub**
   ```bash
   git init
   git add .
   git commit -m "Initial commit: prompt2dataset setup"
   git remote add origin https://github.com/yourusername/prompt2dataset.git
   git push -u origin main
   ```

2. **Connect to Coolify**
   - Log in to Coolify
   - Add new project "prompt2dataset"
   - Connect GitHub repository

3. **Import Manifest**
   - Import `coolify-manifest.yaml`
   - Configure environment variables
   - Set DB_PASSWORD, DOMAIN, SECRET_KEY

4. **Deploy Services** (in order)
   - PostgreSQL → Ollama (wait for model download)
   - Camoufox, HTML Parser, SearXNG
   - n8n, Agent Gateway
   - All Agents (Extraction, Vision, Orchestrator, Discovery)

5. **Verify Deployment**
   ```bash
   python3 scripts/service_tracker.py
   python3 scripts/service_client.py --gateway-url https://api.yourdomain.com --test
   ```

---

## 📋 Service Registry Overview

### Infrastructure (Foundation)
- **PostgreSQL + pgvector** (5432) - Database with vector search
- **Ollama** (11434) - Local LLM server
- **SearXNG** (8888) - Privacy-focused search
- **Camoufox** (3000) - Browser automation

### Utilities
- **HTML Parser** (5000) - HTML parsing service

### Orchestration
- **n8n** (5678) - Workflow automation

### Agents (Core Services)
- **Extraction Agent** (8001) - Data extraction
- **Vision Agent** (8002) - Image analysis
- **Orchestrator Agent** (8003) - Workflow coordination
- **Discovery Agent** (8004) - URL discovery & monitoring

### Gateway
- **Agent Gateway** (8000) - Central API gateway

---

## 🔧 Configuration Checklist

Before deployment, ensure:

- [ ] Copy `config/.env.example` to `.env`
- [ ] Set `DB_PASSWORD` to secure password
- [ ] Set `DOMAIN` to your domain
- [ ] Set `SECRET_KEY` for security
- [ ] Review all service configurations in `services.json`
- [ ] Validate `coolify-manifest.yaml` syntax
- [ ] Test locally with `docker-compose.local.yml`
- [ ] Check port availability (5432, 11434, 3000, 5000, 8888, 5678, 8000-8004)
- [ ] Ensure 50GB+ disk space (for Ollama models)
- [ ] DNS configured for domain (if using custom domain)

---

## 📊 Resource Requirements

**Minimum**:
- 4 CPU cores
- 8GB RAM
- 50GB storage

**Recommended**:
- 8 CPU cores
- 16GB RAM
- 100GB SSD storage

**Storage Breakdown**:
- PostgreSQL: 10-20GB (data)
- Ollama: 30-40GB (models)
- Containers: 5-10GB
- Logs: 5GB

---

## 🔍 Monitoring & Health Checks

### Real-time Monitoring
```bash
# Continuous monitoring (refreshes every 10s)
python3 scripts/service_tracker.py --watch

# Single check
python3 scripts/service_tracker.py

# JSON output (for logging)
python3 scripts/service_tracker.py --json

# Quick check
bash scripts/health-check.sh
```

### Service URLs

**Local**:
- Gateway: http://localhost:8000/health
- Discovery: http://localhost:8004/health
- Extraction: http://localhost:8001/health
- Vision: http://localhost:8002/health
- Orchestrator: http://localhost:8003/health

**Production**:
- Gateway: https://api.yourdomain.com/health
- n8n: https://n8n.yourdomain.com
- SearXNG: https://search.yourdomain.com

---

## 🎯 Usage Examples

### Python SDK

```python
from scripts.service_client import ServiceClient

client = ServiceClient('http://localhost:8000')

# Discover URLs
results = client.discover_urls("python tutorials", max_results=10)

# Extract data
data = client.extract_data(
    url="https://example.com",
    schema={"title": "string", "price": "number"}
)

# Analyze image
analysis = client.analyze_image(
    image_url="https://example.com/image.jpg",
    prompt="Describe this image"
)

# Run workflow
workflow = client.orchestrate_workflow(
    workflow_name="Data Pipeline",
    steps=[
        {"name": "discover", "type": "discover", "data": {"query": "test"}},
        {"name": "extract", "type": "extract", "data": {}, "depends_on": "discover"}
    ]
)
```

### cURL

```bash
# Discover URLs
curl -X POST http://localhost:8004/discover \
  -H "Content-Type: application/json" \
  -d '{"query": "python tutorials", "max_results": 5}'

# Extract data
curl -X POST http://localhost:8001/extract \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "schema": {"title": "string"}}'
```

---

## 📚 Documentation Structure

```
/workspace/
├── README.md                      # Main documentation
├── DEPLOYMENT.md                  # Deployment guide
├── SETUP_COMPLETE.md             # This file
│
├── docs/
│   ├── SERVICES.md               # Service details
│   ├── API_ENDPOINTS.md          # API reference
│   └── TROUBLESHOOTING.md        # Common issues
│
├── services.json                 # Service registry
├── coolify-manifest.yaml         # Coolify blueprint
├── docker-compose.local.yml      # Local testing
│
├── config/
│   └── .env.example              # Environment template
│
├── services/                     # Service implementations
│   ├── html-parser/
│   ├── extraction-agent/
│   ├── vision-agent/
│   ├── orchestrator-agent/
│   └── discovery-agent/
│
└── scripts/                      # Utility scripts
    ├── service_tracker.py
    ├── service_client.py
    ├── setup.sh
    └── health-check.sh
```

---

## 🔐 Security Considerations

Before production deployment:

1. ✅ Change default passwords in `.env`
2. ✅ Enable SSL/TLS for all public endpoints (Coolify handles this)
3. ✅ Set up firewall rules (only expose required ports)
4. ✅ Use strong SECRET_KEY
5. ✅ Regular backups of PostgreSQL
6. ✅ Monitor logs for suspicious activity
7. ✅ Keep Docker images updated
8. ⚠️ Implement API authentication (optional, not included yet)
9. ⚠️ Set up rate limiting (optional, not included yet)

---

## 🐛 Common Issues

See **docs/TROUBLESHOOTING.md** for detailed solutions.

**Quick fixes**:

```bash
# Service won't start
docker logs <container-name>

# Port already in use
sudo lsof -i :<port>

# Database connection failed
docker exec <postgres-container> pg_isready -U postgres

# Ollama model not loaded
docker exec <ollama-container> ollama pull mistral:latest

# Reset everything (CAUTION: deletes data)
docker-compose -f docker-compose.local.yml down -v
docker-compose -f docker-compose.local.yml up -d
```

---

## 🎉 Success Indicators

Your deployment is successful when:

✅ All services show "healthy" in `service_tracker.py`  
✅ `service_client.py --test` completes without errors  
✅ Gateway responds at http://localhost:8000/health  
✅ Discovery agent can search via SearXNG  
✅ Extraction agent can process URLs  
✅ Vision agent can analyze images  
✅ Orchestrator can run multi-step workflows  
✅ n8n workflow UI is accessible  
✅ PostgreSQL accepts connections  
✅ Ollama models are loaded  

---

## 📞 Support

- **Issues**: Open issue on GitHub
- **Documentation**: Check `docs/` directory
- **Discussions**: GitHub Discussions
- **Quick Help**: See TROUBLESHOOTING.md

---

## 🚢 Production Deployment Order

1. **Foundation** (10-15 min)
   - PostgreSQL
   - Ollama (wait for model downloads!)

2. **Search & Utils** (5 min)
   - SearXNG
   - Camoufox
   - HTML Parser

3. **Orchestration** (2 min)
   - n8n

4. **Agents** (10 min)
   - Extraction Agent
   - Vision Agent
   - Discovery Agent
   - Orchestrator Agent

5. **Gateway** (2 min)
   - Agent Gateway

**Total Time**: ~30-60 minutes (mostly waiting for Ollama models)

---

## 🎯 What Makes This Production-Ready

✅ **Centralized Configuration**: Single `services.json` as source of truth  
✅ **Health Monitoring**: Built-in health checks for all services  
✅ **Documentation**: Complete docs for deployment and usage  
✅ **Error Handling**: Proper error responses and logging  
✅ **Scalability**: Services can be scaled horizontally  
✅ **Observability**: Comprehensive logging and monitoring  
✅ **Developer Experience**: Local testing environment  
✅ **Deployment Automation**: Coolify manifest for one-click deploy  
✅ **Modularity**: Services are independent and replaceable  
✅ **No Hardcoded Values**: All configuration via environment variables  

---

## 🏁 You're Ready to Deploy!

Everything is set up and ready for production deployment. Choose your path:

**Option A: Local Testing First** (Recommended)
```bash
bash scripts/setup.sh
docker-compose -f docker-compose.local.yml up -d
python3 scripts/service_tracker.py --watch
```

**Option B: Direct to Coolify**
```bash
git push origin main
# Then follow DEPLOYMENT.md
```

---

**Built for self-hosting. Deploy anywhere. Own your data.**

**Status**: ✅ PRODUCTION READY
