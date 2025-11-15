"""
Model Manager - Downloads and manages AI models for Ollama
"""
import os
import asyncio
import logging
from typing import List, Dict, Any
from datetime import datetime
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
MODELS_CONFIG_PATH = os.getenv("MODELS_CONFIG_PATH", "/app/models.config")

async def check_ollama_ready():
    """Wait for Ollama to be ready"""
    max_retries = 30
    retry_delay = 5
    
    for i in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{OLLAMA_URL}/api/tags")
                if response.status_code == 200:
                    logger.info("Ollama is ready")
                    return True
        except Exception as e:
            logger.info(f"Waiting for Ollama... ({i+1}/{max_retries})")
            await asyncio.sleep(retry_delay)
    
    logger.error("Ollama failed to become ready")
    return False

async def list_models() -> List[str]:
    """List installed models"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{OLLAMA_URL}/api/tags")
            if response.status_code == 200:
                data = response.json()
                models = [model["name"] for model in data.get("models", [])]
                return models
            return []
    except Exception as e:
        logger.error(f"Failed to list models: {e}")
        return []

async def pull_model(model_name: str) -> bool:
    """Pull a model from Ollama library"""
    try:
        logger.info(f"Pulling model: {model_name}")
        
        async with httpx.AsyncClient(timeout=3600.0) as client:  # 1 hour timeout for large models
            async with client.stream(
                "POST",
                f"{OLLAMA_URL}/api/pull",
                json={"name": model_name}
            ) as response:
                if response.status_code == 200:
                    async for line in response.aiter_lines():
                        if line:
                            logger.info(f"{model_name}: {line}")
                    logger.info(f"Successfully pulled {model_name}")
                    return True
                else:
                    logger.error(f"Failed to pull {model_name}: {response.status_code}")
                    return False
                    
    except Exception as e:
        logger.error(f"Error pulling {model_name}: {e}")
        return False

async def load_models_config() -> List[str]:
    """Load models from config file"""
    models = []
    
    if os.path.exists(MODELS_CONFIG_PATH):
        try:
            with open(MODELS_CONFIG_PATH, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        models.append(line)
            logger.info(f"Loaded {len(models)} models from config")
        except Exception as e:
            logger.error(f"Failed to load models config: {e}")
    else:
        logger.warning(f"Models config not found at {MODELS_CONFIG_PATH}")
        # Default models
        models = [
            "llama3.1",
            "llava",
            "qwen3-vl",
            "bge-m3"
        ]
    
    return models

async def download_all_models():
    """Download all configured models"""
    logger.info("Starting model download process")
    
    # Wait for Ollama
    if not await check_ollama_ready():
        logger.error("Ollama not available, exiting")
        return
    
    # Load model list
    models_to_download = await load_models_config()
    
    if not models_to_download:
        logger.warning("No models configured to download")
        return
    
    # Check existing models
    installed_models = await list_models()
    logger.info(f"Currently installed models: {installed_models}")
    
    # Download missing models
    for model in models_to_download:
        if model not in installed_models:
            logger.info(f"Downloading {model}...")
            success = await pull_model(model)
            if not success:
                logger.error(f"Failed to download {model}")
        else:
            logger.info(f"Model {model} already installed, skipping")
    
    # Final status
    final_models = await list_models()
    logger.info(f"Download complete. Total models installed: {len(final_models)}")
    logger.info(f"Installed models: {final_models}")

async def health_check() -> Dict[str, Any]:
    """Check health of model manager and Ollama"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{OLLAMA_URL}/api/tags")
            if response.status_code == 200:
                data = response.json()
                models = data.get("models", [])
                return {
                    "status": "healthy",
                    "ollama_available": True,
                    "models_count": len(models),
                    "models": [m["name"] for m in models],
                    "timestamp": datetime.utcnow().isoformat()
                }
    except Exception as e:
        return {
            "status": "unhealthy",
            "ollama_available": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }

if __name__ == "__main__":
    # Run download process
    asyncio.run(download_all_models())
