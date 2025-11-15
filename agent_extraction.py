"""
Agent Extraction - Extract structured data from HTML using AI models
"""
import os
import json
from typing import Optional, Dict, Any, List
from datetime import datetime
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import httpx
from bs4 import BeautifulSoup
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Agent Extraction", version="1.0.0")

# Configuration
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
EXTRACTION_MODEL = os.getenv("EXTRACTION_MODEL", "llama3.1")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "bge-m3")

# Models
class ExtractionRequest(BaseModel):
    html: str = Field(..., description="HTML content to extract from")
    url: str = Field(..., description="Source URL")
    schema: Optional[Dict[str, Any]] = Field(None, description="Target schema for extraction")
    extract_type: str = Field("general", description="Type: general, product, article, contact, event")
    clean_html: bool = Field(True, description="Clean HTML before extraction")

class ExtractionResponse(BaseModel):
    extracted_data: Dict[str, Any]
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
        "agent": "extraction",
        "ollama_status": ollama_status,
        "timestamp": datetime.utcnow().isoformat()
    }

@app.post("/extract", response_model=ExtractionResponse)
async def extract_data(request: ExtractionRequest):
    """Extract structured data from HTML"""
    try:
        logger.info(f"Extracting data from {request.url}")
        
        # Clean HTML if requested
        if request.clean_html:
            html_content = clean_html(request.html)
        else:
            html_content = request.html
        
        # Prepare extraction based on type and schema
        if request.schema:
            extracted_data = await extract_with_schema(html_content, request.schema, request.url)
        else:
            extracted_data = await extract_by_type(html_content, request.extract_type, request.url)
        
        metadata = {
            "model": EXTRACTION_MODEL,
            "extract_type": request.extract_type,
            "has_schema": request.schema is not None,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(f"Extraction complete for {request.url}")
        
        return ExtractionResponse(
            extracted_data=extracted_data,
            metadata=metadata
        )
        
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def clean_html(html: str) -> str:
    """Clean HTML by removing scripts, styles, and keeping main content"""
    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        # Remove script and style tags
        for tag in soup(['script', 'style', 'noscript', 'iframe']):
            tag.decompose()
        
        # Get text with some structure
        text = soup.get_text(separator='\n', strip=True)
        
        # Remove excessive whitespace
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        cleaned = '\n'.join(lines)
        
        return cleaned
        
    except Exception as e:
        logger.error(f"HTML cleaning failed: {e}")
        return html

async def extract_with_schema(html: str, schema: Dict[str, Any], url: str) -> Dict[str, Any]:
    """Extract data according to a provided schema"""
    try:
        # Build prompt with schema
        schema_str = json.dumps(schema, indent=2)
        prompt = f"""Extract information from the following web content according to this schema:

Schema:
{schema_str}

Web Content:
{html[:10000]}  # Limit content size

Return ONLY a JSON object that matches the schema. Extract as much information as possible."""

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": EXTRACTION_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json"
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                response_text = result.get("response", "{}")
                
                try:
                    return json.loads(response_text)
                except json.JSONDecodeError:
                    # Try to extract JSON from response
                    import re
                    json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                    if json_match:
                        return json.loads(json_match.group())
                    return {"raw_response": response_text}
            else:
                return {"error": "Extraction failed"}
                
    except Exception as e:
        logger.error(f"Schema extraction failed: {e}")
        return {"error": str(e)}

async def extract_by_type(html: str, extract_type: str, url: str) -> Dict[str, Any]:
    """Extract data based on content type"""
    try:
        # Type-specific prompts
        prompts = {
            "general": "Extract key information from this web content including title, main topics, key facts, and important data. Return as JSON.",
            "product": "Extract product information including name, price, description, specifications, images, availability, and reviews. Return as JSON.",
            "article": "Extract article information including title, author, publish date, main content, tags, and category. Return as JSON.",
            "contact": "Extract contact information including names, emails, phone numbers, addresses, and social media links. Return as JSON.",
            "event": "Extract event information including title, date, time, location, description, and registration details. Return as JSON."
        }
        
        prompt = prompts.get(extract_type, prompts["general"])
        full_prompt = f"{prompt}\n\nWeb Content:\n{html[:10000]}"
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": EXTRACTION_MODEL,
                    "prompt": full_prompt,
                    "stream": False,
                    "format": "json"
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                response_text = result.get("response", "{}")
                
                try:
                    return json.loads(response_text)
                except json.JSONDecodeError:
                    import re
                    json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                    if json_match:
                        return json.loads(json_match.group())
                    return {"raw_response": response_text}
            else:
                return {"error": "Extraction failed"}
                
    except Exception as e:
        logger.error(f"Type-based extraction failed: {e}")
        return {"error": str(e)}

@app.post("/summarize")
async def summarize_content(html: str, url: str, max_length: int = 500):
    """Summarize web content"""
    try:
        cleaned = clean_html(html)
        prompt = f"Summarize the following web content in {max_length} characters or less:\n\n{cleaned[:15000]}"
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": EXTRACTION_MODEL,
                    "prompt": prompt,
                    "stream": False
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                return {
                    "summary": result.get("response", ""),
                    "url": url,
                    "model": EXTRACTION_MODEL
                }
            else:
                return {"summary": "", "error": "Summarization failed"}
                
    except Exception as e:
        logger.error(f"Summarization failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/embed")
async def generate_embeddings(text: str):
    """Generate embeddings for text"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/embeddings",
                json={
                    "model": EMBEDDING_MODEL,
                    "prompt": text
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                return {
                    "embeddings": result.get("embedding", []),
                    "model": EMBEDDING_MODEL
                }
            else:
                return {"embeddings": [], "error": "Embedding failed"}
                
    except Exception as e:
        logger.error(f"Embedding generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)
