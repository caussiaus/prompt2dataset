#!/usr/bin/env python3
"""
HTML Parser Service
Parses HTML content and extracts structured data
"""
import os
import logging
from flask import Flask, request, jsonify
from bs4 import BeautifulSoup
import psycopg2
from datetime import datetime

# Configure logging
logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'))
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Database connection
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
    try:
        conn = get_db_connection()
        if conn:
            conn.close()
        else:
            db_status = "unhealthy"
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        db_status = "unhealthy"
    
    return jsonify({
        "status": "healthy" if db_status == "healthy" else "degraded",
        "service": "html-parser",
        "timestamp": datetime.utcnow().isoformat(),
        "database": db_status
    })

@app.route('/parse', methods=['POST'])
def parse_html():
    """Parse HTML content and extract data"""
    try:
        data = request.get_json()
        html_content = data.get('html')
        parser = data.get('parser', 'html.parser')
        
        if not html_content:
            return jsonify({"error": "No HTML content provided"}), 400
        
        # Parse HTML
        soup = BeautifulSoup(html_content, parser)
        
        # Extract structured data
        result = {
            "title": soup.title.string if soup.title else None,
            "headings": {
                "h1": [h.get_text(strip=True) for h in soup.find_all('h1')],
                "h2": [h.get_text(strip=True) for h in soup.find_all('h2')],
                "h3": [h.get_text(strip=True) for h in soup.find_all('h3')]
            },
            "links": [
                {"text": a.get_text(strip=True), "href": a.get('href')}
                for a in soup.find_all('a', href=True)
            ],
            "images": [
                {"alt": img.get('alt', ''), "src": img.get('src')}
                for img in soup.find_all('img')
            ],
            "paragraphs": [p.get_text(strip=True) for p in soup.find_all('p')],
            "meta": {
                meta.get('name', meta.get('property', '')): meta.get('content', '')
                for meta in soup.find_all('meta') if meta.get('content')
            }
        }
        
        logger.info(f"Successfully parsed HTML document")
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Error parsing HTML: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/extract', methods=['POST'])
def extract_text():
    """Extract clean text from HTML"""
    try:
        data = request.get_json()
        html_content = data.get('html')
        
        if not html_content:
            return jsonify({"error": "No HTML content provided"}), 400
        
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()
        
        # Get text
        text = soup.get_text()
        
        # Clean up whitespace
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)
        
        return jsonify({"text": text}), 200
        
    except Exception as e:
        logger.error(f"Error extracting text: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
