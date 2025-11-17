#!/usr/bin/env python3
"""
Agent Gateway
Central gateway for all agent services
"""
import os
import logging
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime
import json

# Configure logging
logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'))
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend access

# Configuration
SERVICES_CONFIG = os.getenv('SERVICES_CONFIG', '/app/services.json')
EXTRACTION_AGENT_URL = os.getenv('EXTRACTION_AGENT_URL', 'http://extraction-agent:8001')
VISION_AGENT_URL = os.getenv('VISION_AGENT_URL', 'http://vision-agent:8002')
ORCHESTRATOR_AGENT_URL = os.getenv('ORCHESTRATOR_AGENT_URL', 'http://orchestrator-agent:8003')
DISCOVERY_AGENT_URL = os.getenv('DISCOVERY_AGENT_URL', 'http://discovery-agent:8004')

def load_services_config():
    """Load services configuration"""
    try:
        with open(SERVICES_CONFIG, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load services config: {e}")
        return {}

@app.route('/', methods=['GET'])
def root():
    """Root endpoint"""
    return jsonify({
        "service": "agent-gateway",
        "version": "1.0.0",
        "status": "running",
        "timestamp": datetime.utcnow().isoformat(),
        "endpoints": {
            "health": "/health",
            "extract": "/api/extract",
            "analyze-image": "/api/analyze-image",
            "orchestrate": "/api/orchestrate",
            "discover": "/api/discover",
            "services": "/api/services"
        }
    })

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    services_status = {}
    
    for service_name, service_url in [
        ('extraction_agent', EXTRACTION_AGENT_URL),
        ('vision_agent', VISION_AGENT_URL),
        ('orchestrator_agent', ORCHESTRATOR_AGENT_URL),
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
        "service": "agent-gateway",
        "timestamp": datetime.utcnow().isoformat(),
        "agents": services_status
    })

@app.route('/api/extract', methods=['POST'])
def extract():
    """Extract data from URL or HTML"""
    try:
        data = request.get_json()
        
        response = requests.post(
            f"{EXTRACTION_AGENT_URL}/extract",
            json=data,
            timeout=60
        )
        
        return jsonify(response.json()), response.status_code
        
    except Exception as e:
        logger.error(f"Error in extract endpoint: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/analyze-image', methods=['POST'])
def analyze_image():
    """Analyze image using vision agent"""
    try:
        data = request.get_json()
        
        response = requests.post(
            f"{VISION_AGENT_URL}/analyze",
            json=data,
            timeout=60
        )
        
        return jsonify(response.json()), response.status_code
        
    except Exception as e:
        logger.error(f"Error in analyze-image endpoint: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/orchestrate', methods=['POST'])
def orchestrate():
    """Orchestrate complex workflows"""
    try:
        data = request.get_json()
        
        response = requests.post(
            f"{ORCHESTRATOR_AGENT_URL}/orchestrate",
            json=data,
            timeout=120
        )
        
        return jsonify(response.json()), response.status_code
        
    except Exception as e:
        logger.error(f"Error in orchestrate endpoint: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/discover', methods=['POST'])
def discover():
    """Discover related content"""
    try:
        data = request.get_json()
        
        response = requests.post(
            f"{DISCOVERY_AGENT_URL}/discover",
            json=data,
            timeout=60
        )
        
        return jsonify(response.json()), response.status_code
        
    except Exception as e:
        logger.error(f"Error in discover endpoint: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/services', methods=['GET'])
def list_services():
    """List all available services"""
    try:
        response = requests.get(
            f"{DISCOVERY_AGENT_URL}/services",
            timeout=10
        )
        
        return jsonify(response.json()), response.status_code
        
    except Exception as e:
        logger.error(f"Error listing services: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/services/status', methods=['GET'])
def services_status():
    """Get status of all services"""
    try:
        response = requests.get(
            f"{DISCOVERY_AGENT_URL}/services/status",
            timeout=10
        )
        
        return jsonify(response.json()), response.status_code
        
    except Exception as e:
        logger.error(f"Error getting services status: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/pipeline', methods=['POST'])
def run_pipeline():
    """Run a complete data extraction pipeline"""
    try:
        data = request.get_json()
        url = data.get('url')
        query = data.get('query', '')
        include_images = data.get('include_images', False)
        
        if not url:
            return jsonify({"error": "No URL provided"}), 400
        
        # Step 1: Extract data
        extraction_response = requests.post(
            f"{EXTRACTION_AGENT_URL}/extract",
            json={"url": url, "type": "full"},
            timeout=60
        )
        
        if extraction_response.status_code != 200:
            return jsonify({"error": "Extraction failed"}), 500
        
        result = {
            "url": url,
            "extraction": extraction_response.json()
        }
        
        # Step 2: Discover related content if query provided
        if query:
            discovery_response = requests.post(
                f"{DISCOVERY_AGENT_URL}/discover",
                json={"query": query, "source_url": url},
                timeout=60
            )
            if discovery_response.status_code == 200:
                result["discovery"] = discovery_response.json()
        
        # Step 3: Analyze images if requested
        if include_images:
            images = result["extraction"].get("images", [])
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
            
            result["analyzed_images"] = analyzed_images
        
        result["timestamp"] = datetime.utcnow().isoformat()
        
        logger.info(f"Pipeline completed successfully for {url}")
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Error in pipeline: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8000))
    app.run(host='0.0.0.0', port=port)
