# 🚀 Coolify Native Setup - Zero Configuration

**This repo is designed to work perfectly with Coolify out of the box.**

---

## ✨ What Coolify Auto-Configures

When you deploy in Coolify, these are **automatically set**:

### 🌐 Service Domains
```bash
SERVICE_FQDN_AGENT_GATEWAY  # Your main API domain
SERVICE_FQDN_N8N            # Your n8n workflow domain
COOLIFY_URL                 # Coolify management URL
COOLIFY_BRANCH              # Current branch
COOLIFY_CONTAINER_*         # Container IDs
```

### 🔒 Network & SSL
- Automatic SSL certificates (Let's Encrypt)
- Reverse proxy configuration
- Internal Docker networking
- Health check monitoring

### 💾 Volume Mounts
Coolify automatically mounts volumes to your server's `/data` directory

---

## 🎯 Your Server-Specific Setup

### Your Server Structure (Already Perfect!)
```bash
/data/
├── mongodb/              ✅ Ready
├── ollama/              ✅ Ready
├── n8n/                 ✅ Ready
├── agent-gateway/       ✅ Ready
├── camoufox/            ✅ Ready
├── extraction-agent/    ✅ Ready
├── vision-agent/        ✅ Ready
└── ... (all other dirs) ✅ Ready
```

### Docker Compose Will Auto-Use These!

The `docker-compose.yml` uses:
```yaml
volumes:
  - ${DATA_PATH:-/data}/mongodb:/data/db
  - ${DATA_PATH:-/data}/ollama:/root/.ollama
  - ${DATA_PATH:-/data}/n8n:/home/node/.n8n
  # etc...
```

Since your `/data` already exists, **it just works!**

---

## 📝 Coolify Setup - Literally 3 Steps

### Step 1: Add Repository (2 min)

In Coolify:
1. **New Resource** → **Public Repository**
2. Repository: `https://github.com/YOUR-USERNAME/ai-scraper`
3. Branch: `main` or `mvp`
4. Build Pack: **Docker Compose**
5. Compose File: `docker-compose.yml` (or `docker-compose.mvp.yml`)

### Step 2: Set ONE Variable (30 sec)

In **Environment** tab:
```
MONGO_PASSWORD=<run: openssl rand -base64 32>
```

**That's literally it!**

Optional:
```
HF_TOKEN=your_token  # Only if using Hugging Face private models
```

### Step 3: Deploy (10 min)

Click **Deploy** and wait for:
- ✅ Images build
- ✅ Services start
- ✅ Models download
- ✅ Health checks pass

---

## 🎨 How Domains Work

### Coolify Creates These Automatically:

**Main API** (agent-gateway):
```
https://random-name.coolify.app
or
https://api.yourdomain.com  (if you set custom domain)
```

**n8n Workflows**:
```
https://n8n-random-name.coolify.app
or
https://n8n.yourdomain.com  (if you set custom domain)
```

### Docker Compose Automatically Uses Them:

```yaml
environment:
  N8N_HOST: ${SERVICE_FQDN_N8N:-localhost}
  WEBHOOK_URL: ${SERVICE_FQDN_N8N:-http://localhost:5678}
```

**No manual configuration needed!**

---

## 🔄 How Internal Services Connect

### Coolify's Docker Network

All services communicate via Docker network:

```
agent-gateway:8000    # Gateway
agent-discovery:8001  # Discovery
agent-camoufox:8002   # Browser
agent-vision:8003     # Vision
agent-extraction:8004 # Extraction
ollama:11434          # AI Models
mongodb:27017         # Database
n8n:5678              # Workflows
```

### Example: n8n calls Gateway

In n8n HTTP Request node:
```
URL: http://agent-gateway:8000/scrape
```

**No IP addresses, no external domains needed!**

---

## 📊 Resource Configuration

### For Your Server (32GB RAM, 1.9TB Disk)

**Already optimized in docker-compose.yml:**

```yaml
# Ollama - AI Models
deploy:
  resources:
    limits:
      memory: 16G  # Perfect for multiple models
    reservations:
      memory: 8G

# Camoufox - Browser
deploy:
  resources:
    limits:
      memory: 4G  # Can run multiple instances
    
# Other services - 512M each (plenty)
```

### Default Environment Variables (Auto-Set)

```bash
# Performance (optimized for 32GB)
MAX_CONCURRENT_REQUESTS=20
OLLAMA_NUM_PARALLEL=4
OLLAMA_MAX_LOADED_MODELS=3

# These are in docker-compose.yml
# No need to set in Coolify!
```

---

## 🎯 Custom Domains (Optional)

### If You Want Custom Domains:

1. **In Coolify** → Your Resource → **Domains**

2. **For Gateway**:
   - Domain: `api.yourdomain.com`
   - Port: `8000`
   - Enable SSL ✅

3. **For n8n**:
   - Domain: `n8n.yourdomain.com`
   - Port: `5678`
   - Enable SSL ✅

4. **Coolify Automatically**:
   - Sets `SERVICE_FQDN_*` variables
   - Configures reverse proxy
   - Obtains SSL certificates
   - Updates DNS (if using Coolify DNS)

**Your app uses these automatically via environment variables!**

---

## ✅ Verify Setup

### 1. Check Coolify Auto-Variables

In Coolify → Resource → **Environment** → **Preview**

You should see:
```bash
SERVICE_FQDN_AGENT_GATEWAY=https://your-app.coolify.app
SERVICE_FQDN_N8N=https://n8n-your-app.coolify.app
# ... other auto-variables
```

### 2. Test Services

```bash
# Main API
curl https://your-app.coolify.app/health

# n8n
curl https://n8n-your-app.coolify.app/healthz
```

### 3. Check Data Mounts

SSH to your server:
```bash
# Should see files appearing after deployment
ls -la /data/mongodb
ls -la /data/ollama
ls -la /data/n8n
```

---

## 🎨 Working with Zie619's Workflows

### Import Workflow

1. Clone locally:
   ```bash
   git clone https://github.com/Zie619/n8n-workflows
   ```

2. Access your n8n: `https://n8n-your-app.coolify.app`

3. **Import** → Select workflow JSON

4. **Update connections** (only these two things):

   **HTTP Request nodes**:
   ```
   URL: http://agent-gateway:8000
   ```

   **MongoDB nodes**:
   ```
   Host: mongodb
   Port: 27017
   Database: webscraper
   Username: admin
   Password: <your-MONGO_PASSWORD>
   ```

**Everything else auto-works!**

---

## 🔧 Advanced: Override Coolify Defaults

### If You Need Custom Configuration

Add to Coolify Environment:

```bash
# Custom ports (if defaults conflict)
GATEWAY_PORT=8100
N8N_PORT=5679

# Custom timezone
TIMEZONE=Europe/London

# Performance tuning
MAX_CONCURRENT_REQUESTS=50  # Your server can handle more

# Custom model selection
VISION_MODEL=qwen3-vl  # Use different model
```

**But 99% of users won't need any of this!**

---

## 📚 What You DON'T Need to Set

### These Are All Automatic:

❌ No need to set:
- `SERVICE_FQDN_*` (Coolify provides)
- `COOLIFY_*` (Coolify provides)
- `*_URL` for internal services (docker-compose sets)
- `DATA_PATH` (defaults to `/data`, your structure)
- Port mappings (docker-compose handles)
- Network configuration (Coolify creates)
- SSL certificates (Coolify manages)
- Volume mounts (docker-compose uses /data)

✅ Only need to set:
- `MONGO_PASSWORD` (security)
- `HF_TOKEN` (optional, for private models)

---

## 🚀 Deploy Checklist

Before hitting Deploy:

- [ ] Repository added to Coolify
- [ ] Branch selected (`main` or `mvp`)
- [ ] Compose file: `docker-compose.yml` (or `.mvp.yml`)
- [ ] Environment: `MONGO_PASSWORD` set
- [ ] (Optional) Custom domains configured
- [ ] `/data` exists on server (you already have this!)

**That's all! Deploy away!**

---

## 💡 Pro Tips

1. **Use Coolify's Logs**: Real-time logs for debugging
2. **Let Coolify Handle SSL**: Don't configure manually
3. **Use Service Names**: Never use IPs in configs
4. **Trust the Defaults**: Everything is pre-optimized
5. **Your /data is Perfect**: Structure already ideal

---

## 🎊 Why This Works So Well

### Smart Defaults
```yaml
# Example from docker-compose.yml
environment:
  N8N_HOST: ${SERVICE_FQDN_N8N:-${N8N_HOST:-localhost}}
```

Reads as:
1. Try Coolify's auto-variable (`SERVICE_FQDN_N8N`)
2. Fall back to manual env var (`N8N_HOST`)
3. Fall back to localhost

**Coolify always wins, manual optional, localhost for local dev.**

### Your Server Integration
```yaml
volumes:
  - ${DATA_PATH:-/data}/mongodb:/data/db
```

Reads as:
1. Use `DATA_PATH` env var if set
2. Default to `/data` (your structure!)

**Works with your existing setup automatically!**

---

## 🎯 The Magic

**You set**: 1 variable (`MONGO_PASSWORD`)

**Coolify provides**: 
- Domains
- SSL
- Networking
- Health checks
- Logs
- Metrics

**Docker Compose provides**:
- Service configuration
- Resource limits
- Volume mounts
- Inter-service networking

**Your server provides**:
- `/data` structure (already done!)
- Docker (already running!)
- Resources (32GB perfect!)

**Result**: Zero-configuration deployment! 🎉

---

## 📞 If Something Seems Wrong

### Check Coolify Environment Preview

Coolify → Resource → Environment → **Show Preview**

Should show all `SERVICE_FQDN_*` variables populated.

If not:
1. Ensure domains are configured
2. Redeploy to trigger auto-configuration
3. Check Coolify logs

### Check Docker Network

On your server:
```bash
docker network ls  # Should see webscraper-network
docker network inspect webscraper-network  # All services listed
```

### Check Volume Mounts

```bash
docker inspect webscraper-mongodb | grep Mounts -A 20
# Should show /data/mongodb mounted
```

---

**Your setup is perfect for Coolify! Just add the repo, set MONGO_PASSWORD, and deploy! 🚀**
