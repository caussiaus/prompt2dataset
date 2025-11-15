# Coolify Deployment Guide

Complete guide for deploying the AI Web Scraper Platform on Coolify.

---

## 📋 Prerequisites

- Coolify v4+ installed and running
- Server with at least:
  - **Minimum**: 16GB RAM, 4 CPU cores, 100GB disk
  - **Recommended**: 32GB RAM, 8 CPU cores, 200GB disk
  - **With GPU**: 64GB RAM, 8 CPU cores, 500GB disk, NVIDIA GPU
- Docker and Docker Compose
- Domain name (optional but recommended)

---

## 🚀 Step-by-Step Deployment

### 1. Prepare Your Repository

```bash
# If deploying from GitHub/GitLab
# Ensure your repository is accessible to Coolify

# If deploying locally
git clone <your-repo> /path/to/coolify/projects/ai-scraper
cd /path/to/coolify/projects/ai-scraper
```

### 2. Configure Environment Variables

```bash
# Copy example environment file
cp .env.example .env

# Edit with your settings
nano .env
```

**Critical Variables**:
```env
# Security
MONGO_PASSWORD=CHANGE_THIS_TO_SECURE_PASSWORD

# Paths
DATA_PATH=/data

# Model Configuration  
VISION_MODEL=llava
EXTRACTION_MODEL=llama3.1
EMBEDDING_MODEL=bge-m3

# Discovery Settings
MAX_CONCURRENT_REQUESTS=10

# Ports (change if needed)
GATEWAY_PORT=8000
N8N_PORT=5678
```

### 3. Select AI Models

Edit `models.config` to select models based on your hardware:

**Small Setup** (16GB RAM, no GPU):
```
# models.config
llama3.1
llava
bge-m3
```

**Medium Setup** (32GB RAM, optional GPU):
```
llama3.1
gemma3
llava
qwen3-vl
codellama
bge-m3
```

**Full Setup** (64GB+ RAM, GPU recommended):
```
# Keep all models or customize as needed
```

### 4. Coolify Project Setup

#### A. Create New Project

1. Log into Coolify dashboard
2. **Projects** → **New Project**
3. Name: `ai-web-scraper`
4. Description: `AI-powered web scraping platform`

#### B. Add Docker Compose Resource

1. In your project, click **Add New Resource**
2. Select **Docker Compose**
3. Choose **Git Repository** or **Compose File**

**If using Git Repository**:
- Repository URL: `https://github.com/your-username/ai-scraper`
- Branch: `main`
- Compose File Path: `docker-compose.yml`

**If using Compose File**:
- Paste contents of `docker-compose.yml`

#### C. Configure Environment Variables

In Coolify's environment section, add:

```
MONGO_USERNAME=admin
MONGO_PASSWORD=your_secure_password_here
MONGO_PORT=27017
DB_NAME=webscraper

OLLAMA_PORT=11434
VISION_MODEL=llava
EXTRACTION_MODEL=llama3.1
EMBEDDING_MODEL=bge-m3

GATEWAY_PORT=8000
N8N_PORT=5678
N8N_HOST=your-domain.com
N8N_PROTOCOL=https

DATA_PATH=/data
MAX_CONCURRENT_REQUESTS=10
TIMEZONE=America/New_York
```

#### D. Configure Domains (Optional)

For each service, set custom domains:

- **Gateway**: `api.your-domain.com`
- **n8n**: `workflows.your-domain.com`

