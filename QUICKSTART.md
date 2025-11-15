# ⚡ Quick Start Guide

Get from `git clone` to running system in **5 minutes**.

## 🚀 Fastest Path to Running

```bash
# 1. Clone the repo
git clone <your-repo-url> ai-scraper
cd ai-scraper

# 2. Run quick start
bash scripts/quick-start.sh

# 3. Wait 5-10 minutes for models to download

# 4. Access services
open http://localhost:8000/docs
```

**That's it!** You now have a running AI web scraper.

---

## 📋 Three Setup Options

### Option 1: Quick Start (Recommended for Testing)
**Time**: ~10 minutes | **Disk**: ~15GB | **RAM**: 8GB

```bash
bash setup.sh
# Select: 1) Quick Start
```

**Includes**:
- Minimal AI models (llama3.1, llava, bge-m3)
- All core services
- Perfect for testing and development

### Option 2: Full Setup
**Time**: ~30 minutes | **Disk**: ~100GB | **RAM**: 16GB+

```bash
bash setup.sh
# Select: 2) Full Setup
```

**Includes**:
- All AI models from models.config
- Production-ready configuration
- Best performance

### Option 3: Using Make Commands
**Fastest for developers**

```bash
make quick    # Quick start
make full     # Full setup
make dev      # Development mode
```

---

## ✅ Verify Installation

```bash
# Check all services
make status

# Run health checks
make health

# Test a scrape
make test-scrape
```

---

## 🎯 First Scrape

### Via API:
```bash
curl -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "strategy": "full",
    "use_vision": false
  }'
```

### Via n8n:
1. Go to http://localhost:5678
2. Import workflow from `n8n-workflows/examples/simple-url-scraper.json`
3. Click "Execute Workflow"

---

## 🛠️ Common Commands

```bash
make help          # Show all commands
make start         # Start services
make stop          # Stop services
make logs          # View logs
make status        # Service status
make health        # Health checks
make test          # Run tests
make models-list   # List AI models
make clean         # Clean up
```

---

## 📊 Service URLs

| Service | URL |
|---------|-----|
| **API Gateway** | http://localhost:8000 |
| **API Documentation** | http://localhost:8000/docs |
| **n8n Workflows** | http://localhost:5678 |
| **Ollama** | http://localhost:11434 |

---

## 🐛 Troubleshooting

### Services won't start?
```bash
# Check requirements
bash scripts/preflight-check.sh

# Check logs
make logs
```

### Models not downloading?
```bash
# Check Ollama
docker logs webscraper-ollama

# Manually trigger download
make models-download
```

### Out of memory?
```bash
# Use minimal models
echo "llama3.1" > models.config
echo "llava" >> models.config
make restart
```

### Port conflicts?
```bash
# Edit .env to change ports
nano .env

# Restart
make restart
```

---

## 🎓 Next Steps

1. **Try Examples**
   - Import n8n workflows from `n8n-workflows/examples/`
   - Read `n8n-workflows/README.md`

2. **Customize Models**
   - Edit `models.config`
   - Run `make models-download`

3. **Deploy to Production**
   - Follow `docs/COOLIFY_DEPLOYMENT.md`
   - Or use your own infrastructure

4. **Create Workflows**
   - Build custom scraping logic in n8n
   - No code needed!

---

## 📚 Full Documentation

- **README.md** - Full platform overview
- **docs/COOLIFY_DEPLOYMENT.md** - Production deployment
- **n8n-workflows/README.md** - Workflow examples
- **API Docs** - http://localhost:8000/docs

---

## 💡 Pro Tips

1. **Start Small**: Use quick start, then upgrade to full
2. **Monitor Resources**: Use `docker stats` to watch memory/CPU
3. **Test First**: Try example.com before real targets
4. **Use Make**: It's faster than remembering docker commands
5. **Check Logs**: `make logs` shows everything

---

## 🆘 Get Help

- Check logs: `make logs`
- Run tests: `make test`
- Health check: `make health`
- GitHub Issues: [link]
- Documentation: `make docs`

---

**You're ready to scrape! 🎉**
