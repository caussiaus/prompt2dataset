"""
Extraction Agent - Data extraction and structuring using LLMs
Extracts structured data from HTML using CSS selectors and LLM processing
"""
from fastapi import FastAPI, HTTPException
from loguru import logger
import httpx
import ollama
from bs4 import BeautifulSoup
from typing import Dict, Any, List, Optional
import json
from datetime import datetime
import re

from config import settings
from models import ExtractionRequest, ExtractionResponse, HealthResponse

app = FastAPI(title="Extraction Agent", version="1.0.0")


class DataExtractor:
    """Data extraction and structuring logic"""
    
    def __init__(self):
        self.ollama_client = ollama.Client(host=settings.OLLAMA_HOST)
    
    async def extract(self, request: ExtractionRequest) -> ExtractionResponse:
        """Extract data from HTML content"""
        
        # Get HTML content
        if request.html_content:
            html = request.html_content
        elif request.url:
            html = await self._fetch_html(request.url)
        else:
            raise ValueError("Either html_content or url must be provided")
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # CSS selector extraction
        extracted_data = {}
        if request.css_selectors:
            extracted_data = self._extract_with_selectors(soup, request.css_selectors)
        
        # LLM-based extraction
        structured_data = None
        summary = None
        
        if request.use_llm and request.llm_prompt:
            # Clean text for LLM
            text_content = self._extract_clean_text(soup)
            
            # Use LLM for extraction
            llm_result = await self._extract_with_llm(
                text_content,
                request.llm_prompt,
                request.extraction_schema
            )
            
            structured_data = llm_result.get("structured_data")
            summary = llm_result.get("summary")
            
            # Merge with CSS extracted data
            if structured_data:
                extracted_data.update(structured_data)
        
        return ExtractionResponse(
            extracted_data=extracted_data,
            structured_data=structured_data,
            summary=summary,
            metadata={
                "extraction_method": "hybrid" if (request.css_selectors and request.use_llm) else "css" if request.css_selectors else "llm",
                "timestamp": datetime.utcnow().isoformat()
            }
        )
    
    async def _fetch_html(self, url: str) -> str:
        """Fetch HTML content from URL"""
        async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT) as client:
            response = await client.get(
                url,
                headers={"User-Agent": settings.USER_AGENT}
            )
            response.raise_for_status()
            return response.text
    
    def _extract_with_selectors(
        self,
        soup: BeautifulSoup,
        selectors: Dict[str, str]
    ) -> Dict[str, Any]:
        """Extract data using CSS selectors"""
        data = {}
        
        for field_name, selector in selectors.items():
            try:
                elements = soup.select(selector)
                
                if len(elements) == 0:
                    data[field_name] = None
                elif len(elements) == 1:
                    data[field_name] = elements[0].get_text(strip=True)
                else:
                    data[field_name] = [el.get_text(strip=True) for el in elements]
            
            except Exception as e:
                logger.error(f"Error extracting {field_name} with selector {selector}: {e}")
                data[field_name] = None
        
        return data
    
    def _extract_clean_text(self, soup: BeautifulSoup) -> str:
        """Extract clean text content from HTML"""
        # Remove script and style elements
        for element in soup(['script', 'style', 'meta', 'noscript']):
            element.decompose()
        
        # Get text
        text = soup.get_text(separator='\n', strip=True)
        
        # Clean up whitespace
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        text = '\n'.join(lines)
        
        # Limit length for LLM
        max_chars = 8000
        if len(text) > max_chars:
            text = text[:max_chars] + "..."
        
        return text
    
    async def _extract_with_llm(
        self,
        text: str,
        prompt: str,
        schema: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Extract structured data using LLM"""
        try:
            # Build extraction prompt
            system_prompt = """You are a data extraction assistant. Extract structured information from the provided text according to the user's instructions. Return your response as valid JSON."""
            
            user_prompt = f"{prompt}\n\nText to extract from:\n{text}"
            
            if schema:
                user_prompt += f"\n\nExpected schema:\n{json.dumps(schema, indent=2)}"
            
            # Call LLM
            response = self.ollama_client.chat(
                model=settings.LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                options={
                    "temperature": 0.1,
                    "num_predict": 2000
                }
            )
            
            llm_output = response['message']['content']
            
            # Try to parse JSON from response
            structured_data = self._parse_json_from_text(llm_output)
            
            # Generate summary if not in structured data
            summary = structured_data.get("summary") if isinstance(structured_data, dict) else None
            
            if not summary:
                summary = await self._generate_summary(text)
            
            return {
                "structured_data": structured_data,
                "summary": summary,
                "raw_llm_output": llm_output
            }
        
        except Exception as e:
            logger.error(f"LLM extraction failed: {e}")
            return {
                "structured_data": None,
                "summary": None,
                "error": str(e)
            }
    
    def _parse_json_from_text(self, text: str) -> Any:
        """Extract and parse JSON from text"""
        # Try direct parse first
        try:
            return json.loads(text)
        except:
            pass
        
        # Try to find JSON in markdown code blocks
        json_pattern = r'```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```'
        matches = re.findall(json_pattern, text, re.DOTALL)
        
        for match in matches:
            try:
                return json.loads(match)
            except:
                continue
        
        # Try to find any JSON object/array
        json_pattern = r'(\{.*?\}|\[.*?\])'
        matches = re.findall(json_pattern, text, re.DOTALL)
        
        for match in matches:
            try:
                return json.loads(match)
            except:
                continue
        
        # Return raw text if no JSON found
        return {"raw_text": text}
    
    async def _generate_summary(self, text: str) -> str:
        """Generate summary of text"""
        try:
            response = self.ollama_client.chat(
                model=settings.LLM_MODEL,
                messages=[
                    {"role": "system", "content": "You are a summarization assistant. Provide concise summaries."},
                    {"role": "user", "content": f"Summarize this text in 2-3 sentences:\n\n{text[:3000]}"}
                ],
                options={"temperature": 0.3, "num_predict": 200}
            )
            return response['message']['content']
        except Exception as e:
            logger.error(f"Summary generation failed: {e}")
            return ""


extractor = DataExtractor()


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    try:
        # Test Ollama connection
        extractor.ollama_client.list()
        ollama_available = True
    except:
        ollama_available = False
    
    return HealthResponse(
        status="healthy" if ollama_available else "degraded",
        agent="extraction",
        dependencies={"ollama": ollama_available}
    )


@app.post("/extract", response_model=ExtractionResponse)
async def extract_data(request: ExtractionRequest):
    """Extract structured data from HTML"""
    try:
        logger.info(f"Starting extraction for URL: {request.url or 'provided HTML'}")
        result = await extractor.extract(request)
        logger.info("Extraction complete")
        return result
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/extract/text")
async def extract_text(url: str):
    """Extract clean text from URL"""
    try:
        async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT) as client:
            response = await client.get(url, headers={"User-Agent": settings.USER_AGENT})
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            text = extractor._extract_clean_text(soup)
            
            return {
                "url": url,
                "text": text,
                "length": len(text)
            }
    except Exception as e:
        logger.error(f"Text extraction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
