#!/usr/bin/env python3
"""
Orchestrator Agent
Coordinates workflows across multiple agents
"""
import os
import logging
import requests
from flask import Flask, request, jsonify
from datetime import datetime
import asyncio
from concurrent.futures import ThreadPoolExecutor

# Configure logging
logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'))
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
EXTRACTION_AGENT_URL = os.getenv('EXTRACTION_AGENT_URL', 'http://extraction-agent:8001')
VISION_AGENT_URL = os.getenv('VISION_AGENT_URL', 'http://vision-agent:8002')
DISCOVERY_AGENT_URL = os.getenv('DISCOVERY_AGENT_URL', 'http://discovery-agent:8004')

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    services_status = {}
    
    for service_name, service_url in [
        ('extraction_agent', EXTRACTION_AGENT_URL),
        ('vision_agent', VISION_AGENT_URL),
        ('discovery_agent', DISCOVERY_AGENT_URL)
    ]:
        try:
            response = requests.get(f"{service_url}/health", timeout=5)
            services_status[service_name] = "healthy" if response.status_code == 200 else "unhealthy"
        except Exception as e:
            logger.error(f"{service_name} health check failed: {e}")
            services_status[service_name] = "unhealthy"
    
    overall_status = "healthy" if all(s == "healthy" for s in services_status.values()) else "degraded"
    
    return jsonify({
        "status": overall_status,
        "service": "orchestrator-agent",
        "timestamp": datetime.utcnow().isoformat(),
        "dependencies": services_status
    })

@app.route('/orchestrate', methods=['POST'])
def orchestrate():
    """Orchestrate a complex workflow"""
    try:
        data = request.get_json()
        workflow_type = data.get('workflow', 'extract-and-analyze')
        url = data.get('url')
        
        if not url:
            return jsonify({"error": "No URL provided"}), 400
        
        logger.info(f"Starting workflow '{workflow_type}' for URL: {url}")
        
        if workflow_type == 'extract-and-analyze':
            result = extract_and_analyze_workflow(url, data)
        elif workflow_type == 'discover-and-extract':
            result = discover_and_extract_workflow(url, data)
        elif workflow_type == 'full-analysis':
            result = full_analysis_workflow(url, data)
        else:
            return jsonify({"error": f"Unknown workflow type: {workflow_type}"}), 400
        
        logger.info(f"Workflow '{workflow_type}' completed successfully")
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Error in orchestration: {e}")
        return jsonify({"error": str(e)}), 500

def extract_and_analyze_workflow(url, data):
    """Extract content and analyze images"""
    # Step 1: Extract content
    extraction_response = requests.post(
        f"{EXTRACTION_AGENT_URL}/extract",
        json={"url": url, "type": "full"},
        timeout=60
    )
    
    if extraction_response.status_code != 200:
        raise Exception("Extraction failed")
    
    extracted_data = extraction_response.json()
    
    # Step 2: Analyze images if present
    images = extracted_data.get('images', [])
    analyzed_images = []
    
    for image in images[:5]:  # Limit to 5 images
        try:
            vision_response = requests.post(
                f"{VISION_AGENT_URL}/analyze",
                json={"image_url": image.get('src')},
                timeout=60
            )
            if vision_response.status_code == 200:
                analyzed_images.append({
                    "image": image,
                    "analysis": vision_response.json()
                })
        except Exception as e:
            logger.warning(f"Failed to analyze image: {e}")
    
    return {
        "workflow": "extract-and-analyze",
        "url": url,
        "extracted_data": extracted_data,
        "analyzed_images": analyzed_images,
        "timestamp": datetime.utcnow().isoformat()
    }

def discover_and_extract_workflow(url, data):
    """Discover related content and extract"""
    # Step 1: Discover related URLs
    query = data.get('query', '')
    discovery_response = requests.post(
        f"{DISCOVERY_AGENT_URL}/discover",
        json={"query": query, "source_url": url},
        timeout=60
    )
    
    discovered_urls = []
    if discovery_response.status_code == 200:
        discovered_urls = discovery_response.json().get('urls', [])
    
    # Step 2: Extract from discovered URLs
    extracted_data = []
    for discovered_url in discovered_urls[:3]:  # Limit to 3 URLs
        try:
            extraction_response = requests.post(
                f"{EXTRACTION_AGENT_URL}/extract",
                json={"url": discovered_url, "type": "full"},
                timeout=60
            )
            if extraction_response.status_code == 200:
                extracted_data.append({
                    "url": discovered_url,
                    "data": extraction_response.json()
                })
        except Exception as e:
            logger.warning(f"Failed to extract from {discovered_url}: {e}")
    
    return {
        "workflow": "discover-and-extract",
        "query": query,
        "discovered_urls": discovered_urls,
        "extracted_data": extracted_data,
        "timestamp": datetime.utcnow().isoformat()
    }

def full_analysis_workflow(url, data):
    """Full analysis with discovery, extraction, and vision"""
    # Combine all workflows
    query = data.get('query', '')
    
    # Run extraction and discovery in parallel
    with ThreadPoolExecutor(max_workers=2) as executor:
        extraction_future = executor.submit(
            requests.post,
            f"{EXTRACTION_AGENT_URL}/extract",
            json={"url": url, "type": "full"},
            timeout=60
        )
        
        discovery_future = executor.submit(
            requests.post,
            f"{DISCOVERY_AGENT_URL}/discover",
            json={"query": query, "source_url": url},
            timeout=60
        )
        
        extraction_response = extraction_future.result()
        discovery_response = discovery_future.result()
    
    extracted_data = extraction_response.json() if extraction_response.status_code == 200 else {}
    discovered_urls = discovery_response.json().get('urls', []) if discovery_response.status_code == 200 else []
    
    # Analyze images
    images = extracted_data.get('images', [])
    analyzed_images = []
    
    for image in images[:3]:  # Limit to 3 images
        try:
            vision_response = requests.post(
                f"{VISION_AGENT_URL}/analyze",
                json={"image_url": image.get('src')},
                timeout=60
            )
            if vision_response.status_code == 200:
                analyzed_images.append({
                    "image": image,
                    "analysis": vision_response.json()
                })
        except Exception as e:
            logger.warning(f"Failed to analyze image: {e}")
    
    return {
        "workflow": "full-analysis",
        "url": url,
        "extracted_data": extracted_data,
        "discovered_urls": discovered_urls,
        "analyzed_images": analyzed_images,
        "timestamp": datetime.utcnow().isoformat()
    }

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8003))
    app.run(host='0.0.0.0', port=port)
