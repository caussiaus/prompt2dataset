#!/bin/bash
sudo apt update && sudo apt install -y docker docker-compose
sudo systemctl start docker && sudo systemctl enable docker
mkdir -p /data/n8n /data/agent-gateway /data/discovery-agent /data/extraction-agent /data/vision-agent /data/validation-agent /data/schema-agent /data/orchestrator-agent /data/mongodb /data/postgres /data/qdrant /data/dragonfly /data/searxng /data/camoufox /data/ollama /data/hf-text-gen
sudo chown -R 1000:1000 /data && sudo chmod -R 755 /data
echo "NVME agent storage ready!"