#!/usr/bin/env python3
"""
Extraction Agent
Extracts and processes data from parsed HTML
"""
import os
import logging
import requests
from flask import Flask, request, jsonify
from datetime import datetime
import psycopg2
import json

# Configure logging
logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'))
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
HTML_PARSER_URL = os.getenv('HTML_PARSER_URL', 'http://html-parser:5000')

def get_db_connection():
    """Get database connection"""
    try:
        conn = psycopg2.connect(
            host=os.getenv('DB_HOST', 'postgres'),
            port=os.getenv('DB_PORT', '5432'),
            database=os.getenv('DB_NAME', 'app_db'),
            user=os.getenv('DB_USER', 'postgres'),
            password=os.getenv('DB_PASSWORD', 'changeme')
        )
        return conn
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        return None

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    db_status = "healthy"
    parser_status = "healthy"
    
    try:
        conn = get_db_connection()
        if conn:
            conn.close()
        else:
            db_status = "unhealthy"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        db_status = "unhealthy"
    
    try:
        response = requests.get(f"{HTML_PARSER_URL}/health", timeout=5)
        if response.status_code != 200:
            parser_status = "unhealthy"
    except Exception as e:
        logger.error(f"HTML Parser health check failed: {e}")
        parser_status = "unhealthy"
    
    overall_status = "healthy" if all([db_status == "healthy", parser_status == "healthy"]) else "degraded"
    
    return jsonify({
        "status": overall_status,
        "service": "extraction-agent",
        "timestamp": datetime.utcnow().isoformat(),
        "dependencies": {
            "database": db_status,
            "html_parser": parser_status
        }
    })

@app.route('/extract', methods=['POST'])
def extract():
    """Extract data from URL or HTML content"""
    try:
        data = request.get_json()
        html_content = data.get('html')
        url = data.get('url')
        extract_type = data.get('type', 'full')
        
        if not html_content and not url:
            return jsonify({"error": "No HTML content or URL provided"}), 400
        
        # If URL provided, fetch content
        if url and not html_content:
            try:
                response = requests.get(url, timeout=30)
                html_content = response.text
            except Exception as e:
                logger.error(f"Error fetching URL: {e}")
                return jsonify({"error": f"Failed to fetch URL: {str(e)}"}), 500
        
        # Parse HTML using parser service
        parse_response = requests.post(
            f"{HTML_PARSER_URL}/parse",
            json={"html": html_content},
            timeout=30
        )
        
        if parse_response.status_code != 200:
            return jsonify({"error": "Failed to parse HTML"}), 500
        
        parsed_data = parse_response.json()
        
        # Extract specific data based on type
        if extract_type == 'links':
            result = {"links": parsed_data.get('links', [])}
        elif extract_type == 'text':
            text_response = requests.post(
                f"{HTML_PARSER_URL}/extract",
                json={"html": html_content},
                timeout=30
            )
            result = text_response.json()
        else:
            result = parsed_data
        
        # Store extraction in database
        try:
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS extractions (
                        id SERIAL PRIMARY KEY,
                        url TEXT,
                        extract_type VARCHAR(50),
                        data JSONB,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                cursor.execute(
                    "INSERT INTO extractions (url, extract_type, data) VALUES (%s, %s, %s)",
                    (url, extract_type, json.dumps(result))
                )
                conn.commit()
                cursor.close()
                conn.close()
        except Exception as e:
            logger.error(f"Error storing extraction: {e}")
        
        logger.info(f"Successfully extracted data from {url or 'HTML content'}")
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Error in extraction: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/extractions', methods=['GET'])
def get_extractions():
    """Get recent extractions"""
    try:
        limit = request.args.get('limit', 10, type=int)
        
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, url, extract_type, data, created_at FROM extractions ORDER BY created_at DESC LIMIT %s",
            (limit,)
        )
        
        extractions = []
        for row in cursor.fetchall():
            extractions.append({
                "id": row[0],
                "url": row[1],
                "extract_type": row[2],
                "data": row[3],
                "created_at": row[4].isoformat()
            })
        
        cursor.close()
        conn.close()
        
        return jsonify({"extractions": extractions}), 200
        
    except Exception as e:
        logger.error(f"Error fetching extractions: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8001))
    app.run(host='0.0.0.0', port=port)
