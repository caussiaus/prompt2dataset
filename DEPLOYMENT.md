# Deployment Guide

Complete guide for deploying prompt2dataset to production using Coolify.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Pre-Deployment Checklist](#pre-deployment-checklist)
- [Local Testing](#local-testing)
- [Coolify Deployment](#coolify-deployment)
- [Post-Deployment](#post-deployment)
- [Monitoring](#monitoring)
- [Scaling](#scaling)

## Prerequisites

### System Requirements

- **CPU**: 4+ cores recommended
- **RAM**: 8GB minimum, 16GB+ recommended
- **Storage**: 50GB+ (mainly for Ollama models)
- **OS**: Linux (Ubuntu 22.04 LTS recommended)
- **Docker**: Version 24.0+
- **Docker Compose**: Version 2.0+

### Network Requirements

- Open ports: 5432, 11434, 3000, 5000, 8888, 5678, 8000-8004
- Stable internet connection (for downloading models)
- DNS configured for your domain

### Coolify Requirements

- Coolify v4+ installed and running
- GitHub repository access
- SSL certificates (automatic via Coolify)

## Pre-Deployment Checklist

### 1. Environment Configuration

```bash
# Copy environment template
cp config/.env.example .env

# Edit .env and set these REQUIRED values:
DB_PASSWORD=<generate-strong-password>
DOMAIN=yourdomain.com
SECRET_KEY=<generate-secret-key>
```

### 2. Validate Configuration Files

```bash
# Validate services.json
python3 -c "import json; json.load(open('services.json'))"

# Check all required files exist
ls -la services.json coolify-manifest.yaml docker-compose.local.yml
```

### 3. Check Docker Requirements

```bash
# Verify Docker is installed
docker --version
docker-compose --version

# Check Docker daemon is running
docker info
```

### 4. Test Locally First

**CRITICAL**: Always test locally before production deployment.

```bash
# Run setup script
bash scripts/setup.sh

# Start services
docker-compose -f docker-compose.local.yml up -d

# Wait for services to start (2-3 minutes)
sleep 180

# Check health
python3 scripts/service_tracker.py

# Run tests
python3 scripts/service_client.py --test
```

If all services are healthy, proceed to production deployment.

## Local Testing

### Start Local Stack

```bash
# Start all services
docker-compose -f docker-compose.local.yml up -d

# Follow logs
docker-compose -f docker-compose.local.yml logs -f

# Check specific service
docker-compose -f docker-compose.local.yml logs -f extraction-agent
```

### Test Individual Services

```bash
# Test HTML Parser
curl http://localhost:5000/health

# Test Extraction Agent
curl -X POST http://localhost:8001/extract \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "schema": {"title": "string"}}'

# Test Discovery Agent
curl -X POST http://localhost:8004/discover \
  -H "Content-Type: application/json" \
  -d '{"query": "test query", "max_results": 5}'
```

### Stop Local Stack

```bash
# Stop services
docker-compose -f docker-compose.local.yml down

# Stop and remove volumes (CAUTION: deletes data)
docker-compose -f docker-compose.local.yml down -v
```

## Coolify Deployment

### Step 1: Push Repository to GitHub

```bash
# Initialize git if not already done
git init
git add .
git commit -m "Initial commit: prompt2dataset setup"

# Add remote and push
git remote add origin https://github.com/yourusername/prompt2dataset.git
git branch -M main
git push -u origin main
```

### Step 2: Connect Repository to Coolify

1. Log in to Coolify dashboard
2. Navigate to your project (or create new project "prompt2dataset")
3. Click **"Add Resource"** → **"New Service"** → **"From Git Repository"**
4. Enter repository URL: `https://github.com/yourusername/prompt2dataset`
5. Select branch: `main`
6. Click **"Continue"**

### Step 3: Import Coolify Manifest

1. In Coolify, go to project settings
2. Click **"Import"** → **"Docker Compose"**
3. Select `coolify-manifest.yaml` from your repository
4. Review the imported services
5. Click **"Save"**

### Step 4: Configure Environment Variables

For each service, configure environment variables:

1. Click on service (e.g., "postgres")
2. Go to **"Environment Variables"** tab
3. Add variables from `config/.env.example`
4. **CRITICAL**: Set these at minimum:
   - `DB_PASSWORD` (secure random password)
   - `DOMAIN` (your domain)
   - `SECRET_KEY` (secure random key)

### Step 5: Deploy Services in Order

**IMPORTANT**: Deploy in this specific order to handle dependencies.

#### Phase 1: Core Infrastructure (5-10 minutes)

1. **PostgreSQL**
   - Deploy
   - Wait for "healthy" status
   - Verify: `docker logs <postgres-container>`

2. **Ollama**
   - Deploy
   - **WAIT 10-15 MINUTES** for model downloads
   - Models to download: `mistral:latest`, `llava:latest`
   - Verify: `curl http://localhost:11434/api/tags`

#### Phase 2: Utilities (2-5 minutes)

3. **Camoufox**
   - Deploy
   - Wait for healthy status

4. **HTML Parser**
   - Deploy
   - Verify: `curl http://localhost:5000/health`

5. **SearXNG**
   - Deploy (if not already running)
   - Verify: `curl http://localhost:8888/`

#### Phase 3: Orchestration (2-5 minutes)

6. **n8n**
   - Deploy (if not already running)
   - Verify: `curl http://localhost:5678/rest/health`

#### Phase 4: Agents (5-10 minutes)

7. **Extraction Agent**
   - Deploy
   - Verify: `curl http://localhost:8001/health`

8. **Vision Agent**
   - Deploy
   - Verify: `curl http://localhost:8002/health`

9. **Discovery Agent**
   - Deploy
   - Verify: `curl http://localhost:8004/health`

10. **Orchestrator Agent**
    - Deploy
    - Verify: `curl http://localhost:8003/health`

#### Phase 5: Gateway (2 minutes)

11. **Agent Gateway**
    - Deploy
    - Verify: `curl http://localhost:8000/health`

### Step 6: Configure Domains & SSL

For each service that needs public access:

1. Go to service settings in Coolify
2. Click **"Domains"** tab
3. Add domain: `service-name.yourdomain.com`
4. Enable **"Generate SSL"**
5. Wait for SSL certificate generation

Recommended public domains:
- `api.yourdomain.com` → Agent Gateway (8000)
- `n8n.yourdomain.com` → n8n (5678)
- `search.yourdomain.com` → SearXNG (8888)

## Post-Deployment

### 1. Verify All Services

```bash
# SSH to your server
ssh user@your-server.com

# Run service tracker
python3 scripts/service_tracker.py

# Expected output: All services "healthy"
```

### 2. Test End-to-End Workflow

```bash
# Test from your local machine
python3 scripts/service_client.py --gateway-url https://api.yourdomain.com --test
```

### 3. Initialize Ollama Models

```bash
# SSH to server
ssh user@your-server.com

# Access Ollama container
docker exec -it <ollama-container> bash

# Download required models
ollama pull mistral:latest
ollama pull llava:latest
ollama pull neural-chat:latest

# Verify
ollama list
```

### 4. Database Initialization

```bash
# Connect to PostgreSQL
docker exec -it <postgres-container> psql -U postgres -d app_db

# Verify pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

# List tables (should show agent tables)
\dt
```

### 5. Configure n8n

1. Access n8n at `https://n8n.yourdomain.com`
2. Create admin account
3. Import workflows from `n8n-workflows/examples/`
4. Configure credentials for services

### 6. Set Up Monitoring

```bash
# Set up service tracker as a cron job
crontab -e

# Add this line to check every 5 minutes
*/5 * * * * /usr/bin/python3 /path/to/scripts/service_tracker.py --json >> /var/log/service-health.log
```

## Monitoring

### Service Health Monitoring

```bash
# Real-time monitoring
python3 scripts/service_tracker.py --watch

# JSON output for logging
python3 scripts/service_tracker.py --json

# Quick check
bash scripts/health-check.sh
```

### View Logs in Coolify

1. Go to Coolify dashboard
2. Click on service
3. Click **"Logs"** tab
4. View real-time logs

### Database Monitoring

```bash
# Check database size
docker exec <postgres-container> psql -U postgres -d app_db -c "SELECT pg_size_pretty(pg_database_size('app_db'));"

# Check active connections
docker exec <postgres-container> psql -U postgres -d app_db -c "SELECT count(*) FROM pg_stat_activity;"

# Check table sizes
docker exec <postgres-container> psql -U postgres -d app_db -c "SELECT relname, pg_size_pretty(pg_total_relation_size(relid)) FROM pg_stat_user_tables ORDER BY pg_total_relation_size(relid) DESC;"
```

### Ollama Model Status

```bash
# Check loaded models
curl http://localhost:11434/api/tags

# Check model usage
docker stats <ollama-container>
```

## Scaling

### Horizontal Scaling

To scale specific agents:

```bash
# In Coolify
# 1. Go to service settings
# 2. Increase "Replicas" count
# 3. Coolify will load balance automatically
```

Recommended scaling:
- **Extraction Agent**: 2-3 replicas for high load
- **Vision Agent**: 2-3 replicas (vision is CPU-intensive)
- **Discovery Agent**: 1 replica sufficient
- **Orchestrator Agent**: 2 replicas for reliability

### Vertical Scaling

To increase resources:

```bash
# Edit docker-compose or Coolify resource limits
# For Ollama (most resource-intensive):
resources:
  limits:
    cpus: '4'
    memory: 8G
```

### Database Scaling

```bash
# For production, consider:
# 1. Separate PostgreSQL server
# 2. Connection pooling (pgbouncer)
# 3. Read replicas for analytics

# Example: Add pgbouncer
docker run -d \
  --name pgbouncer \
  -e DB_HOST=postgres \
  -e DB_PORT=5432 \
  -e DB_USER=postgres \
  -e DB_PASSWORD=$DB_PASSWORD \
  pgbouncer/pgbouncer
```

## Backup & Recovery

### Database Backup

```bash
# Automated backup script
cat > /usr/local/bin/backup-prompt2dataset.sh << 'EOF'
#!/bin/bash
BACKUP_DIR=/backups/prompt2dataset
DATE=$(date +%Y%m%d_%H%M%S)

# Backup PostgreSQL
docker exec <postgres-container> pg_dumpall -U postgres | gzip > $BACKUP_DIR/postgres_$DATE.sql.gz

# Backup Ollama models
tar -czf $BACKUP_DIR/ollama_$DATE.tar.gz /var/lib/docker/volumes/ollama_data

# Keep last 7 days
find $BACKUP_DIR -name "*.gz" -mtime +7 -delete
EOF

chmod +x /usr/local/bin/backup-prompt2dataset.sh

# Add to crontab
crontab -e
# Add: 0 2 * * * /usr/local/bin/backup-prompt2dataset.sh
```

### Restore from Backup

```bash
# Restore PostgreSQL
gunzip < postgres_backup.sql.gz | docker exec -i <postgres-container> psql -U postgres

# Restore Ollama models
tar -xzf ollama_backup.tar.gz -C /var/lib/docker/volumes/
```

## Troubleshooting Deployment

See [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) for common issues.

### Quick Fixes

```bash
# Service won't start
docker logs <container-name>

# Database connection issues
docker exec <postgres-container> pg_isready -U postgres

# Ollama model not loaded
docker exec <ollama-container> ollama list

# Network issues
docker network inspect mvp-network

# Reset everything (CAUTION)
docker-compose -f docker-compose.local.yml down -v
docker-compose -f docker-compose.local.yml up -d
```

## Security Considerations

1. **Change default passwords** in `.env`
2. **Enable firewall** - only open required ports
3. **Use SSL/TLS** for all public services
4. **Regular updates** - keep Docker images updated
5. **Backup secrets** - store `.env` securely
6. **Monitor logs** - check for suspicious activity
7. **Rate limiting** - configure in nginx/gateway

## Next Steps

After successful deployment:

1. ✅ Create test workflows in n8n
2. ✅ Set up monitoring alerts
3. ✅ Configure backups
4. ✅ Document custom workflows
5. ✅ Train team on usage

---

**Need help?** Open an issue on GitHub or check the troubleshooting guide.
