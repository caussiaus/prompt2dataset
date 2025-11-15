"""
Vision Agent - Image processing, OCR, and visual question answering
Handles multimodal tasks using vision-language models
"""
from fastapi import FastAPI, HTTPException, File, UploadFile
from loguru import logger
import httpx
import ollama
from PIL import Image
import io
import base64
from typing import List, Dict, Any, Optional
from datetime import datetime

from config import settings
from models import VisionRequest, VisionResponse, HealthResponse

app = FastAPI(title="Vision Agent", version="1.0.0")


class VisionProcessor:
    """Vision and multimodal processing logic"""
    
    def __init__(self):
        self.ollama_client = ollama.Client(host=settings.OLLAMA_HOST)
    
    async def process_vision_request(self, request: VisionRequest) -> VisionResponse:
        """Process vision request"""
        results = []
        model = request.model or settings.VISION_MODEL
        
        # Process image URLs
        if request.image_urls:
            for idx, image_url in enumerate(request.image_urls):
                try:
                    result = await self._process_image_url(
                        image_url,
                        request.task_type,
                        request.question,
                        model
                    )
                    results.append({
                        "image_url": image_url,
                        "index": idx,
                        **result
                    })
                except Exception as e:
                    logger.error(f"Error processing image {image_url}: {e}")
                    results.append({
                        "image_url": image_url,
                        "index": idx,
                        "error": str(e)
                    })
        
        return VisionResponse(
            results=results,
            metadata={
                "model": model,
                "task_type": request.task_type,
                "total_images": len(results),
                "timestamp": datetime.utcnow().isoformat()
            }
        )
    
    async def _process_image_url(
        self,
        image_url: str,
        task_type: str,
        question: Optional[str],
        model: str
    ) -> Dict[str, Any]:
        """Process a single image from URL"""
        
        # Download image
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(image_url)
            response.raise_for_status()
            image_bytes = response.content
        
        # Convert to base64
        image_b64 = base64.b64encode(image_bytes).decode('utf-8')
        
        # Process based on task type
        if task_type == "ocr":
            return await self._perform_ocr(image_b64, model)
        elif task_type == "vqa":
            return await self._perform_vqa(image_b64, question, model)
        elif task_type == "description":
            return await self._describe_image(image_b64, model)
        elif task_type == "classification":
            return await self._classify_image(image_b64, model)
        else:
            raise ValueError(f"Unknown task type: {task_type}")
    
    async def _perform_ocr(self, image_b64: str, model: str) -> Dict[str, Any]:
        """Perform OCR on image"""
        prompt = """Extract all text from this image. Return the text exactly as it appears, preserving formatting and structure where possible."""
        
        try:
            response = self.ollama_client.chat(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                        "images": [image_b64]
                    }
                ],
                options={"temperature": 0.1}
            )
            
            extracted_text = response['message']['content']
            
            return {
                "task": "ocr",
                "text": extracted_text,
                "success": True
            }
        except Exception as e:
            logger.error(f"OCR failed: {e}")
            return {
                "task": "ocr",
                "text": None,
                "success": False,
                "error": str(e)
            }
    
    async def _perform_vqa(
        self,
        image_b64: str,
        question: Optional[str],
        model: str
    ) -> Dict[str, Any]:
        """Perform visual question answering"""
        if not question:
            question = "What do you see in this image?"
        
        try:
            response = self.ollama_client.chat(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": question,
                        "images": [image_b64]
                    }
                ],
                options={"temperature": 0.3}
            )
            
            answer = response['message']['content']
            
            return {
                "task": "vqa",
                "question": question,
                "answer": answer,
                "success": True
            }
        except Exception as e:
            logger.error(f"VQA failed: {e}")
            return {
                "task": "vqa",
                "question": question,
                "answer": None,
                "success": False,
                "error": str(e)
            }
    
    async def _describe_image(self, image_b64: str, model: str) -> Dict[str, Any]:
        """Generate detailed image description"""
        prompt = """Provide a detailed description of this image. Include:
1. Main subjects and objects
2. Actions or events taking place
3. Setting and context
4. Notable details
5. Overall composition and style"""
        
        try:
            response = self.ollama_client.chat(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                        "images": [image_b64]
                    }
                ],
                options={"temperature": 0.5}
            )
            
            description = response['message']['content']
            
            return {
                "task": "description",
                "description": description,
                "success": True
            }
        except Exception as e:
            logger.error(f"Description failed: {e}")
            return {
                "task": "description",
                "description": None,
                "success": False,
                "error": str(e)
            }
    
    async def _classify_image(self, image_b64: str, model: str) -> Dict[str, Any]:
        """Classify image content"""
        prompt = """Analyze and classify this image. Provide:
1. Primary category/type
2. Key attributes
3. Relevant tags or labels
4. Confidence level (high/medium/low)

Format your response as structured information."""
        
        try:
            response = self.ollama_client.chat(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                        "images": [image_b64]
                    }
                ],
                options={"temperature": 0.2}
            )
            
            classification = response['message']['content']
            
            return {
                "task": "classification",
                "classification": classification,
                "success": True
            }
        except Exception as e:
            logger.error(f"Classification failed: {e}")
            return {
                "task": "classification",
                "classification": None,
                "success": False,
                "error": str(e)
            }


processor = VisionProcessor()


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    try:
        # Test Ollama connection
        processor.ollama_client.list()
        ollama_available = True
    except:
        ollama_available = False
    
    return HealthResponse(
        status="healthy" if ollama_available else "degraded",
        agent="vision",
        dependencies={"ollama": ollama_available}
    )


@app.post("/process", response_model=VisionResponse)
async def process_images(request: VisionRequest):
    """Process images with vision models"""
    try:
        logger.info(f"Processing {len(request.image_urls)} images with task: {request.task_type}")
        result = await processor.process_vision_request(request)
        logger.info(f"Vision processing complete")
        return result
    except Exception as e:
        logger.error(f"Vision processing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ocr")
async def ocr_image(image_url: str, model: Optional[str] = None):
    """Perform OCR on a single image"""
    request = VisionRequest(
        image_urls=[image_url],
        task_type="ocr",
        model=model
    )
    return await process_images(request)


@app.post("/vqa")
async def visual_qa(image_url: str, question: str, model: Optional[str] = None):
    """Answer a question about an image"""
    request = VisionRequest(
        image_urls=[image_url],
        task_type="vqa",
        question=question,
        model=model
    )
    return await process_images(request)


@app.post("/describe")
async def describe_image(image_url: str, model: Optional[str] = None):
    """Generate description of an image"""
    request = VisionRequest(
        image_urls=[image_url],
        task_type="description",
        model=model
    )
    return await process_images(request)


@app.post("/upload")
async def upload_and_process(
    file: UploadFile = File(...),
    task_type: str = "description",
    question: Optional[str] = None
):
    """Upload and process an image file"""
    try:
        # Read image
        image_bytes = await file.read()
        image_b64 = base64.b64encode(image_bytes).decode('utf-8')
        
        # Process based on task
        model = settings.VISION_MODEL
        
        if task_type == "ocr":
            result = await processor._perform_ocr(image_b64, model)
        elif task_type == "vqa":
            result = await processor._perform_vqa(image_b64, question, model)
        elif task_type == "description":
            result = await processor._describe_image(image_b64, model)
        elif task_type == "classification":
            result = await processor._classify_image(image_b64, model)
        else:
            raise ValueError(f"Unknown task type: {task_type}")
        
        return {
            "filename": file.filename,
            **result
        }
    
    except Exception as e:
        logger.error(f"Upload processing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
