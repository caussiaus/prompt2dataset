# Deployment Guide

## Coolify Deployment

### Step 1: Prepare Your Server

Ensure your server meets the requirements:
- Ubuntu 20.04+ or Debian 11+
- 16GB+ RAM (8GB minimum)
- 50GB+ storage
- Docker installed
- (Optional) NVIDIA GPU with drivers

### Step 2: Install Coolify

If not already installed:

```bash
curl -fsSL https://get.coolify.io | bash
```

Access Coolify UI at: `http://your-server-ip:8000`

### Step 3: Add Repository

1. Navigate to Coolify dashboard
2. Click "Add Resource" → "Docker Compose"
3. Select "Git Repository"
4. Enter repository URL
5. Set branch (e.g., `main`)

### Step 4: Configure Environment

In Coolify, navigate to the resource and add environment variables:

```
MONGO_ROOT_USERNAME=admin
MONGO_ROOT_PASSWORD=your_secure_password_here
VISION_MODEL=llava
LLM_MODEL=llama3.1
EMBEDDING_MODEL=bge-m3
CODE_MODEL=deepseek-coder
RAG_MODEL=llama3-chatqa
DEBUG=false
```

### Step 5: Configure Domains (Optional)

Set up custom domains in Coolify:
- Gateway: `api.yourdomain.com` → Port 8000
- Enable SSL/HTTPS automatically

### Step 6: Deploy

1. Click "Deploy"
2. Coolify will:
   - Pull the repository
   - Build Docker images
   - Start all services
   - Configure networking

3. Monitor deployment logs in real-time

### Step 7: Post-Deployment

After successful deployment:

```bash
# Download recommended AI models
curl -X POST https://api.yourdomain.com/models/download/recommended

# Verify all services
curl https://api.yourdomain.com/health
```

## Manual VPS Deployment

### Prerequisites

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Install Docker Compose
sudo apt install docker-compose-plugin -y

# (Optional) Install NVIDIA Docker for GPU
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list
sudo apt update && sudo apt install -y nvidia-docker2
sudo systemctl restart docker
```

### Deployment Steps

```bash
# Clone repository
git clone <your-repo-url>
cd <repo-name>

# Create .env file
cp .env.example .env
nano .env  # Edit with your settings

# Run setup
sudo bash setup.sh

# Verify deployment
curl http://localhost:8000/health
```

### Configure Reverse Proxy (Nginx)

```bash
# Install Nginx
sudo apt install nginx -y

# Create configuration
sudo nano /etc/nginx/sites-available/webscraper
```

Add configuration:

```nginx
server {
    listen 80;
    server_name api.yourdomain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Timeouts for long-running requests
        proxy_connect_timeout 300;
        proxy_send_timeout 300;
        proxy_read_timeout 300;
    }
}
```

Enable site and SSL:

```bash
# Enable site
sudo ln -s /etc/nginx/sites-available/webscraper /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# Install Certbot for SSL
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d api.yourdomain.com
```

## Kubernetes Deployment

### Prerequisites

- Kubernetes cluster (v1.24+)
- kubectl configured
- Helm installed
- Storage class for persistent volumes
- (Optional) GPU node pools

### Deployment

```bash
# Create namespace
kubectl create namespace webscraper

# Create secrets
kubectl create secret generic webscraper-secrets \
  --from-literal=mongodb-password=your_password \
  -n webscraper

# Apply configurations
kubectl apply -f k8s/ -n webscraper

# Verify deployment
kubectl get pods -n webscraper
kubectl get svc -n webscraper
```

### Horizontal Scaling

```yaml
# Scale agents
kubectl scale deployment extraction-agent --replicas=3 -n webscraper
kubectl scale deployment vision-agent --replicas=2 -n webscraper
```

## AWS Deployment

### Using ECS (Elastic Container Service)

1. **Create ECR repositories** for each service
2. **Build and push images**:

```bash
# Login to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account-id>.dkr.ecr.us-east-1.amazonaws.com

# Build and push
docker-compose build
docker tag webscraper-gateway:latest <account-id>.dkr.ecr.us-east-1.amazonaws.com/webscraper-gateway:latest
docker push <account-id>.dkr.ecr.us-east-1.amazonaws.com/webscraper-gateway:latest
```

3. **Create ECS cluster** with Fargate or EC2 instances
4. **Create task definitions** for each service
5. **Create services** with load balancers
6. **Configure auto-scaling**

## GCP Deployment

### Using Cloud Run

```bash
# Build and push to GCR
gcloud builds submit --tag gcr.io/PROJECT-ID/webscraper-gateway

# Deploy services
gcloud run deploy webscraper-gateway \
  --image gcr.io/PROJECT-ID/webscraper-gateway \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --set-env-vars OLLAMA_HOST=http://ollama-service:11434
```

## Azure Deployment

### Using Container Instances

```bash
# Create resource group
az group create --name webscraper-rg --location eastus

