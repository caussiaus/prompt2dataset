#!/usr/bin/env python3
"""
Service Tracker
Monitor and track all services in the MVP ecosystem
"""
import requests
import json
import time
import sys
from datetime import datetime
from typing import Dict, List

# ANSI color codes for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

class ServiceTracker:
    def __init__(self, config_path='services.json'):
        """Initialize service tracker"""
        self.config_path = config_path
        self.services = self.load_config()
    
    def load_config(self) -> Dict:
        """Load services configuration"""
        try:
            with open(self.config_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"{RED}Error loading config: {e}{RESET}")
            return {}
    
    def check_service_health(self, service_id: str, service_info: Dict) -> Dict:
        """Check health of a single service"""
        health_check_url = service_info.get('health_check')
        
        if not health_check_url:
            return {
                'status': 'unknown',
                'message': 'No health check URL configured'
            }
        
        # Ensure URL is properly formatted
        if not health_check_url.startswith('http'):
            health_check_url = f"http://{health_check_url}"
        
        try:
            response = requests.get(health_check_url, timeout=5)
            
            if response.status_code == 200:
                return {
                    'status': 'healthy',
                    'message': 'Service is responding',
                    'response_time': response.elapsed.total_seconds()
                }
            else:
                return {
                    'status': 'unhealthy',
                    'message': f'HTTP {response.status_code}',
                    'response_time': response.elapsed.total_seconds()
                }
        except requests.exceptions.Timeout:
            return {
                'status': 'unhealthy',
                'message': 'Request timeout'
            }
        except requests.exceptions.ConnectionError:
            return {
                'status': 'down',
                'message': 'Connection refused'
            }
        except Exception as e:
            return {
                'status': 'error',
                'message': str(e)
            }
    
    def check_all_services(self) -> Dict[str, Dict]:
        """Check health of all services"""
        results = {}
        services = self.services.get('services', {})
        
        for service_id, service_info in services.items():
            print(f"Checking {service_info.get('name', service_id)}...", end=' ')
            result = self.check_service_health(service_id, service_info)
            results[service_id] = {
                **service_info,
                'health': result
            }
            
            # Print status with color
            status = result['status']
            if status == 'healthy':
                print(f"{GREEN}✓ {status.upper()}{RESET}")
            elif status == 'unhealthy':
                print(f"{YELLOW}⚠ {status.upper()}{RESET}")
            else:
                print(f"{RED}✗ {status.upper()}{RESET}")
        
        return results
    
    def print_summary(self, results: Dict[str, Dict]):
        """Print summary of service health"""
        total = len(results)
        healthy = sum(1 for r in results.values() if r['health']['status'] == 'healthy')
        unhealthy = sum(1 for r in results.values() if r['health']['status'] == 'unhealthy')
        down = sum(1 for r in results.values() if r['health']['status'] in ['down', 'error'])
        
        print(f"\n{BLUE}{'='*60}{RESET}")
        print(f"{BLUE}Service Health Summary{RESET}")
        print(f"{BLUE}{'='*60}{RESET}")
        print(f"Total Services: {total}")
        print(f"{GREEN}Healthy: {healthy}{RESET}")
        print(f"{YELLOW}Unhealthy: {unhealthy}{RESET}")
        print(f"{RED}Down: {down}{RESET}")
        print(f"\n{BLUE}Timestamp: {datetime.utcnow().isoformat()}{RESET}\n")
    
    def print_detailed_report(self, results: Dict[str, Dict]):
        """Print detailed service report"""
        print(f"\n{BLUE}{'='*60}{RESET}")
        print(f"{BLUE}Detailed Service Report{RESET}")
        print(f"{BLUE}{'='*60}{RESET}\n")
        
        for service_id, service_data in results.items():
            health = service_data['health']
            status = health['status']
            
            # Color based on status
            if status == 'healthy':
                color = GREEN
                icon = '✓'
            elif status == 'unhealthy':
                color = YELLOW
                icon = '⚠'
            else:
                color = RED
                icon = '✗'
            
            print(f"{color}{icon} {service_data.get('name', service_id)}{RESET}")
            print(f"  ID: {service_id}")
            print(f"  Type: {service_data.get('type', 'N/A')}")
            print(f"  Port: {service_data.get('port', 'N/A')}")
            print(f"  Status: {color}{status.upper()}{RESET}")
            print(f"  Message: {health.get('message', 'N/A')}")
            
            if 'response_time' in health:
                print(f"  Response Time: {health['response_time']:.3f}s")
            
            print()
    
    def export_json(self, results: Dict[str, Dict], output_file: str = 'service_status.json'):
        """Export results to JSON file"""
        try:
            output = {
                'timestamp': datetime.utcnow().isoformat(),
                'services': results
            }
            
            with open(output_file, 'w') as f:
                json.dump(output, f, indent=2)
            
            print(f"{GREEN}Results exported to {output_file}{RESET}")
        except Exception as e:
            print(f"{RED}Error exporting results: {e}{RESET}")
    
    def watch_services(self, interval: int = 10):
        """Continuously monitor services"""
        print(f"{BLUE}Starting service monitoring (checking every {interval}s)...{RESET}")
        print(f"{BLUE}Press Ctrl+C to stop{RESET}\n")
        
        try:
            while True:
                results = self.check_all_services()
                self.print_summary(results)
                time.sleep(interval)
                print("\n")
        except KeyboardInterrupt:
            print(f"\n{YELLOW}Monitoring stopped{RESET}")

def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Service Tracker - Monitor MVP services')
    parser.add_argument('--config', default='services.json', help='Path to services config file')
    parser.add_argument('--watch', action='store_true', help='Continuously monitor services')
    parser.add_argument('--interval', type=int, default=10, help='Watch interval in seconds')
    parser.add_argument('--detailed', action='store_true', help='Show detailed report')
    parser.add_argument('--export', help='Export results to JSON file')
    
    args = parser.parse_args()
    
    tracker = ServiceTracker(args.config)
    
    if args.watch:
        tracker.watch_services(args.interval)
    else:
        results = tracker.check_all_services()
        tracker.print_summary(results)
        
        if args.detailed:
            tracker.print_detailed_report(results)
        
        if args.export:
            tracker.export_json(results, args.export)

if __name__ == '__main__':
    main()
