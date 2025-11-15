# API Documentation

Complete API reference for the AI-Augmented Web Scraper.

## Base URLs

- Gateway: `http://localhost:8000`
- Discovery Agent: `http://localhost:8001`
- Extraction Agent: `http://localhost:8002`
- Vision Agent: `http://localhost:8003`
- Camoufox Agent: `http://localhost:8004`
- Model Manager: `http://localhost:8005`

**Interactive Documentation**: Visit `http://localhost:8000/docs` for Swagger UI.

---

## Gateway Agent API

### Health Check

Get health status of all services.

**Endpoint**: `GET /health`

**Response**:
```json
{
  "status": "healthy",
  "agent": "gateway",
  "version": "1.0.0",
  "timestamp": "2024-01-01T12:00:00",
  "dependencies": {
    "discovery": true,
    "extraction": true,
    "vision": true,
    "camoufox": true,
    "model_manager": true,
    "mongodb": true
  }
}
```

### Execute Scraping Task

Submit a web scraping task.

**Endpoint**: `POST /scrape`

**Request Body**:
```json
{
  "url": "https://example.com",
  "scraping_type": "full",
  "extract_images": true,
  "extract_text": true,
  "extract_links": true,
  "use_browser": false,
  "javascript_enabled": false,
  "wait_for_selector": null,
  "pagination": false,
  "max_depth": 1,
  "follow_links": false,
  "css_selectors": {
    "title": "h1.title",
    "price": ".price"
  },
  "llm_extraction_prompt": "Extract product information"
}
```

**Parameters**:
- `url` (string, required): Target URL to scrape
- `scraping_type` (string): `"discovery"`, `"extraction"`, `"vision"`, or `"full"` (default: `"full"`)
- `extract_images` (boolean): Extract images (default: `true`)
- `extract_text` (boolean): Extract text content (default: `true`)
- `extract_links` (boolean): Extract links (default: `true`)
- `use_browser` (boolean): Use browser automation (default: `false`)
- `javascript_enabled` (boolean): Enable JavaScript execution (default: `false`)
- `wait_for_selector` (string): CSS selector to wait for
- `max_depth` (integer): Crawling depth (default: `1`)
- `follow_links` (boolean): Follow discovered links (default: `false`)
- `css_selectors` (object): CSS selectors for extraction
- `llm_extraction_prompt` (string): Prompt for LLM extraction

**Response**:
```json
{
  "task_id": "1234567890.123",
  "url": "https://example.com",
  "status": "completed",
  "raw_html": "<html>...</html>",
  "text_content": "Extracted and summarized text...",
  "extracted_data": {
    "title": "Example Title",
    "price": "$19.99"
  },
  "images": [
    {
      "image_url": "https://example.com/image.jpg",
      "description": "Product image showing..."
    }
  ],
  "links": ["https://example.com/page1", "https://example.com/page2"],
  "metadata": {
    "discovery": {...},
    "extraction": {...},
    "vision": {...}
  },
  "processing_time": 5.23,
  "timestamp": "2024-01-01T12:00:00"
}
```

### Get Task Result

Retrieve result of a previously submitted task.

**Endpoint**: `GET /tasks/{task_id}`

**Response**: Same as scraping task response.

### List Tasks

List recent scraping tasks.

**Endpoint**: `GET /tasks?limit=10&skip=0`

**Query Parameters**:
- `limit` (integer): Number of results (default: 10)
- `skip` (integer): Number to skip (default: 0)

**Response**:
```json
[
  {
    "task_id": "1234567890.123",
    "url": "https://example.com",
    "status": "completed",
    "timestamp": "2024-01-01T12:00:00"
  }
]
```

### List Models

Get all available AI models.

**Endpoint**: `GET /models`

**Response**:
```json
[
  {
    "name": "llava",
    "type": "vision",
    "status": "available",
    "source": "ollama",
    "metadata": {
      "description": "Multimodal vision model"
    }
  }
]
```

### Download Models

Download specific AI models.

**Endpoint**: `POST /models/download`

**Request Body**:
```json
{
  "models": ["llava", "llama3.1", "bge-m3"]
}
```

**Response**:
```json
{
  "message": "Started downloading 3 model(s)",
  "results": [
    {"model": "llava", "status": "download_started"},
    {"model": "llama3.1", "status": "download_started"},
    {"model": "bge-m3", "status": "download_started"}
  ]
}
```

### Download Recommended Models

Download the recommended model set.

**Endpoint**: `POST /models/download/recommended`

**Response**:
```json
{
  "message": "Started downloading 5 model(s)",
  "results": [...]
}
```

---

## Discovery Agent API

### Discover Site Structure

Crawl website and discover structure.

**Endpoint**: `POST /discover`

**Request Body**:
```json
{
  "url": "https://example.com",
  "max_depth": 2,
  "follow_links": true,
  "extract_links": true,
  "filters": {}
}
```

