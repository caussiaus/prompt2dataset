# 🚀 Coolify Deployment Guide - MVP Branch

**Deploy from scratch to running system in 10 minutes.**

---

## Prerequisites

- Coolify installed and running
- Server with 8GB+ RAM, 25GB disk
- Domain (optional, can use Coolify subdomain)

---

## 🎯 Deployment Steps

### Step 1: Create Project in Coolify

1. Open Coolify dashboard
2. **Projects** → **New Project**
3. Name: `ai-scraper-mvp`
4. Click **Create**

### Step 2: Add Git Repository

1. In your project: **New Resource** → **Public Repository**
2. **Repository URL**: 
   ```
   https://github.com/YOUR-USERNAME/ai-scraper
   ```
3. **Branch**: `mvp`
4. **Build Pack**: Docker Compose
5. **Compose File**: `docker-compose.mvp.yml`
6. Click **Continue**

### Step 3: Configure Environment

In the **Environment** tab, add:

```env
MONGO_USERNAME=admin
MONGO_PASSWORD=YOUR_SECURE_PASSWORD_HERE
DB_NAME=webscraper
GATEWAY_PORT=8000
N8N_PORT=5678
TIMEZONE=America/New_York
```

**Generate secure password**:
```bash
openssl rand -base64 32
```

### Step 4: Configure Domains (Optional)

#### Option A: Use Coolify Subdomain
Coolify will auto-generate: `random-name.coolify.io`

#### Option B: Use Custom Domain

For **Gateway** (port 8000):
- Domain: `api.yourdomain.com`
- SSL: ✅ Enable Let's Encrypt

For **n8n** (port 5678):
- Domain: `n8n.yourdomain.com`
- SSL: ✅ Enable Let's Encrypt

Update environment:
```env
N8N_HOST=n8n.yourdomain.com
N8N_PROTOCOL=https
WEBHOOK_URL=https://n8n.yourdomain.com
```

### Step 5: Deploy!

1. Click **Deploy**
2. Monitor logs in real-time
3. Wait for:
   - ✅ Containers built (~5 min)
   - ✅ Services started (~1 min)
   - ✅ Models downloaded (~5-10 min)

**Total time**: ~10-15 minutes first deployment

---

## ✅ Verify Deployment

### Check Service Health

```bash
curl https://api.yourdomain.com/health

# Expected response:
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

### Access Services

- **API Docs**: `https://api.yourdomain.com/docs`
- **n8n**: `https://n8n.yourdomain.com`

### Check Logs in Coolify

1. Go to your resource
2. **Logs** tab
3. Select service to view logs

---

## 🔄 Import n8n Workflows

### From Zie619's Repository

1. **Clone workflows locally**:
   ```bash
   git clone https://github.com/Zie619/n8n-workflows
   ```

2. **Access your n8n instance**: `https://n8n.yourdomain.com`

3. **Create owner account** (first time only)

4. **Import workflow**:
   - **Workflows** → **Import from File**
   - Select `.json` file from cloned repo
   - Click **Import**

5. **Update connections**:
   - Find HTTP Request nodes
   - Change URL to: `http://agent-gateway:8000`
   - Save workflow

6. **Test workflow**:
   - Click **Execute Workflow**
   - Check execution results

### Configure MongoDB Connection

If workflow uses MongoDB:

```
Connection Type: MongoDB
Host: mongodb
Port: 27017
Database: webscraper
Username: admin
Password: <your-mongo-password>
Authentication Source: admin
```

---

## 🧪 Test Your Deployment

### Test 1: Simple Scrape via API

```bash
curl -X POST https://api.yourdomain.com/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "strategy": "full",
    "use_vision": false
  }'
```

### Test 2: Check AI Models

```bash
curl https://api.yourdomain.com:11434/api/tags
```

Should show: llama3.1, llava, bge-m3

### Test 3: Run n8n Workflow

1. Import workflow from examples
2. Update URLs to your domain
3. Execute workflow
4. Check results in MongoDB

