# 🔧 Environment Variables Setup Guide

**Minimal configuration for your server setup.**

---

## 📋 Required Environment Variables (Set These!)

### In Coolify or `.env` file:

```bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# REQUIRED - Security
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MONGO_PASSWORD=your_secure_password_here

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# OPTIONAL - AI Model APIs (if using external models)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HF_TOKEN=your_huggingface_token_here
```

**That's it!** Everything else has smart defaults.

---

## 🎯 Quick Setup Commands

### Generate Secure Password
```bash
# On your server
openssl rand -base64 32
```

### Get Hugging Face Token (Optional)
1. Go to https://huggingface.co/settings/tokens
2. Create new token
3. Copy token value

---

## 📝 Full Environment Variables Reference

### For Coolify Dashboard

Copy this into Coolify's environment section:

```env
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECURITY (Required)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MONGO_USERNAME=admin
MONGO_PASSWORD=CHANGE_THIS_TO_SECURE_PASSWORD

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DATABASE (Uses your /data structure)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DB_NAME=webscraper
DATA_PATH=/data

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PORTS (Default - change if needed)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GATEWAY_PORT=8000
N8N_PORT=5678
OLLAMA_PORT=11434
MONGO_PORT=27017

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AI MODELS (Smart defaults, no changes needed)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VISION_MODEL=llava
OCR_MODEL=llava
EXTRACTION_MODEL=llama3.1
EMBEDDING_MODEL=bge-m3

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# EXTERNAL AI APIs (Optional - only if using)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HF_TOKEN=your_huggingface_token
# OPENAI_API_KEY=your_openai_key
# ANTHROPIC_API_KEY=your_anthropic_key

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PERFORMANCE TUNING (Optimized for your 32GB RAM)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MAX_CONCURRENT_REQUESTS=20
OLLAMA_NUM_PARALLEL=4
OLLAMA_MAX_LOADED_MODELS=3

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# N8N CONFIGURATION (Coolify auto-configures domains)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
N8N_HOST=${COOLIFY_FQDN}
N8N_PROTOCOL=https
WEBHOOK_URL=https://${COOLIFY_FQDN}
TIMEZONE=America/New_York

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# NETWORK (Internal Docker - no changes needed)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MONGODB_URI=mongodb://admin:${MONGO_PASSWORD}@mongodb:27017
OLLAMA_URL=http://ollama:11434
DISCOVERY_URL=http://agent-discovery:8001
CAMOUFOX_URL=http://agent-camoufox:8002
VISION_URL=http://agent-vision:8003
EXTRACTION_URL=http://agent-extraction:8004
```

---

## 🚀 Coolify-Specific Setup

### In Coolify Dashboard:

1. **Go to your resource** → **Environment** tab

2. **Set only these 2 variables**:
   ```
   MONGO_PASSWORD=<your-generated-password>
   HF_TOKEN=<your-hf-token>  # Optional
   ```

3. **Coolify automatically provides**:
   - `COOLIFY_FQDN` - Your app domain
   - SSL certificates
   - Network configuration

4. **Click Save** and **Deploy**

---

## 🗂️ Your Data Directory Structure

Your existing `/data` structure is perfect:

```
/data/
├── mongodb/              # MongoDB data (auto-mounted)
├── ollama/              # AI models (auto-mounted)
│   ├── models/
│   └── logs/
├── n8n/                 # n8n workflows (auto-mounted)
├── agent-gateway/       # Gateway data
│   ├── logs/
│   ├── sessions/
│   └── tmp/
├── discovery-agent/     # Discovery data
├── camoufox/           # Browser data
├── extraction-agent/    # Extracted data
│   ├── logs/
│   ├── raw_html/
│   ├── screenshots/
│   ├── sessions/
│   └── tmp/
├── vision-agent/        # Vision processing
│   ├── logs/
│   ├── ocr_results/
│   ├── processed_images/
│   ├── embeddings/
│   └── tmp/
└── ...
```

**The docker-compose will automatically use these directories!**

---

## 🎯 Optimized for Your Server

Your server specs:
- **RAM**: 32GB ✅ (Perfect for full model set)
- **Disk**: 1.9TB ✅ (Plenty of space)
- **Already running**: Docker with Coolify ✅

### Recommended Configuration

Since you have 32GB RAM, use the **full setup**:

```bash
# In models.config (already included)
llama3.1        # 4.7GB
llava           # 4.7GB
qwen3-vl        # 4.7GB
gemma3          # 2GB
deepseek-r1     # 7.5GB
codellama       # 3.8GB
bge-m3          # 2.2GB
mistral-small3.1 # 7.7GB

# Total: ~37GB models (will fit in your disk, uses ~16GB RAM when loaded)
```

### Performance Tuning for Your Setup

Add these to environment (already optimized in defaults):

