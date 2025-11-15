# MVP Branch Creation Checklist

Files to include in MVP branch:

## Core Files (Required)
- [x] README.MVP.md
- [x] DEPLOY.COOLIFY.md
- [x] docker-compose.mvp.yml
- [x] models.mvp.config
- [x] .env.mvp.example
- [x] .gitignore

## Agent Files
- [x] agent_gateway.py
- [x] agent_discovery.py
- [x] agent_camoufox.py
- [x] agent_vision.py
- [x] agent_extraction.py
- [x] model_manager.py

## Dockerfiles
- [x] Dockerfile.agent-gateway
- [x] Dockerfile.discovery-agent
- [x] Dockerfile.camoufox
- [x] Dockerfile.vision-agent
- [x] Dockerfile.extraction-agent
- [x] Dockerfile.model-manager

## Configuration
- [x] requirements.txt

## Camoufox
- [x] camoufox/ (cloned directory)

## Documentation (Minimal)
- [x] README.MVP.md (main doc)
- [x] DEPLOY.COOLIFY.md

## Optional (Can link to main)
- [ ] Full README.md (link to main branch)
- [ ] ARCHITECTURE.md (link to main branch)
- [ ] docs/ (link to main branch)

## Git Commands to Create MVP Branch

```bash
# Create and switch to MVP branch
git checkout -b mvp

# Rename MVP-specific files
cp .env.mvp.example .env.example

# Update README to point to README.MVP.md
echo "# See README.MVP.md for MVP deployment guide" > README.md
cat README.MVP.md >> README.md

# Commit MVP branch
git add .
git commit -m "MVP branch: Minimal deployment configuration for Coolify

- Optimized for 8GB RAM, 25GB disk
- Minimal AI models (llama3.1, llava, bge-m3)
- docker-compose.mvp.yml with resource limits
- Quick deployment guide for Coolify
- Integration guide for Zie619/n8n-workflows"

# Push MVP branch
git push origin mvp
```

## Coolify Configuration

Repository settings:
- Branch: `mvp`
- Compose file: `docker-compose.mvp.yml`
- Build Pack: Docker Compose

Required environment variables:
- MONGO_PASSWORD (user must set)

Optional environment variables:
- N8N_HOST (for custom domain)
- N8N_PROTOCOL (http/https)
- GATEWAY_PORT (default 8000)
- N8N_PORT (default 5678)
