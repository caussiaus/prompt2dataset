#!/usr/bin/env python3
"""
Extraction Agent Service
Handles data extraction from web pages using LLMs
"""
import os
import logging
import requests
from flask import Flask, request, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import json

# Configure logging
logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Service URLs
HTML_PARSER_URL = os.getenv('HTML_PARSER_URL', 'http://html-parser:5000')
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

def extract_with_llm(text, extraction_schema):
    """
    Use Ollama LLM to extract structured data from text
    
    Args:
        text: Text content to extract from
        extraction_schema: Schema defining what to extract
    
    Returns:
        Extracted data as dict
    """
    try:
        prompt = f"""Extract the following information from the text below.
        
Schema: {json.dumps(extraction_schema, indent=2)}

Text:
{text[:4000]}  # Limit context size

Return ONLY a valid JSON object matching the schema. Do not include explanations."""

        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": "mistral:latest",
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "top_p": 0.9
                }
            },
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            generated_text = result.get('response', '{}')
            
            # Try to parse JSON from response
            try:
                # Find JSON in response
                start = generated_text.find('{')
                end = generated_text.rfind('}') + 1
                if start >= 0 and end > start:
                    json_str = generated_text[start:end]
                    extracted_data = json.loads(json_str)
                    return extracted_data
                else:
                    logger.warning("No JSON found in LLM response")
                    return {}
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse LLM response as JSON: {e}")
                return {}
        else:
            logger.error(f"Ollama API error: {response.status_code}")
            return {}
            
    except Exception as e:
        logger.error(f"LLM extraction error: {e}")
        return {}

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    db_status = "healthy"
    html_parser_status = "healthy"
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
        resp = requests.get(f"{HTML_PARSER_URL}/health", timeout=5)
        if resp.status_code != 200:
            html_parser_status = "unavailable"
    except:
        html_parser_status = "error"
    
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if resp.status_code != 200:
            ollama_status = "unavailable"
    except:
        ollama_status = "error"
    
    return jsonify({
        'status': 'healthy',
        'service': 'extraction-agent',
        'version': '1.0.0',
        'dependencies': {
            'database': db_status,
            'html_parser': html_parser_status,
            'ollama': ollama_status
        },
        'timestamp': datetime.utcnow().isoformat()
    }), 200

@app.route('/extract', methods=['POST'])
def extract():
    """
    Extract structured data from URL or HTML
    
    Request body:
    {
        "url": "https://example.com",  # Optional if html provided
        "html": "<html>...</html>",     # Optional if url provided
        "schema": {
            "title": "string",
            "price": "number",
            "description": "string"
        },
        "store": true  # Optional: store results in database
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'error': 'Missing request body',
                'status': 'error'
            }), 400
        
        html_content = data.get('html')
        url = data.get('url')
        extraction_schema = data.get('schema', {})
        
        # Fetch HTML if URL provided
        if url and not html_content:
            try:
                resp = requests.get(url, timeout=30)
                html_content = resp.text
            except Exception as e:
                return jsonify({
                    'error': f'Failed to fetch URL: {str(e)}',
                    'status': 'error'
                }), 400
        
        if not html_content:
            return jsonify({
                'error': 'Either url or html must be provided',
                'status': 'error'
            }), 400
        
        # Parse HTML
        try:
            parse_resp = requests.post(
                f"{HTML_PARSER_URL}/parse",
                json={
                    'html': html_content,
                    'options': {
                        'extract_links': True,
                        'extract_images': True
                    }
                },
                timeout=30
            )
            
            if parse_resp.status_code != 200:
                raise Exception(f"HTML parser error: {parse_resp.status_code}")
            
            parsed_data = parse_resp.json().get('data', {})
            text_content = parsed_data.get('text', '')
            
        except Exception as e:
            logger.error(f"HTML parsing failed: {e}")
            return jsonify({
                'error': f'HTML parsing failed: {str(e)}',
                'status': 'error'
            }), 500
        
        # Extract structured data using LLM if schema provided
        extracted_data = {}
        if extraction_schema:
            extracted_data = extract_with_llm(text_content, extraction_schema)
        
        # Combine results
        result = {
            'url': url,
            'parsed': parsed_data,
            'extracted': extracted_data,
            'extracted_at': datetime.utcnow().isoformat()
        }
        
        # Store in database if requested
        if data.get('store', False):
            try:
                conn = get_db_connection()
                if conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS extractions (
                            id SERIAL PRIMARY KEY,
                            url TEXT,
                            schema JSONB,
                            extracted_data JSONB,
                            parsed_data JSONB,
                            extracted_at TIMESTAMP DEFAULT NOW()
                        )
                    """)
                    
                    cursor.execute("""
                        INSERT INTO extractions (url, schema, extracted_data, parsed_data)
                        VALUES (%s, %s, %s, %s)
                    """, (
                        url,
                        psycopg2.extras.Json(extraction_schema),
                        psycopg2.extras.Json(extracted_data),
                        psycopg2.extras.Json(parsed_data)
                    ))
                    
                    conn.commit()
                    cursor.close()
                    conn.close()
                    
                    logger.info(f"Stored extraction for URL: {url}")
            except Exception as e:
                logger.error(f"Database storage error: {e}")
        
        return jsonify({
            'status': 'success',
            'data': result
        }), 200
        
    except Exception as e:
        logger.error(f"Extract endpoint error: {e}")
        return jsonify({
            'error': str(e),
            'status': 'error'
        }), 500

@app.route('/batch-extract', methods=['POST'])
def batch_extract():
    """
    Extract data from multiple URLs
    
    Request body:
    {
        "urls": ["url1", "url2", ...],
        "schema": {...},
        "store": true
    }
    """
    try:
        data = request.get_json()
        urls = data.get('urls', [])
        schema = data.get('schema', {})
        store = data.get('store', False)
        
        results = []
        for url in urls:
            try:
                resp = requests.post(
                    f"http://localhost:{os.getenv('PORT', 8001)}/extract",
                    json={
                        'url': url,
                        'schema': schema,
                        'store': store
                    },
                    timeout=60
                )
                if resp.status_code == 200:
                    results.append({
                        'url': url,
                        'status': 'success',
                        'data': resp.json().get('data')
                    })
                else:
                    results.append({
                        'url': url,
                        'status': 'error',
                        'error': resp.text
                    })
            except Exception as e:
                results.append({
                    'url': url,
                    'status': 'error',
                    'error': str(e)
                })
        
        return jsonify({
            'status': 'success',
            'results': results,
            'total': len(urls),
            'successful': len([r for r in results if r['status'] == 'success'])
        }), 200
        
    except Exception as e:
        logger.error(f"Batch extract error: {e}")
        return jsonify({
            'error': str(e),
            'status': 'error'
        }), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8001))
    logger.info(f"Starting Extraction Agent Service on port {port}")
    app.run(host='0.0.0.0', port=port, debug=os.getenv('LOG_LEVEL') == 'DEBUG')
