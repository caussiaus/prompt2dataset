"""
Camoufox Agent - Stealth browser automation
Handles JavaScript-heavy sites and anti-bot evasion using Camoufox
"""
from fastapi import FastAPI, HTTPException
from loguru import logger
from playwright.async_api import async_playwright
from typing import Optional, Dict, Any, List
from datetime import datetime
import asyncio
import json

from config import settings
from models import HealthResponse

app = FastAPI(title="Camoufox Agent", version="1.0.0")


class BrowserAutomation:
    """Browser automation with stealth capabilities"""
    
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
    
    async def initialize(self):
        """Initialize Playwright browser"""
        if not self.playwright:
            self.playwright = await async_playwright().start()
            # Use Firefox as Camoufox is Firefox-based
            self.browser = await self.playwright.firefox.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                ]
            )
            self.context = await self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent=settings.USER_AGENT
            )
    
    async def cleanup(self):
        """Cleanup browser resources"""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
    
    async def scrape_page(
        self,
        url: str,
        wait_for_selector: Optional[str] = None,
        wait_time: int = 2,
        screenshot: bool = False,
        execute_js: Optional[str] = None
    ) -> Dict[str, Any]:
        """Scrape a page with browser automation"""
        
        await self.initialize()
        
        page = await self.context.new_page()
        
        try:
            logger.info(f"Navigating to: {url}")
            
            # Navigate to page
            await page.goto(url, wait_until='networkidle', timeout=30000)
            
            # Wait for specific selector if provided
            if wait_for_selector:
                await page.wait_for_selector(wait_for_selector, timeout=10000)
            else:
                # Default wait
                await asyncio.sleep(wait_time)
            
            # Execute custom JavaScript if provided
            js_result = None
            if execute_js:
                js_result = await page.evaluate(execute_js)
            
            # Get content
            html_content = await page.content()
            title = await page.title()
            url_final = page.url
            
            # Extract links
            links = await page.evaluate("""
                () => {
                    return Array.from(document.querySelectorAll('a[href]'))
                        .map(a => a.href)
                        .filter(href => href.startsWith('http'));
                }
            """)
            
            # Extract images
            images = await page.evaluate("""
                () => {
                    return Array.from(document.querySelectorAll('img[src]'))
                        .map(img => ({
                            src: img.src,
                            alt: img.alt || '',
                            width: img.naturalWidth,
                            height: img.naturalHeight
                        }));
                }
            """)
            
            # Take screenshot if requested
            screenshot_data = None
            if screenshot:
                screenshot_data = await page.screenshot(type='png', full_page=True)
                screenshot_data = screenshot_data.hex()
            
            result = {
                "url": url,
                "final_url": url_final,
                "title": title,
                "html": html_content,
                "links": list(set(links)),
                "images": images,
                "screenshot": screenshot_data,
                "js_result": js_result,
                "timestamp": datetime.utcnow().isoformat(),
                "success": True
            }
            
            return result
        
        except Exception as e:
            logger.error(f"Browser automation failed: {e}")
            return {
                "url": url,
                "error": str(e),
                "success": False,
                "timestamp": datetime.utcnow().isoformat()
            }
        
        finally:
            await page.close()
    
    async def scrape_infinite_scroll(
        self,
        url: str,
        scroll_pause_time: float = 2.0,
        max_scrolls: int = 10
    ) -> Dict[str, Any]:
        """Scrape page with infinite scrolling"""
        
        await self.initialize()
        page = await self.context.new_page()
        
        try:
            await page.goto(url, wait_until='networkidle')
            
            # Scroll and load content
            for i in range(max_scrolls):
                # Scroll to bottom
                await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                
                # Wait for content to load
                await asyncio.sleep(scroll_pause_time)
                
                # Check if we've reached the bottom
                reached_bottom = await page.evaluate("""
                    () => {
                        return (window.innerHeight + window.scrollY) >= document.body.scrollHeight;
                    }
                """)
                
                if reached_bottom:
                    break
            
            html_content = await page.content()
            
            return {
                "url": url,
                "html": html_content,
                "scrolls_performed": i + 1,
                "success": True,
                "timestamp": datetime.utcnow().isoformat()
            }
        
        except Exception as e:
            logger.error(f"Infinite scroll failed: {e}")
            return {
                "url": url,
                "error": str(e),
                "success": False
            }
        
        finally:
            await page.close()
    
    async def interact_and_scrape(
        self,
        url: str,
        actions: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Perform interactions and scrape results"""
        
        await self.initialize()
        page = await self.context.new_page()
        
        try:
            await page.goto(url, wait_until='networkidle')
            
            # Execute actions
            for action in actions:
                action_type = action.get('type')
                
                if action_type == 'click':
                    selector = action.get('selector')
                    await page.click(selector)
                    await asyncio.sleep(action.get('wait', 1))
                
                elif action_type == 'type':
                    selector = action.get('selector')
                    text = action.get('text')
                    await page.fill(selector, text)
                
                elif action_type == 'select':
                    selector = action.get('selector')
                    value = action.get('value')
                    await page.select_option(selector, value)
                
                elif action_type == 'wait':
                    wait_time = action.get('time', 1)
                    await asyncio.sleep(wait_time)
                
                elif action_type == 'wait_for_selector':
                    selector = action.get('selector')
                    await page.wait_for_selector(selector)
            
            html_content = await page.content()
            
            return {
                "url": url,
                "html": html_content,
                "actions_performed": len(actions),
                "success": True,
                "timestamp": datetime.utcnow().isoformat()
            }
        
        except Exception as e:
            logger.error(f"Interaction failed: {e}")
            return {
                "url": url,
                "error": str(e),
                "success": False
            }
        
        finally:
            await page.close()


automation = BrowserAutomation()


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        status="healthy",
        agent="camoufox"
    )


@app.post("/scrape")
async def scrape(
    url: str,
    wait_for_selector: Optional[str] = None,
    wait_time: int = 2,
    screenshot: bool = False,
    execute_js: Optional[str] = None
):
    """Scrape a page with browser automation"""
    try:
        result = await automation.scrape_page(
            url=url,
            wait_for_selector=wait_for_selector,
            wait_time=wait_time,
            screenshot=screenshot,
            execute_js=execute_js
        )
        return result
    except Exception as e:
        logger.error(f"Scraping failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/scrape/infinite-scroll")
async def scrape_infinite(
    url: str,
    scroll_pause_time: float = 2.0,
    max_scrolls: int = 10
):
    """Scrape page with infinite scrolling"""
    try:
        result = await automation.scrape_infinite_scroll(
            url=url,
            scroll_pause_time=scroll_pause_time,
            max_scrolls=max_scrolls
        )
        return result
    except Exception as e:
        logger.error(f"Infinite scroll scraping failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/scrape/interact")
async def scrape_with_interaction(url: str, actions: List[Dict[str, Any]]):
    """Perform interactions and scrape results"""
    try:
        result = await automation.interact_and_scrape(url=url, actions=actions)
        return result
    except Exception as e:
        logger.error(f"Interactive scraping failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    await automation.cleanup()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)
