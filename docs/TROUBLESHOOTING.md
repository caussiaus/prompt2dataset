# Troubleshooting Guide

Common issues and solutions for prompt2dataset deployment and operation.

## Table of Contents

- [Deployment Issues](#deployment-issues)
- [Service Health Issues](#service-health-issues)
- [Database Issues](#database-issues)
- [LLM/Ollama Issues](#llmollama-issues)
- [Network Issues](#network-issues)
- [Performance Issues](#performance-issues)
- [Data Issues](#data-issues)

---

## Deployment Issues

### Docker Compose Fails to Start

**Symptom**: `docker-compose up` fails with errors

**Solutions**:

1. **Check Docker is running**:
```bash
docker info
# If error, start Docker daemon
sudo systemctl start docker
```

2. **Check ports are available**:
```bash
# Check if ports are in use
sudo lsof -i :5432  # PostgreSQL
sudo lsof -i :8000  # Gateway
# Kill conflicting processes or change ports
```

3. **Validate docker-compose.yml**:
```bash
docker-compose -f docker-compose.local.yml config
# Fix any syntax errors
```

4. **Check disk space**:
```bash
df -h
# Need at least 50GB free
```

5. **Pull images manually**:
```bash
docker pull pgvector/pgvector:pg16
docker pull ollama/ollama:latest
# etc.
```

---

### Coolify Import Fails

**Symptom**: Can't import coolify-manifest.yaml

**Solutions**:

1. **Validate YAML syntax**:
```bash
# Install yamllint
pip install yamllint

# Validate
yamllint coolify-manifest.yaml
```

2. **Check Coolify version**:
- Ensure Coolify v4+
- Update Coolify if needed

3. **Manual service creation**:
- Create services one by one in Coolify UI
- Copy settings from manifest

---

### Service Won't Build

**Symptom**: Docker build fails for custom services

**Solutions**:

1. **Check Dockerfile syntax**:
```bash
docker build -t test-build services/extraction-agent/
# Review error messages
```

2. **Check requirements.txt**:
```bash
# Test requirements locally
pip install -r services/extraction-agent/requirements.txt
```

3. **Clear build cache**:
```bash
docker-compose -f docker-compose.local.yml build --no-cache
```

4. **Check base image availability**:
```bash
docker pull python:3.11-slim
```

---

## Service Health Issues

### Service Shows "Unhealthy"

**Symptom**: `service_tracker.py` shows services as unhealthy

**Solutions**:

1. **Check service logs**:
```bash
docker logs <container-name>
# Look for errors
```

2. **Manual health check**:
```bash
curl -v http://localhost:8001/health
# Check response
```

3. **Check dependencies**:
```bash
# If extraction-agent is unhealthy
# Check PostgreSQL
curl http://localhost:5432
# Check Ollama
curl http://localhost:11434/api/tags
# Check HTML Parser
curl http://localhost:5000/health
```

4. **Restart service**:
```bash
docker-compose -f docker-compose.local.yml restart extraction-agent
```

---

### Service Keeps Restarting

**Symptom**: Container constantly restarts

**Solutions**:

1. **Check logs for crash reason**:
```bash
docker logs <container-name> --tail 100
```

2. **Common causes**:

   **Out of Memory**:
   ```bash
   # Check container stats
   docker stats
   # Increase memory limit in docker-compose.yml
   ```

   **Missing Environment Variables**:
   ```bash
   # Check env vars
   docker inspect <container-name> | grep -A 20 Env
   # Add missing vars to .env
   ```

   **Port Conflict**:
   ```bash
   # Check port usage
   sudo lsof -i :<port>
   ```

3. **Disable health check temporarily**:
```yaml
# In docker-compose.yml
healthcheck:
  disable: true
```

---

### Gateway Can't Reach Agents

**Symptom**: Gateway health check shows agents as unavailable

**Solutions**:

1. **Check Docker network**:
```bash
docker network inspect mvp-network
# Verify all services are connected
```

2. **Test inter-service communication**:
```bash
# From gateway container
docker exec <gateway-container> curl http://extraction-agent:8001/health
```

3. **Check service names in docker-compose**:
```yaml
# Must match environment variables
EXTRACTION_AGENT_URL: http://extraction-agent:8001
```

4. **Restart network**:
```bash
docker-compose -f docker-compose.local.yml down
docker network prune
docker-compose -f docker-compose.local.yml up -d
```

---

## Database Issues

### Can't Connect to PostgreSQL

**Symptom**: "Connection refused" or "Could not connect to server"

**Solutions**:

1. **Check PostgreSQL is running**:
```bash
docker ps | grep postgres
```

2. **Check PostgreSQL logs**:
```bash
docker logs <postgres-container>
```

3. **Test connection**:
```bash
docker exec <postgres-container> pg_isready -U postgres
```

4. **Check credentials**:
```bash
# Verify DB_PASSWORD in .env matches
docker exec <postgres-container> psql -U postgres -c "SELECT 1"
```

5. **Check port mapping**:
```bash
docker port <postgres-container>
# Should show 5432->5432
```

---

### Database Out of Space

**Symptom**: "No space left on device"

**Solutions**:

1. **Check database size**:
```bash
docker exec <postgres-container> psql -U postgres -d app_db -c "
  SELECT pg_size_pretty(pg_database_size('app_db'));
"
```

2. **Check table sizes**:
```bash
docker exec <postgres-container> psql -U postgres -d app_db -c "
  SELECT relname, pg_size_pretty(pg_total_relation_size(relid))
  FROM pg_stat_user_tables
  ORDER BY pg_total_relation_size(relid) DESC;
"
```

3. **Clean old data**:
```sql
-- Delete old extractions
DELETE FROM extractions WHERE extracted_at < NOW() - INTERVAL '30 days';

-- Vacuum to reclaim space
VACUUM FULL;
```

4. **Increase volume size** (if using volumes)

---

### pgvector Extension Error

**Symptom**: "extension 'vector' does not exist"

**Solutions**:

1. **Create extension**:
```bash
docker exec <postgres-container> psql -U postgres -d app_db -c "
  CREATE EXTENSION IF NOT EXISTS vector;
"
```

2. **Check PostgreSQL image**:
```bash
# Must use pgvector/pgvector image
docker inspect <postgres-container> | grep Image
```

---

## LLM/Ollama Issues

### Ollama Models Not Loading

**Symptom**: "Model not found" errors

**Solutions**:

1. **List available models**:
```bash
docker exec <ollama-container> ollama list
```

2. **Pull required models**:
```bash
docker exec <ollama-container> ollama pull mistral:latest
docker exec <ollama-container> ollama pull llava:latest
```

3. **Check disk space** (models are large):
```bash
docker exec <ollama-container> df -h /root/.ollama
```

4. **Check model download progress**:
```bash
docker logs <ollama-container> -f
```

---

### LLM Responses Too Slow

**Symptom**: Extraction/vision tasks timeout

**Solutions**:

1. **Use smaller models**:
```bash
# Instead of mistral:latest (7B)
docker exec <ollama-container> ollama pull mistral:7b-instruct-q4_0
```

2. **Increase timeout**:
```python
# In agent code
response = requests.post(url, json=data, timeout=120)  # Increase from 60
```

3. **Enable GPU** (if available):
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

4. **Reduce context size**:
```python
# Limit text sent to LLM
text = text[:4000]  # Reduce from larger size
```

---

### Out of Memory (OOM) with LLM

**Symptom**: Ollama container keeps restarting

**Solutions**:

1. **Check memory usage**:
```bash
docker stats <ollama-container>
```

2. **Use quantized models** (smaller memory footprint):
```bash
# Q4 quantization (4-bit)
docker exec <ollama-container> ollama pull mistral:7b-q4_0

# Q8 quantization (8-bit)
docker exec <ollama-container> ollama pull mistral:7b-q8_0
```

3. **Increase container memory limit**:
```yaml
# In docker-compose.yml
ollama:
  mem_limit: 8g  # Increase from default
```

4. **Unload unused models**:
```bash
docker exec <ollama-container> ollama rm <unused-model>
```

---

## Network Issues

### Services Can't Communicate

**Symptom**: "Connection refused" between services

**Solutions**:

1. **Check all services on same network**:
```bash
docker network inspect mvp-network
```

2. **Test DNS resolution**:
```bash
docker exec <container> ping extraction-agent
```

3. **Check service names match**:
```bash
# In docker-compose.yml
services:
  extraction-agent:  # This is the hostname
    # ...
```

4. **Recreate network**:
```bash
docker-compose -f docker-compose.local.yml down
docker network rm mvp-network
docker-compose -f docker-compose.local.yml up -d
```

---

### Can't Access Services from Host

**Symptom**: `curl http://localhost:8000` fails

**Solutions**:

1. **Check port mappings**:
```bash
docker ps
# Look for "0.0.0.0:8000->8000/tcp"
```

2. **Check firewall**:
```bash
# Ubuntu/Debian
sudo ufw status
sudo ufw allow 8000

# CentOS/RHEL
sudo firewall-cmd --list-ports
sudo firewall-cmd --add-port=8000/tcp --permanent
```

3. **Check service binding**:
```python
# In Flask app, must bind to 0.0.0.0
app.run(host='0.0.0.0', port=8000)
```

---

### Coolify SSL Issues

**Symptom**: SSL certificate errors

**Solutions**:

1. **Check domain DNS**:
```bash
nslookup api.yourdomain.com
# Should point to your server IP
```

2. **Regenerate certificate**:
- In Coolify: Service → Domains → Regenerate SSL

3. **Check Let's Encrypt rate limits**:
- Max 50 certificates per domain per week
- Use staging first

4. **Manual certificate**:
- Upload your own SSL certificate in Coolify

---

## Performance Issues

### Slow Response Times

**Symptom**: API requests take too long

**Solutions**:

1. **Check service logs for bottlenecks**:
```bash
docker logs <service-container> --tail 100
```

2. **Profile database queries**:
```sql
-- Enable query logging
ALTER SYSTEM SET log_min_duration_statement = 1000;  -- Log queries > 1s
SELECT pg_reload_conf();

-- View slow queries
SELECT * FROM pg_stat_statements ORDER BY total_time DESC LIMIT 10;
```

3. **Add database indexes**:
```sql
CREATE INDEX idx_extractions_url ON extractions(url);
CREATE INDEX idx_extractions_extracted_at ON extractions(extracted_at);
```

4. **Scale agents horizontally**:
```yaml
# In Coolify or docker-compose
extraction-agent:
  deploy:
    replicas: 3
```

5. **Optimize LLM context**:
```python
# Send less text to LLM
text = extract_relevant_sections(full_text)
```

---

### High Memory Usage

**Symptom**: Server running out of memory

**Solutions**:

1. **Identify memory hogs**:
```bash
docker stats --no-stream
```

2. **Set memory limits**:
```yaml
# In docker-compose.yml
services:
  extraction-agent:
    mem_limit: 1g
    mem_reservation: 512m
```

3. **Use swap** (if available)

4. **Scale down non-essential services**

---

### High CPU Usage

**Symptom**: CPU at 100%

**Solutions**:

1. **Identify CPU-intensive services**:
```bash
docker stats --no-stream
```

2. **Limit CPU usage**:
```yaml
# In docker-compose.yml
services:
  vision-agent:
    cpus: '2'
```

3. **Optimize vision processing**:
- Reduce image resolution
- Use smaller vision models
- Batch process images

---

## Data Issues

### Extracted Data Incomplete

**Symptom**: Missing fields in extraction results

**Solutions**:

1. **Check schema definition**:
```python
# Schema must match expected data
schema = {
    "title": "string",
    "price": "number",  # Not "float" or "decimal"
    "description": "string"
}
```

2. **Improve LLM prompt**:
```python
prompt = f"""
Extract the following from the text:
- title: Product title (string)
- price: Numeric price value (number, no currency symbols)
- description: Full product description (string)

Return ONLY valid JSON.

Text:
{text}
"""
```

3. **Increase LLM context**:
```python
# Send more text if truncated
text = full_text[:8000]  # Instead of 4000
```

4. **Try different model**:
```bash
docker exec <ollama-container> ollama pull llama2:13b
# Use larger model for better extraction
```

---

### Duplicate Data

**Symptom**: Same URLs processed multiple times

**Solutions**:

1. **Add unique constraints**:
```sql
CREATE UNIQUE INDEX idx_extractions_url_unique 
ON extractions(url, extracted_at::date);
```

2. **Check before inserting**:
```python
# In agent code
existing = db.query("SELECT * FROM extractions WHERE url = %s", (url,))
if existing:
    return existing
```

3. **Use idempotency keys**

---

### Vision Analysis Fails

**Symptom**: Image analysis returns errors

**Solutions**:

1. **Check image format**:
```python
# Supported: JPEG, PNG, GIF, WebP
# Convert if needed
```

2. **Check image size**:
```python
# Resize large images
from PIL import Image
img = Image.open(image_path)
img.thumbnail((1024, 1024))
```

3. **Check base64 encoding**:
```python
import base64
with open(image_path, 'rb') as f:
    image_data = base64.b64encode(f.read()).decode('utf-8')
```

4. **Use correct vision model**:
```bash
docker exec <ollama-container> ollama pull llava:latest
# Ensure vision model is loaded
```

---

## Getting Help

### Logs to Collect

When asking for help, provide:

1. **Service logs**:
```bash
docker logs <container-name> > service.log
```

2. **System info**:
```bash
docker info > docker-info.txt
docker version > docker-version.txt
uname -a > system-info.txt
```

3. **Configuration**:
```bash
docker-compose -f docker-compose.local.yml config > compose-config.yml
# Sanitize passwords before sharing
```

4. **Health status**:
```bash
python3 scripts/service_tracker.py --json > health-status.json
```

### Debug Mode

Enable debug logging:

```bash
# In .env
LOG_LEVEL=DEBUG

# Restart services
docker-compose -f docker-compose.local.yml restart
```

### Support Channels

- **GitHub Issues**: https://github.com/yourusername/prompt2dataset/issues
- **Documentation**: Check docs/ directory
- **Discussions**: https://github.com/yourusername/prompt2dataset/discussions

---

## Prevention

### Best Practices

1. **Always test locally first**
2. **Monitor service health regularly**
3. **Set up automated backups**
4. **Keep services updated**
5. **Use meaningful logging**
6. **Document custom changes**
7. **Test error handling**
8. **Monitor resource usage**
9. **Use version control**
10. **Have rollback plan**

### Monitoring Setup

```bash
# Automated health checks
crontab -e
# Add:
*/5 * * * * /usr/bin/python3 /path/to/scripts/service_tracker.py --json >> /var/log/health.log
```

### Backup Setup

```bash
# Automated backups
crontab -e
# Add:
0 2 * * * /usr/local/bin/backup-prompt2dataset.sh
```

---

**Still having issues?** Open an issue with:
- Clear problem description
- Steps to reproduce
- Logs and error messages
- System information
- What you've already tried
