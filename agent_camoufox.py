"""
Agent Camoufox - Browser automation and rendering with anti-detection
"""
import os
import asyncio
import base64
from typing import Optional, Dict, Any
from datetime import datetime
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from playwright.async_api import async_playwright, Browser, Page
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Agent Camoufox", version="1.0.0")

# Global browser instance
browser: Optional[Browser] = None

# Models
class RenderRequest(BaseModel):
    url: str = Field(..., description="URL to render")
    wait_for: str = Field("load", description="Wait condition: load, domcontentloaded, networkidle")
    timeout: int = Field(30000, description="Timeout in milliseconds", ge=1000, le=120000)
    screenshot: bool = Field(True, description="Take screenshot")
    full_page: bool = Field(True, description="Full page screenshot")
    javascript: Optional[str] = Field(None, description="JavaScript to execute")
    viewport: Optional[Dict[str, int]] = Field(None, description="Viewport size")

class RenderResponse(BaseModel):
    url: str
    html: str
    screenshot: Optional[str] = None
    metadata: Dict[str, Any]

@app.on_event("startup")
async def startup():
    """Initialize browser on startup"""
    global browser
    try:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-accelerated-2d-canvas',
                '--disable-gpu',
                '--window-size=1920,1080'
            ]
        )
        logger.info("Browser initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize browser: {e}")
        raise

@app.on_event("shutdown")
async def shutdown():
    """Close browser on shutdown"""
    global browser
    if browser:
        await browser.close()
        logger.info("Browser closed")

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "agent": "camoufox",
        "browser_ready": browser is not None,
        "timestamp": datetime.utcnow().isoformat()
    }

@app.post("/render", response_model=RenderResponse)
async def render_page(request: RenderRequest):
    """Render a web page and return HTML + screenshot"""
    if not browser:
        raise HTTPException(status_code=503, detail="Browser not initialized")
    
    try:
        logger.info(f"Rendering {request.url}")
        
        # Create new context with anti-detection features
        context = await browser.new_context(
            viewport=request.viewport or {"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="en-US",
            timezone_id="America/New_York",
            geolocation={"latitude": 40.7128, "longitude": -74.0060},
            permissions=["geolocation"]
        )
        
        page = await context.new_page()
        
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
            "viewport": await page.viewport_size(),
            "timestamp": datetime.utcnow().isoformat()
        }
        
        await context.close()
        
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
