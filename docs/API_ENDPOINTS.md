# API Endpoints Reference

Complete API documentation for all prompt2dataset services.

## Base URLs

- **Local**: `http://localhost:<port>`
- **Production**: `https://api.yourdomain.com`

## Authentication

Currently, all endpoints are open. For production, implement:
- API keys
- JWT tokens
- OAuth 2.0

---

## Agent Gateway (Port 8000)

Central gateway for all agent services.

### Health Check

**Endpoint**: `GET /health`

**Response**:
```json
{
  "status": "healthy",
  "service": "agent-gateway",
  "version": "1.0.0",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

---

## Discovery Agent (Port 8004)

### Discover URLs

**Endpoint**: `POST /discover`

**Request Body**:
```json
{
  "query": "python web scraping tutorials",
  "max_results": 10,
  "categories": ["general", "it"],
  "filter_domains": ["python.org"],
  "exclude_domains": ["spam.com"],
  "store": true
}
```

**Response**:
```json
{
  "status": "success",
  "data": {
    "query": "python web scraping tutorials",
    "results": [
      {
        "url": "https://example.com/tutorial",
        "title": "Python Web Scraping Guide",
        "content": "Learn how to scrape websites...",
        "engine": "google",
        "score": 0.95
      }
    ],
    "total_found": 10,
    "discovered_at": "2024-01-01T12:00:00Z"
  }
}
```

### Batch Discover

**Endpoint**: `POST /batch-discover`

**Request Body**:
```json
{
  "queries": [
    "python tutorials",
    "web scraping best practices"
  ],
  "max_results": 5,
  "store": true
}
```

**Response**:
```json
{
  "status": "success",
  "results": [
    {
      "query": "python tutorials",
      "status": "success",
      "data": { /* discovery results */ }
    }
  ],
  "total": 2,
  "successful": 2
}
```

### List Services

**Endpoint**: `GET /services`

**Response**:
```json
{
  "status": "success",
  "project": "prompt2dataset",
  "version": "1.0.0",
  "services": {
    "postgres-pgvector": {
      "name": "PostgreSQL + pgvector",
      "status": "healthy",
      "type": "database"
    }
  },
  "total_services": 11,
  "healthy_services": 11,
  "checked_at": "2024-01-01T12:00:00Z"
}
```

### Get Service Info

**Endpoint**: `GET /service/<service_id>`

**Response**:
```json
{
  "status": "success",
  "service": {
    "id": "extraction-agent",
    "name": "Extraction Agent",
    "type": "agent",
    "port": 8001,
    "health_status": "healthy",
    "checked_at": "2024-01-01T12:00:00Z"
  }
}
```

---

## Extraction Agent (Port 8001)

### Extract Data

**Endpoint**: `POST /extract`

**Request Body**:
```json
{
  "url": "https://example.com/product",
  "html": "<html>...</html>",
  "schema": {
    "title": "string",
    "price": "number",
    "description": "string",
    "features": "array",
    "metadata": "object"
  },
  "store": true
}
```

**Parameters**:
- `url` (optional): URL to extract from
- `html` (optional): Raw HTML (if url not provided)
- `schema` (required): Extraction schema
- `store` (optional): Save to database

**Response**:
```json
{
  "status": "success",
  "data": {
    "url": "https://example.com/product",
    "parsed": {
      "title": "Product Page Title",
      "text": "Full page text...",
      "links": [],
      "images": []
    },
    "extracted": {
      "title": "Gaming Laptop Pro",
      "price": 1299.99,
      "description": "High-performance gaming laptop...",
      "features": ["16GB RAM", "RTX 4060", "1TB SSD"],
      "metadata": {
        "brand": "TechCorp",
        "model": "GL-2024"
      }
    },
    "extracted_at": "2024-01-01T12:00:00Z"
  }
}
```

### Batch Extract

**Endpoint**: `POST /batch-extract`

**Request Body**:
```json
{
  "urls": [
    "https://example.com/product1",
    "https://example.com/product2"
  ],
  "schema": {
    "title": "string",
    "price": "number"
  },
  "store": true
}
```

**Response**:
```json
{
  "status": "success",
  "results": [
    {
      "url": "https://example.com/product1",
      "status": "success",
      "data": { /* extracted data */ }
    }
  ],
  "total": 2,
  "successful": 2
}
```

---

## Vision Agent (Port 8002)

### Analyze Image

**Endpoint**: `POST /analyze-image`

**Request Body**:
```json
{
  "image_url": "https://example.com/product.jpg",
  "image_data": "base64_encoded_image_data",
  "prompt": "Describe this product image in detail, including colors, materials, and visible features",
  "store": true
}
```

**Parameters**:
- `image_url` (optional): URL of image
- `image_data` (optional): Base64 encoded image (if url not provided)
- `prompt` (required): Analysis prompt
- `store` (optional): Save to database

**Response**:
```json
{
  "status": "success",
  "data": {
    "image_url": "https://example.com/product.jpg",
    "prompt": "Describe this product...",
    "analysis": {
      "description": "This image shows a sleek gaming laptop with RGB keyboard lighting. The device features a black aluminum chassis with red accents. The screen displays a high-quality gaming interface. Notable features include side air vents and a prominent logo on the lid.",
      "model": "llava:latest",
      "analyzed_at": "2024-01-01T12:00:00Z"
    },
    "analyzed_at": "2024-01-01T12:00:00Z"
  }
}
```

### Batch Analyze

**Endpoint**: `POST /batch-analyze`

**Request Body**:
```json
{
  "images": [
    {
      "url": "https://example.com/image1.jpg",
      "prompt": "Describe this image"
    },
    {
      "url": "https://example.com/image2.jpg",
      "prompt": "What objects are visible?"
    }
  ],
  "store": true
}
```

**Response**:
```json
{
  "status": "success",
  "results": [
    {
      "image": "https://example.com/image1.jpg",
      "status": "success",
      "data": { /* analysis results */ }
    }
  ],
  "total": 2,
  "successful": 2
}
```

---

## Orchestrator Agent (Port 8003)

### Execute Workflow

**Endpoint**: `POST /orchestrate`

**Request Body**:
```json
{
  "workflow_name": "Product Data Extraction Pipeline",
  "steps": [
    {
      "name": "discover_products",
      "type": "discover",
      "data": {
        "query": "gaming laptops 2024",
        "max_results": 10
      }
    },
    {
      "name": "extract_product_data",
      "type": "extract",
      "data": {
        "schema": {
          "name": "string",
          "price": "number",
          "specs": "object"
        },
        "store": true
      },
      "depends_on": "discover_products"
    },
    {
      "name": "analyze_product_images",
      "type": "analyze_image",
      "data": {
        "prompt": "Describe product appearance and features"
      },
      "depends_on": "extract_product_data"
    }
  ],
  "parallel": false,
  "store": true
}
```

**Parameters**:
- `workflow_name` (required): Descriptive workflow name
- `steps` (required): Array of workflow steps
- `parallel` (optional): Execute independent steps in parallel
- `store` (optional): Save workflow results

**Step Types**:
- `discover`: URL discovery
- `extract`: Data extraction
- `analyze_image`: Image analysis

**Response**:
```json
{
  "status": "success",
  "data": {
    "workflow_name": "Product Data Extraction Pipeline",
    "steps": [
      {
        "step": "discover_products",
        "type": "discover",
        "result": {
          "status": "success",
          "data": { /* discovery results */ }
        }
      },
      {
        "step": "extract_product_data",
        "type": "extract",
        "result": {
          "status": "success",
          "data": { /* extraction results */ }
        }
      },
      {
        "step": "analyze_product_images",
        "type": "analyze_image",
        "result": {
          "status": "success",
          "data": { /* vision analysis results */ }
        }
      }
    ],
    "total_steps": 3,
    "successful_steps": 3,
    "completed_at": "2024-01-01T12:05:00Z"
  }
}
```

### List Workflows

**Endpoint**: `GET /workflows`

**Response**:
```json
{
  "status": "success",
  "workflows": [
    {
      "id": 1,
      "workflow_name": "Product Data Extraction Pipeline",
      "completed_at": "2024-01-01T12:05:00Z"
    }
  ]
}
```

---

## HTML Parser (Port 5000)

### Parse HTML

**Endpoint**: `POST /parse`

**Request Body**:
```json
{
  "html": "<html><body><h1>Title</h1><p>Content</p></body></html>",
  "url": "https://example.com",
  "options": {
    "parser": "lxml",
    "extract_links": true,
    "extract_images": true,
    "extract_tables": false,
    "store": true
  }
}
```

**Response**:
```json
{
  "status": "success",
  "data": {
    "title": "Title",
    "text": "Title Content",
    "links": [
      {
        "href": "https://example.com/page",
        "text": "Link Text"
      }
    ],
    "images": [
      {
        "src": "https://example.com/image.jpg",
        "alt": "Image Description"
      }
    ],
    "metadata": {
      "description": "Page description",
      "keywords": "keyword1, keyword2"
    },
    "headings": {
      "h1": ["Title"],
      "h2": ["Subtitle 1", "Subtitle 2"]
    },
    "parsed_at": "2024-01-01T12:00:00Z"
  }
}
```

### Extract Text

**Endpoint**: `POST /extract-text`

**Request Body**:
```json
{
  "html": "<html><body><p>Content</p></body></html>",
  "separator": " "
}
```

**Response**:
```json
{
  "status": "success",
  "text": "Content"
}
```

---

## Error Responses

All endpoints return standardized error responses:

### 400 Bad Request

```json
{
  "error": "Missing required parameter: query",
  "status": "error"
}
```

### 500 Internal Server Error

```json
{
  "error": "Database connection failed",
  "status": "error"
}
```

### 503 Service Unavailable

```json
{
  "error": "Service temporarily unavailable",
  "status": "error"
}
```

---

## Rate Limiting

**Current**: No rate limiting (development)

**Production Recommendation**:
- 100 requests/minute per IP
- 1000 requests/hour per API key
- Implement via nginx or API gateway

---

## Pagination

For endpoints returning large result sets:

**Request**:
```json
{
  "query": "search term",
  "page": 1,
  "per_page": 20
}
```

**Response**:
```json
{
  "status": "success",
  "data": { /* results */ },
  "pagination": {
    "page": 1,
    "per_page": 20,
    "total_pages": 5,
    "total_results": 100
  }
}
```

---

## Webhooks

Configure webhooks for async notifications:

**Request**:
```json
{
  "webhook_url": "https://your-app.com/webhook",
  "events": ["extraction_complete", "workflow_complete"]
}
```

**Webhook Payload**:
```json
{
  "event": "extraction_complete",
  "data": { /* extraction results */ },
  "timestamp": "2024-01-01T12:00:00Z"
}
```

---

## Code Examples

### Python

```python
import requests

