# 🚀 Coolify Quick Start - Your Server

**From zero to scraping in 10 minutes on your Arch server.**

---

## Your Server Specs ✅

```
RAM: 32GB        ✅ Perfect for full model set
Disk: 1.9TB      ✅ Plenty of space  
Data: /data/     ✅ Already structured
Docker: Running  ✅ Ready to go
```

---

## 🎯 5-Step Deploy

### Step 1: Generate Password (30 seconds)

```bash
# On your server
openssl rand -base64 32

# Copy the output, you'll need it
```

### Step 2: Add to Coolify (2 minutes)

1. **Coolify Dashboard** → **New Project** → **Public Repository**
2. **Repository**: `https://github.com/YOUR-USERNAME/ai-scraper`
3. **Branch**: Choose one:
   - `main` - Full production setup
   - `mvp` - Minimal test setup (recommended first time)
4. **Build Pack**: Docker Compose
5. **Compose File**: 
   - `docker-compose.yml` (if main branch)
   - `docker-compose.mvp.yml` (if mvp branch)

### Step 3: Set Environment (1 minute)

In Coolify **Environment** tab, add:

```
MONGO_PASSWORD=<paste-your-generated-password>
```

**Optional** (only if using Hugging Face private models):
```
HF_TOKEN=<your-hf-token>
```

That's it! Everything else auto-configured.

### Step 4: Deploy (5-10 minutes)

1. Click **Deploy**
2. Monitor logs in Coolify
3. Wait for:
   - Containers build (5 min)
   - Models download (5-10 min)
   - Health checks pass

### Step 5: Access (30 seconds)

```bash
# Get your Coolify domain
# Should be: https://your-app.coolify.app

# Test API
curl https://your-app.coolify.app/health

# Access services
open https://your-app.coolify.app/docs    # API
open https://n8n.your-app.coolify.app     # n8n
```

---

## 🎨 Your Data Structure Integration

Your existing `/data` folders are automatically used:

```bash
/data/mongodb/          → MongoDB data
/data/ollama/           → AI models (~40GB)
/data/n8n/              → Workflows
/data/agent-gateway/    → Gateway logs
/data/extraction-agent/ → Scraped data
/data/vision-agent/     → OCR results
/data/camoufox/         → Browser data
```

**No changes needed** - docker-compose.yml already configured!

---

## 🧪 Quick Test

### 1. Health Check
```bash
curl https://your-app.coolify.app/health
```

Expected:
```json
{
  "status": "ok",
  "services": {
    "discovery": "ok",
    "camoufox": "ok",
    "vision": "ok",
    "extraction": "ok"
  }
}
```

### 2. Test Scrape
```bash
curl -X POST https://your-app.coolify.app/scrape \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","strategy":"full"}'
```

### 3. Check Models
```bash
# SSH to your server
cd /data/ollama/models
ls -lh  # Should see model files
```

---

## 🔄 Import Zie619's Workflows

### Quick Import

1. **On your local machine**:
   ```bash
   git clone https://github.com/Zie619/n8n-workflows
   ```

2. **Access your n8n**: `https://n8n.your-app.coolify.app`

3. **Import workflow**:
   - **Workflows** → **Import from File**
   - Select workflow JSON
   - Click **Import**

4. **Update connections**:
   - Find **HTTP Request** nodes
   - Change URL to: `http://agent-gateway:8000`
   - Save

5. **Execute**:
   - Click **Execute Workflow**
   - Check results

### MongoDB Connection (in n8n)

```
Host: mongodb
Port: 27017
Database: webscraper
Username: admin
Password: <your-MONGO_PASSWORD>
Auth Source: admin
```

---

## 📊 Monitoring Your Deployment

### In Coolify Dashboard

- **Logs Tab**: Real-time logs
- **Metrics Tab**: CPU/RAM usage
- **Health Tab**: Service status

### On Your Server

```bash
# Check data usage
du -sh /data/*

# Check running containers
docker ps

# View container logs
docker logs -f webscraper-gateway
docker logs -f webscraper-ollama

# Check resource usage
docker stats
```

---

## 🚀 Recommended Workflow Tests

From Zie619's repo, test these first:

1. **simple-web-scraper** - Basic scraping
2. **ai-content-extractor** - Structured extraction
3. **scheduled-monitor** - Periodic scraping
4. **data-pipeline** - Full ETL

---

## 🔧 Optimize for Your 32GB Server

### Use Full Model Set

Your server can handle all models. In `models.config`:

```bash
# Recommended for 32GB RAM
llama3.1          # General LLM
llava             # Vision
qwen3-vl          # Better vision
gemma3            # Fast LLM
deepseek-r1       # Advanced reasoning
codellama         # Code generation
bge-m3            # Embeddings
mistral-small3.1  # Alternative LLM
```

### Performance Tuning

Add to Coolify environment:

```env
MAX_CONCURRENT_REQUESTS=20      # Your server can handle it
OLLAMA_NUM_PARALLEL=4           # Parallel AI inference
OLLAMA_MAX_LOADED_MODELS=3      # Keep models in RAM
```

---

## 🐛 Troubleshooting

### Models Still Downloading?

```bash
# Check progress on your server
docker logs -f webscraper-ollama
docker logs -f webscraper-model-manager
```

### Can't Connect to Services?

```bash
# Check Coolify network
# All services should be on: webscraper-network
docker network inspect webscraper-network
```

### Out of Disk Space?

```bash
# Your server has 1.9TB, unlikely
# But if needed, check:
df -h /data

# Clean old containers if needed:
docker system prune -a
```

### n8n Workflows Failing?

**Common issues**:
1. Wrong URL - Use `http://agent-gateway:8000` (not localhost)
2. Wrong MongoDB host - Use `mongodb` (not localhost)
3. Missing password - Check MONGO_PASSWORD in env

---

## ✅ Success Checklist

- [ ] Coolify project created
- [ ] Environment variables set (MONGO_PASSWORD)
- [ ] Deployed successfully
- [ ] All health checks pass (curl /health)
- [ ] Can access API docs
- [ ] Can access n8n
- [ ] Models downloaded (check /data/ollama)
- [ ] Test scrape works
- [ ] Imported at least one Zie619 workflow
- [ ] Workflow executes successfully

---

## 🎯 Your Next Steps

1. ✅ Deploy (you're doing this now)
2. 🔄 Import Zie619's workflows
3. 🧪 Test with real websites
4. 🎨 Customize workflows for your needs
5. 📊 Monitor performance
6. 🚀 Scale if needed (add replicas)

---

## 💡 Pro Tips for Your Setup

1. **Use Full Models**: Your 32GB can handle it
2. **Monitor /data**: Keep eye on disk usage
3. **Check Logs**: Coolify makes it easy
4. **Start with MVP**: Test before going full
5. **Backup /data**: Especially MongoDB and n8n

---

## 🎊 You're Ready!

Your server is perfect for this platform. With 32GB RAM and 1.9TB disk, you can run everything at full capacity.

**Deploy now and start scraping!**

---

## 📞 Quick Reference

**Coolify Environment (Minimum)**:
```
MONGO_PASSWORD=<generated-password>
```

**Optional**:
```
HF_TOKEN=<huggingface-token>
```

**Access URLs**:
- API: `https://your-app.coolify.app`
- Docs: `https://your-app.coolify.app/docs`
- n8n: `https://n8n.your-app.coolify.app`

**Data Location**:
- All in `/data/` on your server
- Already created ✅
- Auto-mounted by Docker ✅

**You're all set! 🚀**
