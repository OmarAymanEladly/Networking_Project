# run_tests.py
#!/usr/bin/env python3
"""
Automated test runner for Grid Clash Project 2 (Phase 2)
Tests all scenarios using netem on virtualbox interface enp0s3
"""

import subprocess
import time
import os
import sys
import signal
import threading
import argparse
from pathlib import Path
import csv
import json

class GridClashTester:
    def __init__(self, interface='enp0s3', server_port=5555):
        self.interface = interface
        self.server_port = server_port
        self.test_dir = Path("test_results")
        self.test_dir.mkdir(exist_ok=True)
        
        # Test scenarios from PDF
        self.test_scenarios = {
            'baseline': {
                'name': 'Baseline (no impairment)',
                'netem_cmd': None,
                'duration': 60,  # 60 seconds test
                'clients': 4
            },
            'loss_2pct': {
                'name': 'Loss 2% (LAN-like)',
                'netem_cmd': f'sudo tc qdisc add dev {self.interface} root netem loss 2%',
                'duration': 60,
                'clients': 4
            },
            'loss_5pct': {
                'name': 'Loss 5% (WAN-like)',
                'netem_cmd': f'sudo tc qdisc add dev {self.interface} root netem loss 5%',
                'duration': 60,
                'clients': 4
            },
            'delay_100ms': {
                'name': 'Delay 100ms (WAN delay)',
                'netem_cmd': f'sudo tc qdisc add dev {self.interface} root netem delay 100ms',
                'duration': 90,  # Longer for delay tests
                'clients': 4
            },
            'delay_jitter': {
                'name': 'Delay + Jitter (100ms ±10ms)',
                'netem_cmd': f'sudo tc qdisc add dev {self.interface} root netem delay 100ms 10ms',
                'duration': 90,
                'clients': 4
            }
        }
        
        # Processes tracking
        self.server_process = None
        self.client_processes = []
        self.pcap_process = None
        
    def cleanup_netem(self):
        """Remove any existing netem rules"""
        print("Cleaning up existing netem rules...")
        try:
            subprocess.run(f'sudo tc qdisc del dev {self.interface} root', 
                         shell=True, capture_output=True)
            time.sleep(1)
        except:
            pass
            
    def setup_netem(self, netem_cmd):
        """Setup network impairment using netem"""
        if netem_cmd:
            print(f"Setting up: {netem_cmd}")
            result = subprocess.run(netem_cmd, shell=True, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"Warning: {result.stderr}")
            time.sleep(2)
            
    def start_server(self, test_name):
        """Start the game server"""
        print(f"Starting server for test: {test_name}")
        
        # Create test-specific directory
        test_path = self.test_dir / test_name
        test_path.mkdir(exist_ok=True)
        
        # Start server with logging
        server_log = test_path / "server.log"
        server_metrics = test_path / "server_metrics.csv"
        
        # Kill any existing server on the port
        subprocess.run(f"fuser -k {self.server_port}/udp 2>/dev/null", shell=True)
        time.sleep(1)
        
        # Start server
        cmd = f"python3 server_optimized.py > {server_log} 2>&1"
        self.server_process = subprocess.Popen(cmd, shell=True, preexec_fn=os.setsid)
        print(f"Server started with PID: {self.server_process.pid}")
        time.sleep(3)  # Give server time to start
        
        return test_path
        
    def start_pcap_capture(self, test_path, test_name):
        """Start packet capture for the test"""
        pcap_file = test_path / f"{test_name}.pcap"
        print(f"Starting packet capture to: {pcap_file}")
        
        cmd = f"sudo tcpdump -i {self.interface} -w {pcap_file} port {self.server_port}"
        self.pcap_process = subprocess.Popen(cmd, shell=True, preexec_fn=os.setsid)
        time.sleep(2)
        
    def start_clients(self, test_path, num_clients=4):
        """Start game clients (headless bots)"""
        print(f"Starting {num_clients} headless clients...")
        
        for i in range(num_clients):
            client_id = i + 1
            client_log = test_path / f"client_{client_id}.log"
            client_csv = test_path / f"client_{client_id}.csv"
            
            # Clean up old CSV
            if client_csv.exists():
                client_csv.unlink()
            
            # Start client in headless mode
            cmd = f"python3 client.py 127.0.0.1 --headless > {client_log} 2>&1"
            proc = subprocess.Popen(cmd, shell=True, preexec_fn=os.setsid)
            self.client_processes.append(proc)
            print(f"  Client {client_id} started (PID: {proc.pid})")
            
            # Stagger client starts
            time.sleep(0.5)
            
    def stop_processes(self):
        """Stop all running processes"""
        print("\nStopping all processes...")
        
        # Stop packet capture
        if self.pcap_process:
            try:
                os.killpg(os.getpgid(self.pcap_process.pid), signal.SIGTERM)
                self.pcap_process.wait(timeout=5)
            except:
                os.killpg(os.getpgid(self.pcap_process.pid), signal.SIGKILL)
            self.pcap_process = None
            
        # Stop clients
        for proc in self.client_processes:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.wait(timeout=2)
            except:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        self.client_processes = []
        
        # Stop server
        if self.server_process:
            try:
                os.killpg(os.getpgid(self.server_process.pid), signal.SIGTERM)
                self.server_process.wait(timeout=5)
            except:
                os.killpg(os.getpgid(self.server_process.pid), signal.SIGKILL)
            self.server_process = None
            
        time.sleep(2)
        
    def run_test_scenario(self, scenario_key, scenario_config):
        """Run a single test scenario"""
        print(f"\n{'='*60}")
        print(f"Running test: {scenario_config['name']}")
        print(f"{'='*60}")
        
        # Cleanup from previous tests
        self.cleanup_netem()
        self.stop_processes()
        time.sleep(2)
        
        # Setup test environment
        test_path = self.start_server(scenario_key)
        self.start_pcap_capture(test_path, scenario_key)
        
        # Setup network impairment
        self.setup_netem(scenario_config['netem_cmd'])
        
        # Start clients
        self.start_clients(test_path, scenario_config['clients'])
        
        # Let test run
        print(f"\nTest running for {scenario_config['duration']} seconds...")
        for remaining in range(scenario_config['duration'], 0, -1):
            print(f"\rTime remaining: {remaining:3d}s", end="", flush=True)
            time.sleep(1)
        print()
        
        # Collect client CSV files before stopping
        self.collect_client_data(test_path, scenario_config['clients'])
        
        # Cleanup for this test
        self.stop_processes()
        self.cleanup_netem()
        
        # Save test metadata
        self.save_test_metadata(test_path, scenario_config)
        
        print(f"Test '{scenario_key}' completed!")
        time.sleep(3)  # Cool-down between tests
        
    def collect_client_data(self, test_path, num_clients):
        """Ensure client CSV files are properly closed"""
        print("Collecting client data...")
        time.sleep(2)  # Give clients time to flush logs
        
        for i in range(num_clients):
            client_id = i + 1
            csv_file = test_path / f"client_data_{client_id}.csv"
            target_file = test_path / f"client_{client_id}.csv"
            
            if csv_file.exists():
                csv_file.rename(target_file)
                print(f"  Collected data for client {client_id}")
                
    def save_test_metadata(self, test_path, scenario_config):
        """Save test configuration and metadata"""
        metadata = {
            'test_name': scenario_config['name'],
            'timestamp': time.time(),
            'netem_command': scenario_config['netem_cmd'],
            'duration': scenario_config['duration'],
            'clients': scenario_config['clients'],
            'interface': self.interface,
            'server_port': self.server_port
        }
        
        meta_file = test_path / "test_metadata.json"
        with open(meta_file, 'w') as f:
            json.dump(metadata, f, indent=2)
            
    def run_all_tests(self):
        """Run all test scenarios"""
        print("Grid Clash Automated Test Suite")
        print("=" * 40)
        print(f"Interface: {self.interface}")
        print(f"Server Port: {self.server_port}")
        print(f"Results Directory: {self.test_dir}")
        print()
        
        # Run each test scenario
        for scenario_key, scenario_config in self.test_scenarios.items():
            self.run_test_scenario(scenario_key, scenario_config)
            
        print("\n" + "="*60)
        print("ALL TESTS COMPLETED SUCCESSFULLY!")
        print(f"Results saved in: {self.test_dir}")
        print("\nTo analyze results, run:")
        print("python3 analyze_results.py")
        
    def run_single_test(self, test_name):
        """Run a specific test scenario"""
        if test_name not in self.test_scenarios:
            print(f"Error: Test '{test_name}' not found!")
            print(f"Available tests: {list(self.test_scenarios.keys())}")
            return
            
        self.run_test_scenario(test_name, self.test_scenarios[test_name])
        
    def cleanup_all(self):
        """Cleanup everything"""
        print("Performing complete cleanup...")
        self.cleanup_netem()
        self.stop_processes()
        
        # Kill any remaining processes
        subprocess.run(f"fuser -k {self.server_port}/udp 2>/dev/null", shell=True)
        
def main():
    parser = argparse.ArgumentParser(description='Run Grid Clash network tests')
    parser.add_argument('--test', '-t', help='Run specific test (baseline, loss_2pct, loss_5pct, delay_100ms, delay_jitter)')
    parser.add_argument('--interface', '-i', default='enp0s3', help='Network interface (default: enp0s3)')
    parser.add_argument('--cleanup', '-c', action='store_true', help='Cleanup only')
    
    args = parser.parse_args()
    
    tester = GridClashTester(interface=args.interface)
    
    if args.cleanup:
        tester.cleanup_all()
        return
        
    if args.test:
        tester.run_single_test(args.test)
    else:
        tester.run_all_tests()

if __name__ == "__main__":
    main()