# 🚀 Deployment Checklist

Complete checklist before deploying to your server.

---

## 📋 Pre-Deployment Checklist

### ✅ Repository Setup

- [ ] Git repository initialized
- [ ] All files committed to main branch
- [ ] MVP branch created and pushed
- [ ] Repository accessible (GitHub/GitLab/etc.)

### ✅ Server Prerequisites

Your server (already done ✅):
- [x] Docker installed and running
- [x] `/data` directory structure created
- [x] 32GB RAM, 1.9TB disk available
- [x] Arch Linux with NVIDIA drivers (for GPU)

### ✅ GPU Setup (For 4090 optimization)

- [ ] NVIDIA drivers installed (`nvidia-smi` works)
- [ ] nvidia-container-toolkit installed
- [ ] Docker configured for GPU (`docker run --gpus all nvidia/cuda:12.0-base nvidia-smi`)

### ✅ Coolify Setup

- [ ] Coolify installed and accessible
- [ ] Can create new projects in Coolify
- [ ] Network connectivity from Coolify to your repository

---

## 🌿 Creating Branches

### Create MVP Branch (For Testing)

```bash
# Run the script
bash create-mvp-branch.sh

# Push to remote
git push origin mvp
```

### Create 4090 Branch (For GPU Optimization)

```bash
# Create 4090 branch
git checkout -b 4090-optimized

# Copy GPU-specific files
cp .env.4090.example .env.example
cp README.md README.main.md
cat ARCH_4090_SETUP.md > README.md

# Commit
git add .
git commit -m "4090-optimized branch: GPU acceleration for RTX 4090"

# Push
git push origin 4090-optimized
```

---

## 🎯 Which Branch to Deploy?

### MVP Branch (Recommended First Deployment)

**Use when:**
- Testing the platform
- Limited resources (8-16GB RAM)
- Want quick setup (10 minutes)
- Prototyping workflows

**Specs:**
- Minimal models (~12GB)
- Single instance of each service
- CPU-based inference
- Perfect for learning

**Deploy command:**
```
Branch: mvp
Compose: docker-compose.mvp.yml
Environment: MONGO_PASSWORD only
```

### Main Branch (Full Production)

**Use when:**
- Production deployment
- 16GB+ RAM available
- Want all features
- Running at scale

**Specs:**
- Full model set (~40GB)
- Multiple replicas
- All features enabled
- Production-ready

**Deploy command:**
```
Branch: main
Compose: docker-compose.yml
Environment: MONGO_PASSWORD + custom settings
```

### 4090 Branch (Maximum Performance)

**Use when:**
- You have RTX 4090
- Need maximum speed
- Processing large volumes
- Quality is critical

**Specs:**
- Larger models (32B parameters)
- GPU acceleration
- 5x Camoufox browsers
- 20-30x faster than CPU

**Deploy command:**
```
Branch: 4090-optimized
Compose: docker-compose.4090.yml
Environment: MONGO_PASSWORD + GPU settings
```

---

## 🚀 Coolify Deployment Steps

### Step 1: Verify Repository Access

```bash
# Ensure repository is pushed
git push origin main
git push origin mvp
git push origin 4090-optimized  # if using GPU

# Verify on GitHub/GitLab
# Repository should be accessible
```

### Step 2: Create Project in Coolify

1. **Coolify Dashboard** → **New Project**
2. Name: `ai-web-scraper`
3. Click **Create**

### Step 3: Add Repository

1. **New Resource** → **Public Repository**
2. **Repository URL**: `https://github.com/YOUR-USERNAME/ai-scraper`
3. **Branch**: Choose one:
   - `mvp` - Quick test
   - `main` - Full production
   - `4090-optimized` - GPU acceleration
4. **Build Pack**: Docker Compose
5. **Compose File**:
   - MVP: `docker-compose.mvp.yml`
   - Main: `docker-compose.yml`
   - 4090: `docker-compose.4090.yml`

### Step 4: Configure Environment

In Coolify → **Environment** tab:

**Minimum (all branches):**
```
MONGO_PASSWORD=<run: openssl rand -base64 32>
```

**For 4090 branch, also add:**
```
CUDA_VISIBLE_DEVICES=0
OLLAMA_NUM_PARALLEL=8
OLLAMA_MAX_LOADED_MODELS=4
```

### Step 5: Configure Domains (Optional)

**Gateway** (port 8000):
- Domain: `api.yourdomain.com`
- SSL: ✅ Enable

