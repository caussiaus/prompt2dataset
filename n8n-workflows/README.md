# n8n Workflow Templates

This directory contains pre-built n8n workflows for common web scraping scenarios.

## 📥 How to Import

1. Access your n8n instance at `http://your-domain:5678`
2. Click **Workflows** → **Import from File**
3. Select a `.json` file from the examples below
4. Activate the workflow

## 🎯 Available Workflows

### 1. Simple URL Scraper (`simple-url-scraper.json`)
**Use Case**: Scrape a single URL with full pipeline

**Triggers**: Manual or Webhook
**Steps**:
- Accepts URL input
- Calls Gateway API for full scrape
- Returns structured data

**Configuration**:
- Set your gateway URL in HTTP Request node
- Customize extraction schema

---

### 2. Product Price Monitor (`product-price-monitor.json`)
**Use Case**: Monitor product prices and get alerts

**Triggers**: Schedule (every hour)
**Steps**:
- Load product URLs from database
- Scrape each product page
- Extract price, stock, title
- Compare with previous price
- Send alert if price changed

**Configuration**:
- Set MongoDB connection
- Configure alert webhook/email
- Add product URLs to monitor

---

### 3. News Article Aggregator (`news-aggregator.json`)
**Use Case**: Discover and extract news articles

**Triggers**: Schedule (daily)
**Steps**:
- Discovery: Find article URLs
- Extract article content (title, author, date, body)
- Take screenshots for archives
- Store in database with embeddings

**Configuration**:
- Set news site URLs
- Configure extraction schema for articles
- Set storage destination

---

### 4. E-commerce Product Catalog (`ecommerce-catalog.json`)
**Use Case**: Build product catalog from online stores

**Triggers**: Webhook
**Steps**:
- Discovery: Find all product pages
- Render with Camoufox (JavaScript-heavy sites)
- Vision: Extract from product images
- Extraction: Structured product data
- Export to CSV/JSON

**Configuration**:
- Set category/search URLs
- Define product schema
- Configure export format

---

### 5. Real Estate Listings (`real-estate-listings.json`)
**Use Case**: Collect property listings with images

**Triggers**: Schedule
**Steps**:
- Discover property URLs
- Screenshot property pages
- OCR on images (extract details from photos)
- Extract structured property data
- Store with geolocation

**Configuration**:
- Set real estate site URL
- Configure location filters
- Define property schema

---

### 6. Job Posting Scraper (`job-posting-scraper.json`)
**Use Case**: Aggregate job postings from multiple sites

**Triggers**: Schedule (every 6 hours)
**Steps**:
- Discover new job postings
- Extract job details (title, company, salary, requirements)
- Generate embeddings for semantic search
- Store in database
- Deduplicate similar jobs

**Configuration**:
- Add job board URLs
- Set search keywords/filters
- Configure deduplication logic

---

## 🔗 Connecting to Services

### Gateway API Connection

All workflows connect to the Gateway API:

```
HTTP Request Node Settings:
URL: http://agent-gateway:8000/scrape
Method: POST
Body:
{
  "url": "{{$json.url}}",
  "strategy": "full",
  "use_vision": true
}
```

### MongoDB Connection

For storing results:

```
MongoDB Node Settings:
Host: mongodb
Port: 27017
Database: webscraper
Username: admin
Password: [from .env]
```

### Individual Agent Connections

For advanced workflows:

```
Discovery: http://agent-discovery:8001/discover
Camoufox: http://agent-camoufox:8002/render
Vision: http://agent-vision:8003/process
Extraction: http://agent-extraction:8004/extract
```

---

## 🎨 Creating Custom Workflows

### Basic Structure

```
[Trigger] 
  → [Get URLs]
  → [Call Gateway/Agent]
  → [Process Results]
  → [Store/Export Data]
```

### Best Practices

1. **Use Error Handlers**: Add error handling nodes
2. **Batch Processing**: Use Loop nodes for multiple URLs
3. **Rate Limiting**: Add delays between requests
4. **Data Validation**: Validate extracted data
5. **Idempotency**: Check if data already exists before storing

### Example: Custom Product Scraper

```json
{
  "name": "Custom Product Scraper",
  "nodes": [
    {
      "name": "Schedule Trigger",
      "type": "n8n-nodes-base.scheduleTrigger",
      "parameters": {
        "rule": {
          "interval": [{ "field": "hours", "value": 6 }]
        }
      }
    },
    {
      "name": "Get Product URLs",
      "type": "n8n-nodes-base.mongoDb",
      "parameters": {
        "operation": "find",
        "collection": "products"
      }
    },
    {
      "name": "Scrape Products",
      "type": "n8n-nodes-base.httpRequest",
      "parameters": {
        "url": "http://agent-gateway:8000/scrape",
        "method": "POST",
        "jsonParameters": true,
        "bodyParametersJson": {
          "url": "={{$json.product_url}}",
          "strategy": "extraction",
          "extract_schema": {
            "product_name": "string",
            "price": "number",
            "in_stock": "boolean"
          }
        }
      }
    },
    {
      "name": "Store Results",
      "type": "n8n-nodes-base.mongoDb",
      "parameters": {
        "operation": "insert",
        "collection": "scrape_results"
      }
    }
  ]
}
```

---

## 📖 Advanced Examples

### Using Vision for Screenshot Analysis

```javascript
// In Function node
const screenshotData = {
  url: items[0].json.url,
  screenshot: items[0].json.screenshot,
  tasks: ["ocr", "describe", "extract_tables"]
};

return [{ json: screenshotData }];
```

### Parallel Processing Multiple URLs

```javascript
// Use Split In Batches node
{
  "batchSize": 5, // Process 5 URLs at a time
  "options": {}
}
```

### Conditional Extraction Based on Content

```javascript
// In IF node
if ({{$json.results.render.html}}.includes("product-page")) {
  return [{ json: { strategy: "product" } }];
} else if ({{$json.results.render.html}}.includes("article")) {
  return [{ json: { strategy: "article" } }];
}
```

---

## 🚀 Pro Tips

1. **Test with Single URL First**: Before scheduling, test workflows manually
2. **Monitor Resource Usage**: Check Docker stats during runs
3. **Use Webhooks for Real-time**: Trigger scrapes via webhooks
4. **Cache Rendered Pages**: Store Camoufox results to reduce re-rendering
5. **Incremental Scraping**: Only scrape new/changed content

---

## 🤝 Contributing Workflows

Share your workflow:

1. Export from n8n (Workflow → Download)
2. Add to `community/` folder
3. Create README with:
   - Use case description
   - Required configuration
   - Expected input/output
4. Submit PR

---

## 📚 Resources

- [n8n Documentation](https://docs.n8n.io/)
- [Agent API Docs](http://your-domain:8000/docs)
- [Workflow Examples](./examples/)
- [Community Workflows](./community/)

---

**Happy Scraping! 🎉**
