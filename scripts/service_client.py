#!/usr/bin/env python3
"""
Service Client
SDK for interacting with the MVP service ecosystem
"""
import requests
import json
from typing import Dict, List, Optional
from datetime import datetime

class ServiceClient:
    """Client for interacting with MVP services"""
    
    def __init__(self, gateway_url: str = 'http://localhost:8000'):
        """Initialize service client"""
        self.gateway_url = gateway_url.rstrip('/')
        self.session = requests.Session()
    
    def health_check(self) -> Dict:
        """Check gateway health"""
        try:
            response = self.session.get(f"{self.gateway_url}/health", timeout=5)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": str(e), "status": "error"}
    
    def extract_data(self, url: str, extract_type: str = 'full') -> Dict:
        """Extract data from URL"""
        try:
            response = self.session.post(
                f"{self.gateway_url}/api/extract",
                json={"url": url, "type": extract_type},
                timeout=60
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": str(e)}
    
    def analyze_image(self, image_url: Optional[str] = None, 
                     image_base64: Optional[str] = None,
                     prompt: str = 'Describe this image in detail.',
                     model: str = 'llava:latest') -> Dict:
        """Analyze image using vision model"""
        try:
            payload = {
                "prompt": prompt,
                "model": model
            }
            
            if image_url:
                payload["image_url"] = image_url
            elif image_base64:
                payload["image_base64"] = image_base64
            else:
                return {"error": "No image URL or base64 data provided"}
            
            response = self.session.post(
                f"{self.gateway_url}/api/analyze-image",
                json=payload,
                timeout=60
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": str(e)}
    
    def orchestrate_workflow(self, workflow: str, url: str, **kwargs) -> Dict:
        """Orchestrate a complex workflow"""
        try:
            payload = {
                "workflow": workflow,
                "url": url,
                **kwargs
            }
            
            response = self.session.post(
                f"{self.gateway_url}/api/orchestrate",
                json=payload,
                timeout=120
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": str(e)}
    
    def discover_content(self, query: str, source_url: Optional[str] = None,
                        limit: int = 10) -> Dict:
        """Discover related content"""
        try:
            payload = {
                "query": query,
                "limit": limit
            }
            
            if source_url:
                payload["source_url"] = source_url
            
            response = self.session.post(
                f"{self.gateway_url}/api/discover",
                json=payload,
                timeout=60
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": str(e)}
    
    def list_services(self) -> Dict:
        """List all available services"""
        try:
            response = self.session.get(
                f"{self.gateway_url}/api/services",
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": str(e)}
    
    def get_services_status(self) -> Dict:
        """Get status of all services"""
        try:
            response = self.session.get(
                f"{self.gateway_url}/api/services/status",
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": str(e)}
    
    def run_pipeline(self, url: str, query: Optional[str] = None,
                    include_images: bool = False) -> Dict:
        """Run complete data extraction pipeline"""
        try:
            payload = {
                "url": url,
                "include_images": include_images
            }
            
            if query:
                payload["query"] = query
            
            response = self.session.post(
                f"{self.gateway_url}/api/pipeline",
                json=payload,
                timeout=120
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": str(e)}

def print_json(data: Dict):
    """Pretty print JSON data"""
    print(json.dumps(data, indent=2))

def main():
    """Main function for CLI usage"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Service Client - Interact with MVP services')
    parser.add_argument('--gateway', default='http://localhost:8000', help='Gateway URL')
    parser.add_argument('--test', action='store_true', help='Run test suite')
    parser.add_argument('--health', action='store_true', help='Check gateway health')
    parser.add_argument('--services', action='store_true', help='List all services')
    parser.add_argument('--status', action='store_true', help='Get services status')
    parser.add_argument('--extract', help='Extract data from URL')
    parser.add_argument('--discover', help='Discover content with query')
    parser.add_argument('--pipeline', help='Run pipeline on URL')
    parser.add_argument('--query', help='Search query for discovery')
    parser.add_argument('--export', help='Export results to file')
    
    args = parser.parse_args()
    
    client = ServiceClient(args.gateway)
    result = None
    
    if args.test:
        print("Running test suite...")
        print("\n1. Health Check:")
        print_json(client.health_check())
        
        print("\n2. List Services:")
        print_json(client.list_services())
        
        print("\n3. Services Status:")
        print_json(client.get_services_status())
        
        print("\nTest suite completed!")
        return
    
    if args.health:
        result = client.health_check()
    elif args.services:
        result = client.list_services()
    elif args.status:
        result = client.get_services_status()
    elif args.extract:
        result = client.extract_data(args.extract)
    elif args.discover:
        result = client.discover_content(args.discover, limit=10)
    elif args.pipeline:
        result = client.run_pipeline(
            args.pipeline,
            query=args.query,
            include_images=False
        )
    else:
        parser.print_help()
        return
    
    if result:
        print_json(result)
        
        if args.export:
            try:
                with open(args.export, 'w') as f:
                    json.dump(result, f, indent=2)
                print(f"\nResults exported to {args.export}")
            except Exception as e:
                print(f"\nError exporting results: {e}")

if __name__ == '__main__':
    main()
