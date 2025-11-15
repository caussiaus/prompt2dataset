.PHONY: help setup quick full dev start stop restart logs status test clean health models

# Colors
BLUE := \033[0;34m
GREEN := \033[0;32m
NC := \033[0m

help: ## Show this help message
	@echo "$(BLUE)AI Web Scraper Platform - Make Commands$(NC)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-15s$(NC) %s\n", $$1, $$2}'
	@echo ""

# Setup commands
setup: ## Run full setup wizard
	@bash setup.sh

quick: ## Quick start (minimal, fastest)
	@bash scripts/quick-start.sh

full: ## Full setup with all models
	@bash setup.sh full

dev: ## Development setup
	@bash setup.sh dev

preflight: ## Run pre-flight checks
	@bash scripts/preflight-check.sh

# Service management
start: ## Start all services
	@docker-compose up -d
	@echo "✓ Services started"

stop: ## Stop all services
	@docker-compose down
	@echo "✓ Services stopped"

restart: ## Restart all services
	@docker-compose restart
	@echo "✓ Services restarted"

down: ## Stop and remove all containers
	@docker-compose down -v
	@echo "✓ All containers removed"

# Monitoring
logs: ## View all logs (follow)
	@docker-compose logs -f

logs-gateway: ## View gateway logs
	@docker-compose logs -f agent-gateway

logs-ollama: ## View Ollama logs
	@docker-compose logs -f ollama

logs-models: ## View model download logs
	@docker-compose logs -f model-manager

status: ## Show service status
	@docker-compose ps

health: ## Check service health
	@bash scripts/test-deployment.sh

# Testing
test: ## Run deployment tests
	@bash scripts/test-deployment.sh

test-scrape: ## Test a simple scrape
	@echo "Testing scrape of example.com..."
	@curl -s -X POST http://localhost:8000/scrape \
		-H "Content-Type: application/json" \
		-d '{"url":"https://example.com","strategy":"full","use_vision":false}' | jq .

test-health: ## Test all health endpoints
	@curl -s http://localhost:8000/health | jq .
	@curl -s http://localhost:8001/health | jq .
	@curl -s http://localhost:8002/health | jq .
	@curl -s http://localhost:8003/health | jq .
	@curl -s http://localhost:8004/health | jq .

# Models
models-list: ## List installed AI models
	@curl -s http://localhost:11434/api/tags | jq -r '.models[] | "\(.name) (\(.size / 1e9 | floor)GB)"'

models-download: ## Download all configured models
	@docker-compose up model-manager

models-config: ## Edit models configuration
	@${EDITOR:-nano} models.config

# Data management
backup: ## Backup all data
	@mkdir -p backups
	@docker exec webscraper-mongodb mongodump --out=/tmp/backup
	@docker cp webscraper-mongodb:/tmp/backup ./backups/mongodb-$(shell date +%Y%m%d-%H%M%S)
	@echo "✓ Backup created in backups/"

restore: ## Restore from latest backup
	@LATEST=$$(ls -t backups/mongodb-* | head -1); \
	docker cp $$LATEST webscraper-mongodb:/tmp/restore; \
	docker exec webscraper-mongodb mongorestore /tmp/restore
	@echo "✓ Restored from backup"

clean-data: ## Remove all data (WARNING: destructive)
	@read -p "Delete all data? (yes/no): " confirm; \
	if [ "$$confirm" = "yes" ]; then \
		rm -rf data/*; \
		echo "✓ Data deleted"; \
	fi

# Development
build: ## Rebuild all containers
	@docker-compose build --parallel

rebuild: ## Force rebuild all containers
	@docker-compose build --no-cache --parallel

shell-gateway: ## Open shell in gateway container
	@docker exec -it webscraper-gateway bash

shell-ollama: ## Open shell in ollama container
	@docker exec -it webscraper-ollama bash

shell-mongo: ## Open MongoDB shell
	@docker exec -it webscraper-mongodb mongosh -u admin

# Documentation
docs: ## Open documentation
	@if command -v xdg-open > /dev/null; then \
		xdg-open docs/COOLIFY_DEPLOYMENT.md; \
	elif command -v open > /dev/null; then \
		open docs/COOLIFY_DEPLOYMENT.md; \
	else \
		cat docs/COOLIFY_DEPLOYMENT.md; \
	fi

n8n-docs: ## Open n8n workflow documentation
	@if command -v xdg-open > /dev/null; then \
		xdg-open n8n-workflows/README.md; \
	elif command -v open > /dev/null; then \
		open n8n-workflows/README.md; \
	else \
		cat n8n-workflows/README.md; \
	fi

# Cleanup
clean: ## Clean up containers and images
	@docker-compose down
	@docker system prune -f
	@echo "✓ Cleaned up"

clean-all: ## Remove everything including volumes
	@docker-compose down -v
	@docker system prune -af --volumes
	@echo "✓ All Docker resources removed"

# Info
info: ## Show system information
	@echo "System Information:"
	@echo "  Docker Version: $$(docker --version)"
	@echo "  Compose Version: $$(docker-compose --version 2>/dev/null || docker compose version)"
	@echo "  Disk Space: $$(df -h . | tail -1 | awk '{print $$4}') available"
	@echo "  Memory: $$(free -h 2>/dev/null | grep Mem | awk '{print $$2}' || sysctl hw.memsize | awk '{print $$2/1024/1024/1024 "GB"}')"
	@echo ""
	@echo "Services:"
	@docker-compose ps

urls: ## Show service URLs
	@echo "Service URLs:"
	@echo "  Gateway:   http://localhost:8000"
	@echo "  API Docs:  http://localhost:8000/docs"
	@echo "  n8n:       http://localhost:5678"
	@echo "  Ollama:    http://localhost:11434"
	@echo "  MongoDB:   mongodb://localhost:27017"
