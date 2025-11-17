#!/usr/bin/env python3
"""
Service Tracker - Monitor all services health status
"""
import json
import requests
import sys
import time
from datetime import datetime
from typing import Dict, List

SERVICES_CONFIG = '../services.json'

def load_services():
    """Load services configuration"""
    try:
        with open(SERVICES_CONFIG, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: {SERVICES_CONFIG} not found")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON in {SERVICES_CONFIG}")
        sys.exit(1)

def check_service_health(service_id: str, service_info: Dict) -> Dict:
    """
    Check health of a single service
    
    Returns:
        Dict with health status
    """
    health_check = service_info.get('health_check')
    
    if not health_check:
        return {
            'status': 'unknown',
            'message': 'No health check configured'
        }
    
    try:
        response = requests.get(health_check, timeout=5)
        
        if response.status_code == 200:
            return {
                'status': 'healthy',
                'status_code': response.status_code,
                'response_time_ms': int(response.elapsed.total_seconds() * 1000)
            }
        else:
            return {
                'status': 'unhealthy',
                'status_code': response.status_code,
                'message': f'HTTP {response.status_code}'
            }
    except requests.exceptions.ConnectionError:
        return {
            'status': 'unreachable',
            'message': 'Connection failed'
        }
    except requests.exceptions.Timeout:
        return {
            'status': 'timeout',
            'message': 'Request timeout'
        }
    except Exception as e:
        return {
            'status': 'error',
            'message': str(e)
        }

def print_status_table(services: Dict, health_results: Dict):
    """Print formatted status table"""
    
    # ANSI color codes
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    RESET = '\033[0m'
    BOLD = '\033[1m'
    
    def get_status_color(status):
        if status == 'healthy':
            return GREEN
        elif status in ['unknown', 'pending']:
            return YELLOW
        else:
            return RED
    
    print(f"\n{BOLD}{'='*80}{RESET}")
    print(f"{BOLD}Service Health Status - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{RESET}")
    print(f"{BOLD}{'='*80}{RESET}\n")
    
    print(f"{BOLD}{'Service':<25} {'Type':<15} {'Status':<15} {'Details':<25}{RESET}")
    print("-" * 80)
    
    for service_id, service_info in services.items():
        name = service_info.get('name', service_id)
        service_type = service_info.get('type', 'unknown')
        health = health_results.get(service_id, {})
        status = health.get('status', 'unknown')
        
        color = get_status_color(status)
        
        # Format details
        details = ""
        if status == 'healthy':
            response_time = health.get('response_time_ms', 0)
            details = f"{response_time}ms"
        else:
            details = health.get('message', '')[:25]
        
        print(f"{name:<25} {service_type:<15} {color}{status:<15}{RESET} {details:<25}")
    
    print("-" * 80)
    
    # Summary
    total = len(services)
    healthy = len([h for h in health_results.values() if h.get('status') == 'healthy'])
    unhealthy = total - healthy
    
    summary_color = GREEN if unhealthy == 0 else RED
    print(f"\n{BOLD}Summary:{RESET} {summary_color}{healthy}/{total} services healthy{RESET}")
    
    if unhealthy > 0:
        print(f"{RED}⚠ {unhealthy} service(s) need attention{RESET}")
    else:
        print(f"{GREEN}✓ All services are healthy{RESET}")
    
    print()

def watch_services(interval: int = 10):
    """Continuously monitor services"""
    print("Starting service monitoring (Ctrl+C to stop)...")
    
    try:
        while True:
            config = load_services()
            services = config.get('services', {})
            
            health_results = {}
            for service_id, service_info in services.items():
                health_results[service_id] = check_service_health(service_id, service_info)
            
            # Clear screen
            print("\033[2J\033[H", end="")
            
            print_status_table(services, health_results)
            print(f"Refreshing every {interval}s... (Ctrl+C to stop)")
            
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print("\n\nMonitoring stopped.")
        sys.exit(0)

def check_once():
    """Check all services once and exit"""
    config = load_services()
    services = config.get('services', {})
    
    health_results = {}
    for service_id, service_info in services.items():
        health_results[service_id] = check_service_health(service_id, service_info)
    
    print_status_table(services, health_results)
    
    # Exit with error if any service is unhealthy
    unhealthy = len([h for h in health_results.values() if h.get('status') != 'healthy'])
    sys.exit(1 if unhealthy > 0 else 0)

def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Monitor health status of all services'
    )
    parser.add_argument(
        '--watch',
        action='store_true',
        help='Continuously monitor services'
    )
    parser.add_argument(
        '--interval',
        type=int,
        default=10,
        help='Refresh interval in seconds (default: 10)'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output results as JSON'
    )
    
    args = parser.parse_args()
    
    if args.watch:
        watch_services(args.interval)
    elif args.json:
        config = load_services()
        services = config.get('services', {})
        
        health_results = {}
        for service_id, service_info in services.items():
            health_results[service_id] = check_service_health(service_id, service_info)
        
        output = {
            'timestamp': datetime.now().isoformat(),
            'services': health_results
        }
        print(json.dumps(output, indent=2))
    else:
        check_once()

if __name__ == '__main__':
    main()
