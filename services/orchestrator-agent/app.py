#!/usr/bin/env python3
"""
Orchestrator Agent Service
Coordinates workflows between different agents
"""
import os
import logging
import requests
from flask import Flask, request, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configure logging
logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Service URLs
EXTRACTION_AGENT_URL = os.getenv('EXTRACTION_AGENT_URL', 'http://extraction-agent:8001')
VISION_AGENT_URL = os.getenv('VISION_AGENT_URL', 'http://vision-agent:8002')
DISCOVERY_AGENT_URL = os.getenv('DISCOVERY_AGENT_URL', 'http://discovery-agent:8004')

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

def execute_workflow_step(step_config):
    """
    Execute a single workflow step
    
    Args:
        step_config: Dict with step configuration
    
    Returns:
        Step result
    """
    step_type = step_config.get('type')
    step_data = step_config.get('data', {})
    
    try:
        if step_type == 'extract':
            response = requests.post(
                f"{EXTRACTION_AGENT_URL}/extract",
                json=step_data,
                timeout=60
            )
        elif step_type == 'analyze_image':
            response = requests.post(
                f"{VISION_AGENT_URL}/analyze-image",
                json=step_data,
                timeout=120
            )
        elif step_type == 'discover':
            response = requests.post(
                f"{DISCOVERY_AGENT_URL}/discover",
                json=step_data,
                timeout=60
            )
        else:
            return {
                'status': 'error',
                'error': f'Unknown step type: {step_type}'
            }
        
        if response.status_code == 200:
            return {
                'status': 'success',
                'data': response.json()
            }
        else:
            return {
                'status': 'error',
                'error': f'Step failed with status {response.status_code}',
                'details': response.text
            }
            
    except Exception as e:
        logger.error(f"Step execution error: {e}")
        return {
            'status': 'error',
            'error': str(e)
        }

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    db_status = "healthy"
    extraction_status = "healthy"
    vision_status = "healthy"
    discovery_status = "healthy"
    
    try:
        conn = get_db_connection()
        if conn:
            conn.close()
        else:
            db_status = "unavailable"
    except:
        db_status = "error"
    
    try:
        resp = requests.get(f"{EXTRACTION_AGENT_URL}/health", timeout=5)
        if resp.status_code != 200:
            extraction_status = "unavailable"
    except:
        extraction_status = "error"
    
    try:
        resp = requests.get(f"{VISION_AGENT_URL}/health", timeout=5)
        if resp.status_code != 200:
            vision_status = "unavailable"
    except:
        vision_status = "error"
    
    try:
        resp = requests.get(f"{DISCOVERY_AGENT_URL}/health", timeout=5)
        if resp.status_code != 200:
            discovery_status = "unavailable"
    except:
        discovery_status = "error"
    
    return jsonify({
        'status': 'healthy',
        'service': 'orchestrator-agent',
        'version': '1.0.0',
        'dependencies': {
            'database': db_status,
            'extraction_agent': extraction_status,
            'vision_agent': vision_status,
            'discovery_agent': discovery_status
        },
        'timestamp': datetime.utcnow().isoformat()
    }), 200

