#!/usr/bin/env python3
"""
Vision Agent Service
Processes images and visual content using vision models
"""
import os
import logging
import requests
import base64
from io import BytesIO
from flask import Flask, request, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from PIL import Image

# Configure logging
logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Service URLs
OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://ollama:11434')

def get_db_connection():
    """Get PostgreSQL database connection"""
    try:
        conn = psycopg2.connect(
            host=os.getenv('DB_HOST', 'postgres'),
            port=os.getenv('DB_PORT', '5432'),
            database=os.getenv('DB_NAME', 'app_db'),
            user=os.getenv('DB_USER', 'postgres'),
            password=os.getenv('DB_PASSWORD', '')
        )
        return conn
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return None

def analyze_image_with_vision_model(image_data, prompt):
    """
    Analyze image using Ollama vision model
    
    Args:
        image_data: Base64 encoded image or image URL
        prompt: Analysis prompt
    
    Returns:
        Analysis results as dict
    """
    try:
        # Use LLaVA or similar vision model via Ollama
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": "llava:latest",  # Vision-capable model
                "prompt": prompt,
                "images": [image_data],
                "stream": False
            },
            timeout=120  # Vision models take longer
        )
        
        if response.status_code == 200:
            result = response.json()
            return {
                'description': result.get('response', ''),
                'model': 'llava:latest',
                'analyzed_at': datetime.utcnow().isoformat()
            }
        else:
            logger.error(f"Ollama vision API error: {response.status_code}")
            return {
                'error': f'Vision API error: {response.status_code}',
                'analyzed_at': datetime.utcnow().isoformat()
            }
            
    except Exception as e:
        logger.error(f"Image analysis error: {e}")
        return {
            'error': str(e),
            'analyzed_at': datetime.utcnow().isoformat()
        }

def process_image(image_source, source_type='url'):
    """
    Process and prepare image for analysis
    
    Args:
        image_source: URL or base64 data
        source_type: 'url' or 'base64'
    
    Returns:
        Base64 encoded image
    """
    try:
        if source_type == 'url':
            response = requests.get(image_source, timeout=30)
            image_data = base64.b64encode(response.content).decode('utf-8')
        else:
            image_data = image_source
        
        return image_data
        
    except Exception as e:
        logger.error(f"Image processing error: {e}")
        raise

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    db_status = "healthy"
    ollama_status = "healthy"
    
    try:
        conn = get_db_connection()
        if conn:
            conn.close()
        else:
            db_status = "unavailable"
    except:
        db_status = "error"
    
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if resp.status_code != 200:
            ollama_status = "unavailable"
    except:
        ollama_status = "error"
    
    return jsonify({
        'status': 'healthy',
        'service': 'vision-agent',
        'version': '1.0.0',
        'dependencies': {
            'database': db_status,
            'ollama': ollama_status
        },
        'timestamp': datetime.utcnow().isoformat()
    }), 200

@app.route('/analyze-image', methods=['POST'])
def analyze_image():
    """
    Analyze image content
    
    Request body:
    {
        "image_url": "https://example.com/image.jpg",  # Or use image_data
        "image_data": "base64_encoded_image",          # Alternative to image_url
        "prompt": "Describe this image in detail",
        "store": true  # Optional: store results
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'error': 'Missing request body',
                'status': 'error'
            }), 400
        
        image_url = data.get('image_url')
        image_data = data.get('image_data')
        prompt = data.get('prompt', 'Describe this image in detail.')
        
        if not image_url and not image_data:
            return jsonify({
                'error': 'Either image_url or image_data must be provided',
                'status': 'error'
            }), 400
        
        # Process image
        try:
            if image_url:
                processed_image = process_image(image_url, 'url')
            else:
                processed_image = process_image(image_data, 'base64')
        except Exception as e:
            return jsonify({
                'error': f'Image processing failed: {str(e)}',
                'status': 'error'
            }), 400
        
        # Analyze with vision model
        analysis = analyze_image_with_vision_model(processed_image, prompt)
        
        result = {
            'image_url': image_url,
            'prompt': prompt,
            'analysis': analysis,
            'analyzed_at': datetime.utcnow().isoformat()
        }
        
        # Store in database if requested
        if data.get('store', False):
            try:
                conn = get_db_connection()
                if conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS vision_analyses (
                            id SERIAL PRIMARY KEY,
                            image_url TEXT,
                            prompt TEXT,
                            analysis JSONB,
                            analyzed_at TIMESTAMP DEFAULT NOW()
                        )
                    """)
                    
                    cursor.execute("""
                        INSERT INTO vision_analyses (image_url, prompt, analysis)
                        VALUES (%s, %s, %s)
                    """, (
                        image_url,
                        prompt,
                        psycopg2.extras.Json(analysis)
                    ))
                    
                    conn.commit()
                    cursor.close()
                    conn.close()
                    
                    logger.info(f"Stored vision analysis for: {image_url}")
            except Exception as e:
                logger.error(f"Database storage error: {e}")
        
        return jsonify({
            'status': 'success',
            'data': result
        }), 200
        
    except Exception as e:
        logger.error(f"Analyze image endpoint error: {e}")
        return jsonify({
            'error': str(e),
            'status': 'error'
        }), 500

@app.route('/batch-analyze', methods=['POST'])
def batch_analyze():
    """
    Analyze multiple images
    
    Request body:
    {
        "images": [
            {"url": "...", "prompt": "..."},
            {"url": "...", "prompt": "..."}
        ],
        "store": true
    }
    """
    try:
        data = request.get_json()
        images = data.get('images', [])
        store = data.get('store', False)
        
        results = []
        for img in images:
            try:
                resp = requests.post(
                    f"http://localhost:{os.getenv('PORT', 8002)}/analyze-image",
                    json={
                        'image_url': img.get('url'),
                        'image_data': img.get('data'),
                        'prompt': img.get('prompt', 'Describe this image.'),
                        'store': store
                    },
                    timeout=120
                )
                if resp.status_code == 200:
                    results.append({
                        'image': img.get('url') or 'base64_data',
                        'status': 'success',
                        'data': resp.json().get('data')
                    })
                else:
                    results.append({
                        'image': img.get('url') or 'base64_data',
                        'status': 'error',
                        'error': resp.text
                    })
            except Exception as e:
                results.append({
                    'image': img.get('url') or 'base64_data',
                    'status': 'error',
                    'error': str(e)
                })
        
        return jsonify({
            'status': 'success',
            'results': results,
            'total': len(images),
            'successful': len([r for r in results if r['status'] == 'success'])
        }), 200
        
    except Exception as e:
        logger.error(f"Batch analyze error: {e}")
        return jsonify({
            'error': str(e),
            'status': 'error'
        }), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8002))
    logger.info(f"Starting Vision Agent Service on port {port}")
    app.run(host='0.0.0.0', port=port, debug=os.getenv('LOG_LEVEL') == 'DEBUG')
