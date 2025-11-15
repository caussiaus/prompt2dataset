# Prompt2Dataset Multi-Agent Stack

## Setup

1. Run `setup.sh` as root to prep persistent storage.
2. Copy `.env.example` to `.env` and fill secrets/resources.
3. Open Coolify, add this repo as a project.
4. Add each Compose YAML as a resource, fill env vars from `.env`.
5. Deploy and test `/health` endpoints.

All agent/service logs, datasets, and outputs go to `/data/<service>`. See each service’s folder for files!

## Model Selection
- Edit `models.config` to list the models you wish to pull/download before setup.
- Examples for Ollama and HuggingFace are shown; add/remove entries as desired.
- Run `bash setup.sh` to automatically download all those models!