@app.route('/orchestrate', methods=['POST'])
def orchestrate():
    """
    Orchestrate a multi-step workflow
    
    Request body:
    {
        "workflow_name": "Extract and Analyze",
        "steps": [
            {
                "name": "discover_urls",
                "type": "discover",
                "data": {"query": "...", "max_results": 10}
            },
            {
                "name": "extract_data",
                "type": "extract",
                "data": {"schema": {...}, "store": true},
                "depends_on": "discover_urls"
            }
        ],
        "parallel": false,  # Execute steps in parallel if possible
        "store": true
    }
    """
    try:
        data = request.get_json()
        
        if not data or 'steps' not in data:
            return jsonify({
                'error': 'Missing workflow steps',
                'status': 'error'
            }), 400
        
        workflow_name = data.get('workflow_name', 'Unnamed Workflow')
        steps = data.get('steps', [])
        parallel = data.get('parallel', False)
        store = data.get('store', True)
        
        logger.info(f"Starting workflow: {workflow_name} with {len(steps)} steps")
        
        results = []
        step_outputs = {}
        
        if parallel:
            # Execute steps in parallel where possible
            with ThreadPoolExecutor(max_workers=5) as executor:
                future_to_step = {}
                
                for step in steps:
                    # Check dependencies
                    depends_on = step.get('depends_on')
                    if depends_on and depends_on in step_outputs:
                        # Inject dependency output into step data
                        step['data']['dependency_output'] = step_outputs[depends_on]
                    
                    future = executor.submit(execute_workflow_step, step)
                    future_to_step[future] = step
                
                for future in as_completed(future_to_step):
                    step = future_to_step[future]
                    step_name = step.get('name', 'unnamed_step')
                    
                    try:
                        result = future.result()
                        step_outputs[step_name] = result.get('data')
                        results.append({
                            'step': step_name,
                            'type': step.get('type'),
                            'result': result
                        })
                    except Exception as e:
                        results.append({
                            'step': step_name,
                            'type': step.get('type'),
                            'result': {
                                'status': 'error',
                                'error': str(e)
                            }
                        })
        else:
            # Execute steps sequentially
            for step in steps:
                step_name = step.get('name', 'unnamed_step')
                
                # Check dependencies
                depends_on = step.get('depends_on')
                if depends_on and depends_on in step_outputs:
                    # Inject dependency output into step data
                    step['data']['dependency_output'] = step_outputs[depends_on]
                
                result = execute_workflow_step(step)
                step_outputs[step_name] = result.get('data')
                
                results.append({
                    'step': step_name,
                    'type': step.get('type'),
                    'result': result
                })
                
                # Stop on error if not configured to continue
                if result.get('status') == 'error' and not step.get('continue_on_error', False):
                    logger.warning(f"Workflow stopped at step {step_name} due to error")
                    break
        
        workflow_result = {
            'workflow_name': workflow_name,
            'steps': results,
            'total_steps': len(steps),
            'successful_steps': len([r for r in results if r['result'].get('status') == 'success']),
            'completed_at': datetime.utcnow().isoformat()
        }
        
        # Store workflow result in database
        if store:
            try:
                conn = get_db_connection()
                if conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS workflows (
                            id SERIAL PRIMARY KEY,
                            workflow_name TEXT,
                            steps JSONB,
                            results JSONB,
                            completed_at TIMESTAMP DEFAULT NOW()
                        )
                    """)
                    
                    cursor.execute("""
                        INSERT INTO workflows (workflow_name, steps, results)
                        VALUES (%s, %s, %s)
                    """, (
                        workflow_name,
                        psycopg2.extras.Json(steps),
                        psycopg2.extras.Json(workflow_result)
                    ))
                    
                    conn.commit()
                    cursor.close()
                    conn.close()
                    
                    logger.info(f"Stored workflow: {workflow_name}")
            except Exception as e:
                logger.error(f"Database storage error: {e}")
        
        return jsonify({
            'status': 'success',
            'data': workflow_result
        }), 200
        
    except Exception as e:
        logger.error(f"Orchestrate endpoint error: {e}")
        return jsonify({
            'error': str(e),
            'status': 'error'
        }), 500

@app.route('/workflows', methods=['GET'])
def list_workflows():
    """List all stored workflows"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({
                'error': 'Database unavailable',
                'status': 'error'
            }), 503
        
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT id, workflow_name, completed_at
            FROM workflows
            ORDER BY completed_at DESC
            LIMIT 100
        """)
        
        workflows = cursor.fetchall()
        cursor.close()
        conn.close()
        
        return jsonify({
            'status': 'success',
            'workflows': workflows
        }), 200
        
    except Exception as e:
        logger.error(f"List workflows error: {e}")
        return jsonify({
            'error': str(e),
            'status': 'error'
        }), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8003))
    logger.info(f"Starting Orchestrator Agent Service on port {port}")
    app.run(host='0.0.0.0', port=port, debug=os.getenv('LOG_LEVEL') == 'DEBUG')
