#!/usr/bin/env python3
"""
HTML Parser Service
Extracts structured data from HTML content
"""
import os
import logging
from flask import Flask, request, jsonify
from bs4 import BeautifulSoup
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Database connection
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

def parse_html(html_content, options=None):
    """
    Parse HTML content and extract structured data
    
    Args:
        html_content: Raw HTML string
        options: Dict with parsing options (parser, extract_links, etc.)
    
    Returns:
        Dict with parsed data
    """
    options = options or {}
    parser = options.get('parser', 'lxml')
    
    try:
        soup = BeautifulSoup(html_content, parser)
        
        # Extract basic structure
        result = {
            'title': soup.title.string if soup.title else None,
            'text': soup.get_text(separator=' ', strip=True),
            'links': [],
            'images': [],
            'metadata': {},
            'headings': {},
            'parsed_at': datetime.utcnow().isoformat()
        }
        
        # Extract links if requested
        if options.get('extract_links', True):
            result['links'] = [
                {
                    'href': a.get('href'),
                    'text': a.get_text(strip=True)
                }
                for a in soup.find_all('a', href=True)
            ]
        
        # Extract images
        if options.get('extract_images', True):
            result['images'] = [
                {
                    'src': img.get('src'),
                    'alt': img.get('alt', '')
                }
                for img in soup.find_all('img', src=True)
            ]
        
        # Extract metadata
        for meta in soup.find_all('meta'):
            name = meta.get('name') or meta.get('property')
            content = meta.get('content')
            if name and content:
                result['metadata'][name] = content
        
        # Extract headings
        for level in range(1, 7):
            tag = f'h{level}'
            headings = [h.get_text(strip=True) for h in soup.find_all(tag)]
            if headings:
                result['headings'][tag] = headings
        
        # Extract tables if requested
        if options.get('extract_tables', False):
            result['tables'] = []
            for table in soup.find_all('table'):
                table_data = []
                for row in table.find_all('tr'):
                    row_data = [cell.get_text(strip=True) for cell in row.find_all(['td', 'th'])]
                    if row_data:
                        table_data.append(row_data)
                if table_data:
                    result['tables'].append(table_data)
        
        return result
        
    except Exception as e:
        logger.error(f"HTML parsing error: {e}")
        raise

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    db_status = "healthy"
    try:
        conn = get_db_connection()
        if conn:
            conn.close()
        else:
            db_status = "unavailable"
    except:
        db_status = "error"
    
    return jsonify({
        'status': 'healthy',
        'service': 'html-parser',
        'version': '1.0.0',
        'database': db_status,
        'timestamp': datetime.utcnow().isoformat()
    }), 200

@app.route('/parse', methods=['POST'])
def parse():
    """
    Parse HTML content
    
    Request body:
    {
        "html": "<html>...</html>",
        "options": {
            "parser": "lxml",
            "extract_links": true,
            "extract_images": true,
            "extract_tables": false
        }
    }
    """
    try:
        data = request.get_json()
        
        if not data or 'html' not in data:
            return jsonify({
                'error': 'Missing html content',
                'status': 'error'
            }), 400
        
        html_content = data['html']
        options = data.get('options', {})
        
        # Parse HTML
        result = parse_html(html_content, options)
        
        # Store in database if requested
        if options.get('store', False) and 'url' in data:
            try:
                conn = get_db_connection()
                if conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS parsed_html (
                            id SERIAL PRIMARY KEY,
                            url TEXT,
                            title TEXT,
                            text_content TEXT,
                            metadata JSONB,
                            parsed_data JSONB,
                            parsed_at TIMESTAMP DEFAULT NOW()
                        )
                    """)
                    
                    cursor.execute("""
                        INSERT INTO parsed_html (url, title, text_content, metadata, parsed_data)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (
                        data['url'],
                        result.get('title'),
                        result.get('text'),
                        psycopg2.extras.Json(result.get('metadata', {})),
                        psycopg2.extras.Json(result)
                    ))
                    
                    conn.commit()
                    cursor.close()
                    conn.close()
                    
                    logger.info(f"Stored parsed HTML for URL: {data['url']}")
            except Exception as e:
                logger.error(f"Database storage error: {e}")
        
        return jsonify({
            'status': 'success',
            'data': result
        }), 200
        
    except Exception as e:
        logger.error(f"Parse endpoint error: {e}")
        return jsonify({
            'error': str(e),
            'status': 'error'
        }), 500

@app.route('/extract-text', methods=['POST'])
def extract_text():
    """
    Extract clean text from HTML
    
    Request body:
    {
        "html": "<html>...</html>",
        "separator": " "
    }
    """
    try:
        data = request.get_json()
        
        if not data or 'html' not in data:
            return jsonify({
                'error': 'Missing html content',
                'status': 'error'
            }), 400
        
        html_content = data['html']
        separator = data.get('separator', ' ')
        
        soup = BeautifulSoup(html_content, 'lxml')
        text = soup.get_text(separator=separator, strip=True)
        
        return jsonify({
            'status': 'success',
            'text': text
        }), 200
        
    except Exception as e:
        logger.error(f"Extract text error: {e}")
        return jsonify({
            'error': str(e),
            'status': 'error'
        }), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    logger.info(f"Starting HTML Parser Service on port {port}")
    app.run(host='0.0.0.0', port=port, debug=os.getenv('FLASK_ENV') == 'development')
