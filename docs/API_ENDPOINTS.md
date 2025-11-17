# API Endpoints Documentation

Complete API reference for all services in the prompt2dataset MVP stack.

## Table of Contents

1. [Agent Gateway API](#agent-gateway-api)
2. [Extraction Agent API](#extraction-agent-api)
3. [Vision Agent API](#vision-agent-api)
4. [Orchestrator Agent API](#orchestrator-agent-api)
5. [Discovery Agent API](#discovery-agent-api)
6. [HTML Parser API](#html-parser-api)
7. [Client SDK Usage](#client-sdk-usage)

---

## Base URLs

**Local Development**:
- Gateway: `http://localhost:8000`
- Individual agents: `http://localhost:800X`

**Production** (via Coolify):
- Gateway: `https://api.yourdomain.com`

---

## Agent Gateway API

Base URL: `http://localhost:8000`

### GET /

**Description**: Service information

**Response**:
```json
{
  "service": "agent-gateway",
  "version": "1.0.0",
  "status": "running",
  "timestamp": "2024-01-01T00:00:00.000Z",
  "endpoints": {
    "health": "/health",
    "extract": "/api/extract",
    "analyze-image": "/api/analyze-image",
    "orchestrate": "/api/orchestrate",
    "discover": "/api/discover",
    "services": "/api/services"
  }
}
```

---

### GET /health

**Description**: Health check for gateway and all agents

**Response**:
```json
{
  "status": "healthy",
  "service": "agent-gateway",
  "timestamp": "2024-01-01T00:00:00.000Z",
  "agents": {
    "extraction_agent": "healthy",
    "vision_agent": "healthy",
    "orchestrator_agent": "healthy",
    "discovery_agent": "healthy"
  }
}
```

**Status Values**:
- `healthy`: All services operational
- `degraded`: Some services down
- `unhealthy`: Critical services down

---

### POST /api/extract

**Description**: Extract data from URL or HTML content

**Request Body**:
```json
{
  "url": "https://example.com",
  "html": "<html>...</html>",  // Optional, if not providing URL
  "type": "full"  // "full", "links", or "text"
}
```

**Response**:
```json
{
  "title": "Example Page",
  "headings": {
    "h1": ["Main Title"],
    "h2": ["Subtitle 1", "Subtitle 2"]
  },
  "links": [
    {"text": "Link Text", "href": "https://..."}
  ],
  "images": [
    {"alt": "Image description", "src": "https://..."}
  ],
  "paragraphs": ["Text content..."],
  "meta": {
    "description": "Page description",
    "keywords": "keyword1, keyword2"
  }
}
```

**Example**:
```bash
curl -X POST http://localhost:8000/api/extract \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "type": "full"
  }'
```

---

### POST /api/analyze-image

**Description**: Analyze image using vision model

**Request Body**:
```json
{
  "image_url": "https://example.com/image.jpg",
  "image_base64": "base64_encoded_image",  // Alternative to image_url
  "prompt": "Describe this image in detail.",
  "model": "llava:latest"
}
```

**Response**:
```json
{
  "analysis": "This image shows a beautiful sunset over the ocean...",
  "model": "llava:latest",
  "prompt": "Describe this image in detail."
}
```

**Example**:
```bash
curl -X POST http://localhost:8000/api/analyze-image \
  -H "Content-Type: application/json" \
  -d '{
    "image_url": "https://example.com/sunset.jpg",
    "prompt": "What colors are in this image?"
  }'
```

---

### POST /api/orchestrate

**Description**: Run complex multi-agent workflow

**Request Body**:
```json
{
  "workflow": "full-analysis",  // "extract-and-analyze", "discover-and-extract", "full-analysis"
  "url": "https://example.com",
  "query": "machine learning"  // Optional, for discovery
}
```

**Workflow Types**:

1. **extract-and-analyze**: Extract content + analyze images
2. **discover-and-extract**: Discover URLs + extract from them
3. **full-analysis**: Complete analysis (extract + discover + vision)

**Response**:
```json
{
  "workflow": "full-analysis",
  "url": "https://example.com",
  "extracted_data": {...},
  "discovered_urls": [...],
  "analyzed_images": [...],
  "timestamp": "2024-01-01T00:00:00.000Z"
}
```

**Example**:
```bash
curl -X POST http://localhost:8000/api/orchestrate \
  -H "Content-Type: application/json" \
  -d '{
    "workflow": "full-analysis",
    "url": "https://example.com",
    "query": "artificial intelligence"
  }'
```

---

### POST /api/discover

**Description**: Discover related content using search

**Request Body**:
```json
{
  "query": "machine learning tutorials",
  "source_url": "https://example.com",  // Optional
  "limit": 10
}
```

**Response**:
```json
{
  "query": "machine learning tutorials",
  "source_url": "https://example.com",
  "urls": [
    {
      "url": "https://discovered.com",
      "title": "ML Tutorial",
      "description": "Comprehensive machine learning guide...",
      "engine": "google"
    }
  ],
  "total": 10,
  "timestamp": "2024-01-01T00:00:00.000Z"
}
```

**Example**:
```bash
curl -X POST http://localhost:8000/api/discover \
  -H "Content-Type: application/json" \
  -d '{
    "query": "deep learning frameworks",
    "limit": 5
  }'
```

---

### GET /api/services

**Description**: List all registered services

**Response**:
```json
{
  "services": [
    {
      "id": "extraction-agent",
      "name": "Extraction Agent",
      "type": "agent",
      "port": 8001,
      "status": "pending",
      "health_check": "http://localhost:8001/health"
    }
  ],
  "total": 11
}
```

---

### GET /api/services/status

**Description**: Get real-time status of all services

**Response**:
```json
{
  "statuses": {
    "postgres": "healthy",
    "ollama": "healthy",
    "extraction-agent": "healthy",
    "vision-agent": "unhealthy"
  },
  "healthy": 3,
  "total": 4,
  "timestamp": "2024-01-01T00:00:00.000Z"
}
```

---

### POST /api/pipeline

**Description**: Run complete data extraction pipeline

**Request Body**:
```json
{
  "url": "https://example.com",
  "query": "related topics",  // Optional
  "include_images": true
}
```

**Response**:
```json
{
  "url": "https://example.com",
  "extraction": {...},
  "discovery": {...},  // If query provided
  "analyzed_images": [...],  // If include_images=true
  "timestamp": "2024-01-01T00:00:00.000Z"
}
```

**Example**:
```bash
curl -X POST http://localhost:8000/api/pipeline \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "query": "similar articles",
    "include_images": true
  }'
```

---

## Extraction Agent API

Base URL: `http://localhost:8001`

### GET /health

**Description**: Health check

**Response**:
```json
{
  "status": "healthy",
  "service": "extraction-agent",
  "timestamp": "2024-01-01T00:00:00.000Z",
  "dependencies": {
    "database": "healthy",
    "html_parser": "healthy"
  }
}
```

---

### POST /extract

**Description**: Extract data from URL or HTML

**Request Body**:
```json
{
  "url": "https://example.com",
  "html": "<html>...</html>",
  "type": "full"  // "full", "links", "text"
}
```

**Response**: See [POST /api/extract](#post-apiextract) response

---

### GET /extractions?limit=10

**Description**: Get recent extractions from database

**Query Parameters**:
- `limit` (optional): Number of results (default: 10)

**Response**:
```json
{
  "extractions": [
    {
      "id": 1,
      "url": "https://example.com",
      "extract_type": "full",
      "data": {...},
      "created_at": "2024-01-01T00:00:00.000Z"
    }
  ]
}
```

---

## Vision Agent API

Base URL: `http://localhost:8002`

### GET /health

**Description**: Health check

**Response**:
```json
{
  "status": "healthy",
  "service": "vision-agent",
  "timestamp": "2024-01-01T00:00:00.000Z",
  "dependencies": {
    "ollama": "healthy"
  }
}
```

---

### POST /analyze

**Description**: Analyze image with vision model

**Request Body**:
```json
{
  "image_url": "https://example.com/image.jpg",
  "image_base64": "...",  // Alternative
  "prompt": "Describe this image",
  "model": "llava:latest"
}
```

**Response**:
```json
{
  "analysis": "Detailed description...",
  "model": "llava:latest",
  "prompt": "Describe this image"
}
```

---

### POST /extract-text

**Description**: Extract text from image (OCR)

**Request Body**:
```json
{
  "image_url": "https://example.com/document.jpg",
  "image_base64": "..."
}
```

**Response**:
```json
{
  "text": "Extracted text from image..."
}
```

---

### GET /models

**Description**: List available vision models

**Response**:
```json
{
  "models": [
    {
      "name": "llava:latest",
      "size": "4.5GB",
      "modified_at": "2024-01-01T00:00:00.000Z"
    }
  ]
}
```

---

## Orchestrator Agent API

Base URL: `http://localhost:8003`

### GET /health

**Description**: Health check

**Response**:
```json
{
  "status": "healthy",
  "service": "orchestrator-agent",
  "timestamp": "2024-01-01T00:00:00.000Z",
  "dependencies": {
    "extraction_agent": "healthy",
    "vision_agent": "healthy",
    "discovery_agent": "healthy"
  }
}
```

---

### POST /orchestrate

**Description**: Run workflow

See [POST /api/orchestrate](#post-apiorchestrate) documentation.

---

## Discovery Agent API

Base URL: `http://localhost:8004`

### GET /health

**Description**: Health check

**Response**:
```json
{
  "status": "healthy",
  "service": "discovery-agent",
  "timestamp": "2024-01-01T00:00:00.000Z",
  "dependencies": {
    "searxng": "healthy"
  }
}
```

---

### POST /discover

**Description**: Discover related content

See [POST /api/discover](#post-apidiscover) documentation.

---

### GET /services

**Description**: List all services from registry

**Response**:
```json
{
  "services": [...],
  "total": 11
}
```

---

### GET /services/status

**Description**: Check health of all services

**Response**:
```json
{
  "statuses": {
    "service-id": "healthy|unhealthy|unknown"
  },
  "healthy": 8,
  "total": 11,
  "timestamp": "2024-01-01T00:00:00.000Z"
}
```

---

### POST /extract-links

**Description**: Extract all links from webpage

**Request Body**:
```json
{
  "url": "https://example.com"
}
```

**Response**:
```json
{
  "url": "https://example.com",
  "links": [
    {
      "url": "https://example.com/page",
      "text": "Link text",
      "title": "Link title"
    }
  ],
  "total": 42,
  "timestamp": "2024-01-01T00:00:00.000Z"
}
```

---

## HTML Parser API

Base URL: `http://localhost:5000`

### GET /health

**Description**: Health check

**Response**:
```json
{
  "status": "healthy",
  "service": "html-parser",
  "timestamp": "2024-01-01T00:00:00.000Z",
  "database": "healthy"
}
```

---

### POST /parse

**Description**: Parse HTML into structured data

**Request Body**:
```json
{
  "html": "<html>...</html>",
  "parser": "html.parser"  // "html.parser", "lxml", "html5lib"
}
```

**Response**:
```json
{
  "title": "Page Title",
  "headings": {...},
  "links": [...],
  "images": [...],
  "paragraphs": [...],
  "meta": {...}
}
```

---

### POST /extract

**Description**: Extract clean text from HTML

**Request Body**:
```json
{
  "html": "<html>...</html>"
}
```

**Response**:
```json
{
  "text": "Clean extracted text without HTML tags..."
}
```

---

## Client SDK Usage

### Python SDK

```python
from scripts.service_client import ServiceClient

# Initialize client
client = ServiceClient('http://localhost:8000')

# Health check
health = client.health_check()
print(health)

# Extract data
result = client.extract_data('https://example.com')
print(result)

# Analyze image
analysis = client.analyze_image(
    image_url='https://example.com/image.jpg',
    prompt='What is in this image?'
)
print(analysis)

# Run workflow
workflow_result = client.orchestrate_workflow(
    workflow='full-analysis',
    url='https://example.com',
    query='related content'
)
print(workflow_result)

# Discover content
discoveries = client.discover_content(
    query='machine learning',
    limit=10
)
print(discoveries)

# Run pipeline
pipeline_result = client.run_pipeline(
    url='https://example.com',
    query='similar pages',
    include_images=True
)
print(pipeline_result)
```

### CLI Usage

```bash
# Health check
python scripts/service_client.py --health

# List services
python scripts/service_client.py --services

# Services status
python scripts/service_client.py --status

# Extract data
python scripts/service_client.py --extract "https://example.com"

# Discover content
python scripts/service_client.py --discover "machine learning"

# Run pipeline
python scripts/service_client.py --pipeline "https://example.com" --query "AI"

# Export results
python scripts/service_client.py --extract "https://example.com" --export results.json

# Run test suite
python scripts/service_client.py --test
```

---

## Error Handling

All endpoints return consistent error format:

```json
{
  "error": "Error message describing what went wrong"
}
```

**Common HTTP Status Codes**:
- `200`: Success
- `400`: Bad request (missing parameters)
- `500`: Internal server error
- `503`: Service unavailable (dependency down)

**Error Examples**:

```json
// Missing parameter
{
  "error": "No URL provided"
}

// Service down
{
  "error": "Failed to connect to extraction-agent"
}

// Timeout
{
  "error": "Request timeout after 60s"
}
```

---

## Rate Limiting

Currently no rate limiting implemented. For production:

1. Add rate limiting middleware
2. Implement per-IP limits
3. Add API key authentication
4. Queue long-running requests

---

## Authentication

Currently no authentication required. For production:

1. Add API key header: `X-API-Key: your-key`
2. Implement JWT tokens
3. OAuth2 integration
4. Role-based access control

---

## Monitoring

Track these metrics:

- Request count per endpoint
- Response times
- Error rates
- Active connections
- Queue depths

Use tools:
- Prometheus + Grafana
- ELK Stack (Elasticsearch, Logstash, Kibana)
- Custom monitoring via `/health` endpoints

---

## Best Practices

1. **Always check health first**: Verify services are up
2. **Use appropriate timeouts**: Long operations may need 60s+
3. **Handle errors gracefully**: Check for `error` field in response
4. **Batch requests**: Use pipeline endpoint for multiple operations
5. **Cache results**: Many extractions can be cached
6. **Monitor usage**: Track API calls and resource usage

---

## Examples

### Complete Workflow Example

```bash
# 1. Check health
curl http://localhost:8000/health

# 2. Extract data from page
curl -X POST http://localhost:8000/api/extract \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "type": "full"}'

# 3. Discover related content
curl -X POST http://localhost:8000/api/discover \
  -H "Content-Type: application/json" \
  -d '{"query": "example topic", "limit": 5}'

# 4. Analyze image from page
curl -X POST http://localhost:8000/api/analyze-image \
  -H "Content-Type: application/json" \
  -d '{"image_url": "https://example.com/image.jpg"}'

# 5. Run complete pipeline
curl -X POST http://localhost:8000/api/pipeline \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "query": "related content",
    "include_images": true
  }'
```

### Python Integration Example

```python
import requests

GATEWAY_URL = 'http://localhost:8000'

def extract_and_process(url):
    """Extract data and process results"""
    
    # Extract data
    response = requests.post(
        f'{GATEWAY_URL}/api/extract',
        json={'url': url, 'type': 'full'}
    )
    
    if response.status_code != 200:
        print(f"Error: {response.json()}")
        return
    
    data = response.json()
    
    # Process links
    print(f"Found {len(data['links'])} links")
    
    # Process images
    for image in data['images'][:3]:
        # Analyze each image
        analysis_response = requests.post(
            f'{GATEWAY_URL}/api/analyze-image',
            json={'image_url': image['src']}
        )
        
        if analysis_response.status_code == 200:
            analysis = analysis_response.json()
            print(f"Image: {image['alt']}")
            print(f"Analysis: {analysis['analysis']}")
    
    return data

# Usage
result = extract_and_process('https://example.com')
```
