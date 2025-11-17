# Troubleshooting Guide

Common issues and solutions for the prompt2dataset MVP stack.

## Table of Contents

1. [Service Health Issues](#service-health-issues)
2. [Database Problems](#database-problems)
3. [Ollama/LLM Issues](#ollamallm-issues)
4. [Network and Connectivity](#network-and-connectivity)
5. [Docker and Container Issues](#docker-and-container-issues)
6. [Performance Problems](#performance-problems)
7. [Coolify Deployment Issues](#coolify-deployment-issues)
8. [Common Error Messages](#common-error-messages)

---

## Quick Diagnostics

Run these commands first to diagnose issues:

```bash
# Check all services
python scripts/service_tracker.py --detailed

# Check Docker containers
docker ps -a

# Check logs
docker-compose logs --tail=50

# Test gateway
curl http://localhost:8000/health

# Check disk space
df -h

# Check memory
free -h
```

---

## Service Health Issues

### Symptom: Service shows as "unhealthy"

**Diagnosis**:
```bash
# Check service logs
docker logs <container-name>

# Check if service is running
docker ps | grep <service-name>

# Test health endpoint
curl http://localhost:<port>/health
```

**Solutions**:

1. **Service not starting**:
```bash
# Restart service
docker-compose restart <service-name>

# Or restart all
docker-compose restart
```

2. **Dependencies not ready**:
```bash
# Check dependency order in docker-compose.yml
# Wait for dependencies to be healthy
python scripts/service_tracker.py --watch
```

3. **Port conflicts**:
```bash
# Check if port is already in use
sudo lsof -i :<port>

# Kill conflicting process
sudo kill -9 <PID>

# Or change port in docker-compose.yml
```

---

### Symptom: Service keeps restarting

**Diagnosis**:
```bash
# Check restart count
docker ps -a

# View crash logs
docker logs <container-name> --tail=100
```

**Common Causes**:

1. **Missing environment variables**:
```bash
# Check env vars
docker exec <container-name> env

# Add missing vars to .env file
echo "MISSING_VAR=value" >> .env
docker-compose up -d
```

2. **Out of memory**:
```bash
# Check memory usage
docker stats

# Increase memory limit in docker-compose.yml:
services:
  service-name:
    mem_limit: 2g
```

3. **Failed health checks**:
```bash
# Increase health check timeout
healthcheck:
  timeout: 10s
  start_period: 30s
```

---

## Database Problems

### Symptom: "Database connection failed"

**Diagnosis**:
```bash
# Check if Postgres is running
docker ps | grep postgres

# Test connection
docker exec postgres psql -U postgres -c "SELECT 1;"

# Check logs
docker logs postgres --tail=50
```

**Solutions**:

1. **Postgres not running**:
```bash
docker-compose up -d postgres

# Wait for healthy
while ! docker exec postgres pg_isready -U postgres; do
  sleep 1
done
```

2. **Wrong credentials**:
```bash
# Verify credentials in .env
cat .env | grep DB_

# Update if needed
docker-compose down
docker-compose up -d
```

3. **Database doesn't exist**:
```bash
# Create database
docker exec postgres psql -U postgres -c "CREATE DATABASE app_db;"

# Or run migrations
docker exec extraction-agent python migrate.py
```

---

### Symptom: "Table doesn't exist"

**Solution**:
```bash
# Tables are created automatically on first use
# Test extraction to create tables
curl -X POST http://localhost:8001/extract \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'

# Or manually create
docker exec postgres psql -U postgres -d app_db -c "
CREATE TABLE IF NOT EXISTS extractions (
  id SERIAL PRIMARY KEY,
  url TEXT,
  extract_type VARCHAR(50),
  data JSONB,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);"
```

---

### Symptom: Database is slow

**Solutions**:

1. **Vacuum database**:
```bash
docker exec postgres vacuumdb -U postgres -d app_db -v
```

2. **Add indexes**:
```bash
docker exec postgres psql -U postgres -d app_db -c "
CREATE INDEX IF NOT EXISTS idx_extractions_url ON extractions(url);
CREATE INDEX IF NOT EXISTS idx_extractions_created_at ON extractions(created_at);"
```

3. **Check connections**:
```bash
docker exec postgres psql -U postgres -c "
SELECT count(*) FROM pg_stat_activity;"

# Increase max connections if needed
```

---

## Ollama/LLM Issues

### Symptom: "Failed to connect to Ollama"

**Diagnosis**:
```bash
# Check if Ollama is running
docker ps | grep ollama

# Test API
curl http://localhost:11434/api/tags

# Check logs
docker logs ollama --tail=50
```

**Solutions**:

1. **Ollama not started**:
```bash
docker-compose up -d ollama

# Wait for startup (can take 1-2 minutes)
sleep 60
```

2. **Models not downloaded**:
```bash
# List models
docker exec ollama ollama list

# Download models
docker exec ollama ollama pull mistral:latest
docker exec ollama ollama pull llava:latest
```

---

### Symptom: Vision analysis fails

**Diagnosis**:
```bash
# Check if vision model is available
docker exec ollama ollama list | grep llava

# Test vision endpoint
curl -X POST http://localhost:8002/models
```

**Solutions**:

1. **Install vision model**:
```bash
docker exec ollama ollama pull llava:latest

# Verify
docker exec ollama ollama list
```

2. **Insufficient memory**:
```bash
# Vision models need 8GB+ RAM
# Check available memory
free -h

# Restart Ollama with more memory
docker-compose down
# Edit docker-compose.yml to increase mem_limit
docker-compose up -d
```

---

### Symptom: LLM inference is very slow

**Solutions**:

1. **Use GPU acceleration**:
```yaml
# In docker-compose.yml
ollama:
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
```

2. **Use smaller models**:
```bash
# Remove large models
docker exec ollama ollama rm qwen:14b

# Use smaller alternatives
docker exec ollama ollama pull mistral:7b
```

3. **Reduce concurrent requests**:
- Limit vision-agent replicas to 1-2
- Implement request queue

---

## Network and Connectivity

### Symptom: Services can't reach each other

**Diagnosis**:
```bash
# Check network
docker network ls
docker network inspect mvp-network

# Test connectivity
docker exec extraction-agent ping postgres
docker exec extraction-agent curl http://html-parser:5000/health
```

**Solutions**:

1. **Not on same network**:
```bash
# Recreate network
docker network rm mvp-network
docker network create mvp-network

# Restart services
docker-compose down
docker-compose up -d
```

2. **Using wrong hostname**:
```bash
# Use service name from docker-compose.yml
# ✅ Correct: http://html-parser:5000
# ❌ Wrong: http://localhost:5000
```

---

### Symptom: Can't access services from host

**Solutions**:

1. **Check port mapping**:
```bash
# View port mappings
docker-compose ps

# Or
docker ps --format "table {{.Names}}\t{{.Ports}}"
```

2. **Firewall blocking**:
```bash
# Allow ports
sudo ufw allow 8000
sudo ufw allow 5678
sudo ufw status
```

3. **Binding to wrong interface**:
```yaml
# In docker-compose.yml, ensure:
ports:
  - "8000:8000"  # ✅ Correct
  # - "127.0.0.1:8000:8000"  # ❌ Only localhost
```

---

## Docker and Container Issues

### Symptom: "No space left on device"

**Diagnosis**:
```bash
# Check disk usage
df -h

# Check Docker disk usage
docker system df
```

**Solutions**:

1. **Clean up Docker**:
```bash
# Remove unused containers
docker container prune -f

# Remove unused images
docker image prune -a -f

# Remove unused volumes
docker volume prune -f

# Clean everything
docker system prune -a --volumes -f
```

2. **Free up space**:
```bash
# Remove old Ollama models
docker exec ollama ollama list
docker exec ollama ollama rm old-model:tag

# Clear logs
sudo truncate -s 0 /var/lib/docker/containers/*/*-json.log
```

---

### Symptom: Build failures

**Common Issues**:

1. **Network timeout during build**:
```bash
# Increase timeout
DOCKER_BUILDKIT=0 docker-compose build --no-cache

# Or use mirror
docker-compose build --build-arg PIP_INDEX_URL=https://pypi.org/simple
```

2. **Cache issues**:
```bash
# Force clean build
docker-compose build --no-cache <service-name>
```

3. **Missing dependencies**:
```bash
# Check requirements.txt
cat services/<service>/requirements.txt

# Update if needed
docker-compose build <service-name>
```

---

### Symptom: Container logs show errors

**Diagnosis**:
```bash
# View logs
docker logs <container-name>

# Follow logs
docker logs -f <container-name>

# Last 100 lines
docker logs --tail=100 <container-name>

# Logs with timestamps
docker logs -t <container-name>
```

**Common Errors**:

```bash
# "ModuleNotFoundError"
# Solution: Rebuild image
docker-compose build --no-cache <service>

# "Permission denied"
# Solution: Check file permissions
chmod +x scripts/*.py

# "Address already in use"
# Solution: Change port or kill process
```

---

## Performance Problems

### Symptom: Slow response times

**Diagnosis**:
```bash
# Check resource usage
docker stats

# Check service response times
python scripts/service_tracker.py --detailed

# Test individual endpoints
time curl http://localhost:8000/api/extract -d '{"url":"https://example.com"}'
```

**Solutions**:

1. **Insufficient resources**:
```bash
# Increase container limits
# In docker-compose.yml:
services:
  service-name:
    mem_limit: 2g
    cpus: 2
```

2. **Database optimization**:
```bash
# Add indexes
# Vacuum regularly
# Use connection pooling
```

3. **Cache responses**:
```python
# Add Redis for caching
# Cache extracted data
# Cache LLM responses
```

---

### Symptom: High memory usage

**Solutions**:

1. **Limit Ollama models**:
```bash
# Only keep necessary models
docker exec ollama ollama list
docker exec ollama ollama rm unused-model
```

2. **Configure memory limits**:
```yaml
services:
  ollama:
    mem_limit: 8g
  extraction-agent:
    mem_limit: 1g
```

3. **Monitor and restart**:
```bash
# Auto-restart on OOM
services:
  service-name:
    restart: unless-stopped
```

---

## Coolify Deployment Issues

### Symptom: Deployment fails in Coolify

**Common Issues**:

1. **Invalid YAML**:
```bash
# Validate locally
docker-compose -f coolify-manifest.yaml config

# Fix syntax errors
# Ensure proper indentation
```

2. **Missing environment variables**:
- Go to Coolify → Resource → Environment Variables
- Add all variables from `config/.env.example`
- Click "Deploy"

3. **Build timeout**:
- Increase build timeout in Coolify settings
- Or use pre-built images

---

### Symptom: Services not starting in Coolify

**Solutions**:

1. **Check logs in Coolify**:
- Go to Resource → Logs
- View deployment logs
- Check application logs

2. **Verify dependencies**:
- Deploy in correct order
- Wait for each service to be healthy

3. **Network issues**:
- Ensure all services on same network
- Check internal URLs use service names

---

### Symptom: Can't access deployed services

**Solutions**:

1. **Configure domains**:
- Coolify → Resource → Domains
- Add domain/subdomain
- Wait for SSL certificate

2. **Check proxy settings**:
- Ensure Coolify proxy is running
- Verify port mappings

3. **Firewall rules**:
- Open required ports on server
- Check cloud provider security groups

---

## Common Error Messages

### "Connection refused"

**Cause**: Service not running or wrong port

**Solution**:
```bash
# Check if service is running
docker ps | grep <service>

# Verify port
docker-compose ps

# Restart service
docker-compose restart <service>
```

---

### "Request timeout"

**Cause**: Service overloaded or stuck

**Solution**:
```bash
# Increase timeout
# In client code:
requests.post(url, timeout=120)

# Check service logs
docker logs <service>

# Restart if stuck
docker-compose restart <service>
```

---

### "Out of memory"

**Cause**: Insufficient RAM

**Solution**:
```bash
# Check memory
free -h
docker stats

# Increase limits
# Or reduce model sizes
```

---

### "Module not found"

**Cause**: Missing Python package

**Solution**:
```bash
# Rebuild image
docker-compose build --no-cache <service>

# Or install manually
docker exec <container> pip install <package>
```

---

### "Database connection pool exhausted"

**Cause**: Too many concurrent connections

**Solution**:
```sql
-- Increase max connections
ALTER SYSTEM SET max_connections = 200;

-- Restart postgres
docker-compose restart postgres
```

---

## Getting Help

### 1. Gather Information

```bash
# System info
uname -a
docker --version
docker-compose --version

# Service status
python scripts/service_tracker.py --detailed --export debug.json

# Logs
docker-compose logs > all-logs.txt
```

### 2. Check Documentation

- [DEPLOYMENT.md](/DEPLOYMENT.md)
- [SERVICES.md](SERVICES.md)
- [API_ENDPOINTS.md](API_ENDPOINTS.md)

### 3. Debug Checklist

- [ ] All services running: `docker ps`
- [ ] Logs checked: `docker-compose logs`
- [ ] Health endpoints tested
- [ ] Environment variables set
- [ ] Disk space available
- [ ] Ports not conflicting
- [ ] Network connectivity working
- [ ] Dependencies deployed first

---

## Prevention

### Regular Maintenance

```bash
# Weekly
docker system prune -f
python scripts/service_tracker.py --detailed

# Monthly
docker image prune -a -f
docker exec postgres vacuumdb -U postgres -d app_db

# Backup
docker exec postgres pg_dump -U postgres app_db > backup.sql
```

### Monitoring

```bash
# Continuous monitoring
python scripts/service_tracker.py --watch --interval 30

# Resource monitoring
docker stats

# Log monitoring
docker-compose logs -f | grep ERROR
```

### Best Practices

1. **Always check health before requests**
2. **Use appropriate timeouts**
3. **Handle errors gracefully**
4. **Monitor resource usage**
5. **Keep logs manageable**
6. **Regular backups**
7. **Test in staging first**
8. **Document custom changes**
