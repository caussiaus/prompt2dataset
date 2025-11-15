#!/bin/bash
set -e

echo "╔═══════════════════════════════════════════════════════════╗"
echo "║   Creating MVP Branch for Coolify Deployment             ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# Check if we're in a git repo
if [ ! -d .git ]; then
    echo "❌ Not a git repository. Run 'git init' first."
    exit 1
fi

# Save current branch
CURRENT_BRANCH=$(git branch --show-current)
echo "📍 Current branch: $CURRENT_BRANCH"
echo ""

# Create MVP branch
echo "🌿 Creating MVP branch..."
git checkout -b mvp || git checkout mvp

echo ""
echo "📝 Setting up MVP branch files..."

# Copy MVP-specific .env example
cp .env.mvp.example .env.example

# Create simple README for MVP
cat > README.md << 'EOF'
# AI Web Scraper - MVP Branch

**Quick deployment branch for testing and prototyping.**

## 🚀 Quick Deploy on Coolify

### Step 1: Add to Coolify
- Repository: This repo
- Branch: `mvp`
- Build Pack: Docker Compose
- Compose File: `docker-compose.mvp.yml`

### Step 2: Set Environment
In Coolify, add only:
```
MONGO_PASSWORD=<run: openssl rand -base64 32>
```

### Step 3: Deploy
Click Deploy. Done in 10 minutes!

---

## 📚 Documentation

- **Quick Start**: See [README.MVP.md](README.MVP.md)
- **Coolify Deployment**: See [DEPLOY.COOLIFY.md](DEPLOY.COOLIFY.md)
- **Full Docs**: Switch to `main` branch

## 🎯 What's Included

MVP includes:
- ✅ All core agents (gateway, discovery, camoufox, vision, extraction)
- ✅ Ollama (AI models)
- ✅ MongoDB (data storage)
- ✅ n8n (workflows)
- ✅ Minimal models (~12GB): llama3.1, llava, bge-m3

**Perfect for testing with Zie619's n8n workflows!**

---

## 🔄 Upgrade to Full

When ready for production:
```bash
git checkout main
# Use docker-compose.yml instead
```

---

## 🎊 Your Server

This MVP is optimized for your setup:
- ✅ 32GB RAM
- ✅ 1.9TB NVMe
- ✅ RTX 4090 (GPU support)
- ✅ /data directory structure
- ✅ Arch Linux

**For GPU optimization, use docker-compose.4090.yml instead!**

---

**Deploy now and start scraping!** 🚀
EOF

# Add all necessary files for MVP
echo "📦 Staging MVP files..."

git add \
    README.md \
    README.MVP.md \
    DEPLOY.COOLIFY.md \
    COOLIFY_NATIVE_SETUP.md \
    COOLIFY_ONE_VARIABLE_SETUP.txt \
    .env.example \
    .env.mvp.example \
    .env.coolify.example \
    .env.coolify.minimal \
    .gitignore \
    docker-compose.mvp.yml \
    models.mvp.config \
    agent_gateway.py \
    agent_discovery.py \
    agent_camoufox.py \
    agent_vision.py \
    agent_extraction.py \
    model_manager.py \
    Dockerfile.agent-gateway \
    Dockerfile.discovery-agent \
    Dockerfile.camoufox \
    Dockerfile.vision-agent \
    Dockerfile.extraction-agent \
    Dockerfile.model-manager \
    requirements.txt \
    camoufox/ \
    n8n-workflows/ \
    2>/dev/null || true

echo ""
echo "💾 Committing MVP branch..."
git commit -m "MVP branch: Minimal deployment for Coolify

Features:
- Optimized for 8GB RAM minimum
- Minimal AI models (llama3.1, llava, bge-m3)
- docker-compose.mvp.yml with resource limits
- Works with existing /data structure
- Coolify native integration
- Ready for Zie619/n8n-workflows

Perfect for rapid prototyping and testing." || echo "⚠️  Nothing to commit (files already committed)"

echo ""
echo "✅ MVP branch created successfully!"
echo ""
echo "Next steps:"
echo "  1. Push MVP branch:"
echo "     git push origin mvp"
echo ""
echo "  2. In Coolify:"
echo "     - Add this repository"
echo "     - Select branch: mvp"
echo "     - Compose file: docker-compose.mvp.yml"
echo "     - Set MONGO_PASSWORD in environment"
echo "     - Deploy!"
echo ""
echo "  3. Access services:"
echo "     - API: https://your-app.coolify.app"
echo "     - n8n: https://n8n.your-app.coolify.app"
echo ""
echo "Returning to $CURRENT_BRANCH branch..."
git checkout "$CURRENT_BRANCH"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "MVP branch ready! Push it and deploy on Coolify! 🚀"
echo "═══════════════════════════════════════════════════════════"
