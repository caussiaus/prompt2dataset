"""
Discovery Agent - Web crawling and site structure discovery
Discovers URLs, site structure, and navigation patterns
"""
from fastapi import FastAPI, HTTPException
from loguru import logger
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from typing import List, Set, Dict, Any
import asyncio
from datetime import datetime

from config import settings
from models import DiscoveryRequest, DiscoveryResponse, HealthResponse

app = FastAPI(title="Discovery Agent", version="1.0.0")


class WebDiscoverer:
    """Web discovery and crawling logic"""
    
    def __init__(self):
        self.visited_urls: Set[str] = set()
        self.discovered_urls: List[str] = []
        self.site_structure: Dict[str, Any] = {}
    
    async def discover(self, request: DiscoveryRequest) -> DiscoveryResponse:
        """Discover URLs and site structure"""
        self.visited_urls.clear()
        self.discovered_urls.clear()
        self.site_structure = {}
        
        await self._crawl_recursive(
            request.url,
            base_domain=urlparse(request.url).netloc,
            max_depth=request.max_depth,
            current_depth=0,
            follow_links=request.follow_links
        )
        
        return DiscoveryResponse(
            url=request.url,
            discovered_urls=self.discovered_urls,
            site_structure=self.site_structure,
            metadata={
                "total_urls": len(self.discovered_urls),
                "depth_reached": request.max_depth,
                "timestamp": datetime.utcnow().isoformat()
            }
        )
    
    async def _crawl_recursive(
        self,
        url: str,
        base_domain: str,
        max_depth: int,
        current_depth: int,
        follow_links: bool
    ):
        """Recursively crawl URLs"""
        if current_depth > max_depth or url in self.visited_urls:
            return
        
        self.visited_urls.add(url)
        logger.info(f"Crawling: {url} (depth: {current_depth})")
        
        try:
            async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT) as client:
                response = await client.get(
                    url,
                    headers={"User-Agent": settings.USER_AGENT},
                    follow_redirects=True
                )
                response.raise_for_status()
                
                if 'text/html' not in response.headers.get('content-type', ''):
                    return
                
                html = response.text
                soup = BeautifulSoup(html, 'html.parser')
                
                # Extract links
                links = self._extract_links(soup, url, base_domain)
                
                # Build structure
                self.site_structure[url] = {
                    "title": soup.title.string if soup.title else None,
                    "links": links,
                    "depth": current_depth,
                    "status_code": response.status_code
                }
                
                self.discovered_urls.extend(links)
                
                # Recursive crawl if follow_links enabled
                if follow_links and current_depth < max_depth:
                    tasks = []
                    for link in links[:10]:  # Limit concurrent requests
                        if link not in self.visited_urls:
                            tasks.append(
                                self._crawl_recursive(
                                    link, base_domain, max_depth,
                                    current_depth + 1, follow_links
                                )
                            )
                    
                    if tasks:
                        await asyncio.gather(*tasks, return_exceptions=True)
        
        except Exception as e:
            logger.error(f"Error crawling {url}: {e}")
            self.site_structure[url] = {
                "error": str(e),
                "depth": current_depth
            }
    
    def _extract_links(self, soup: BeautifulSoup, base_url: str, base_domain: str) -> List[str]:
        """Extract and filter links from HTML"""
        links = []
        
        for anchor in soup.find_all('a', href=True):
            href = anchor['href']
            absolute_url = urljoin(base_url, href)
            
            # Parse URL
            parsed = urlparse(absolute_url)
            
            # Filter: same domain, http/https only, no fragments
            if (parsed.netloc == base_domain and
                parsed.scheme in ['http', 'https'] and
                absolute_url not in self.visited_urls):
                
                # Remove fragment
                clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                if parsed.query:
                    clean_url += f"?{parsed.query}"
                
                if clean_url not in links:
                    links.append(clean_url)
        
        return links


discoverer = WebDiscoverer()


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        status="healthy",
        agent="discovery"
    )


@app.post("/discover", response_model=DiscoveryResponse)
async def discover_site(request: DiscoveryRequest):
    """Discover site structure and URLs"""
    try:
        logger.info(f"Starting discovery for: {request.url}")
        result = await discoverer.discover(request)
        logger.info(f"Discovery complete. Found {len(result.discovered_urls)} URLs")
        return result
    except Exception as e:
        logger.error(f"Discovery failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/links")
async def extract_links(url: str, same_domain_only: bool = True):
    """Extract links from a single page"""
    try:
        async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT) as client:
            response = await client.get(
                url,
                headers={"User-Agent": settings.USER_AGENT}
            )
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            base_domain = urlparse(url).netloc
            
            links = discoverer._extract_links(soup, url, base_domain)
            
            return {
                "url": url,
                "links": links,
                "count": len(links)
            }
    except Exception as e:
        logger.error(f"Link extraction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
