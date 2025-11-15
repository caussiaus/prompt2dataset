#!/bin/bash
set -e

# Standard Docker/Coolify prep (as you already have)
sudo apt update && sudo apt install -y docker docker-compose git
sudo systemctl start docker && sudo systemctl enable docker

# Make all persistent data folders (as before)
mkdir -p /data/n8n /data/agent-gateway /data/discovery-agent /data/extraction-agent /data/vision-agent /data/validation-agent /data/schema-agent /data/orchestrator-agent /data/mongodb /data/postgres /data/qdrant /data/dragonfly /data/searxng /data/camoufox /data/ollama /data/hf-text-gen
sudo chown -R 1000:1000 /data && sudo chmod -R 755 /data

# ------> Download/install extra Python or Node dependencies from GitHub <------
# Example: pip install directly from GitHub
pip install "git+https://github.com/someuser/somepackage.git@main"

# Example: clone a utility repo for data/tools (change URL as needed)
git clone https://github.com/user/another-tool.git /opt/another-tool

# Optionally run a setup from the cloned repo
if [ -f /opt/another-tool/setup.sh ]; then
  bash /opt/another-tool/setup.sh
fi

echo "NVME agent storage and dependencies ready!"
