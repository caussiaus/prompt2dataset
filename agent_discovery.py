"""
Agent Discovery - Discovers URLs, crawls sites, and builds site maps
"""
import os
import asyncio
from typing import List, Set, Dict, Optional
from urllib.parse import urljoin, urlparse
from datetime import datetime
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import httpx
from pymongo import MongoClient
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Agent Discovery", version="1.0.0")

# Configuration
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://mongodb:27017")
DB_NAME = os.getenv("DB_NAME", "webscraper")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
MAX_CONCURRENT_REQUESTS = int(os.getenv("MAX_CONCURRENT_REQUESTS", "10"))

# MongoDB connection
mongo_client = MongoClient(MONGODB_URI)
db = mongo_client[DB_NAME]

# Models
class DiscoveryRequest(BaseModel):
    url: str = Field(..., description="Starting URL for discovery")
    depth: int = Field(1, description="Crawl depth", ge=1, le=5)
    max_pages: int = Field(100, description="Maximum pages to discover", ge=1, le=1000)
    follow_external: bool = Field(False, description="Follow external links")
    patterns: Optional[List[str]] = Field(None, description="URL patterns to include")

class DiscoveryResponse(BaseModel):
    discovered_urls: List[str]
    sitemap: Dict[str, List[str]]
    metadata: Dict[str, any]

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "agent": "discovery",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.post("/discover", response_model=DiscoveryResponse)
async def discover_urls(request: DiscoveryRequest):
    """Discover URLs from a starting point"""
    try:
        logger.info(f"Starting discovery for {request.url}")
        
        discovered_urls: Set[str] = set()
        sitemap: Dict[str, List[str]] = {}
        visited: Set[str] = set()
        to_visit: List[tuple] = [(request.url, 0)]  # (url, depth)
        
        base_domain = urlparse(request.url).netloc
        
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=MAX_CONCURRENT_REQUESTS)
        ) as client:
            while to_visit and len(discovered_urls) < request.max_pages:
                current_url, current_depth = to_visit.pop(0)
                
                if current_url in visited or current_depth > request.depth:
                    continue
                
                visited.add(current_url)
                logger.info(f"Discovering: {current_url} (depth: {current_depth})")
                
                try:
                    # Fetch the page
                    response = await client.get(current_url)
                    if response.status_code != 200:
                        continue
                    
                    discovered_urls.add(current_url)
                    
                    # Extract links
                    links = extract_links(response.text, current_url)
                    sitemap[current_url] = links
                    
                    # Add new links to visit
                    for link in links:
                        link_domain = urlparse(link).netloc
                        
                        # Check if we should follow this link
                        if link not in visited:
                            if request.follow_external or link_domain == base_domain:
                                if request.patterns:
                                    if any(pattern in link for pattern in request.patterns):
                                        to_visit.append((link, current_depth + 1))
                                else:
                                    to_visit.append((link, current_depth + 1))
                    
                    # Store in database
                    db.discovered_urls.update_one(
                        {"url": current_url},
                        {
                            "$set": {
                                "url": current_url,
                                "discovered_at": datetime.utcnow(),
                                "links": links,
                                "depth": current_depth,
                                "status": response.status_code
                            }
                        },
                        upsert=True
                    )
                    
                except Exception as e:
                    logger.error(f"Error discovering {current_url}: {e}")
                    continue
        
        metadata = {
            "total_discovered": len(discovered_urls),
            "total_visited": len(visited),
            "max_depth_reached": max([depth for _, depth in [(url, 0)] + to_visit], default=0),
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(f"Discovery complete: {len(discovered_urls)} URLs found")
        
        return DiscoveryResponse(
            discovered_urls=list(discovered_urls),
            sitemap=sitemap,
            metadata=metadata
        )
        
    except Exception as e:
        logger.error(f"Discovery failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def extract_links(html: str, base_url: str) -> List[str]:
    """Extract and normalize links from HTML"""
    import re
    
    # Simple regex-based link extraction
    link_pattern = r'href=["\']([^"\']+)["\']'
    raw_links = re.findall(link_pattern, html)
    
    normalized_links = []
    for link in raw_links:
        # Skip anchors, javascript, mailto, tel
        if link.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
            continue
        
        # Normalize relative URLs
        full_url = urljoin(base_url, link)
        
        # Only HTTP(S) URLs
        if full_url.startswith(('http://', 'https://')):
            normalized_links.append(full_url)
    
    return list(set(normalized_links))  # Deduplicate

@app.get("/sitemap/{domain}")
async def get_sitemap(domain: str):
    """Get discovered sitemap for a domain"""
    try:
        urls = list(db.discovered_urls.find(
            {"url": {"$regex": domain}},
            {"_id": 0}
        ))
        return {"domain": domain, "urls": urls}
    except Exception as e:
        logger.error(f"Error fetching sitemap: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
