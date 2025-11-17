#!/usr/bin/env python3
"""
Discovery Agent Service
Discovers URLs and content sources using search engines
"""
import os
import logging
import requests
import json
from flask import Flask, request, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from urllib.parse import urlparse, urljoin

# Configure logging
logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Service URLs
SEARXNG_URL = os.getenv('SEARXNG_URL', 'http://searxng:8888')
SERVICES_CONFIG = os.getenv('SERVICES_CONFIG', '/app/services.json')

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

def load_services_config():
    """Load services configuration"""
    try:
        if os.path.exists(SERVICES_CONFIG):
            with open(SERVICES_CONFIG, 'r') as f:
                return json.load(f)
        else:
            logger.warning(f"Services config not found: {SERVICES_CONFIG}")
            return {}
    except Exception as e:
        logger.error(f"Failed to load services config: {e}")
        return {}

def search_searxng(query, num_results=10, categories=None):
    """
    Search using SearXNG
    
    Args:
        query: Search query
        num_results: Number of results to return
        categories: List of categories to search
    
    Returns:
        List of search results
    """
    try:
        params = {
            'q': query,
            'format': 'json',
            'pageno': 1
        }
        
        if categories:
            params['categories'] = ','.join(categories)
        
        response = requests.get(
            f"{SEARXNG_URL}/search",
            params=params,
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            results = data.get('results', [])[:num_results]
            
            return [
                {
                    'url': result.get('url'),
                    'title': result.get('title'),
                    'content': result.get('content'),
                    'engine': result.get('engine'),
                    'score': result.get('score', 0)
                }
                for result in results
            ]
        else:
            logger.error(f"SearXNG API error: {response.status_code}")
            return []
            
    except Exception as e:
        logger.error(f"SearXNG search error: {e}")
        return []

def discover_service_health():
    """
    Check health status of all configured services
    
    Returns:
        Dict with service health status
    """
    services_config = load_services_config()
    services = services_config.get('services', {})
    
    health_status = {}
    
    for service_id, service_info in services.items():
        health_check = service_info.get('health_check')
        if health_check:
            try:
                response = requests.get(health_check, timeout=5)
                health_status[service_id] = {
                    'name': service_info.get('name'),
                    'status': 'healthy' if response.status_code == 200 else 'unhealthy',
                    'status_code': response.status_code,
                    'type': service_info.get('type')
                }
            except Exception as e:
                health_status[service_id] = {
                    'name': service_info.get('name'),
                    'status': 'unreachable',
                    'error': str(e),
                    'type': service_info.get('type')
                }
    
    return health_status

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    db_status = "healthy"
    searxng_status = "healthy"
    
    try:
        conn = get_db_connection()
        if conn:
            conn.close()
        else:
            db_status = "unavailable"
    except:
        db_status = "error"
    
    try:
        resp = requests.get(f"{SEARXNG_URL}/", timeout=5)
        if resp.status_code != 200:
            searxng_status = "unavailable"
    except:
        searxng_status = "error"
    
    return jsonify({
        'status': 'healthy',
        'service': 'discovery-agent',
        'version': '1.0.0',
        'dependencies': {
            'database': db_status,
            'searxng': searxng_status
        },
        'timestamp': datetime.utcnow().isoformat()
    }), 200

@app.route('/discover', methods=['POST'])
def discover():
    """
    Discover URLs based on search query
    
    Request body:
    {
        "query": "search query",
        "max_results": 10,
        "categories": ["general", "news"],
        "filter_domains": [],  # Optional: only include these domains
        "exclude_domains": [], # Optional: exclude these domains
        "store": true
    }
    """
    try:
        data = request.get_json()
        
        if not data or 'query' not in data:
            return jsonify({
                'error': 'Missing query parameter',
                'status': 'error'
            }), 400
        
        query = data['query']
        max_results = data.get('max_results', 10)
        categories = data.get('categories')
        filter_domains = data.get('filter_domains', [])
        exclude_domains = data.get('exclude_domains', [])
        
        logger.info(f"Discovering URLs for query: {query}")
        
        # Search using SearXNG
        results = search_searxng(query, max_results, categories)
        
        # Filter results by domain if specified
        if filter_domains:
            results = [
                r for r in results
                if any(domain in r['url'] for domain in filter_domains)
            ]
        
        if exclude_domains:
            results = [
                r for r in results
                if not any(domain in r['url'] for domain in exclude_domains)
            ]
        
        discovery_result = {
            'query': query,
            'results': results,
            'total_found': len(results),
            'discovered_at': datetime.utcnow().isoformat()
        }
        
        # Store in database if requested
        if data.get('store', False):
            try:
                conn = get_db_connection()
                if conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS discoveries (
                            id SERIAL PRIMARY KEY,
                            query TEXT,
                            results JSONB,
                            total_found INTEGER,
                            discovered_at TIMESTAMP DEFAULT NOW()
                        )
                    """)
                    
                    cursor.execute("""
                        INSERT INTO discoveries (query, results, total_found)
                        VALUES (%s, %s, %s)
                    """, (
                        query,
                        psycopg2.extras.Json(results),
                        len(results)
                    ))
                    
                    conn.commit()
                    cursor.close()
                    conn.close()
                    
                    logger.info(f"Stored discovery for query: {query}")
            except Exception as e:
                logger.error(f"Database storage error: {e}")
        
        return jsonify({
            'status': 'success',
            'data': discovery_result
        }), 200
        
    except Exception as e:
        logger.error(f"Discover endpoint error: {e}")
        return jsonify({
            'error': str(e),
            'status': 'error'
        }), 500

@app.route('/services', methods=['GET'])
def list_services():
    """
    List all configured services and their health status
    """
    try:
        services_config = load_services_config()
        health_status = discover_service_health()
        
        return jsonify({
            'status': 'success',
            'project': services_config.get('project'),
            'version': services_config.get('version'),
            'services': health_status,
            'total_services': len(health_status),
            'healthy_services': len([s for s in health_status.values() if s.get('status') == 'healthy']),
            'checked_at': datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"List services error: {e}")
        return jsonify({
            'error': str(e),
            'status': 'error'
        }), 500

@app.route('/service/<service_id>', methods=['GET'])
def get_service_info(service_id):
    """
    Get detailed information about a specific service
    """
    try:
        services_config = load_services_config()
        services = services_config.get('services', {})
        
        if service_id not in services:
            return jsonify({
                'error': f'Service {service_id} not found',
                'status': 'error'
            }), 404
        
        service_info = services[service_id]
        
        # Check health
        health_check = service_info.get('health_check')
        health_status = 'unknown'
        
        if health_check:
            try:
                response = requests.get(health_check, timeout=5)
                health_status = 'healthy' if response.status_code == 200 else 'unhealthy'
            except:
                health_status = 'unreachable'
        
        service_info['health_status'] = health_status
        service_info['checked_at'] = datetime.utcnow().isoformat()
        
        return jsonify({
            'status': 'success',
            'service': service_info
        }), 200
        
    except Exception as e:
        logger.error(f"Get service info error: {e}")
        return jsonify({
            'error': str(e),
            'status': 'error'
        }), 500

@app.route('/batch-discover', methods=['POST'])
def batch_discover():
    """
    Discover URLs for multiple queries
    
    Request body:
    {
        "queries": ["query1", "query2", ...],
        "max_results": 10,
        "store": true
    }
    """
    try:
        data = request.get_json()
        queries = data.get('queries', [])
        max_results = data.get('max_results', 10)
        store = data.get('store', False)
        
        results = []
        for query in queries:
            try:
                resp = requests.post(
                    f"http://localhost:{os.getenv('PORT', 8004)}/discover",
                    json={
                        'query': query,
                        'max_results': max_results,
                        'store': store
                    },
                    timeout=30
                )
                if resp.status_code == 200:
                    results.append({
                        'query': query,
                        'status': 'success',
                        'data': resp.json().get('data')
                    })
                else:
                    results.append({
                        'query': query,
                        'status': 'error',
                        'error': resp.text
                    })
            except Exception as e:
                results.append({
                    'query': query,
                    'status': 'error',
                    'error': str(e)
                })
        
        return jsonify({
            'status': 'success',
            'results': results,
            'total': len(queries),
            'successful': len([r for r in results if r['status'] == 'success'])
        }), 200
        
    except Exception as e:
        logger.error(f"Batch discover error: {e}")
        return jsonify({
            'error': str(e),
            'status': 'error'
        }), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8004))
    logger.info(f"Starting Discovery Agent Service on port {port}")
    app.run(host='0.0.0.0', port=port, debug=os.getenv('LOG_LEVEL') == 'DEBUG')
