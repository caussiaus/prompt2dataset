# 🚀 Deploy from GitHub/GitLab URL to Coolify

**Complete guide for deploying from repository URL.**

---

## 📋 Before You Start

### 1. Push Repository to GitHub/GitLab

```bash
# In your workspace (Cursor)
bash PREPARE_FOR_DEPLOYMENT.sh

# Add your remote (replace with your URL)
git remote add origin https://github.com/YOUR-USERNAME/ai-scraper.git

# Push all branches
git push -u origin main
git push -u origin mvp
git push -u origin 4090-optimized
```

### 2. Verify Repository

Check that your repository is accessible:
- Public repository: No authentication needed
- Private repository: You'll need to add SSH key or token in Coolify

---

## 🎯 Deployment Options

### Option 1: MVP (Quick Test - Recommended First)

**Best for**: Testing, learning, prototyping

**Requirements**:
- 8GB+ RAM
- 25GB+ disk
- No GPU needed

**Coolify Config**:
```
Repository: https://github.com/YOUR-USERNAME/ai-scraper
Branch: mvp
Compose File: docker-compose.mvp.yml
Environment:
  MONGO_PASSWORD=<generate secure password>
```

**Deploy Time**: ~10 minutes

---

### Option 2: 4090-Optimized (Maximum Performance)

**Best for**: Production, high volume, maximum speed

**Requirements**:
- RTX 4090 GPU
- 32GB+ RAM
- 100GB+ disk
- NVIDIA drivers + nvidia-container-toolkit

**Coolify Config**:
```
Repository: https://github.com/YOUR-USERNAME/ai-scraper
Branch: 4090-optimized
Compose File: docker-compose.4090.yml
Environment:
  MONGO_PASSWORD=<generate secure password>
  CUDA_VISIBLE_DEVICES=0
```

**Deploy Time**: ~15 minutes

---

### Option 3: Main (Full Production)

**Best for**: Production without GPU

**Requirements**:
- 16GB+ RAM
- 50GB+ disk

**Coolify Config**:
```
Repository: https://github.com/YOUR-USERNAME/ai-scraper
Branch: main
Compose File: docker-compose.yml
Environment:
  MONGO_PASSWORD=<generate secure password>
```

**Deploy Time**: ~30 minutes

---

## 📝 Step-by-Step Coolify Deployment

### Step 1: Open Coolify Dashboard

1. Access your Coolify instance
2. Click **Projects** → **New Project**
3. Name: `ai-web-scraper`
4. Click **Create**

### Step 2: Add Repository

1. In your project, click **New Resource**
2. Select **Public Repository** (or Private if applicable)
3. Fill in:
   ```
   Repository URL: https://github.com/YOUR-USERNAME/ai-scraper
   Branch: mvp (or 4090-optimized)
   Build Pack: Docker Compose
   Compose File: docker-compose.mvp.yml (or .4090.yml)
   ```
4. Click **Continue**

### Step 3: Configure Environment

In the **Environment** tab, add:

**For MVP or Main**:
```env
MONGO_PASSWORD=<paste-generated-password>
```

**For 4090-Optimized**, also add:
```env
CUDA_VISIBLE_DEVICES=0
OLLAMA_NUM_PARALLEL=8
OLLAMA_MAX_LOADED_MODELS=4
OLLAMA_FLASH_ATTENTION=1
```

**Generate secure password**:
```bash
openssl rand -base64 32
```

### Step 4: Configure Domains (Optional)

**For Gateway** (port 8000):
- Click **Domains** → **Add Domain**
- Domain: `api.yourdomain.com` (or use Coolify subdomain)
- Enable SSL ✅

**For n8n** (port 5678):
- Add another domain
- Domain: `n8n.yourdomain.com`
- Enable SSL ✅

### Step 5: Deploy

1. Click **Deploy** button
2. Monitor logs in real-time
3. Wait for:
   - ✅ Images build (5 min)
   - ✅ Services start (1 min)
   - ✅ Models download (5-30 min depending on branch)
   - ✅ Health checks pass (1 min)

### Step 6: Verify Deployment

Once deployed, test:

```bash
# Health check
curl https://your-app.coolify.app/health

# Should return:
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

---

## 🌐 Access Your Services

After deployment:

**API Gateway**:
- URL: Check Coolify for generated URL
- Docs: `https://your-app.coolify.app/docs`

**n8n Workflows**:
- URL: Check Coolify for generated URL
- Create account on first visit

**MongoDB**:
- Internal: `mongodb://admin:<password>@mongodb:27017`
- Not exposed externally (secure)

---

## 🔄 Import Zie619's Workflows

### 1. Clone Workflows (On Your Local Machine)

```bash
git clone https://github.com/Zie619/n8n-workflows
```

### 2. Access n8n

Open your n8n URL from Coolify

### 3. Import Workflow

1. **Workflows** → **Import from File**
2. Select workflow JSON
3. Click **Import**

### 4. Update Connections

**HTTP Request nodes**:
```
URL: http://agent-gateway:8000/scrape
Method: POST
```

