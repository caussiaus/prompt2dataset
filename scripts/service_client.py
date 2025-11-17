#!/usr/bin/env python3
"""
Service Client - Python SDK for interacting with prompt2dataset services
"""
import json
import requests
from typing import Dict, List, Optional
from datetime import datetime

class ServiceClient:
    """Client for prompt2dataset services"""
    
    def __init__(self, gateway_url: str = 'http://localhost:8000'):
        """
        Initialize service client
        
        Args:
            gateway_url: Base URL for the agent gateway
        """
        self.gateway_url = gateway_url.rstrip('/')
        self.extraction_url = gateway_url.replace(':8000', ':8001')
        self.vision_url = gateway_url.replace(':8000', ':8002')
        self.orchestrator_url = gateway_url.replace(':8000', ':8003')
        self.discovery_url = gateway_url.replace(':8000', ':8004')
    
    def health_check(self) -> Dict:
        """Check health of all services"""
        try:
            response = requests.get(f"{self.gateway_url}/health", timeout=5)
            return response.json()
        except Exception as e:
            return {'error': str(e), 'status': 'error'}
    
    def discover_urls(
        self,
        query: str,
        max_results: int = 10,
        categories: Optional[List[str]] = None,
        store: bool = False
    ) -> Dict:
        """
        Discover URLs using search
        
        Args:
            query: Search query
            max_results: Maximum number of results
            categories: Search categories
            store: Store results in database
        
        Returns:
            Discovery results
        """
        try:
            response = requests.post(
                f"{self.discovery_url}/discover",
                json={
                    'query': query,
                    'max_results': max_results,
                    'categories': categories,
                    'store': store
                },
                timeout=30
            )
            return response.json()
        except Exception as e:
            return {'error': str(e), 'status': 'error'}
    
    def extract_data(
        self,
        url: Optional[str] = None,
        html: Optional[str] = None,
        schema: Optional[Dict] = None,
        store: bool = False
    ) -> Dict:
        """
        Extract structured data from URL or HTML
        
        Args:
            url: URL to extract from
            html: HTML content (if url not provided)
            schema: Extraction schema
            store: Store results in database
        
        Returns:
            Extracted data
        """
        try:
            response = requests.post(
                f"{self.extraction_url}/extract",
                json={
                    'url': url,
                    'html': html,
                    'schema': schema,
                    'store': store
                },
                timeout=60
            )
            return response.json()
        except Exception as e:
            return {'error': str(e), 'status': 'error'}
    
    def analyze_image(
        self,
        image_url: Optional[str] = None,
        image_data: Optional[str] = None,
        prompt: str = "Describe this image in detail.",
        store: bool = False
    ) -> Dict:
        """
        Analyze image content
        
        Args:
            image_url: URL of image
            image_data: Base64 encoded image (if url not provided)
            prompt: Analysis prompt
            store: Store results in database
        
        Returns:
            Image analysis results
        """
        try:
            response = requests.post(
                f"{self.vision_url}/analyze-image",
                json={
                    'image_url': image_url,
                    'image_data': image_data,
                    'prompt': prompt,
                    'store': store
                },
                timeout=120
            )
            return response.json()
        except Exception as e:
            return {'error': str(e), 'status': 'error'}
    
    def orchestrate_workflow(
        self,
        workflow_name: str,
        steps: List[Dict],
        parallel: bool = False,
        store: bool = True
    ) -> Dict:
        """
        Execute a multi-step workflow
        
        Args:
            workflow_name: Name of the workflow
            steps: List of workflow steps
            parallel: Execute steps in parallel
            store: Store workflow results
        
        Returns:
            Workflow execution results
        """
        try:
            response = requests.post(
                f"{self.orchestrator_url}/orchestrate",
                json={
                    'workflow_name': workflow_name,
                    'steps': steps,
                    'parallel': parallel,
                    'store': store
                },
                timeout=300
            )
            return response.json()
        except Exception as e:
            return {'error': str(e), 'status': 'error'}
    
    def list_services(self) -> Dict:
        """List all available services"""
        try:
            response = requests.get(
                f"{self.discovery_url}/services",
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {'error': str(e), 'status': 'error'}
    
    def export_endpoints(self) -> Dict:
        """Export all service endpoints"""
        endpoints = {
            'gateway': self.gateway_url,
            'extraction_agent': self.extraction_url,
            'vision_agent': self.vision_url,
            'orchestrator_agent': self.orchestrator_url,
            'discovery_agent': self.discovery_url,
            'endpoints': {
                'health': f"{self.gateway_url}/health",
                'discover': f"{self.discovery_url}/discover",
                'extract': f"{self.extraction_url}/extract",
                'analyze_image': f"{self.vision_url}/analyze-image",
                'orchestrate': f"{self.orchestrator_url}/orchestrate",
                'list_services': f"{self.discovery_url}/services"
            }
        }
        return endpoints

def main():
    """CLI interface for service client"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Interact with prompt2dataset services'
    )
    parser.add_argument(
        '--gateway-url',
        default='http://localhost:8000',
        help='Gateway URL'
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='Run test workflow'
    )
    parser.add_argument(
        '--export',
        action='store_true',
        help='Export endpoint information'
    )
    
    args = parser.parse_args()
    
    client = ServiceClient(args.gateway_url)
    
    if args.export:
        endpoints = client.export_endpoints()
        print(json.dumps(endpoints, indent=2))
    elif args.test:
        print("Running test workflow...")
        
        # Test 1: Health check
        print("\n1. Checking service health...")
        health = client.health_check()
        print(json.dumps(health, indent=2))
        
        # Test 2: Discover URLs
        print("\n2. Discovering URLs...")
        discovery = client.discover_urls("python web scraping", max_results=5)
        print(json.dumps(discovery, indent=2))
        
        # Test 3: List services
        print("\n3. Listing services...")
        services = client.list_services()
        print(json.dumps(services, indent=2))
        
        print("\n✓ Test workflow completed!")
    else:
        parser.print_help()

if __name__ == '__main__':
    main()