**n8n** (port 5678):
- Domain: `n8n.yourdomain.com`
- SSL: ✅ Enable

### Step 6: Deploy

1. Click **Deploy**
2. Monitor logs in Coolify
3. Wait for:
   - ✅ Build complete (~5 min)
   - ✅ Services start (~1 min)
   - ✅ Models download (~10 min for MVP, ~30 min for full)
   - ✅ Health checks pass

---

## ✅ Post-Deployment Verification

### 1. Check Service Health

```bash
# From your local machine or server
curl https://your-app.coolify.app/health

# Expected response:
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

### 2. Access Services

- **API Docs**: https://your-app.coolify.app/docs
- **n8n**: https://n8n.your-app.coolify.app

### 3. Test Scrape

```bash
curl -X POST https://your-app.coolify.app/scrape \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","strategy":"full"}'
```

### 4. Check Data Directory

SSH to your server:
```bash
# Should see data appearing
ls -lh /data/mongodb
ls -lh /data/ollama/models
ls -lh /data/n8n
```

### 5. Monitor Resources

In Coolify:
- **Metrics** tab - CPU/RAM usage
- **Logs** tab - Service logs
- **Health** tab - Service status

---

## 🔄 Import Zie619's Workflows

### After Successful Deployment

1. **Clone workflows locally:**
   ```bash
   git clone https://github.com/Zie619/n8n-workflows
   ```

2. **Access n8n**: https://n8n.your-app.coolify.app

3. **Create owner account** (first time)

4. **Import workflow:**
   - Workflows → Import from File
   - Select `.json` file
   - Click Import

5. **Update connections:**
   
   **HTTP Request nodes:**
   ```
   URL: http://agent-gateway:8000
   ```
   
   **MongoDB nodes:**
   ```
   Host: mongodb
   Port: 27017
   Database: webscraper
   Username: admin
   Password: <your-MONGO_PASSWORD>
   ```

6. **Test workflow:**
   - Click Execute Workflow
   - Check results

---

## 🐛 Troubleshooting

### Models Not Downloading

```bash
# Check Ollama logs in Coolify
# Or SSH to server:
docker logs webscraper-ollama
docker logs webscraper-model-manager
```

### Services Won't Start

```bash
# Check Coolify logs
# Common issues:
# - Port conflicts (change ports in environment)
# - Memory limits (reduce replicas or models)
# - GPU not detected (verify nvidia-container-toolkit)
```

### Can't Access Services

```bash
# Check Coolify domains are configured
# Check SSL certificates issued
# Check firewall allows ports 80, 443
```

### Out of Memory

```bash
# Reduce models in models.mvp.config
# Or switch to smaller models:
echo "llama3.1" > models.mvp.config
echo "llava" >> models.mvp.config
```

---

## 📊 Deployment Time Estimates

### MVP Branch
- Build: 5 minutes
- Model download: 5-10 minutes
- **Total: ~15 minutes**

### Main Branch
- Build: 5 minutes
- Model download: 20-30 minutes
- **Total: ~35 minutes**

### 4090 Branch
- Build: 5 minutes
- Model download: 30-40 minutes (larger models)
- **Total: ~45 minutes**

---

## ✅ Final Checklist

Before considering deployment complete:

- [ ] All health checks pass
- [ ] Can access API docs
- [ ] Can access n8n
- [ ] Test scrape completes
- [ ] At least 1 Zie619 workflow imported and tested
- [ ] Results visible in MongoDB
- [ ] Resource usage is acceptable
- [ ] Logs show no critical errors
- [ ] Saved credentials securely

---

## 🎉 Success!

Once all checks pass:

1. ✅ Your platform is deployed
2. 🔄 Import Zie619's workflows
3. 🧪 Test with real websites
4. 🎨 Customize for your needs
5. 📈 Monitor and optimize
6. 🚀 Scale when needed

---

## 📞 Quick Reference

**MVP Deployment:**
```bash
bash create-mvp-branch.sh
git push origin mvp
# Deploy in Coolify with mvp branch
```

**Verify:**
```bash
curl https://your-app.coolify.app/health
```

**Access:**
- API: https://your-app.coolify.app/docs
- n8n: https://n8n.your-app.coolify.app

**Credentials:**
- MongoDB: admin / <your-MONGO_PASSWORD>
- n8n: Create on first login

---

**Your deployment is ready! 🚀**