```env
# With 32GB RAM, you can run multiple models simultaneously
OLLAMA_NUM_PARALLEL=4          # Run 4 requests in parallel
OLLAMA_MAX_LOADED_MODELS=3     # Keep 3 models in RAM

# With your network setup
MAX_CONCURRENT_REQUESTS=20     # 20 concurrent scrape requests

# GPU (if you have one)
# CUDA_VISIBLE_DEVICES=0       # Uncomment if you have NVIDIA GPU
```

---

## 🔐 Security Best Practices

### Generate Strong Passwords

```bash
# MongoDB password
MONGO_PASSWORD=$(openssl rand -base64 32)
echo "MONGO_PASSWORD=$MONGO_PASSWORD"

# Save to file (restrict permissions)
echo "MONGO_PASSWORD=$MONGO_PASSWORD" > /root/.scraper-credentials
chmod 600 /root/.scraper-credentials
```

### API Keys

**Hugging Face Token** (for downloading models):
- Only needed if using private models
- Get from: https://huggingface.co/settings/tokens
- Permissions needed: "Read access to contents of all repos"

**Not required for basic operation** - Ollama downloads models directly.

---

## 🧪 Test Your Configuration

### 1. Check Environment Loaded

```bash
# In Coolify, view container logs
# Should see:
# ✓ MongoDB connected
# ✓ Ollama available
# ✓ Models downloading
```

### 2. Verify Data Mounts

```bash
# On your server
ls -la /data/mongodb    # Should see MongoDB files after startup
ls -la /data/ollama/models    # Should see models after download
ls -la /data/n8n       # Should see n8n data
```

### 3. Test Services

```bash
# Gateway
curl http://your-domain:8000/health

# Ollama
curl http://your-domain:11434/api/tags

# n8n
curl http://your-domain:5678/healthz
```

---

## 🔄 Integration with Zie619's Workflows

### n8n Credentials Setup

When importing workflows from https://github.com/Zie619/n8n-workflows:

**MongoDB Connection**:
```
Type: MongoDB
Host: mongodb
Port: 27017
Database: webscraper
Username: admin
Password: <your-MONGO_PASSWORD>
Authentication Source: admin
```

**HTTP Request (for Gateway)**:
```
Base URL: http://agent-gateway:8000
```

**No API keys needed** - internal network communication!

---

## 📊 Environment Variables by Category

### Minimal (Required)
```bash
MONGO_PASSWORD=<secure-password>
```

### Optional AI APIs
```bash
HF_TOKEN=<token>              # Only for private HF models
OPENAI_API_KEY=<key>          # Only if using OpenAI
ANTHROPIC_API_KEY=<key>       # Only if using Claude
```

### Auto-Configured (Don't touch)
```bash
COOLIFY_FQDN                  # Set by Coolify
MONGODB_URI                   # Constructed from other vars
OLLAMA_URL                    # Internal Docker network
*_URL variables               # All internal Docker
```

### Performance (Optional tuning)
```bash
MAX_CONCURRENT_REQUESTS=20    # Higher with more RAM
OLLAMA_NUM_PARALLEL=4         # Parallel AI requests
OLLAMA_MAX_LOADED_MODELS=3    # Models in RAM
```

---

## 🚨 Troubleshooting Environment Issues

### MongoDB Connection Failed

```bash
# Check password matches
docker exec webscraper-mongodb mongosh \
  -u admin -p $MONGO_PASSWORD --eval "db.adminCommand('ping')"
```

### Models Not Downloading

```bash
# Check HF_TOKEN if using private models
# Otherwise, Ollama doesn't need it
docker logs webscraper-ollama
```

### Services Can't Connect

```bash
# Ensure all on same Docker network
docker network inspect webscraper-network
```

### Out of Memory

```bash
# Your server has 32GB, this shouldn't happen
# If it does, reduce models:
# Edit models.config, keep only:
# - llama3.1
# - llava
# - bge-m3
```

---

## ✅ Final Checklist

Before deploying:

- [ ] Generated secure MONGO_PASSWORD
- [ ] (Optional) Got HF_TOKEN from Hugging Face
- [ ] Set environment variables in Coolify
- [ ] `/data` directories exist (you already did this!)
- [ ] Reviewed models.config (use full set with 32GB RAM)
- [ ] Ready to deploy!

---

## 🎯 Quick Copy-Paste for Coolify

**Just set these two in Coolify:**

```
MONGO_PASSWORD=<run: openssl rand -base64 32>
HF_TOKEN=<optional, from HF website>
```

**Everything else is automatic!**

---

## 📞 If Something Goes Wrong

1. **Check Coolify logs** - Most issues show up here
2. **Verify environment** - Use Coolify's env viewer
3. **Check data mounts** - `ls -la /data/*`
4. **Test connectivity** - `curl` health endpoints
5. **Review this guide** - Most issues are covered above

---

**Your server is ready! With 32GB RAM and 1.9TB disk, you can run the full platform at maximum capacity! 🚀**
