"""
Agent Vision - OCR, Vision-Language models, and multimodal processing
"""
import os
import base64
import asyncio
from typing import Optional, Dict, Any, List
from datetime import datetime
from io import BytesIO
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import httpx
from PIL import Image
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Agent Vision", version="1.0.0")

# Configuration
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
VISION_MODEL = os.getenv("VISION_MODEL", "llava")
OCR_MODEL = os.getenv("OCR_MODEL", "llava")

# Models
class VisionRequest(BaseModel):
    screenshot: Optional[str] = Field(None, description="Base64 encoded screenshot")
    image_url: Optional[str] = Field(None, description="URL to image")
    url: str = Field(..., description="Source URL")
    tasks: List[str] = Field(["ocr", "describe"], description="Tasks: ocr, describe, analyze, extract_tables")
    prompt: Optional[str] = Field(None, description="Custom prompt for vision model")

class VisionResponse(BaseModel):
    results: Dict[str, Any]
    metadata: Dict[str, Any]

@app.get("/health")
async def health():
    """Health check"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{OLLAMA_URL}/api/tags")
            ollama_status = "ok" if response.status_code == 200 else "error"
    except:
        ollama_status = "error"
    
    return {
        "status": "ok",
        "agent": "vision",
        "ollama_status": ollama_status,
        "timestamp": datetime.utcnow().isoformat()
    }

@app.post("/process", response_model=VisionResponse)
async def process_vision(request: VisionRequest):
    """Process image with vision models"""
    try:
        logger.info(f"Processing vision tasks for {request.url}")
        
        # Get image data
        image_data = None
        if request.screenshot:
            image_data = request.screenshot
        elif request.image_url:
            async with httpx.AsyncClient() as client:
                response = await client.get(request.image_url)
                image_data = base64.b64encode(response.content).decode('utf-8')
        else:
            raise HTTPException(status_code=400, detail="No image provided")
        
        results = {}
        
        # Process each task
        for task in request.tasks:
            if task == "ocr":
                results["ocr"] = await perform_ocr(image_data)
            elif task == "describe":
                results["description"] = await describe_image(image_data, request.prompt)
            elif task == "analyze":
                results["analysis"] = await analyze_layout(image_data)
            elif task == "extract_tables":
                results["tables"] = await extract_tables(image_data)
        
        metadata = {
            "model": VISION_MODEL,
            "tasks_completed": len(results),
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(f"Vision processing complete for {request.url}")
        
        return VisionResponse(
            results=results,
            metadata=metadata
        )
        
    except Exception as e:
        logger.error(f"Vision processing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def perform_ocr(image_base64: str) -> Dict[str, Any]:
    """Extract text from image using OCR"""
    try:
        prompt = "Extract all visible text from this image. Return the text in a structured format, preserving layout where possible."
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": OCR_MODEL,
                    "prompt": prompt,
                    "images": [image_base64],
                    "stream": False
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                return {
                    "text": result.get("response", ""),
                    "model": OCR_MODEL
                }
            else:
                return {"text": "", "error": "OCR failed"}
                
    except Exception as e:
        logger.error(f"OCR failed: {e}")
        return {"text": "", "error": str(e)}

async def describe_image(image_base64: str, custom_prompt: Optional[str] = None) -> Dict[str, Any]:
    """Describe image content"""
    try:
        prompt = custom_prompt or "Describe this webpage screenshot in detail. Include information about layout, key elements, navigation, content sections, and any notable visual features."
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": VISION_MODEL,
                    "prompt": prompt,
                    "images": [image_base64],
                    "stream": False
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                return {
                    "description": result.get("response", ""),
                    "model": VISION_MODEL
                }
            else:
                return {"description": "", "error": "Description failed"}
                
    except Exception as e:
        logger.error(f"Description failed: {e}")
        return {"description": "", "error": str(e)}

async def analyze_layout(image_base64: str) -> Dict[str, Any]:
    """Analyze page layout and structure"""
    try:
        prompt = """Analyze this webpage layout and identify:
        1. Main content areas (header, navigation, content, sidebar, footer)
        2. Visual hierarchy and structure
        3. Interactive elements (buttons, forms, links)
        4. Content organization
        Return your analysis in a structured format."""
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": VISION_MODEL,
                    "prompt": prompt,
                    "images": [image_base64],
                    "stream": False
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                return {
                    "layout_analysis": result.get("response", ""),
                    "model": VISION_MODEL
                }
            else:
                return {"layout_analysis": "", "error": "Layout analysis failed"}
                
    except Exception as e:
        logger.error(f"Layout analysis failed: {e}")
        return {"layout_analysis": "", "error": str(e)}

async def extract_tables(image_base64: str) -> Dict[str, Any]:
    """Extract tables from image"""
    try:
        prompt = "Identify and extract all tables from this image. Return the table data in a structured format with rows and columns clearly labeled."
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": VISION_MODEL,
                    "prompt": prompt,
                    "images": [image_base64],
                    "stream": False
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                return {
                    "tables": result.get("response", ""),
                    "model": VISION_MODEL
                }
            else:
                return {"tables": "", "error": "Table extraction failed"}
                
    except Exception as e:
        logger.error(f"Table extraction failed: {e}")
        return {"tables": "", "error": str(e)}

@app.post("/ocr")
async def ocr_endpoint(screenshot: str, url: str):
    """Dedicated OCR endpoint"""
    request = VisionRequest(
        screenshot=screenshot,
        url=url,
        tasks=["ocr"]
    )
    result = await process_vision(request)
    return result.results.get("ocr", {})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
