#!/usr/bin/env python3
"""
Discovery Agent
Discovers and monitors services, finds related content
"""
import os
import logging
import requests
from flask import Flask, request, jsonify
from datetime import datetime
import json
from urllib.parse import urljoin, urlparse

# Configure logging
logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'))
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
SEARXNG_URL = os.getenv('SEARXNG_URL', 'http://searxng:8888')
SERVICES_CONFIG = os.getenv('SERVICES_CONFIG', '/app/services.json')

def load_services_config():
    """Load services configuration"""
    try:
        with open(SERVICES_CONFIG, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load services config: {e}")
        return {}

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    searxng_status = "healthy"
    
    try:
        response = requests.get(SEARXNG_URL, timeout=5)
        if response.status_code != 200:
            searxng_status = "unhealthy"
    except Exception as e:
        logger.error(f"SearxNG health check failed: {e}")
        searxng_status = "unhealthy"
    
    return jsonify({
        "status": "healthy" if searxng_status == "healthy" else "degraded",
        "service": "discovery-agent",
        "timestamp": datetime.utcnow().isoformat(),
        "dependencies": {
            "searxng": searxng_status
        }
    })

@app.route('/discover', methods=['POST'])
def discover():
    """Discover related content using search"""
    try:
        data = request.get_json()
        query = data.get('query')
        source_url = data.get('source_url')
        limit = data.get('limit', 10)
        
        if not query:
            return jsonify({"error": "No query provided"}), 400
        
        # Search using SearxNG
        search_params = {
            'q': query,
            'format': 'json',
            'pageno': 1
        }
        
        response = requests.get(
            f"{SEARXNG_URL}/search",
            params=search_params,
            timeout=30
        )
        
        if response.status_code != 200:
            return jsonify({"error": "Search failed"}), 500
        
        search_results = response.json()
        
        # Extract URLs from results
        urls = []
        for result in search_results.get('results', [])[:limit]:
            urls.append({
                "url": result.get('url'),
                "title": result.get('title'),
                "description": result.get('content', ''),
                "engine": result.get('engine', '')
            })
        
        logger.info(f"Discovered {len(urls)} URLs for query: {query}")
        
        return jsonify({
            "query": query,
            "source_url": source_url,
            "urls": urls,
            "total": len(urls),
            "timestamp": datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"Error in discovery: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/services', methods=['GET'])
def list_services():
    """List all registered services"""
    try:
        config = load_services_config()
        services = config.get('services', {})
        
        service_list = []
        for service_id, service_info in services.items():
            service_list.append({
                "id": service_id,
                "name": service_info.get('name'),
                "type": service_info.get('type'),
                "port": service_info.get('port'),
                "status": service_info.get('status'),
                "health_check": service_info.get('health_check')
            })
        
        return jsonify({
            "services": service_list,
            "total": len(service_list)
        }), 200
        
    except Exception as e:
        logger.error(f"Error listing services: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/services/status', methods=['GET'])
def check_services_status():
    """Check status of all services"""
    try:
        config = load_services_config()
        services = config.get('services', {})
        
        statuses = {}
        for service_id, service_info in services.items():
            health_check_url = service_info.get('health_check')
            
            if not health_check_url:
                statuses[service_id] = "unknown"
                continue
            
            try:
                # Ensure URL is properly formatted
                if not health_check_url.startswith('http'):
                    health_check_url = f"http://{health_check_url}"
                
                response = requests.get(health_check_url, timeout=5)
                statuses[service_id] = "healthy" if response.status_code == 200 else "unhealthy"
            except Exception as e:
                logger.warning(f"Health check failed for {service_id}: {e}")
                statuses[service_id] = "unhealthy"
        
        overall_healthy = sum(1 for s in statuses.values() if s == "healthy")
        overall_total = len(statuses)
        
        return jsonify({
            "statuses": statuses,
            "healthy": overall_healthy,
            "total": overall_total,
            "timestamp": datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"Error checking services status: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/extract-links', methods=['POST'])
def extract_links():
    """Extract links from a webpage"""
    try:
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            return jsonify({"error": "No URL provided"}), 400
        
        # Fetch the page
        response = requests.get(url, timeout=30)
        html_content = response.text
        
        # Parse and extract links
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_content, 'html.parser')
        
        links = []
        for a in soup.find_all('a', href=True):
            href = a.get('href')
            # Convert relative URLs to absolute
            absolute_url = urljoin(url, href)
            
            # Filter out non-http(s) links
            parsed = urlparse(absolute_url)
            if parsed.scheme in ['http', 'https']:
                links.append({
                    "url": absolute_url,
                    "text": a.get_text(strip=True),
                    "title": a.get('title', '')
                })
        
        logger.info(f"Extracted {len(links)} links from {url}")
        
        return jsonify({
            "url": url,
            "links": links,
            "total": len(links),
            "timestamp": datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"Error extracting links: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8004))
    app.run(host='0.0.0.0', port=port)
