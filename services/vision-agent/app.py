#!/usr/bin/env python3
"""
Vision Agent
Processes images and visual content using Ollama vision models
"""
import os
import logging
import requests
from flask import Flask, request, jsonify
from datetime import datetime
import base64
from io import BytesIO
from PIL import Image

# Configure logging
logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'))
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://ollama:11434')

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    ollama_status = "healthy"
    
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if response.status_code != 200:
            ollama_status = "unhealthy"
    except Exception as e:
        logger.error(f"Ollama health check failed: {e}")
        ollama_status = "unhealthy"
    
    return jsonify({
        "status": "healthy" if ollama_status == "healthy" else "degraded",
        "service": "vision-agent",
        "timestamp": datetime.utcnow().isoformat(),
        "dependencies": {
            "ollama": ollama_status
        }
    })

@app.route('/analyze', methods=['POST'])
def analyze_image():
    """Analyze image using vision model"""
    try:
        data = request.get_json()
        image_url = data.get('image_url')
        image_base64 = data.get('image_base64')
        prompt = data.get('prompt', 'Describe this image in detail.')
        model = data.get('model', 'llava:latest')
        
        if not image_url and not image_base64:
            return jsonify({"error": "No image URL or base64 data provided"}), 400
        
        # Fetch image if URL provided
        if image_url and not image_base64:
            try:
                response = requests.get(image_url, timeout=30)
                image_base64 = base64.b64encode(response.content).decode('utf-8')
            except Exception as e:
                logger.error(f"Error fetching image: {e}")
                return jsonify({"error": f"Failed to fetch image: {str(e)}"}), 500
        
        # Call Ollama vision API
        ollama_response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "images": [image_base64],
                "stream": False
            },
            timeout=60
        )
        
        if ollama_response.status_code != 200:
            return jsonify({"error": "Failed to analyze image"}), 500
        
        result = ollama_response.json()
        
        logger.info(f"Successfully analyzed image")
        return jsonify({
            "analysis": result.get('response', ''),
            "model": model,
            "prompt": prompt
        }), 200
        
    except Exception as e:
        logger.error(f"Error analyzing image: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/extract-text', methods=['POST'])
def extract_text_from_image():
    """Extract text from image (OCR)"""
    try:
        data = request.get_json()
        image_url = data.get('image_url')
        image_base64 = data.get('image_base64')
        
        if not image_url and not image_base64:
            return jsonify({"error": "No image URL or base64 data provided"}), 400
        
        # Fetch image if URL provided
        if image_url and not image_base64:
            try:
                response = requests.get(image_url, timeout=30)
                image_base64 = base64.b64encode(response.content).decode('utf-8')
            except Exception as e:
                logger.error(f"Error fetching image: {e}")
                return jsonify({"error": f"Failed to fetch image: {str(e)}"}), 500
        
        # Use vision model for OCR
        ollama_response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": "llava:latest",
                "prompt": "Extract all text from this image. Return only the text, without any additional commentary.",
                "images": [image_base64],
                "stream": False
            },
            timeout=60
        )
        
        if ollama_response.status_code != 200:
            return jsonify({"error": "Failed to extract text"}), 500
        
        result = ollama_response.json()
        
        logger.info(f"Successfully extracted text from image")
        return jsonify({
            "text": result.get('response', '')
        }), 200
        
    except Exception as e:
        logger.error(f"Error extracting text: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/models', methods=['GET'])
def list_models():
    """List available vision models"""
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=10)
        if response.status_code != 200:
            return jsonify({"error": "Failed to fetch models"}), 500
        
        models = response.json().get('models', [])
        vision_models = [m for m in models if 'llava' in m.get('name', '').lower() or 'vision' in m.get('name', '').lower()]
        
        return jsonify({"models": vision_models}), 200
        
    except Exception as e:
        logger.error(f"Error listing models: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8002))
    app.run(host='0.0.0.0', port=port)
