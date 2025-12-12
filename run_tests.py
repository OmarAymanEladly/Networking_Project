# run_tests.py
#!/usr/bin/env python3
"""
Automated test runner for Grid Clash Project 2
Starts server and clients automatically, runs all tests
"""

import subprocess
import time
import os
import signal
import threading
from pathlib import Path
import sys
import json
import pandas as pd

class GridClashTester:
    def __init__(self, server_port=5555):
        self.server_port = server_port
        self.test_dir = Path("test_results")
        self.test_dir.mkdir(exist_ok=True)
        
        # Test scenarios from PDF
        self.test_scenarios = {
            'baseline': {
                'name': 'Baseline (no impairment)',
                'netem_cmd': None,
                'duration': 30,  # 30 seconds per test
                'clients': 2
            },
            'loss_2pct': {
                'name': 'Loss 2% (LAN-like)',
                'netem_cmd': f'tc qdisc add dev lo root netem loss 2%',
                'duration': 30,
                'clients': 2
            },
            'loss_5pct': {
                'name': 'Loss 5% (WAN-like)',
                'netem_cmd': f'tc qdisc add dev lo root netem loss 5%',
                'duration': 30,
                'clients': 2
            },
            'delay_100ms': {
                'name': 'Delay 100ms (WAN delay)',
                'netem_cmd': f'tc qdisc add dev lo root netem delay 100ms',
                'duration': 40,  # Longer for delay
                'clients': 2
            },
            'delay_jitter': {
                'name': 'Delay + Jitter (100ms ±10ms)',
                'netem_cmd': f'tc qdisc add dev lo root netem delay 100ms 10ms',
                'duration': 40,
                'clients': 2
            }
        }
        
        # Process tracking
        self.server_process = None
        self.client_processes = []
        
    def cleanup_netem(self):
        """Remove any existing netem rules"""
        print("Cleaning up netem rules...")
        try:
            subprocess.run(['sudo', 'tc', 'qdisc', 'del', 'dev', 'lo', 'root'], 
                         capture_output=True, stderr=subprocess.DEVNULL)
            time.sleep(1)
        except:
            pass
    
    def setup_netem(self, netem_cmd):
        """Setup network impairment using netem"""
        if netem_cmd:
            print(f"Setting up network impairment: {netem_cmd}")
            # Remove sudo for local testing
            cmd = netem_cmd.replace('sudo ', '')
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"Warning: Could not set up netem. You may need to run with sudo.")
                print(f"Error: {result.stderr}")
            else:
                print("Network impairment setup complete")
            time.sleep(2)
    
    def kill_existing_processes(self):
        """Kill any existing server/client processes"""
        print("Cleaning up existing processes...")
        
        # Kill processes on our port
        try:
            subprocess.run(['fuser', '-k', f'{self.server_port}/udp'], 
                         capture_output=True, stderr=subprocess.DEVNULL)
        except:
            pass
        
        # Kill any python processes running our scripts
        try:
            subprocess.run(['pkill', '-f', 'server_optimized.py'], 
                         capture_output=True, stderr=subprocess.DEVNULL)
            subprocess.run(['pkill', '-f', 'client.py'], 
                         capture_output=True, stderr=subprocess.DEVNULL)
        except:
            pass
        
        time.sleep(2)
    
    def start_server(self, test_name):
        """Start the game server"""
        print(f"\nStarting server for test: {test_name}")
        
        # Create test directory
        test_path = self.test_dir / test_name
        test_path.mkdir(exist_ok=True)
        
        # Kill any existing server
        self.kill_existing_processes()
        
        # Start server with output to log file
        server_log = test_path / "server.log"
        print(f"Server log: {server_log}")
        
        # Start server process
        self.server_process = subprocess.Popen(
            ['python3', 'server_optimized.py'],
            stdout=open(server_log, 'w'),
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid
        )
        
        print(f"Server started with PID: {self.server_process.pid}")
        
        # Wait for server to start
        print("Waiting for server to initialize...", end="", flush=True)
        for _ in range(10):
            try:
                # Check if server is listening on port
                result = subprocess.run(['ss', '-uln', 'sport', f':{self.server_port}'], 
                                      capture_output=True, text=True)
                if str(self.server_port) in result.stdout:
                    print(" ✓")
                    break
            except:
                pass
            print(".", end="", flush=True)
            time.sleep(1)
        else:
            print(" ✗")
            print("Warning: Server may not have started properly")
        
        time.sleep(2)
        return test_path
    
    def start_clients(self, test_path, num_clients):
        """Start game clients in headless mode"""
        print(f"\nStarting {num_clients} headless clients...")
        
        self.client_processes = []
        
        for i in range(num_clients):
            client_id = i + 1
            client_log = test_path / f"client_{client_id}.log"
            
            print(f"  Starting client {client_id}...", end="", flush=True)
            
            # Start client process
            proc = subprocess.Popen(
                ['python3', 'client.py', '127.0.0.1', '--headless'],
                stdout=open(client_log, 'w'),
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid
            )
            
            self.client_processes.append(proc)
            print(f" ✓ (PID: {proc.pid})")
            
            # Stagger client starts
            time.sleep(1.5)
        
        print("All clients started")
    
    def collect_csv_files(self, test_path):
        """Collect and rename CSV files created during test"""
        print("\nCollecting CSV files...")
        
        # Wait a moment for files to be written
        time.sleep(2)
        
        # Look for client CSV files (client_data_*.csv)
        client_csv_files = list(Path('.').glob('client_data_*.csv'))
        for csv_file in client_csv_files:
            # Try to extract client ID from PID
            pid = csv_file.stem.split('_')[-1]
            dest_file = test_path / f"client_{pid}.csv"
            
            try:
                # Read and save with proper formatting
                df = pd.read_csv(csv_file)
                df.to_csv(dest_file, index=False)
                csv_file.unlink()  # Remove original
                print(f"  Collected: {csv_file.name} -> {dest_file.name} ({len(df)} rows)")
            except Exception as e:
                print(f"  Error processing {csv_file}: {e}")
        
        # Look for server metrics CSV
        server_csv = Path('server_metrics.csv')
        if server_csv.exists():
            dest_file = test_path / "server_metrics.csv"
            try:
                server_csv.rename(dest_file)
                print(f"  Collected: server_metrics.csv")
            except:
                pass
    
    def stop_processes(self):
        """Stop all running processes"""
        print("\nStopping processes...")
        
        # Stop clients
        for proc in self.client_processes:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.wait(timeout=3)
            except:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except:
                    pass
        
        self.client_processes = []
        
        # Stop server
        if self.server_process:
            try:
                os.killpg(os.getpgid(self.server_process.pid), signal.SIGTERM)
                self.server_process.wait(timeout=3)
            except:
                try:
                    os.killpg(os.getpgid(self.server_process.pid), signal.SIGKILL)
                except:
                    pass
        
        self.server_process = None
        
        time.sleep(2)
        print("All processes stopped")
    
    def run_test_scenario(self, scenario_key, scenario_config):
        """Run a single test scenario"""
        print(f"\n{'='*60}")
        print(f"TEST: {scenario_config['name']}")
        print(f"{'='*60}")
        
        # Cleanup from previous tests
        self.cleanup_netem()
        self.kill_existing_processes()
        time.sleep(2)
        
        # Setup test directory and start server
        test_path = self.start_server(scenario_key)
        
        # Setup network impairment if specified
        if scenario_config['netem_cmd']:
            self.setup_netem(scenario_config['netem_cmd'])
        
        # Start clients
        self.start_clients(test_path, scenario_config['clients'])
        
        # Run test for specified duration
        print(f"\nTest running for {scenario_config['duration']} seconds...")
        start_time = time.time()
        
        # Show progress bar
        duration = scenario_config['duration']
        for i in range(duration):
            elapsed = time.time() - start_time
            remaining = max(0, duration - i)
            
            # Simple progress bar
            progress = int((i / duration) * 40)
            bar = '[' + '=' * progress + ' ' * (40 - progress) + ']'
            print(f'\r{bar} {remaining:3d}s remaining', end='', flush=True)
            
            time.sleep(1)
        
        print(f'\r[{'=' * 40}] Test complete!')
        
        # Collect CSV files
        self.collect_csv_files(test_path)
        
        # Stop processes
        self.stop_processes()
        
        # Cleanup netem
        self.cleanup_netem()
        
        # Save test metadata
        self.save_test_metadata(test_path, scenario_config)
        
        print(f"Test '{scenario_key}' completed successfully!")
        print(f"Results saved in: {test_path}")
        
        # Cool-down between tests
        print("\nCooling down for 5 seconds...")
        time.sleep(5)
    
    def save_test_metadata(self, test_path, scenario_config):
        """Save test configuration and metadata"""
        metadata = {
            'test_name': scenario_config['name'],
            'timestamp': time.time(),
            'netem_command': scenario_config['netem_cmd'],
            'duration': scenario_config['duration'],
            'clients': scenario_config['clients'],
            'server_port': self.server_port
        }
        
        meta_file = test_path / "test_metadata.json"
        with open(meta_file, 'w') as f:
            json.dump(metadata, f, indent=2)
    
    def run_all_tests(self):
        """Run all test scenarios"""
        print("GRID CLASH AUTOMATED TEST SUITE")
        print("=" * 50)
        print("This script will:")
        print("1. Start the server automatically")
        print("2. Start headless clients")
        print("3. Apply network impairments (loss, delay, jitter)")
        print("4. Run tests for specified durations")
        print("5. Collect all results and logs")
        print("=" * 50)
        print(f"Results will be saved in: {self.test_dir}")
        print()
        
        input("Press Enter to start tests (or Ctrl+C to cancel)...")
        print()
        
        # Run each test scenario
        test_order = ['baseline', 'loss_2pct', 'loss_5pct', 'delay_100ms', 'delay_jitter']
        
        for scenario_key in test_order:
            if scenario_key in self.test_scenarios:
                try:
                    self.run_test_scenario(scenario_key, self.test_scenarios[scenario_key])
                except KeyboardInterrupt:
                    print("\n\nTest interrupted by user!")
                    self.cleanup_all()
                    return
                except Exception as e:
                    print(f"\nError running test {scenario_key}: {e}")
                    self.cleanup_all()
        
        print("\n" + "="*60)
        print("ALL TESTS COMPLETED SUCCESSFULLY!")
        print("="*60)
        print(f"\nTest results saved in: {self.test_dir}")
        print("\nTo analyze results, run:")
        print("python3 analyze_result.py")
        print("\nOr for individual test analysis:")
        print("python3 analyze_result.py --dir test_results/baseline")
    
    def cleanup_all(self):
        """Cleanup everything"""
        print("\nPerforming complete cleanup...")
        self.cleanup_netem()
        self.stop_processes()
        self.kill_existing_processes()
        print("Cleanup complete!")