# Discovery
response = requests.post('http://localhost:8004/discover', json={
    'query': 'python tutorials',
    'max_results': 10
})
results = response.json()

# Extraction
response = requests.post('http://localhost:8001/extract', json={
    'url': 'https://example.com',
    'schema': {'title': 'string', 'price': 'number'}
})
data = response.json()

# Vision Analysis
response = requests.post('http://localhost:8002/analyze-image', json={
    'image_url': 'https://example.com/image.jpg',
    'prompt': 'Describe this image'
})
analysis = response.json()

# Workflow Orchestration
response = requests.post('http://localhost:8003/orchestrate', json={
    'workflow_name': 'Test Workflow',
    'steps': [
        {'name': 'discover', 'type': 'discover', 'data': {'query': 'test'}}
    ]
})
workflow = response.json()
```

### JavaScript

```javascript
// Discovery
const response = await fetch('http://localhost:8004/discover', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    query: 'python tutorials',
    max_results: 10
  })
});
const results = await response.json();

// Extraction
const extractResponse = await fetch('http://localhost:8001/extract', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    url: 'https://example.com',
    schema: { title: 'string', price: 'number' }
  })
});
const data = await extractResponse.json();
```

### cURL

```bash
# Discovery
curl -X POST http://localhost:8004/discover \
  -H "Content-Type: application/json" \
  -d '{"query": "python tutorials", "max_results": 10}'

# Extraction
curl -X POST http://localhost:8001/extract \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "schema": {"title": "string"}}'

# Vision Analysis
curl -X POST http://localhost:8002/analyze-image \
  -H "Content-Type: application/json" \
  -d '{"image_url": "https://example.com/image.jpg", "prompt": "Describe"}'
```

---

## Testing

Use the provided service client for testing:

```bash
# Test all endpoints
python3 scripts/service_client.py --test

# Export endpoint information
python3 scripts/service_client.py --export
```

---

**For more information, see:**
- [Services Documentation](SERVICES.md)
- [Deployment Guide](../DEPLOYMENT.md)
- [Main README](../README.md)