In Coolify:
1. Resource → Domains
2. Add domain for each service
3. Enable SSL (Let's Encrypt)

### 5. Deploy

1. Click **Deploy** in Coolify
2. Monitor deployment logs
3. First deployment takes **10-30 minutes** (downloading AI models)

**What happens during first deploy**:
```
1. ✓ Building Docker images (5 min)
2. ✓ Starting MongoDB (1 min)
3. ✓ Starting Ollama (1 min)
4. ⏳ Downloading AI models (10-30 min)
5. ✓ Starting agents (2 min)
6. ✓ Starting n8n (1 min)
7. ✓ Health checks pass (1 min)
```

### 6. Verify Deployment

Check service health:

```bash
# Gateway
curl http://your-domain:8000/health

# Or in browser
http://your-domain:8000/docs
```

Expected response:
```json
{
  "status": "ok",
  "agent": "gateway",
  "timestamp": "2025-01-15T...",
  "services": {
    "discovery": "ok",
    "camoufox": "ok",
    "vision": "ok",
    "extraction": "ok"
  }
}
```

### 7. Access Services

- **API Documentation**: `http://your-domain:8000/docs`
- **n8n Workflows**: `http://your-domain:5678`
- **MongoDB**: `mongodb://admin:password@your-domain:27017`

---

## 🎯 Post-Deployment Configuration

### n8n First-Time Setup

1. Access `http://your-domain:5678`
2. Create owner account
3. Import workflows from `n8n-workflows/examples/`
4. Configure connections:
   - Gateway API: `http://agent-gateway:8000`
   - MongoDB: `mongodb://admin:password@mongodb:27017`

### Test First Scrape

```bash
curl -X POST http://your-domain:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "strategy": "full",
    "use_vision": false
  }'
```

---

## 📊 Resource Management

### Storage Locations

All data is stored in `DATA_PATH` (default: `/data`):

```
/data/
├── mongodb/       # Database files
├── ollama/        # AI models (largest)
├── gateway/       # Job data
├── discovery/     # Crawl data
├── camoufox/      # Screenshots
├── vision/        # OCR results
├── extraction/    # Extracted data
└── n8n/          # Workflow data
```

### Disk Space Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| Ollama Models | 20GB | 100GB |
| MongoDB | 5GB | 50GB |
| Screenshots | 5GB | 20GB |
| System | 10GB | 30GB |
| **Total** | **40GB** | **200GB** |

### Memory Allocation

Configure in Coolify → Resource → Advanced:

```yaml
services:
  ollama:
    deploy:
      resources:
        limits:
          memory: 16G
        reservations:
          memory: 8G
  
  agent-camoufox:
    deploy:
      resources:
        limits:
          memory: 4G
        reservations:
          memory: 2G
```

---

## 🔧 GPU Configuration

If you have an NVIDIA GPU:

### 1. Install NVIDIA Container Toolkit

```bash
# On your server
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

### 2. Verify GPU Access

```bash
docker run --rm --gpus all nvidia/cuda:11.0-base nvidia-smi
```

### 3. Enable in Docker Compose

Already configured in `docker-compose.yml`:
```yaml
ollama:
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: all
            capabilities: [gpu]
```

---

## 🔒 Security Hardening

### 1. Change Default Passwords

```env
# .env
MONGO_PASSWORD=use_strong_random_password_here
```

### 2. Enable HTTPS

In Coolify:
1. Domains → Enable SSL
2. Auto-renew Let's Encrypt

### 3. Restrict Network Access

In Coolify → Resource → Networks:
- Only expose ports 8000 and 5678 publicly
- Keep other services on internal network

### 4. Add Authentication

Add API key middleware to gateway:

```python
# agent_gateway.py
from fastapi import Security, HTTPException
from fastapi.security import APIKeyHeader

API_KEY = os.getenv("API_KEY", "change-this-key")
api_key_header = APIKeyHeader(name="X-API-Key")

def verify_api_key(api_key: str = Security(api_key_header)):
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return api_key

# Apply to routes
@app.post("/scrape", dependencies=[Depends(verify_api_key)])
```

### 5. Rate Limiting

Use Coolify's built-in rate limiting or add to gateway:

```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.post("/scrape")
@limiter.limit("10/minute")
async def create_scrape_job(...):
    ...
```

---

## 📈 Scaling Strategies

### Horizontal Scaling

In Coolify, increase replicas:

```yaml
# Coolify UI: Resource → Replicas
agent-camoufox: 3 replicas
agent-extraction: 2 replicas
agent-discovery: 2 replicas
```

### Load Balancing

Coolify automatically load balances between replicas.

### Database Scaling

For high-volume scraping:

1. Enable MongoDB replication
2. Add read replicas
3. Use connection pooling

---

## 🐛 Troubleshooting

### Deployment Fails

```bash
# Check Coolify logs
docker logs coolify

# Check specific service
docker logs webscraper-gateway
```

### Models Not Downloading

```bash
# Check Ollama connectivity
docker exec webscraper-ollama curl http://localhost:11434/api/tags

# Manually trigger download
docker exec webscraper-model-manager python model_manager.py
```

### Out of Memory

1. Reduce models in `models.config`
2. Increase swap space
3. Add more RAM
4. Use smaller model variants

### Browser Crashes

```bash
# Increase shared memory for Camoufox
docker-compose.yml:
  agent-camoufox:
    shm_size: 4gb  # Increase from 2gb
```

### Network Issues

```bash
# Check service connectivity
docker exec webscraper-gateway curl http://agent-camoufox:8002/health
```

---

## 🔄 Updates and Maintenance

### Updating the Platform

```bash
# In Coolify
1. Go to Resource
2. Click "Redeploy"
3. Select "Force rebuild"
```

### Backup Strategy

```bash
# Backup MongoDB
docker exec webscraper-mongodb mongodump --out=/backup

# Backup n8n workflows
docker exec webscraper-n8n tar -czf /backup/n8n-backup.tar.gz /home/node/.n8n

# Backup to host
docker cp webscraper-mongodb:/backup ./backups/
```

### Restore from Backup

```bash
# Restore MongoDB
docker exec webscraper-mongodb mongorestore /backup

# Restore n8n
docker exec webscraper-n8n tar -xzf /backup/n8n-backup.tar.gz -C /
```

---

## 📞 Support

### Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f agent-gateway
```

### Health Checks

```bash
# Check all services
curl http://your-domain:8000/health

# Check database
docker exec webscraper-mongodb mongosh --eval "db.adminCommand('ping')"
```

### Performance Monitoring

```bash
# Resource usage
docker stats

# Disk space
df -h /data
```

---

## ✅ Deployment Checklist

- [ ] Server meets minimum requirements
- [ ] .env file configured with secure passwords
- [ ] models.config edited for your hardware
- [ ] Domain names configured (optional)
- [ ] SSL certificates enabled
- [ ] Coolify project created
- [ ] Environment variables set in Coolify
- [ ] First deployment completed successfully
- [ ] All health checks passing
- [ ] n8n accessible and configured
- [ ] Test scrape job completed
- [ ] Backups configured
- [ ] Monitoring set up

---

**Your AI Web Scraper Platform is now live! 🎉**
