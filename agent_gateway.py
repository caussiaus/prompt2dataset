"""
Gateway Agent - Main orchestrator and API gateway
Coordinates all specialized agents and provides unified API
"""
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
import httpx
from typing import Dict, Any, List, Optional
from datetime import datetime
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

from config import settings
from models import (
    ScrapingTask, ScrapingResult, TaskStatus,
    DiscoveryRequest, ExtractionRequest, VisionRequest,
    HealthResponse
)

app = FastAPI(
    title="AI-Augmented Web Scraper Gateway",
    version="1.0.0",
    description="Orchestrates multi-agent web scraping with SOTA AI models"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB client
mongo_client: Optional[AsyncIOMotorClient] = None
db = None


@app.on_event("startup")
async def startup_db_client():
    """Initialize MongoDB connection"""
    global mongo_client, db
    try:
        mongo_client = AsyncIOMotorClient(settings.MONGODB_URL)
        db = mongo_client[settings.MONGODB_DB]
        logger.info("Connected to MongoDB")
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {e}")


@app.on_event("shutdown")
async def shutdown_db_client():
    """Close MongoDB connection"""
    if mongo_client:
        mongo_client.close()
        logger.info("Closed MongoDB connection")


class OrchestrationEngine:
    """Orchestrates multiple agents for web scraping tasks"""
    
    def __init__(self):
        self.http_client = httpx.AsyncClient(timeout=60.0)
    
    async def execute_task(self, task: ScrapingTask) -> ScrapingResult:
        """Execute a scraping task using appropriate agents"""
        
        result = ScrapingResult(
            task_id=task.task_id,
            url=task.url,
            status=TaskStatus.RUNNING
        )
        
        start_time = datetime.utcnow()
        
        try:
            # Step 1: Discovery (if needed)
            if task.scraping_type in ["discovery", "full"] or task.follow_links:
                logger.info(f"Running discovery for {task.url}")
                discovery_data = await self._run_discovery(task)
                result.metadata["discovery"] = discovery_data
            
            # Step 2: Fetch content (using browser if needed)
            if task.use_browser or task.javascript_enabled:
                logger.info(f"Using browser automation for {task.url}")
                page_data = await self._scrape_with_browser(task)
            else:
                logger.info(f"Using standard HTTP for {task.url}")
                page_data = await self._scrape_standard(task)
            
            result.raw_html = page_data.get("html")
            result.links = page_data.get("links", [])
            
            # Step 3: Extraction
            if task.scraping_type in ["extraction", "full"]:
                logger.info(f"Running extraction for {task.url}")
                extraction_data = await self._run_extraction(task, page_data.get("html"))
                result.extracted_data = extraction_data.get("extracted_data")
                result.text_content = extraction_data.get("summary")
                result.metadata["extraction"] = extraction_data
            
            # Step 4: Vision processing (if images found and requested)
            if task.extract_images and page_data.get("images"):
                logger.info(f"Running vision processing for {task.url}")
                image_urls = [img.get("src") for img in page_data.get("images", [])[:5]]  # Limit to 5
                vision_data = await self._run_vision(image_urls)
                result.images = vision_data.get("results", [])
                result.metadata["vision"] = vision_data
            
            # Success
            result.status = TaskStatus.COMPLETED
            end_time = datetime.utcnow()
            result.processing_time = (end_time - start_time).total_seconds()
            
            logger.info(f"Task {task.task_id} completed in {result.processing_time}s")
        
        except Exception as e:
            logger.error(f"Task {task.task_id} failed: {e}")
            result.status = TaskStatus.FAILED
            result.error = str(e)
        
        return result
    
    async def _run_discovery(self, task: ScrapingTask) -> Dict[str, Any]:
        """Run discovery agent"""
        try:
            request = DiscoveryRequest(
                url=task.url,
                max_depth=task.max_depth,
                follow_links=task.follow_links,
                extract_links=task.extract_links
            )
            
            response = await self.http_client.post(
                f"{settings.DISCOVERY_URL}/discover",
                json=request.dict()
            )
            response.raise_for_status()
            return response.json()
        
        except Exception as e:
            logger.error(f"Discovery agent failed: {e}")
            return {"error": str(e)}
    
    async def _scrape_with_browser(self, task: ScrapingTask) -> Dict[str, Any]:
        """Scrape using browser automation"""
        try:
            params = {
                "url": task.url,
                "wait_time": 2
            }
            
            if task.wait_for_selector:
                params["wait_for_selector"] = task.wait_for_selector
            
            response = await self.http_client.post(
                f"{settings.CAMOUFOX_URL}/scrape",
                params=params
            )
            response.raise_for_status()
            return response.json()
        
        except Exception as e:
            logger.error(f"Browser automation failed: {e}")
            return {"error": str(e), "html": "", "links": [], "images": []}
    
    async def _scrape_standard(self, task: ScrapingTask) -> Dict[str, Any]:
        """Standard HTTP scraping"""
        try:
            response = await self.http_client.get(
                task.url,
                headers={"User-Agent": settings.USER_AGENT},
                follow_redirects=True
            )
            response.raise_for_status()
            
            # Basic link extraction could be done here or delegated
            return {
                "html": response.text,
                "links": [],
                "images": []
            }
        
        except Exception as e:
            logger.error(f"Standard scraping failed: {e}")
            raise
    
    async def _run_extraction(self, task: ScrapingTask, html: str) -> Dict[str, Any]:
        """Run extraction agent"""
        try:
            request = ExtractionRequest(
                html_content=html,
                css_selectors=task.css_selectors,
                llm_prompt=task.llm_extraction_prompt,
                use_llm=bool(task.llm_extraction_prompt)
            )
            
            response = await self.http_client.post(
                f"{settings.EXTRACTION_URL}/extract",
                json=request.dict()
            )
            response.raise_for_status()
            return response.json()
        
        except Exception as e:
            logger.error(f"Extraction agent failed: {e}")
            return {"error": str(e)}
    
    async def _run_vision(self, image_urls: List[str]) -> Dict[str, Any]:
        """Run vision agent"""
        try:
            request = VisionRequest(
                image_urls=image_urls,
                task_type="description"
            )
            
            response = await self.http_client.post(
                f"{settings.VISION_URL}/process",
                json=request.dict()
            )
            response.raise_for_status()
            return response.json()
        
        except Exception as e:
            logger.error(f"Vision agent failed: {e}")
            return {"error": str(e)}


orchestrator = OrchestrationEngine()


@app.get("/", response_model=Dict[str, Any])
async def root():
    """Root endpoint"""
    return {
        "name": "AI-Augmented Web Scraper",
        "version": "1.0.0",
        "description": "Multi-agent web scraping with SOTA AI models",
        "endpoints": {
            "health": "/health",
            "scrape": "/scrape",
            "tasks": "/tasks",
            "models": "/models"
        }
    }


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check for gateway and all agents"""
    
    agents_health = {}
    
    # Check each agent
    agents = {
        "discovery": settings.DISCOVERY_URL,
        "extraction": settings.EXTRACTION_URL,
        "vision": settings.VISION_URL,
        "camoufox": settings.CAMOUFOX_URL,
        "model_manager": settings.MODEL_MANAGER_URL,
    }
    
    async with httpx.AsyncClient(timeout=5.0) as client:
        for agent_name, agent_url in agents.items():
            try:
                response = await client.get(f"{agent_url}/health")
                agents_health[agent_name] = response.status_code == 200
            except:
                agents_health[agent_name] = False
    
    # Check MongoDB
    try:
        if db:
            await db.command('ping')
            agents_health["mongodb"] = True
        else:
            agents_health["mongodb"] = False
    except:
        agents_health["mongodb"] = False
    
    all_healthy = all(agents_health.values())
    
    return HealthResponse(
        status="healthy" if all_healthy else "degraded",
        agent="gateway",
        dependencies=agents_health
    )


@app.post("/scrape", response_model=ScrapingResult)
async def scrape(task: ScrapingTask, background: bool = False):
    """Execute a scraping task"""
    
    # Store task in database
    if db:
        await db.tasks.insert_one(task.dict())
    
    if background:
        # Return immediately and process in background
        return ScrapingResult(
            task_id=task.task_id,
            url=task.url,
            status=TaskStatus.PENDING,
            metadata={"message": "Task queued for background processing"}
        )
    else:
        # Process synchronously
        result = await orchestrator.execute_task(task)
        
        # Store result in database
        if db:
            await db.results.insert_one(result.dict())
        
        return result


@app.get("/tasks/{task_id}", response_model=ScrapingResult)
async def get_task_result(task_id: str):
    """Get result of a scraping task"""
    
    if not db:
        raise HTTPException(status_code=503, detail="Database not available")
    
    result = await db.results.find_one({"task_id": task_id})
    
    if not result:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return ScrapingResult(**result)


@app.get("/tasks", response_model=List[Dict[str, Any]])
async def list_tasks(limit: int = 10, skip: int = 0):
    """List recent scraping tasks"""
    
    if not db:
        raise HTTPException(status_code=503, detail="Database not available")
    
    cursor = db.results.find().sort("timestamp", -1).skip(skip).limit(limit)
    results = await cursor.to_list(length=limit)
    
    return results


@app.get("/models")
async def list_models():
    """List available AI models"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{settings.MODEL_MANAGER_URL}/models")
            response.raise_for_status()
            return response.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/models/download")
async def download_models(models: List[str]):
    """Download AI models"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{settings.MODEL_MANAGER_URL}/models/download",
                json={"models": models}
            )
            response.raise_for_status()
            return response.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/models/download/recommended")
async def download_recommended_models():
    """Download recommended model set"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{settings.MODEL_MANAGER_URL}/models/download/recommended"
            )
            response.raise_for_status()
            return response.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.GATEWAY_HOST, port=settings.GATEWAY_PORT)
