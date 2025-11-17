# Deployment Guide

Complete step-by-step guide for deploying the prompt2dataset MVP stack.

## Table of Contents

1. [Pre-Deployment Checklist](#pre-deployment-checklist)
2. [Local Development Setup](#local-development-setup)
3. [Coolify Deployment](#coolify-deployment)
4. [Post-Deployment Verification](#post-deployment-verification)
5. [Troubleshooting](#troubleshooting)

---

## Pre-Deployment Checklist

Before deploying, ensure you have:

- [ ] Docker and Docker Compose installed
- [ ] Git repository access
- [ ] Coolify instance running (for production)
- [ ] Required ports available (5432, 11434, 3000, 5000, 5678, 8000-8004, 8888)
- [ ] At least 50GB free disk space (for Ollama models)
- [ ] Environment variables configured

### Required Environment Variables

Copy the example environment file and configure:

```bash
cp config/.env.example .env
```

Edit `.env` and set:

- `DB_PASSWORD`: Secure PostgreSQL password
- `DOMAIN`: Your domain name (for production)
- Other service-specific variables as needed

---

## Local Development Setup

### 1. Clone Repository

```bash
git clone <your-repo-url>
cd prompt2dataset
```

### 2. Configure Environment

```bash
cp config/.env.example .env
# Edit .env with your settings
```

### 3. Start Services

```bash
# Start all services
docker-compose -f docker-compose.local.yml up -d

# Or start specific services
docker-compose -f docker-compose.local.yml up -d postgres ollama
```

### 4. Verify Services

```bash
# Check all services are running
docker-compose -f docker-compose.local.yml ps

# Use service tracker
python scripts/service_tracker.py
```

### 5. Download Ollama Models

```bash
# Access Ollama container
docker exec -it mvp-ollama bash

# Pull models
ollama pull mistral:latest
ollama pull llava:latest
ollama pull neural-chat:latest

# Exit container
exit
```

### 6. Test Services

```bash
# Run test suite
python scripts/service_client.py --test

# Test extraction
python scripts/service_client.py --extract "https://example.com"
```

---

## Coolify Deployment

### 1. Connect Repository to Coolify

1. Log in to your Coolify instance
2. Navigate to your project (or create new "MVP" project)
3. Click "Add Resource" → "Docker Compose"
4. Select "Import from Git Repository"
5. Choose your `prompt2dataset` repository
6. Select branch: `main`
7. Set compose file: `coolify-manifest.yaml`

### 2. Configure Environment Variables

In Coolify UI, add environment variables:

1. Go to your resource → "Environment Variables"
2. Add variables from `config/.env.example`
3. **Important variables:**
   - `DB_PASSWORD`: Generate a secure password
   - `DOMAIN`: Your domain name
   - `LOG_LEVEL`: Set to `info` for production

### 3. Deploy Services in Order

Deploy services in this order for proper dependency management:

#### Phase 1: Core Infrastructure
```
1. postgres (wait until healthy)
2. ollama (will take 5-10 minutes to download models)
```

#### Phase 2: Utilities
```
3. camoufox
4. html-parser
5. searxng
```

#### Phase 3: Orchestration
```
6. n8n
```

#### Phase 4: Agents
```
7. extraction-agent
8. vision-agent
9. orchestrator-agent
10. discovery-agent
```

#### Phase 5: Gateway
```
11. agent-gateway
```

### 4. Download Ollama Models

After Ollama is deployed:

```bash
# SSH into your server
ssh user@your-server

# Find Ollama container
docker ps | grep ollama

# Execute model downloads
docker exec -it <ollama-container-id> ollama pull mistral:latest
docker exec -it <ollama-container-id> ollama pull llava:latest
docker exec -it <ollama-container-id> ollama pull neural-chat:latest
```

Or configure Coolify to run these commands automatically:

1. Go to Ollama service → "Post-deployment Script"
2. Add:
```bash
ollama pull mistral:latest
ollama pull llava:latest
ollama pull neural-chat:latest
```

### 5. Configure Networking

Coolify automatically creates a Docker network. Ensure:

- All services are on the same network (`mvp-network`)
- Internal service URLs use container names (e.g., `http://postgres:5432`)
- External access is configured via Coolify's proxy

### 6. Set Up Domains (Optional)

For production with custom domains:

1. In Coolify, go to each service
2. Click "Domains"
3. Add domain/subdomain:
   - Gateway: `api.yourdomain.com`
   - n8n: `n8n.yourdomain.com`
   - SearxNG: `search.yourdomain.com`

Coolify will automatically configure SSL certificates via Let's Encrypt.

---

## Post-Deployment Verification

### 1. Health Check All Services

```bash
# On server
python scripts/service_tracker.py --detailed

# Or via API
curl http://localhost:8000/health
curl http://localhost:8000/api/services/status
```

### 2. Test Core Functionality

```bash
# Test extraction
curl -X POST http://localhost:8000/api/extract \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "type": "full"}'

# Test discovery
curl -X POST http://localhost:8000/api/discover \
  -H "Content-Type: application/json" \
  -d '{"query": "machine learning"}'

# Test vision (requires image URL)
curl -X POST http://localhost:8000/api/analyze-image \
  -H "Content-Type: application/json" \
  -d '{"image_url": "https://example.com/image.jpg"}'
```

### 3. Verify Database

```bash
# Access PostgreSQL
docker exec -it <postgres-container> psql -U postgres -d app_db

# Check tables
\dt

# Check n8n database
\c n8n
\dt
```

### 4. Monitor Logs

```bash
# View all logs
docker-compose -f docker-compose.local.yml logs -f

# View specific service
docker-compose -f docker-compose.local.yml logs -f extraction-agent

# In Coolify: each service has a "Logs" tab
```

---

## Service Deployment Order

Critical services must be deployed first:

```
postgres → ollama → utilities → orchestration → agents → gateway
```

### Why This Order?

1. **postgres**: All agents need database
2. **ollama**: Vision agent depends on it
3. **utilities**: Extraction agent needs html-parser
4. **orchestration**: n8n needs postgres
5. **agents**: Need all dependencies running
6. **gateway**: Needs all agents available

---

## Scaling Considerations

### For High Traffic

1. **Agent Replicas**: Scale extraction/vision agents
   ```yaml
   extraction-agent:
     deploy:
       replicas: 3
   ```

2. **Load Balancer**: Add nginx in front of gateway

3. **Database**: Use managed PostgreSQL (RDS, etc.)

4. **Ollama**: Consider GPU instances for faster inference

### For Multiple Environments

Create separate compose files:
- `docker-compose.dev.yml`
- `docker-compose.staging.yml`
- `docker-compose.prod.yml`

---

## Backup Strategy

### Database Backups

```bash
# Automated backup script
docker exec postgres pg_dump -U postgres app_db > backup_$(date +%Y%m%d).sql

# Restore
docker exec -i postgres psql -U postgres app_db < backup_20240101.sql
```

### Configuration Backups

```bash
# Backup all config
tar -czf config_backup_$(date +%Y%m%d).tar.gz config/ services.json coolify-manifest.yaml

# Version control
git add .
git commit -m "Config backup $(date +%Y%m%d)"
git push
```

---

## Security Checklist

- [ ] Change default database password
- [ ] Use environment variables for secrets
- [ ] Enable HTTPS for public-facing services
- [ ] Configure firewall rules
- [ ] Set up monitoring and alerts
- [ ] Regular security updates
- [ ] Limit database access to internal network
- [ ] Use Coolify's built-in security features

---

## Next Steps

After successful deployment:

1. **Configure n8n Workflows**
   - Access n8n at `http://localhost:5678`
   - Import example workflows from `n8n-workflows/`
   - Create custom workflows

2. **Set Up Monitoring**
   - Use `service_tracker.py --watch` for continuous monitoring
   - Set up alerts for service failures
   - Monitor resource usage

3. **Integrate with Frontend**
   - Use `service_client.py` as SDK
   - Point frontend to gateway URL
   - Implement error handling

4. **Documentation**
   - Document custom workflows
   - Update API endpoints as needed
   - Train team on service usage

---

## Support

For issues:

1. Check [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)
2. Review service logs
3. Use `service_tracker.py --detailed` for diagnostics
4. Check Coolify logs if deployment fails

---

## Quick Reference Commands

```bash
# Local development
docker-compose -f docker-compose.local.yml up -d
docker-compose -f docker-compose.local.yml down

# Monitor services
python scripts/service_tracker.py --watch

# Test services
python scripts/service_client.py --test

# View logs
docker-compose -f docker-compose.local.yml logs -f [service-name]

# Restart service
docker-compose -f docker-compose.local.yml restart [service-name]

# Clean up
docker-compose -f docker-compose.local.yml down -v
```
