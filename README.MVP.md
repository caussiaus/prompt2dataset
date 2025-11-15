# 🚀 MVP Quick Deploy Branch

**Minimal, fast, production-ready deployment for Coolify.**

This MVP branch is optimized for:
- ⚡ **Fast deployment** (~5 minutes)
- 🎯 **Minimal resources** (8GB RAM, 20GB disk)
- 🔄 **n8n workflow testing** with [Zie619's workflows](https://github.com/Zie619/n8n-workflows)
- 🧪 **Rapid prototyping** and iteration

---

## 📦 What's Included

### Core Services
- ✅ Agent Gateway (orchestration)
- ✅ Agent Discovery (URL crawling)
- ✅ Agent Camoufox (browser rendering)
- ✅ Agent Vision (OCR/image analysis)
- ✅ Agent Extraction (data extraction)
- ✅ Ollama (AI models)
- ✅ MongoDB (data storage)
- ✅ n8n (workflow automation)

### AI Models (Minimal Set)
- `llama3.1` (8B - general LLM)
- `llava` (7B - vision/OCR)
- `bge-m3` (embedding model)

**Total**: ~12GB models (downloads in 5-10 min)

---

## 🎯 One-Click Coolify Deploy

### Method 1: Direct from GitHub

1. **In Coolify Dashboard**:
   - New Resource → Docker Compose
   - Repository: `https://github.com/YOUR-USERNAME/ai-scraper`
   - Branch: `mvp`
   - Compose file: `docker-compose.mvp.yml`

2. **Set Environment Variables**:
   ```
   MONGO_PASSWORD=your_secure_password_here
   ```

3. **Deploy** → Wait 10 minutes → Done! 🎉

### Method 2: Git Clone + Deploy

```bash
# On your Coolify server
git clone -b mvp https://github.com/YOUR-USERNAME/ai-scraper
cd ai-scraper
docker-compose -f docker-compose.mvp.yml up -d
```

---

## 🔧 Quick Configuration

### Before Deployment

**1. Secure Your Installation**
```bash
# Generate secure password
openssl rand -base64 32

# Add to Coolify environment variables
MONGO_PASSWORD=<generated-password>
```

**2. (Optional) Customize Models**
Edit `models.mvp.config` if you want different models:
```bash
# Smaller/faster
gemma3        # 2B model (faster, less accurate)
llava         # Keep for vision

# Larger/better (requires 16GB+ RAM)
llama3.1:70b  # Larger model (slower, more accurate)
qwen3-vl      # Better vision model
```

---

## 🌐 Access Your Services

After deployment:

| Service | URL | Purpose |
|---------|-----|---------|
| **API Gateway** | `https://your-app.coolify.app` | Main API |
| **API Docs** | `https://your-app.coolify.app/docs` | Interactive API docs |
| **n8n** | `https://n8n.your-app.coolify.app` | Workflow builder |

---

## 🔄 Using with n8n Workflows

### Import Zie619's Workflows

1. **Clone workflow repo**:
   ```bash
   git clone https://github.com/Zie619/n8n-workflows
   ```

2. **Import to n8n**:
   - Go to your n8n instance
   - Workflows → Import from File
   - Select workflow JSON files

3. **Configure connections**:
   ```javascript
   // In HTTP Request nodes, set:
   Base URL: http://agent-gateway:8000
   
   // For MongoDB nodes:
   Host: mongodb
   Port: 27017
   Database: webscraper
   Username: admin
   Password: <your-mongo-password>
   ```

### Recommended Test Workflows

From Zie619's repo, start with:
1. **Web Scraper** - Basic page scraping
2. **AI Content Extractor** - Structured data extraction
3. **Scheduled Monitor** - Periodic scraping
4. **Data Pipeline** - Full ETL workflow

### Create Your Own Workflow

**Example: Simple Product Scraper**
```javascript
// 1. Webhook Trigger
// 2. HTTP Request to Gateway
{
  "url": "{{$json.product_url}}",
  "strategy": "extraction",
  "extract_schema": {
    "name": "string",
    "price": "number",
    "in_stock": "boolean"
  }
}
// 3. Store in MongoDB
// 4. Send notification
```

---

## 🧪 Testing Your Deployment

### 1. Health Check
```bash
curl https://your-app.coolify.app/health
```

Expected:
```json
{
  "status": "ok",
  "agent": "gateway",
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
  -d '{
    "url": "https://example.com",
    "strategy": "full",
    "use_vision": false
  }'
```

### 3. Check Models
```bash
curl https://your-app.coolify.app:11434/api/tags
```

---

## 📊 Resource Usage (MVP)

### Minimum Requirements
- **RAM**: 8GB
- **CPU**: 2 cores
- **Disk**: 25GB (20GB for models + 5GB for data)
- **Network**: 1Gbps recommended

### Typical Usage
- **Idle**: ~3GB RAM
- **Light scraping**: ~4-6GB RAM
- **Heavy scraping**: ~6-8GB RAM

### Scaling Up Later
When ready for production, upgrade to main branch:
```bash
# In Coolify, change branch to 'main'
# Redeploy with full model set
```

---

## 🔥 Quick Start Scenarios

### Scenario 1: Test with Example.com
```bash
# Via API
curl -X POST https://your-app.coolify.app/scrape \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","strategy":"full"}'

# Get results
curl https://your-app.coolify.app/jobs/{job_id}
```

### Scenario 2: Import Workflow and Run
```bash
# 1. Import workflow from Zie619's repo
# 2. Update URLs to your instance
# 3. Execute workflow in n8n
# 4. Check MongoDB for results
```

### Scenario 3: Build Custom Pipeline
```bash
# 1. Create new workflow in n8n
# 2. Add HTTP Request node → Gateway
# 3. Add data processing nodes
# 4. Store results in MongoDB or webhook
```

---

## 🐛 Troubleshooting

### Deployment Issues

**Models not downloading?**
```bash
# Check Ollama logs in Coolify
# Or manually trigger:
docker exec <ollama-container> ollama pull llama3.1
```

**Services not connecting?**
```bash
# Check network in Coolify
# Ensure all services are on same Docker network
```

**Out of memory?**
```bash
# Reduce models in models.mvp.config
# Keep only llama3.1 and llava
```

### n8n Workflow Issues

**Can't connect to Gateway?**
- Use `http://agent-gateway:8000` (internal Docker network)
- NOT `http://localhost:8000`

**MongoDB connection fails?**
- Host: `mongodb` (not localhost)
- Port: `27017`
- Check password matches .env

---

## 🚀 Upgrade Path

### From MVP to Production

1. **Switch to main branch** in Coolify
2. **Update models.config** with full model set
3. **Scale services**:
   - Camoufox: 3 replicas
   - Extraction: 2 replicas
4. **Add monitoring** (Prometheus/Grafana)
5. **Enable backups** (automated MongoDB dumps)
6. **Add authentication** (API keys, OAuth)

---

## 📚 Next Steps

1. ✅ **Deploy MVP** (you are here)
2. 🔄 **Import n8n workflows** from Zie619's repo
3. 🧪 **Test with real sites** (start with simple ones)
4. 🎨 **Customize workflows** for your use cases
5. 📈 **Monitor & optimize** resource usage
6. 🚀 **Upgrade to full** when ready for production

---

## 💡 Pro Tips

1. **Start Small**: Test with simple sites before complex ones
2. **Monitor Logs**: Use Coolify's log viewer to debug
3. **Iterate Fast**: MVP is for learning, break things!
4. **Share Workflows**: Contribute back to Zie619's repo
5. **Document Everything**: Keep notes on what works

---

## 🤝 Community Workflows

Check out these awesome n8n workflow collections:

- [Zie619/n8n-workflows](https://github.com/Zie619/n8n-workflows) - Web scraping workflows
- [n8n-io/n8n-workflow-template](https://github.com/n8n-io/n8n-workflow-template) - Official templates

---

## 📞 Need Help?

- **Coolify Docs**: https://coolify.io/docs
- **n8n Docs**: https://docs.n8n.io
- **This Repo**: GitHub Issues
- **Zie619's Workflows**: https://github.com/Zie619/n8n-workflows/issues

---

## 🎯 Success Criteria

You'll know it's working when:
- ✅ All health checks pass
- ✅ Test scrape completes successfully
- ✅ n8n can create and execute workflows
- ✅ Results appear in MongoDB
- ✅ You can import and run Zie619's workflows

---

**🎉 You're ready to scrape! Deploy now and start building!**