**Response**:
```json
{
  "url": "https://example.com",
  "discovered_urls": [
    "https://example.com/page1",
    "https://example.com/page2"
  ],
  "site_structure": {
    "https://example.com": {
      "title": "Home Page",
      "links": ["https://example.com/page1"],
      "depth": 0,
      "status_code": 200
    }
  },
  "metadata": {
    "total_urls": 25,
    "depth_reached": 2,
    "timestamp": "2024-01-01T12:00:00"
  }
}
```

### Extract Links

Extract links from a single page.

**Endpoint**: `POST /links?url=https://example.com&same_domain_only=true`

**Response**:
```json
{
  "url": "https://example.com",
  "links": ["https://example.com/page1"],
  "count": 1
}
```

---

## Extraction Agent API

### Extract Data

Extract structured data from HTML.

**Endpoint**: `POST /extract`

**Request Body**:
```json
{
  "url": "https://example.com",
  "html_content": null,
  "css_selectors": {
    "title": "h1",
    "author": ".author-name",
    "date": "time.published"
  },
  "extraction_schema": {
    "title": "string",
    "author": "string",
    "date": "date"
  },
  "llm_prompt": "Extract article metadata including title, author, and date",
  "use_llm": true
}
```

**Parameters**:
- `url` (string): URL to extract from (either url or html_content required)
- `html_content` (string): HTML content to extract from
- `css_selectors` (object): CSS selectors for specific fields
- `extraction_schema` (object): Expected data schema
- `llm_prompt` (string): Custom extraction instructions
- `use_llm` (boolean): Use LLM for extraction (default: `true`)

**Response**:
```json
{
  "extracted_data": {
    "title": "Article Title",
    "author": "John Doe",
    "date": "2024-01-01"
  },
  "structured_data": {
    "title": "Article Title",
    "author": "John Doe"
  },
  "summary": "This article discusses...",
  "metadata": {
    "extraction_method": "hybrid",
    "timestamp": "2024-01-01T12:00:00"
  }
}
```

### Extract Text

Extract clean text from URL.

**Endpoint**: `POST /extract/text?url=https://example.com`

**Response**:
```json
{
  "url": "https://example.com",
  "text": "Clean extracted text content...",
  "length": 1234
}
```

---

## Vision Agent API

### Process Images

Process multiple images with vision models.

**Endpoint**: `POST /process`

**Request Body**:
```json
{
  "image_urls": [
    "https://example.com/image1.jpg",
    "https://example.com/image2.jpg"
  ],
  "task_type": "description",
  "question": "What is in this image?",
  "model": "llava"
}
```

**Parameters**:
- `image_urls` (array): List of image URLs
- `task_type` (string): `"ocr"`, `"vqa"`, `"description"`, or `"classification"`
- `question` (string): Question for VQA tasks
- `model` (string): Vision model to use (default: `llava`)

**Response**:
```json
{
  "results": [
    {
      "image_url": "https://example.com/image1.jpg",
      "index": 0,
      "task": "description",
      "description": "The image shows a landscape with mountains...",
      "success": true
    }
  ],
  "metadata": {
    "model": "llava",
    "task_type": "description",
    "total_images": 2,
    "timestamp": "2024-01-01T12:00:00"
  }
}
```

### OCR

Extract text from image.

**Endpoint**: `POST /ocr?image_url=https://example.com/image.jpg&model=llava`

**Response**:
```json
{
  "results": [
    {
      "task": "ocr",
      "text": "Extracted text from image...",
      "success": true
    }
  ]
}
```

### Visual Question Answering

Ask questions about an image.

**Endpoint**: `POST /vqa?image_url=https://example.com/chart.jpg&question=What+is+the+trend?`

**Response**:
```json
{
  "results": [
    {
      "task": "vqa",
      "question": "What is the trend?",
      "answer": "The chart shows an upward trend...",
      "success": true
    }
  ]
}
```

### Describe Image

Generate detailed image description.

**Endpoint**: `POST /describe?image_url=https://example.com/photo.jpg`

**Response**:
```json
{
  "results": [
    {
      "task": "description",
      "description": "The image depicts...",
      "success": true
    }
  ]
}
```

### Upload Image

Upload and process image file.

**Endpoint**: `POST /upload`

**Form Data**:
- `file` (file): Image file
- `task_type` (string): Task type
- `question` (string): Question for VQA

**Response**:
```json
{
  "filename": "image.jpg",
  "task": "description",
  "description": "The uploaded image shows...",
  "success": true
}
```

---

## Camoufox Agent API

### Scrape with Browser

Scrape page using browser automation.

**Endpoint**: `POST /scrape`

**Query Parameters**:
- `url` (string): Target URL
- `wait_for_selector` (string): CSS selector to wait for
- `wait_time` (integer): Wait time in seconds (default: 2)
- `screenshot` (boolean): Capture screenshot (default: `false`)
- `execute_js` (string): JavaScript code to execute

