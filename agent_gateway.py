"""
Agent Gateway - Orchestrates all scraping agents and manages the pipeline
"""
import os
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import httpx
from pymongo import MongoClient
from bson import ObjectId
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Agent Gateway", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://mongodb:27017")
DB_NAME = os.getenv("DB_NAME", "webscraper")
DISCOVERY_URL = os.getenv("DISCOVERY_URL", "http://agent-discovery:8001")
CAMOUFOX_URL = os.getenv("CAMOUFOX_URL", "http://agent-camoufox:8002")
VISION_URL = os.getenv("VISION_URL", "http://agent-vision:8003")
EXTRACTION_URL = os.getenv("EXTRACTION_URL", "http://agent-extraction:8004")

# MongoDB connection
mongo_client = MongoClient(MONGODB_URI)
db = mongo_client[DB_NAME]

# Models
class ScrapeRequest(BaseModel):
    url: str = Field(..., description="Target URL to scrape")
    strategy: str = Field("full", description="Scraping strategy: full, discovery, extraction, vision")
    depth: int = Field(1, description="Crawl depth for discovery")
    extract_schema: Optional[Dict[str, Any]] = Field(None, description="Schema for structured extraction")
    use_vision: bool = Field(False, description="Enable vision/OCR processing")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)

class JobResponse(BaseModel):
    job_id: str
    status: str
    message: str

class JobStatus(BaseModel):
    job_id: str
    status: str
    progress: float
    results: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime

# Endpoints
@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "ok",
        "agent": "gateway",
        "timestamp": datetime.utcnow().isoformat(),
        "services": await check_services()
    }

async def check_services():
    """Check health of all downstream services"""
    services = {
        "discovery": DISCOVERY_URL,
        "camoufox": CAMOUFOX_URL,
        "vision": VISION_URL,
        "extraction": EXTRACTION_URL
    }
    
    health_status = {}
    async with httpx.AsyncClient(timeout=5.0) as client:
        for name, url in services.items():
            try:
                response = await client.get(f"{url}/health")
                health_status[name] = "ok" if response.status_code == 200 else "error"
            except Exception as e:
                health_status[name] = "error"
                logger.error(f"Service {name} health check failed: {e}")
    
    return health_status

@app.post("/scrape", response_model=JobResponse)
async def create_scrape_job(request: ScrapeRequest, background_tasks: BackgroundTasks):
    """Create a new scraping job"""
    try:
        # Create job record
        job = {
            "url": request.url,
            "strategy": request.strategy,
            "depth": request.depth,
            "extract_schema": request.extract_schema,
            "use_vision": request.use_vision,
            "metadata": request.metadata,
            "status": "pending",
            "progress": 0.0,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "results": {}
        }
        
        result = db.jobs.insert_one(job)
        job_id = str(result.inserted_id)
        
        # Start background processing
        background_tasks.add_task(process_scrape_job, job_id, request)
        
        return JobResponse(
            job_id=job_id,
            status="pending",
            message="Job created and queued for processing"
        )
    except Exception as e:
        logger.error(f"Error creating job: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/jobs/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str):
    """Get status of a scraping job"""
    try:
        job = db.jobs.find_one({"_id": ObjectId(job_id)})
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        
        return JobStatus(
            job_id=job_id,
            status=job["status"],
            progress=job.get("progress", 0.0),
            results=job.get("results"),
            error=job.get("error"),
            created_at=job["created_at"],
            updated_at=job["updated_at"]
        )
    except Exception as e:
        logger.error(f"Error fetching job: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/jobs")
async def list_jobs(skip: int = 0, limit: int = 50):
    """List all scraping jobs"""
    try:
        jobs = list(db.jobs.find().sort("created_at", -1).skip(skip).limit(limit))
        for job in jobs:
            job["_id"] = str(job["_id"])
        return {"jobs": jobs, "total": db.jobs.count_documents({})}
    except Exception as e:
        logger.error(f"Error listing jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def process_scrape_job(job_id: str, request: ScrapeRequest):
    """Process a scraping job through the pipeline"""
    try:
        logger.info(f"Processing job {job_id}")
        update_job_status(job_id, "processing", 0.1)
        
        async with httpx.AsyncClient(timeout=300.0) as client:
            results = {}
            
            # Step 1: Discovery (if needed)
            if request.strategy in ["full", "discovery"]:
                logger.info(f"Job {job_id}: Running discovery")
                discovery_response = await client.post(
                    f"{DISCOVERY_URL}/discover",
                    json={"url": request.url, "depth": request.depth}
                )
                results["discovery"] = discovery_response.json()
                update_job_status(job_id, "processing", 0.3, results)
            
            # Step 2: Browser rendering (Camoufox)
            logger.info(f"Job {job_id}: Rendering with Camoufox")
            render_response = await client.post(
                f"{CAMOUFOX_URL}/render",
                json={"url": request.url, "wait_for": "networkidle"}
            )
            render_data = render_response.json()
            results["render"] = render_data
            update_job_status(job_id, "processing", 0.5, results)
            
            # Step 3: Vision processing (if enabled)
            if request.use_vision or request.strategy == "vision":
                logger.info(f"Job {job_id}: Running vision processing")
                vision_response = await client.post(
                    f"{VISION_URL}/process",
                    json={
                        "screenshot": render_data.get("screenshot"),
                        "url": request.url
                    }
                )
                results["vision"] = vision_response.json()
                update_job_status(job_id, "processing", 0.7, results)
            
            # Step 4: Data extraction
            if request.strategy in ["full", "extraction"]:
                logger.info(f"Job {job_id}: Extracting data")
                extraction_response = await client.post(
                    f"{EXTRACTION_URL}/extract",
                    json={
                        "html": render_data.get("html"),
                        "url": request.url,
                        "schema": request.extract_schema
                    }
                )
                results["extraction"] = extraction_response.json()
                update_job_status(job_id, "processing", 0.9, results)
            
            # Complete
            update_job_status(job_id, "completed", 1.0, results)
            logger.info(f"Job {job_id} completed successfully")
            
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        db.jobs.update_one(
            {"_id": ObjectId(job_id)},
            {
                "$set": {
                    "status": "failed",
                    "error": str(e),
                    "updated_at": datetime.utcnow()
                }
            }
        )

def update_job_status(job_id: str, status: str, progress: float, results: Dict = None):
    """Update job status in database"""
    update_data = {
        "status": status,
        "progress": progress,
        "updated_at": datetime.utcnow()
    }
    if results:
        update_data["results"] = results
    
    db.jobs.update_one(
        {"_id": ObjectId(job_id)},
        {"$set": update_data}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