---

## 🔧 Common Coolify Issues

### Issue: Models not downloading

**Solution**: Check Ollama logs in Coolify
```
Logs → Select "ollama" service
Look for download progress
```

If stuck, restart model-manager:
```
Restart → Select "model-manager" service
```

### Issue: Port already in use

**Solution**: Change ports in environment:
```env
GATEWAY_PORT=8100
N8N_PORT=5679
```

Then redeploy.

### Issue: Services can't connect

**Solution**: Check network configuration
- All services must be on same Docker network
- Use service names (e.g., `mongodb`, not `localhost`)

### Issue: Out of memory

**Solution**: 
1. Check server resources in Coolify
2. Reduce model count in `models.mvp.config`
3. Keep only `llama3.1` and `llava`

---

## 📊 Monitor Resources

### In Coolify Dashboard

1. Go to your resource
2. **Metrics** tab
3. Monitor:
   - CPU usage
   - Memory usage
   - Disk space

### Resource Expectations (MVP)

- **Idle**: 3-4GB RAM
- **Light scraping**: 5-6GB RAM
- **Heavy scraping**: 7-8GB RAM

---

## 🚀 Scale When Ready

### Add More Workers

In Coolify:
1. **Configuration** → **Replicas**
2. Set replicas for:
   - `agent-camoufox`: 2-3 (most beneficial)
   - `agent-extraction`: 2
3. Save and redeploy

### Upgrade to Full Version

1. Change branch to `main`
2. Use `docker-compose.yml` instead of `docker-compose.mvp.yml`
3. Update `models.config` to include more models
4. Redeploy

---

## 🔐 Security Checklist

Before going to production:

- [ ] Changed MONGO_PASSWORD to secure value
- [ ] Enabled SSL/HTTPS for all services
- [ ] Set up backups (MongoDB)
- [ ] Configured firewall rules
- [ ] Added monitoring/alerts
- [ ] Documented credentials securely

---

## 📚 Zie619's Workflow Integration

### Recommended Workflows to Test

From https://github.com/Zie619/n8n-workflows:

1. **Basic Web Scraper**
   - Import and test first
   - Update URLs to your instance

2. **AI Content Extractor**
   - Tests extraction agent
   - Good for structured data

3. **Scheduled Monitor**
   - Tests scheduling
   - Good for periodic scraping

4. **Data Pipeline**
   - Full end-to-end test
   - Tests all agents

### Workflow Configuration Pattern

For each imported workflow:

1. **Find HTTP Request nodes**
2. **Update base URL**: `http://agent-gateway:8000`
3. **Check authentication**: None needed (internal)
4. **Test execution**: Run manually first
5. **Enable scheduling**: When working
6. **Monitor results**: Check MongoDB

---

## 🎯 Success Checklist

Your MVP is ready when:

- [ ] All health checks pass
- [ ] API docs accessible
- [ ] n8n accessible and configured
- [ ] Test scrape completes successfully
- [ ] At least one Zie619 workflow running
- [ ] Results visible in MongoDB
- [ ] No memory/disk issues

---

## 🆘 Need Help?

### Coolify Issues
- Coolify Docs: https://coolify.io/docs
- Coolify Discord: https://discord.gg/coolify

### n8n Issues
- n8n Docs: https://docs.n8n.io
- n8n Forum: https://community.n8n.io

### This Platform
- GitHub Issues: [your-repo]/issues
- Check logs in Coolify
- Review README.MVP.md

### Zie619's Workflows
- Workflow Repo: https://github.com/Zie619/n8n-workflows
- Create issue there for workflow-specific questions

---

## 🎉 You're Live!

Your MVP is deployed! Next steps:

1. ✅ Test with simple sites
2. 🔄 Import Zie619's workflows
3. 🎨 Customize for your use cases
4. 📈 Monitor and optimize
5. 🚀 Scale when ready

**Happy scraping! 🎊**