**MongoDB nodes**:
```
Host: mongodb
Port: 27017
Database: webscraper
Username: admin
Password: <your-MONGO_PASSWORD>
Authentication Source: admin
```

### 5. Test Workflow

1. Click **Execute Workflow**
2. Check results
3. If successful, activate for scheduled runs

---

## 🔧 Monitoring & Management

### View Logs

In Coolify:
1. Go to your resource
2. **Logs** tab
3. Select service to view logs
4. Use search/filter

### Check Metrics

In Coolify:
1. **Metrics** tab
2. Monitor CPU, RAM, disk usage
3. Set up alerts if needed

### SSH to Server (If Needed)

```bash
# Check data directory
ls -lh /data/

# Check models downloaded
ls -lh /data/ollama/models/

# Check n8n data
ls -lh /data/n8n/

# Monitor GPU (4090 branch)
watch -n 0.5 nvidia-smi

# Check containers
docker ps

# View container logs
docker logs -f webscraper-gateway
docker logs -f webscraper-ollama
```

---

## 🔄 Switching Branches

### Test → Production

If you started with MVP and want to upgrade:

1. In Coolify, go to your resource
2. **Configuration** → **Branch**
3. Change `mvp` to `4090-optimized`
4. Change Compose file to `docker-compose.4090.yml`
5. Add GPU environment variables
6. Click **Save**
7. Click **Redeploy**

### Or Create New Deployment

Keep MVP running, deploy 4090 separately:
1. **New Resource** → **Public Repository**
2. Use `4090-optimized` branch
3. Different compose file
4. Different domain

---

## 🐛 Troubleshooting

### Repository Not Found

- Check repository URL is correct
- If private, add SSH key or access token in Coolify
- Verify branch name is exact

### Build Fails

- Check Coolify logs for error
- Common: Missing Dockerfile → Check compose file path
- Solution: Verify compose file name matches

### Models Not Downloading

```bash
# SSH to server
docker logs -f webscraper-ollama
docker logs -f webscraper-model-manager

# Manually trigger if needed
docker restart webscraper-model-manager
```

### Services Not Starting

- Check environment variables set correctly
- Check port conflicts (change ports if needed)
- Check RAM/disk space available

### GPU Not Detected (4090 branch)

```bash
# On server
nvidia-smi  # Should show GPU

# Check Docker can access GPU
docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi

# Check container
docker exec webscraper-ollama nvidia-smi
```

---

## 📊 Branch Comparison

| Feature | MVP | Main | 4090-Optimized |
|---------|-----|------|----------------|
| **Deploy Time** | 10 min | 30 min | 15 min |
| **RAM Required** | 8GB | 16GB | 32GB |
| **Disk Space** | 25GB | 50GB | 100GB |
| **GPU Required** | No | No | Yes (4090) |
| **Model Size** | Small (8B) | Medium (8B-13B) | Large (32B) |
| **Performance** | Good | Better | Elite (20-30x) |
| **Concurrent Jobs** | 10 | 20 | 50 |
| **Best For** | Testing | Production | Max Performance |

---

## ✅ Deployment Checklist

Before deploying:

- [ ] Repository pushed to GitHub/GitLab
- [ ] All branches pushed (main, mvp, 4090-optimized)
- [ ] Repository is accessible (public or SSH key added)
- [ ] Generated secure MONGO_PASSWORD
- [ ] Decided which branch to deploy
- [ ] Verified server meets requirements
- [ ] (Optional) Custom domains configured

After deploying:

- [ ] Health check passes
- [ ] Can access API docs
- [ ] Can access n8n
- [ ] Test scrape completes successfully
- [ ] Zie619 workflow imported and tested
- [ ] Monitoring set up

---

## 🎯 Quick Deploy Commands

### On Your Local Machine (Cursor)

```bash
# Prepare repository
bash PREPARE_FOR_DEPLOYMENT.sh

# Add remote
git remote add origin https://github.com/YOUR-USERNAME/ai-scraper.git

# Push all branches
git push -u origin main mvp 4090-optimized
```

### In Coolify

1. New Resource → Public Repository
2. URL: `https://github.com/YOUR-USERNAME/ai-scraper`
3. Branch: `mvp` or `4090-optimized`
4. Compose: `docker-compose.mvp.yml` or `.4090.yml`
5. Environment: `MONGO_PASSWORD=<secure-password>`
6. Deploy

### Verify

```bash
curl https://your-app.coolify.app/health
```

---

## 🎉 Success!

Once deployed:
- ✅ API running at your Coolify URL
- ✅ n8n accessible for workflows
- ✅ Ready to import Zie619's workflows
- ✅ Can start scraping immediately

**Your AI web scraper platform is live! 🚀**

---

## 📞 Support

- **Check logs**: Coolify → Logs tab
- **Monitor resources**: Coolify → Metrics tab
- **Test endpoints**: Use API docs at `/docs`
- **Zie619 workflows**: https://github.com/Zie619/n8n-workflows

---

**Happy Scraping! 🎊**
