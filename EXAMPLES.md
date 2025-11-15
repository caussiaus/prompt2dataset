# Usage Examples

Practical examples for using the AI-Augmented Web Scraper.

## Table of Contents
- [Basic Scraping](#basic-scraping)
- [LLM-Powered Extraction](#llm-powered-extraction)
- [Browser Automation](#browser-automation)
- [Image Processing](#image-processing)
- [Advanced Workflows](#advanced-workflows)

---

## Basic Scraping

### Simple Page Scrape

Extract content from a static webpage:

```bash
curl -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "scraping_type": "extraction",
    "extract_text": true,
    "extract_links": true
  }'
```

### Multiple Page Crawl

Discover and crawl multiple pages:

```bash
curl -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://blog.example.com",
    "scraping_type": "discovery",
    "max_depth": 2,
    "follow_links": true
  }'
```

---

## LLM-Powered Extraction

### Extract Product Information

```bash
curl -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://shop.example.com/product/123",
    "scraping_type": "extraction",
    "css_selectors": {
      "title": "h1.product-title",
      "price": ".price-tag",
      "description": ".product-description"
    },
    "llm_extraction_prompt": "Extract product details including name, price, description, features, and availability. Structure the data in a clear format."
  }'
```

### Extract Article Metadata

```bash
curl -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://news.example.com/article/456",
    "scraping_type": "extraction",
    "llm_extraction_prompt": "Extract: article title, author name, publication date, category/tags, summary (2-3 sentences), and key points as bullet list."
  }'
```

### Extract Structured Data from Tables

```bash
curl -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://data.example.com/table",
    "scraping_type": "extraction",
    "llm_extraction_prompt": "Convert the table data into JSON format with appropriate field names and data types."
  }'
```

---

## Browser Automation

### Scrape JavaScript-Heavy SPA

```bash
curl -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://spa.example.com",
    "use_browser": true,
    "javascript_enabled": true,
    "wait_for_selector": ".content-loaded",
    "scraping_type": "extraction"
  }'
```

### Infinite Scroll Social Feed

```bash
curl -X POST http://localhost:8004/scrape/infinite-scroll \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://social.example.com/feed",
    "scroll_pause_time": 2.0,
    "max_scrolls": 10
  }'
```

### Interactive Form Submission

```bash
curl -X POST http://localhost:8004/scrape/interact \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://search.example.com",
    "actions": [
      {
        "type": "type",
        "selector": "input#search",
        "text": "artificial intelligence"
      },
      {
        "type": "click",
        "selector": "button[type=submit]",
        "wait": 2
      },
      {
        "type": "wait_for_selector",
        "selector": ".results"
      }
    ]
  }'
```

### Capture Screenshot

```bash
curl -X POST "http://localhost:8004/scrape?url=https://example.com&screenshot=true" \
  | jq -r '.screenshot' \
  | xxd -r -p > screenshot.png
```

---

## Image Processing

### Extract Text from Image (OCR)

```bash
curl -X POST "http://localhost:8003/ocr" \
  -H "Content-Type: application/json" \
  -d '{
    "image_urls": ["https://example.com/document.jpg"]
  }'
```

### Analyze Chart or Graph

```bash
curl -X POST http://localhost:8003/vqa \
  -H "Content-Type: application/json" \
  -d '{
    "image_urls": ["https://example.com/chart.png"],
    "question": "What is the main trend shown in this chart? What are the key data points?"
  }'
```

### Describe Product Images

```bash
curl -X POST http://localhost:8003/describe \
  -H "Content-Type: application/json" \
  -d '{
    "image_urls": [
      "https://shop.example.com/product1.jpg",
      "https://shop.example.com/product2.jpg"
    ]
  }'
```

### Upload and Process Image

```bash
curl -X POST http://localhost:8003/upload \
  -F "file=@/path/to/image.jpg" \
  -F "task_type=ocr"
```

---

## Advanced Workflows

### E-commerce Product Scraper

Complete workflow to scrape product catalog:

```python
import requests
import json

BASE_URL = "http://localhost:8000"

# Step 1: Discover product pages
discovery = requests.post(f"{BASE_URL}/scrape", json={
    "url": "https://shop.example.com/products",
    "scraping_type": "discovery",
    "max_depth": 1,
    "follow_links": True
})

product_urls = discovery.json()["links"]

# Step 2: Extract product data from each page
products = []
for url in product_urls[:10]:  # Process first 10
    result = requests.post(f"{BASE_URL}/scrape", json={
        "url": url,
        "scraping_type": "full",
        "extract_images": True,
        "css_selectors": {
            "name": "h1.product-name",
            "price": ".price",
            "sku": ".product-sku"
        },
        "llm_extraction_prompt": "Extract product name, price, SKU, description, features, and specifications. Also identify the product category."
    })
    
    product_data = result.json()
    products.append({
        "url": url,
        "data": product_data["extracted_data"],
        "images": product_data["images"]
    })

# Save results
with open("products.json", "w") as f:
    json.dump(products, f, indent=2)

print(f"Scraped {len(products)} products")
```

### News Article Aggregator

Scrape and summarize news articles:

```python
import requests

BASE_URL = "http://localhost:8000"

# Scrape news site
result = requests.post(f"{BASE_URL}/scrape", json={
    "url": "https://news.example.com",
    "scraping_type": "extraction",
    "llm_extraction_prompt": """
    Extract all news articles on this page. For each article, provide:
    - Headline
    - Summary (1-2 sentences)
    - Author
    - Publication time
    - Category
    - Link to full article
    
    Return as a JSON array of articles.
    """
})

articles = result.json()["extracted_data"]
print(f"Found {len(articles)} articles")
```

### Real Estate Listing Scraper

```python
import requests

BASE_URL = "http://localhost:8000"

def scrape_listing(url):
    return requests.post(f"{BASE_URL}/scrape", json={
        "url": url,
        "scraping_type": "full",
        "use_browser": True,  # Many real estate sites use JS
        "extract_images": True,
        "css_selectors": {
            "address": ".property-address",
            "price": ".listing-price"
        },
        "llm_extraction_prompt": """
        Extract property details:
        - Address
        - Price
        - Bedrooms and bathrooms
        - Square footage
        - Property type (house, apartment, etc.)
        - Year built
        - Key features and amenities
        - Description summary
        """
    }).json()

# Scrape multiple listings
listings = [
    scrape_listing("https://realestate.example.com/listing/1"),
    scrape_listing("https://realestate.example.com/listing/2")
]
```

### Job Posting Aggregator

```python
import requests

BASE_URL = "http://localhost:8000"

def scrape_job_board(url):
    # First discover all job postings
    discovery = requests.post(f"{BASE_URL}/scrape", json={
        "url": url,
        "scraping_type": "discovery",
        "max_depth": 1,
        "follow_links": True
    })
    
    job_urls = [u for u in discovery.json()["links"] if "/job/" in u]
    
    # Then extract details from each
    jobs = []
    for job_url in job_urls:
        result = requests.post(f"{BASE_URL}/scrape", json={
            "url": job_url,
            "scraping_type": "extraction",
            "llm_extraction_prompt": """
            Extract job posting information:
            - Job title
            - Company name
            - Location (remote/hybrid/on-site)
            - Salary range (if mentioned)
            - Required experience level
            - Key requirements (as bullet list)
            - Key responsibilities (as bullet list)
            - Application deadline
            """
        })
        jobs.append(result.json()["extracted_data"])
    
    return jobs

jobs = scrape_job_board("https://jobs.example.com")
```

### Recipe Collection

```bash
# Scrape recipe with images
curl -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://recipes.example.com/chocolate-cake",
    "scraping_type": "full",
    "extract_images": true,
    "llm_extraction_prompt": "Extract: recipe title, prep time, cook time, servings, ingredients (as list), instructions (as numbered steps), nutrition info, and tips/notes."
  }'
```

### Academic Paper Scraper

```python
import requests

BASE_URL = "http://localhost:8000"

def scrape_paper(url):
    result = requests.post(f"{BASE_URL}/scrape", json={
        "url": url,
        "scraping_type": "extraction",
        "llm_extraction_prompt": """
        Extract academic paper metadata:
        - Title
        - Authors (list)
        - Publication date
        - Abstract
        - Keywords
        - Main contributions (bullet list)
        - Methodology summary
        - Key findings (bullet list)
        - DOI or arxiv ID
        """
    })
    
    paper_data = result.json()["extracted_data"]
    
    # Extract figures and charts
    vision_result = requests.post("http://localhost:8003/describe", json={
        "image_urls": result.json()["images"][:5]  # First 5 images
    })
    
    paper_data["figures"] = vision_result.json()["results"]
    
    return paper_data
```

### Social Media Profile Scraper

```bash
curl -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://social.example.com/profile/username",
    "use_browser": true,
    "wait_for_selector": ".profile-loaded",
    "scraping_type": "extraction",
    "llm_extraction_prompt": "Extract profile information: name, username, bio, follower count, following count, verified status, website links, and recent posts."
  }'
```

---

## Batch Processing

### Process Multiple URLs

```python
import requests
import concurrent.futures

BASE_URL = "http://localhost:8000"

urls = [
    "https://example.com/page1",
    "https://example.com/page2",
    "https://example.com/page3",
]

def scrape_url(url):
    return requests.post(f"{BASE_URL}/scrape", json={
        "url": url,
        "scraping_type": "extraction"
    }).json()

# Parallel processing
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
    results = list(executor.map(scrape_url, urls))

print(f"Processed {len(results)} URLs")
```

---

## Model Management

### Download Required Models

```bash
# Download specific models
curl -X POST http://localhost:8000/models/download \
  -H "Content-Type: application/json" \
  -d '{
    "models": ["llava", "llama3.1", "bge-m3", "deepseek-coder"]
  }'

# Check download status
curl http://localhost:8005/models/download/status

# List available models
curl http://localhost:8000/models
```

### Using Different Models

```bash
# Use Qwen vision model instead of Llava
curl -X POST http://localhost:8003/describe \
  -H "Content-Type: application/json" \
  -d '{
    "image_urls": ["https://example.com/image.jpg"],
    "model": "qwen3-vl"
  }'
```

---

## Python SDK Example

Create a simple Python wrapper:

```python
import requests
from typing import List, Dict, Any, Optional

class WebScraperClient:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
    
    def scrape(
        self,
        url: str,
        scraping_type: str = "full",
        use_browser: bool = False,
        llm_prompt: Optional[str] = None,
        css_selectors: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Scrape a URL"""
        payload = {
            "url": url,
            "scraping_type": scraping_type,
            "use_browser": use_browser,
        }
        
        if llm_prompt:
            payload["llm_extraction_prompt"] = llm_prompt
        
        if css_selectors:
            payload["css_selectors"] = css_selectors
        
        response = requests.post(f"{self.base_url}/scrape", json=payload)
        response.raise_for_status()
        return response.json()
    
    def list_models(self) -> List[Dict[str, Any]]:
        """List available AI models"""
        response = requests.get(f"{self.base_url}/models")
        response.raise_for_status()
        return response.json()
    
    def download_models(self, models: List[str]) -> Dict[str, Any]:
        """Download AI models"""
        response = requests.post(
            f"{self.base_url}/models/download",
            json={"models": models}
        )
        response.raise_for_status()
        return response.json()

# Usage
client = WebScraperClient()

# Scrape a page
result = client.scrape(
    url="https://example.com",
    llm_prompt="Extract main content and summarize"
)

print(result["extracted_data"])
```

---

## Tips and Best Practices

1. **Use Browser Automation Sparingly**: Only enable `use_browser` when necessary, as it's slower and more resource-intensive

2. **Specific LLM Prompts**: Be specific in your extraction prompts for better results

3. **CSS Selectors First**: Use CSS selectors for structured data when possible, then enhance with LLM

4. **Rate Limiting**: Implement delays between requests to avoid overwhelming target sites

5. **Error Handling**: Always check response status and handle errors gracefully

6. **Model Selection**: Choose appropriate models based on task complexity

7. **Batch Processing**: Use concurrent requests for better throughput

---

For more information, see [API_DOCUMENTATION.md](API_DOCUMENTATION.md)
