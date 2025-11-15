"""
Agent Camoufox - Browser automation and rendering with anti-detection using Camoufox
"""
import os
import sys
import asyncio
import base64
from typing import Optional, Dict, Any
from datetime import datetime
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import logging

# Add Camoufox to path
sys.path.insert(0, '/app/camoufox/pythonlib')

from camoufox.async_api import AsyncCamoufox

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Agent Camoufox", version="1.0.0")

# Models
class RenderRequest(BaseModel):
    url: str = Field(..., description="URL to render")
    wait_for: str = Field("load", description="Wait condition: load, domcontentloaded, networkidle")
    timeout: int = Field(30000, description="Timeout in milliseconds", ge=1000, le=120000)
    screenshot: bool = Field(True, description="Take screenshot")
    full_page: bool = Field(True, description="Full page screenshot")
    javascript: Optional[str] = Field(None, description="JavaScript to execute")
    viewport: Optional[Dict[str, int]] = Field(None, description="Viewport size")
    config: Optional[Dict[str, Any]] = Field(None, description="Camoufox fingerprint config")

class RenderResponse(BaseModel):
    url: str
    html: str
    screenshot: Optional[str] = None
    metadata: Dict[str, Any]

@app.on_event("startup")
async def startup():
    """Initialize on startup"""
    logger.info("Camoufox agent started")

@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown"""
    logger.info("Camoufox agent stopped")

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "agent": "camoufox",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.post("/render", response_model=RenderResponse)
async def render_page(request: RenderRequest):
    """Render a web page using Camoufox with advanced anti-detection"""
    try:
        logger.info(f"Rendering {request.url} with Camoufox")
        
        # Prepare Camoufox config with fingerprint rotation
        camoufox_config = request.config or {}
        
        # Set viewport if provided
        if request.viewport:
            camoufox_config['window.innerWidth'] = request.viewport['width']
            camoufox_config['window.innerHeight'] = request.viewport['height']
        
        # Launch Camoufox with fingerprint rotation
        async with AsyncCamoufox(
            config=camoufox_config,
            headless=True,
            humanize=True,  # Enable human-like mouse movement
            geoip=True  # Enable geolocation based on proxy
        ) as browser:
            page = await browser.new_page()
            
            # Navigate to URL
            await page.goto(
                request.url,
                wait_until=request.wait_for,
                timeout=request.timeout
            )
            
            # Execute custom JavaScript if provided
            if request.javascript:
                await page.evaluate(request.javascript)
                await asyncio.sleep(1)  # Wait for JS execution
            
            # Get HTML content
            html = await page.content()
            
            # Take screenshot if requested
            screenshot_base64 = None
            if request.screenshot:
                screenshot_bytes = await page.screenshot(
                    full_page=request.full_page,
                    type="png"
                )
                screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
            
            # Collect metadata
            metadata = {
                "title": await page.title(),
                "final_url": page.url,
                "timestamp": datetime.utcnow().isoformat(),
                "camoufox_config": camoufox_config
            }
        
        logger.info(f"Successfully rendered {request.url}")
        
        return RenderResponse(
            url=request.url,
            html=html,
            screenshot=screenshot_base64,
            metadata=metadata
        )
        
    except Exception as e:
        logger.error(f"Rendering failed for {request.url}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/screenshot")
async def take_screenshot(
    url: str,
    full_page: bool = True,
    width: int = 1920,
    height: int = 1080
):
    """Take a screenshot of a URL"""
    request = RenderRequest(
        url=url,
        screenshot=True,
        full_page=full_page,
        viewport={"width": width, "height": height}
    )
    result = await render_page(request)
    return {"url": url, "screenshot": result.screenshot}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