# Create container group
az container create \
  --resource-group webscraper-rg \
  --file docker-compose.yml \
  --dns-name-label webscraper-api
```

## Environment-Specific Configurations

### Development

```yaml
# docker-compose.dev.yml
version: '3.8'
services:
  gateway:
    environment:
      - DEBUG=true
      - LOG_LEVEL=DEBUG
    volumes:
      - ./:/app
    command: uvicorn agent_gateway:app --reload --host 0.0.0.0
```

```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up
```

### Staging

```yaml
# docker-compose.staging.yml
version: '3.8'
services:
  gateway:
    environment:
      - DEBUG=false
      - MAX_CONCURRENT_REQUESTS=5
```

### Production

```yaml
# docker-compose.prod.yml
version: '3.8'
services:
  gateway:
    environment:
      - DEBUG=false
      - MAX_CONCURRENT_REQUESTS=20
    deploy:
      replicas: 3
      resources:
        limits:
          cpus: '2'
          memory: 4G
```

## Monitoring Setup

### Prometheus + Grafana

```yaml
# Add to docker-compose.yml
services:
  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus
    ports:
      - "9090:9090"

  grafana:
    image: grafana/grafana:latest
    volumes:
      - grafana_data:/var/lib/grafana
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
```

### Log Aggregation (ELK Stack)

```yaml
services:
  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.11.0
    environment:
      - discovery.type=single-node
    ports:
      - "9200:9200"

  logstash:
    image: docker.elastic.co/logstash/logstash:8.11.0
    volumes:
      - ./logstash.conf:/usr/share/logstash/pipeline/logstash.conf

  kibana:
    image: docker.elastic.co/kibana/kibana:8.11.0
    ports:
      - "5601:5601"
```

## Backup and Recovery

### Database Backup

```bash
# MongoDB backup
docker exec webscraper-mongodb mongodump --out /backup

# Copy from container
docker cp webscraper-mongodb:/backup ./backup-$(date +%Y%m%d)

# Automate with cron
0 2 * * * docker exec webscraper-mongodb mongodump --out /backup && docker cp webscraper-mongodb:/backup /path/to/backups/backup-$(date +\%Y\%m\%d)
```

### Model Backup

```bash
# Backup Ollama models
docker cp webscraper-ollama:/root/.ollama ./ollama-backup
```

### Restore

```bash
# Restore MongoDB
docker cp ./backup-20240101 webscraper-mongodb:/backup
docker exec webscraper-mongodb mongorestore /backup

# Restore Ollama models
docker cp ./ollama-backup webscraper-ollama:/root/.ollama
docker restart webscraper-ollama
```

## Security Hardening

### 1. Network Isolation

```yaml
# Use internal networks
networks:
  frontend:
    driver: bridge
  backend:
    driver: bridge
    internal: true
```

### 2. Secrets Management

Use Docker secrets or external secret managers:

```yaml
secrets:
  mongodb_password:
    external: true

services:
  mongodb:
    secrets:
      - mongodb_password
```

### 3. Resource Limits

```yaml
services:
  gateway:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 512M
```

### 4. Security Scanning

```bash
# Scan images
docker scan webscraper-gateway:latest

# Use Trivy
trivy image webscraper-gateway:latest
```

## Troubleshooting Deployment Issues

### Issue: Services won't start

```bash
# Check logs
docker-compose logs

# Check resource usage
docker stats

# Verify network
docker network ls
docker network inspect scraper-network
```

### Issue: Out of memory

```bash
# Increase Docker memory
# Edit /etc/docker/daemon.json
{
  "default-ulimits": {
    "memlock": {
      "Soft": -1,
      "Hard": -1
    }
  }
}

sudo systemctl restart docker
```

### Issue: GPU not available

```bash
# Verify GPU runtime
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi

# Check docker daemon configuration
cat /etc/docker/daemon.json
# Should include:
{
  "runtimes": {
    "nvidia": {
      "path": "nvidia-container-runtime"
    }
  }
}
```

## Performance Optimization

### 1. Enable Caching

```yaml
services:
  gateway:
    environment:
      - CACHE_ENABLED=true
      - CACHE_TTL=3600
```

### 2. Optimize Ollama

```yaml
services:
  ollama:
    environment:
      - OLLAMA_NUM_PARALLEL=4
      - OLLAMA_MAX_LOADED_MODELS=2
```

### 3. Database Indexing

```javascript
// MongoDB indexes
db.results.createIndex({ task_id: 1 })
db.results.createIndex({ timestamp: -1 })
db.results.createIndex({ url: 1 })
```

### 4. Connection Pooling

```python
# In config.py
MONGODB_MAX_POOL_SIZE=50
MONGODB_MIN_POOL_SIZE=10
```

---

For additional support, refer to the main README.md or open an issue on GitHub.