**Response**:
```json
{
  "url": "https://example.com",
  "final_url": "https://example.com/redirected",
  "title": "Page Title",
  "html": "<html>...</html>",
  "links": ["https://example.com/link1"],
  "images": [
    {
      "src": "https://example.com/img.jpg",
      "alt": "Image description",
      "width": 800,
      "height": 600
    }
  ],
  "screenshot": "hexencoded_screenshot_data",
  "js_result": {"custom": "data"},
  "success": true,
  "timestamp": "2024-01-01T12:00:00"
}
```

### Infinite Scroll Scraping

Scrape pages with infinite scrolling.

**Endpoint**: `POST /scrape/infinite-scroll`

**Query Parameters**:
- `url` (string): Target URL
- `scroll_pause_time` (float): Pause between scrolls (default: 2.0)
- `max_scrolls` (integer): Maximum scroll attempts (default: 10)

**Response**:
```json
{
  "url": "https://example.com",
  "html": "<html>...</html>",
  "scrolls_performed": 8,
  "success": true,
  "timestamp": "2024-01-01T12:00:00"
}
```

### Interactive Scraping

Perform interactions before scraping.

**Endpoint**: `POST /scrape/interact`

**Request Body**:
```json
{
  "url": "https://example.com",
  "actions": [
    {
      "type": "click",
      "selector": "#load-more",
      "wait": 1
    },
    {
      "type": "type",
      "selector": "input[name='search']",
      "text": "query"
    },
    {
      "type": "select",
      "selector": "select#category",
      "value": "electronics"
    },
    {
      "type": "wait",
      "time": 2
    },
    {
      "type": "wait_for_selector",
      "selector": ".results-loaded"
    }
  ]
}
```

**Action Types**:
- `click`: Click element
- `type`: Type text into input
- `select`: Select dropdown option
- `wait`: Wait for specified time
- `wait_for_selector`: Wait for element to appear

**Response**:
```json
{
  "url": "https://example.com",
  "html": "<html>...</html>",
  "actions_performed": 5,
  "success": true,
  "timestamp": "2024-01-01T12:00:00"
}
```

---

## Model Manager API

### List All Models

Get information about all available models.

**Endpoint**: `GET /models`

**Response**:
```json
[
  {
    "name": "llava",
    "type": "vision",
    "size": null,
    "status": "available",
    "source": "ollama",
    "metadata": {
      "description": "Multimodal vision model"
    }
  },
  {
    "name": "llama3.1",
    "type": "llm",
    "status": "downloading",
    "source": "ollama",
    "metadata": {}
  }
]
```

### Get Model Info

Get detailed information about a specific model.

**Endpoint**: `GET /models/{model_name}`

**Response**:
```json
{
  "name": "llama3.1",
  "status": "available",
  "details": {
    "format": "gguf",
    "family": "llama",
    "parameter_size": "8B",
    "quantization_level": "Q4_0"
  }
}
```

### Download Models

Download one or more models.

**Endpoint**: `POST /models/download`

**Request Body**:
```json
{
  "models": ["llava", "llama3.1"],
  "source": "ollama",
  "force": false
}
```

**Response**:
```json
{
  "message": "Started downloading 2 model(s)",
  "results": [
    {"model": "llava", "status": "download_started"},
    {"model": "llama3.1", "status": "already_downloading"}
  ]
}
```

### Download Status

Get download progress for all models.

**Endpoint**: `GET /models/download/status`

**Response**:
```json
{
  "llava": {
    "status": "downloading",
    "progress": 45.2,
    "started_at": "2024-01-01T12:00:00",
    "last_status": "downloading layers"
  },
  "llama3.1": {
    "status": "completed",
    "progress": 100,
    "completed_at": "2024-01-01T11:45:00"
  }
}
```

### Delete Model

Remove a model from the system.

**Endpoint**: `DELETE /models/{model_name}`

**Response**:
```json
{
  "message": "Model llava deleted successfully"
}
```

---

## Error Responses

All endpoints may return error responses:

```json
{
  "detail": "Error message description"
}
```

**HTTP Status Codes**:
- `200`: Success
- `400`: Bad Request
- `404`: Not Found
- `500`: Internal Server Error
- `503`: Service Unavailable

---

## Rate Limiting

Currently no rate limiting is implemented. For production use, consider adding rate limiting at the reverse proxy level.

## Authentication

Currently no authentication is required. For production use, implement API key or OAuth2 authentication:

```python
# Add to gateway agent
from fastapi.security import APIKeyHeader

API_KEY = os.getenv("API_KEY")
api_key_header = APIKeyHeader(name="X-API-Key")

@app.post("/scrape")
async def scrape(task: ScrapingTask, api_key: str = Depends(api_key_header)):
    if api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    # ... rest of the code
```

---

For more examples and interactive testing, visit the Swagger UI at `/docs` on any agent.