def check_dependencies():
    """Check if required tools are available"""
    print("Checking dependencies...")
    
    required = ['python3', 'tc']
    
    for cmd in required:
        try:
            subprocess.run([cmd, '--version'], capture_output=True, stderr=subprocess.DEVNULL)
            print(f"  ✓ {cmd}")
        except:
            print(f"  ✗ {cmd} not found")
            return False
    
    # Check Python modules
    try:
        import pygame, numpy, pandas, matplotlib
        print("  ✓ Python modules")
    except ImportError as e:
        print(f"  ✗ Missing Python module: {e}")
        return False
    
    print("All dependencies satisfied!")
    return True

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Run Grid Clash network tests')
    parser.add_argument('--test', '-t', 
                       help='Run specific test (baseline, loss_2pct, loss_5pct, delay_100ms, delay_jitter)')
    parser.add_argument('--cleanup', '-c', action='store_true', 
                       help='Cleanup only (stop processes, remove netem rules)')
    
    args = parser.parse_args()
    
    # Check dependencies
    if not check_dependencies():
        print("\nPlease install missing dependencies and try again.")
        sys.exit(1)
    
    tester = GridClashTester()
    
    if args.cleanup:
        tester.cleanup_all()
        return
    
    if args.test:
        if args.test in tester.test_scenarios:
            print(f"Running single test: {args.test}")
            tester.run_test_scenario(args.test, tester.test_scenarios[args.test])
            
            print(f"\nTest '{args.test}' completed!")
            print(f"Results in: test_results/{args.test}/")
        else:
            print(f"Error: Test '{args.test}' not found!")
            print(f"Available tests: {list(tester.test_scenarios.keys())}")
    else:
        tester.run_all_tests()

if __name__ == "__main__":
    main()