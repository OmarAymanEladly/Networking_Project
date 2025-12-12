#!/usr/bin/env python
"""
Grid Clash Automated Test Runner
Automatically starts server and clients, runs all tests
"""

import subprocess
import time
import os
import sys
from pathlib import Path
import json
import threading
import shlex

class GridClashAutoTester:
    def __init__(self):
        self.test_dir = Path("test_results")
        self.test_dir.mkdir(exist_ok=True)
        
        # Test configurations
        self.test_scenarios = {
            'baseline': {
                'name': 'Baseline (no impairment)',
                'duration': 30,
                'clients': 2
            },
            'loss_2pct': {
                'name': 'Loss 2% (LAN-like)',
                'duration': 30,
                'clients': 2
            },
            'loss_5pct': {
                'name': 'Loss 5% (WAN-like)',
                'duration': 30,
                'clients': 2
            }
        }
        
        self.server_proc = None
        self.client_procs = []
        
    def run_command(self, cmd, output_file=None, shell=False):
        """Run a command and return the process"""
        if output_file:
            stdout = open(output_file, 'w')
            stderr = subprocess.STDOUT
        else:
            stdout = subprocess.PIPE
            stderr = subprocess.PIPE
        
        if shell:
            proc = subprocess.Popen(cmd, shell=True, stdout=stdout, stderr=stderr)
        else:
            # Split command for subprocess
            if isinstance(cmd, str):
                cmd = shlex.split(cmd)
            proc = subprocess.Popen(cmd, stdout=stdout, stderr=stderr)
        
        return proc
    
    def cleanup(self):
        """Clean up any running processes"""
        print("\nCleaning up processes...")
        
        # Kill clients
        for proc in self.client_procs:
            try:
                proc.terminate()
            except:
                pass
        
        # Kill server
        if self.server_proc:
            try:
                self.server_proc.terminate()
            except:
                pass
        
        # Wait a bit
        time.sleep(2)
        
        # Force kill if still running
        for proc in self.client_procs + ([self.server_proc] if self.server_proc else []):
            try:
                proc.kill()
            except:
                pass
        
        self.client_procs = []
        self.server_proc = None
        
        # Clean up any stray Python processes
        try:
            # Linux/Mac
            subprocess.run(['pkill', '-f', 'server_optimized.py'], 
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(['pkill', '-f', 'client.py'], 
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except:
            pass
        
        print("Cleanup complete")
    
    def start_server(self, test_name):
        """Start the game server"""
        print(f"\n🚀 Starting server for test: {test_name}")
        
        # Create test directory
        test_path = self.test_dir / test_name
        test_path.mkdir(exist_ok=True)
        
        # Clean up first
        self.cleanup()
        time.sleep(2)
        
        # Start server
        server_log = test_path / "server.log"
        print(f"📝 Server log: {server_log}")
        
        # Use sys.executable to run the server script
        server_script = Path("server_optimized.py")
        if not server_script.exists():
            print(f"❌ Error: {server_script} not found!")
            return None
        
        self.server_proc = self.run_command(
            f'"{sys.executable}" "{server_script}"',
            output_file=server_log,
            shell=True
        )
        
        print(f"✅ Server started (PID: {self.server_proc.pid})")
        
        # Wait for server to be ready
        print("⏳ Waiting for server to initialize...", end="", flush=True)
        for i in range(15):  # Wait up to 15 seconds
            if self.server_proc.poll() is not None:
                print("\n❌ Server terminated unexpectedly!")
                # Read error from log
                if server_log.exists():
                    with open(server_log, 'r') as f:
                        print(f"Server error:\n{f.read()}")
                return None
            
            # Check if server is listening (simplified check)
            time.sleep(1)
            print(".", end="", flush=True)
            
            # Quick check if log shows server is ready
            if server_log.exists() and server_log.stat().st_size > 0:
                with open(server_log, 'r') as f:
                    content = f.read()
                    if "started" in content or "Server" in content:
                        print(" ✅")
                        break
        
        time.sleep(2)  # Extra safety wait
        return test_path
    
    def start_clients(self, test_path, num_clients):
        """Start headless clients"""
        print(f"\n🎮 Starting {num_clients} headless clients...")
        
        client_script = Path("client.py")
        if not client_script.exists():
            print(f"❌ Error: {client_script} not found!")
            return
        
        self.client_procs = []
        
        for i in range(num_clients):
            client_id = i + 1
            client_log = test_path / f"client_{client_id}.log"
            
            print(f"  Starting client {client_id}...", end="", flush=True)
            
            # Start client
            proc = self.run_command(
                f'"{sys.executable}" "{client_script}" 127.0.0.1 --headless',
                output_file=client_log,
                shell=True
            )
            
            self.client_procs.append(proc)
            print(f" ✅ (PID: {proc.pid})")
            
            # Stagger client starts
            time.sleep(3)
        
        print("✅ All clients started")
    
    def monitor_test(self, duration):
        """Monitor the test and show progress"""
        print(f"\n⏱️  Test running for {duration} seconds...")
        print("   [", end="", flush=True)
        
        start_time = time.time()
        check_interval = 5  # Check every 5 seconds
        
        while time.time() - start_time < duration:
            elapsed = time.time() - start_time
            progress = int((elapsed / duration) * 40)
            
            # Update progress bar
            bar = "=" * progress + " " * (40 - progress)
            print(f"\r   [{bar}] {int(elapsed)}/{duration}s", end="", flush=True)
            
            # Check if processes are still running
            if self.server_proc and self.server_proc.poll() is not None:
                print(f"\n❌ Server crashed at {int(elapsed)}s!")
                return False
            
            # Check clients
            dead_clients = [i+1 for i, p in enumerate(self.client_procs) if p.poll() is not None]
            if dead_clients:
                print(f"\n⚠️  Clients {dead_clients} crashed at {int(elapsed)}s")
            
            time.sleep(check_interval)
        
        print(f"\r   [{'=' * 40}] ✅ Test complete!")
        return True
    
    def collect_results(self, test_path):
        """Collect and organize results"""
        print(f"\n📊 Collecting results...")
        
        # Look for generated CSV files
        csv_files = list(Path('.').glob('*.csv'))
        moved_files = []
        
        for csv_file in csv_files:
            dest = test_path / csv_file.name
            try:
                if csv_file.exists():
                    csv_file.rename(dest)
                    moved_files.append(csv_file.name)
            except Exception as e:
                print(f"  ⚠️  Couldn't move {csv_file.name}: {e}")
        
        if moved_files:
            print(f"  ✅ Collected: {', '.join(moved_files)}")
        else:
            print("  ℹ️  No CSV files generated")
        
        # Save test metadata
        metadata = {
            'timestamp': time.time(),
            'test_completed': True,
            'files_collected': moved_files
        }
        
        meta_file = test_path / "test_metadata.json"
        with open(meta_file, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        print(f"  ✅ Results saved in: {test_path}")
    
    def run_single_test(self, test_name, config):
        """Run a single test scenario"""
        print(f"\n{'='*60}")
        print(f"🧪 TEST: {config['name']}")
        print(f"{'='*60}")
        
        # Start server
        test_path = self.start_server(test_name)
        if not test_path:
            print("❌ Failed to start server. Skipping test.")
            return False
        
        # Start clients
        self.start_clients(test_path, config['clients'])
        
        # Run test
        success = self.monitor_test(config['duration'])
        
        # Collect results
        if success:
            self.collect_results(test_path)
        
        # Cleanup
        self.cleanup()
        
        # Cool down between tests
        print(f"\n😴 Cooling down for 5 seconds...")
        time.sleep(5)
        
        return success
    
    def run_all_tests(self):
        """Run all configured tests"""
        print("🎯 GRID CLASH AUTOMATED TEST SUITE")
        print("=" * 60)
        print("This script will:")
        print("  1. 🚀 Start the server automatically")
        print("  2. 🎮 Start headless clients")
        print("  3. ⏱️  Run tests for specified durations")
        print("  4. 📊 Collect all results and logs")
        print("  5. 🧹 Clean up everything when done")
        print("=" * 60)
        print(f"Results will be saved in: {self.test_dir}")
        print()
        
        # Ask for confirmation
        response = input("Press Enter to start tests (or type 'no' to cancel): ")
        if response.lower() == 'no':
            print("❌ Tests cancelled.")
            return
        
        print("\n" + "="*60)
        
        # Run tests in order
        test_order = ['baseline', 'loss_2pct', 'loss_5pct']
        successful_tests = []
        failed_tests = []
        
        for test_name in test_order:
            if test_name in self.test_scenarios:
                config = self.test_scenarios[test_name]
                
                try:
                    success = self.run_single_test(test_name, config)
                    
                    if success:
                        successful_tests.append(test_name)
                        print(f"\n✅ Test '{test_name}' PASSED")
                    else:
                        failed_tests.append(test_name)
                        print(f"\n❌ Test '{test_name}' FAILED")
                    
                except KeyboardInterrupt:
                    print(f"\n\n⚠️  Test '{test_name}' INTERRUPTED by user")
                    self.cleanup()
                    break
                except Exception as e:
                    print(f"\n❌ Test '{test_name}' ERROR: {e}")
                    failed_tests.append(test_name)
                    self.cleanup()
        
        # Final summary
        print("\n" + "="*60)
        print("📋 TEST SUITE COMPLETE")
        print("="*60)
        
        if successful_tests:
            print(f"✅ PASSED: {len(successful_tests)} tests")
            for test in successful_tests:
                print(f"   - {test}")
        
        if failed_tests:
            print(f"❌ FAILED: {len(failed_tests)} tests")
            for test in failed_tests:
                print(f"   - {test}")
        
        print(f"\n📁 All results saved in: {self.test_dir}")
        print("\n📈 To analyze results, run:")
        print("   python analyze_result.py")
        print("\n🔍 For individual test analysis:")
        print(f"   python analyze_result.py --dir test_results/baseline")

def main():
    """Main entry point"""
    try:
        tester = GridClashAutoTester()
        tester.run_all_tests()
    except KeyboardInterrupt:
        print("\n\n⚠️  Test suite interrupted by user")
        print("Cleaning up...")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Ensure cleanup
        try:
            tester.cleanup()
        except:
            pass

if __name__ == "__main__":
    main()