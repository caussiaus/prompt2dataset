"""
Model Manager Agent - Handles AI model downloads and management
Downloads and manages Ollama models for the entire pipeline
"""
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from loguru import logger
import ollama
import asyncio
import httpx
from typing import List, Dict, Any
from datetime import datetime
import os

from config import settings
from models import ModelInfo, ModelDownloadRequest, HealthResponse

app = FastAPI(title="Model Manager Agent", version="1.0.0")

# Model registry with recommended models for each pipeline stage
MODEL_REGISTRY = {
    "vision": {
        "qwen3-vl": {"description": "Vision-language model for VQA and image understanding"},
        "llava": {"description": "Multimodal vision model"},
        "llama3.2-vision": {"description": "Llama vision model"},
        "minicpm-v": {"description": "Efficient multimodal model"},
    },
    "llm": {
        "llama3.1": {"description": "General purpose LLM (8B)"},
        "llama3.3": {"description": "Latest Llama model"},
        "gemma3": {"description": "Efficient LLM for single GPU"},
        "deepseek-r1": {"description": "Reasoning and RAG model"},
        "qwen3": {"description": "Qwen language model"},
        "glm-4.6": {"description": "Advanced agentic model"},
        "mistral-small3.1": {"description": "Fast lightweight LLM"},
    },
    "embedding": {
        "bge-m3": {"description": "BGE embedding model"},
        "bge-large": {"description": "Large BGE embedding"},
        "nomic-embed-text": {"description": "Nomic embedding model"},
        "mxbai-embed-large": {"description": "MixedBread embedding"},
    },
    "code": {
        "deepseek-coder": {"description": "Code generation and analysis"},
        "codellama": {"description": "Meta's code model"},
        "qwen3-coder": {"description": "Qwen code model"},
        "starcoder2": {"description": "StarCoder 2 model"},
    },
    "rag": {
        "llama3-chatqa": {"description": "Specialized Q&A model"},
        "deepseek-r1": {"description": "Reasoning model"},
    }
}

# Track download status
download_status: Dict[str, Dict[str, Any]] = {}


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    try:
        # Test Ollama connection
        client = ollama.Client(host=settings.OLLAMA_HOST)
        models = client.list()
        ollama_available = True
    except Exception as e:
        logger.error(f"Ollama connection failed: {e}")
        ollama_available = False
    
    return HealthResponse(
        status="healthy" if ollama_available else "degraded",
        agent="model-manager",
        dependencies={
            "ollama": ollama_available
        }
    )


@app.get("/models", response_model=List[ModelInfo])
async def list_models():
    """List all available models"""
    try:
        client = ollama.Client(host=settings.OLLAMA_HOST)
        installed_models = client.list()
        installed_names = [m.model.split(':')[0] for m in installed_models.models]
        
        models_list = []
        for category, models in MODEL_REGISTRY.items():
            for model_name, info in models.items():
                status = "available" if model_name in installed_names else "not_available"
                
                # Check if currently downloading
                if model_name in download_status and download_status[model_name].get("status") == "downloading":
                    status = "downloading"
                
                models_list.append(ModelInfo(
                    name=model_name,
                    type=category,
                    status=status,
                    source="ollama",
                    metadata=info
                ))
        
        return models_list
    except Exception as e:
        logger.error(f"Error listing models: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/models/{model_name}")
async def get_model_info(model_name: str):
    """Get information about a specific model"""
    try:
        client = ollama.Client(host=settings.OLLAMA_HOST)
        
        try:
            info = client.show(model_name)
            return {
                "name": model_name,
                "status": "available",
                "details": info
            }
        except:
            return {
                "name": model_name,
                "status": "not_available",
                "details": None
            }
    except Exception as e:
        logger.error(f"Error getting model info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def download_model_task(model_name: str):
    """Background task to download a model"""
    download_status[model_name] = {
        "status": "downloading",
        "progress": 0,
        "started_at": datetime.utcnow().isoformat()
    }
    
    try:
        logger.info(f"Starting download of model: {model_name}")
        client = ollama.Client(host=settings.OLLAMA_HOST)
        
        # Pull the model
        stream = client.pull(model_name, stream=True)
        
        for progress in stream:
            if 'status' in progress:
                logger.info(f"{model_name}: {progress['status']}")
                download_status[model_name]["last_status"] = progress['status']
            
            if 'completed' in progress and 'total' in progress:
                percent = (progress['completed'] / progress['total']) * 100
                download_status[model_name]["progress"] = percent
        
        download_status[model_name] = {
            "status": "completed",
            "progress": 100,
            "completed_at": datetime.utcnow().isoformat()
        }
        logger.info(f"Successfully downloaded model: {model_name}")
        
    except Exception as e:
        logger.error(f"Error downloading model {model_name}: {e}")
        download_status[model_name] = {
            "status": "failed",
            "error": str(e),
            "failed_at": datetime.utcnow().isoformat()
        }


@app.post("/models/download")
async def download_models(
    request: ModelDownloadRequest,
    background_tasks: BackgroundTasks
):
    """Download one or more models"""
    results = []
    
    for model_name in request.models:
        # Check if already downloading
        if model_name in download_status and download_status[model_name].get("status") == "downloading":
            results.append({
                "model": model_name,
                "status": "already_downloading"
            })
            continue
        
        # Add download task
        background_tasks.add_task(download_model_task, model_name)
        results.append({
            "model": model_name,
            "status": "download_started"
        })
    
    return {
        "message": f"Started downloading {len(request.models)} model(s)",
        "results": results
    }


@app.get("/models/download/status")
async def get_download_status():
    """Get status of all model downloads"""
    return download_status


@app.post("/models/download/recommended")
async def download_recommended_models(background_tasks: BackgroundTasks):
    """Download the recommended model set for web scraping pipeline"""
    recommended = [
        settings.VISION_MODEL,      # llava
        settings.LLM_MODEL,          # llama3.1
        settings.EMBEDDING_MODEL,    # bge-m3
        settings.CODE_MODEL,         # deepseek-coder
        settings.RAG_MODEL,          # llama3-chatqa
    ]
    
    # Remove duplicates
    recommended = list(set(recommended))
    
    request = ModelDownloadRequest(models=recommended)
    return await download_models(request, background_tasks)


@app.delete("/models/{model_name}")
async def delete_model(model_name: str):
    """Delete a model"""
    try:
        client = ollama.Client(host=settings.OLLAMA_HOST)
        client.delete(model_name)
        
        return {
            "message": f"Model {model_name} deleted successfully"
        }
    except Exception as e:
        logger.error(f"Error deleting model {model_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8005)
