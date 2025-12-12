import subprocess
import time
import os
import signal
import sys
import shutil
import platform
import argparse
import threading
import json
from datetime import datetime

# Configuration
SERVER_SCRIPT = "server_optimized.py"
CLIENT_SCRIPT = "client.py"
PYTHON_CMD = sys.executable
DURATION = 60  # PDF requires 60s for baseline test

IS_LINUX = platform.system() == "Linux"
IS_WINDOWS = platform.system() == "Windows"

class PCAPManager:
    """Manage PCAP capture processes"""
    def __init__(self):
        self.processes = []
        self.pcap_files = []
        
    def start_capture(self, test_name, interface="lo", port=5555):
        """Start tshark capture for specific test"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pcap_file = f"captures/{test_name}_{timestamp}.pcap"
        
        # Ensure captures directory exists
        os.makedirs("captures", exist_ok=True)
        
        print(f"📡 Starting PCAP capture: {os.path.basename(pcap_file)}")
        
        try:
            if IS_WINDOWS:
                # On Windows, try to find the right interface
                cmd = ["tshark", "-i", interface, "-f", f"udp port {port}", 
                      "-w", pcap_file, "-q"]
            else:
                # Linux/Mac - use sudo for tshark
                cmd = ["sudo", "tshark", "-i", interface, "-f", f"udp port {port}", 
                      "-w", pcap_file, "-q"]
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            self.processes.append(process)
            self.pcap_files.append(pcap_file)
            
            # Wait a moment for tshark to start
            time.sleep(2)
            
            # Verify it's running
            if process.poll() is None:
                print(f"   ✅ PCAP capture running (PID: {process.pid})")
                return pcap_file
            else:
                stdout, stderr = process.communicate()
                print(f"   ❌ PCAP failed to start: {stderr}")
                return None
                
        except FileNotFoundError:
            print(f"   ⚠️  tshark not found. Install Wireshark/tshark first.")
            print(f"   On Ubuntu: sudo apt-get install tshark")
            print(f"   On Windows: Install Wireshark (includes tshark)")
            return None
        except Exception as e:
            print(f"   ❌ PCAP error: {e}")
            return None
    
    def stop_all(self):
        """Stop all PCAP captures"""
        for process in self.processes:
            if process and process.poll() is None:
                try:
                    if IS_WINDOWS:
                        process.send_signal(signal.CTRL_C_EVENT)
                    else:
                        process.send_signal(signal.SIGINT)
                    
                    # Wait for graceful shutdown
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                        process.wait(timeout=1)
                except:
                    pass
        
        self.processes = []
        time.sleep(1)
        print("   ✅ All PCAP captures stopped")
    
    def get_pcap_files(self):
        """Get list of captured PCAP files"""
        return [f for f in self.pcap_files if os.path.exists(f)]

def simple_cleanup():
    """Clean up any running processes and files"""
    print("\n🧹 Cleaning up...")
    
    # Kill Python processes
    try:
        if IS_WINDOWS:
            subprocess.run(['taskkill', '/F', '/IM', 'python.exe'], 
                          stdout=subprocess.DEVNULL, 
                          stderr=subprocess.DEVNULL)
            subprocess.run(['taskkill', '/F', '/IM', 'tshark.exe'], 
                          stdout=subprocess.DEVNULL, 
                          stderr=subprocess.DEVNULL)
        else:
            subprocess.run(['pkill', '-f', f"{PYTHON_CMD}.*{SERVER_SCRIPT}"], 
                          stdout=subprocess.DEVNULL, 
                          stderr=subprocess.DEVNULL)
            subprocess.run(['pkill', '-f', f"{PYTHON_CMD}.*{CLIENT_SCRIPT}"], 
                          stdout=subprocess.DEVNULL, 
                          stderr=subprocess.DEVNULL)
            subprocess.run(['pkill', '-f', 'tshark'], 
                          stdout=subprocess.DEVNULL, 
                          stderr=subprocess.DEVNULL)
        time.sleep(2)
    except:
        pass
    
    # Clean network rules (Linux only)
    if IS_LINUX:
        try:
            subprocess.run(['sudo', 'tc', 'qdisc', 'del', 'dev', 'lo', 'root'], 
                          stdout=subprocess.DEVNULL, 
                          stderr=subprocess.DEVNULL)
        except:
            pass
    
    time.sleep(2)
    print("   ✅ Cleanup complete")

def apply_network_conditions(scenario_name):
    """Apply network conditions using tc netem (Linux only) according to PDF specifications"""
    print(f"\n🌐 Applying network conditions for: {scenario_name}")
    
    if not IS_LINUX:
        print("   ⚠️  Network simulation only available on Linux")
        print("   On Windows, use Clumsy tool for network impairment")
        return True
    
    # Clean existing rules
    try:
        subprocess.run(['sudo', 'tc', 'qdisc', 'del', 'dev', 'lo', 'root'], 
                      stdout=subprocess.DEVNULL, 
                      stderr=subprocess.DEVNULL)
        time.sleep(1)
    except:
        pass
    
    # Apply scenario-specific conditions (PDF requirements)
    scenario_commands = {
        "baseline": [],  # No impairment
        "loss_2pct": ['sudo', 'tc', 'qdisc', 'add', 'dev', 'lo', 'root', 'netem', 'loss', '2%'],
        "loss_5pct": ['sudo', 'tc', 'qdisc', 'add', 'dev', 'lo', 'root', 'netem', 'loss', '5%'],
        "delay_100ms": ['sudo', 'tc', 'qdisc', 'add', 'dev', 'lo', 'root', 'netem', 'delay', '100ms'],
        "delay_jitter": ['sudo', 'tc', 'qdisc', 'add', 'dev', 'lo', 'root', 'netem', 'delay', '100ms', '10ms'],
    }
    
    if scenario_name in scenario_commands:
        cmd = scenario_commands[scenario_name]
        if cmd:  # Only run if there's a command (not baseline)
            try:
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    print(f"   ✅ Network conditions applied: {scenario_name}")
                    
                    # Verify the rules
                    print("   📋 Current network rules:")
                    verify_result = subprocess.run(['sudo', 'tc', 'qdisc', 'show', 'dev', 'lo'], 
                                                  capture_output=True, text=True)
                    if verify_result.returncode == 0:
                        print(f"      {verify_result.stdout.strip()}")
                    
                    return True
                else:
                    print(f"   ❌ Failed to apply network conditions")
                    print(f"   Error: {result.stderr}")
                    return False
            except Exception as e:
                print(f"   ❌ Exception: {e}")
                return False
        else:
            print("   ✅ Baseline network conditions (no impairment)")
            return True
    else:
        print(f"   ⚠️  Unknown scenario: {scenario_name}")
        return True

def run_single_scenario(scenario_name, loss=0, delay=0, jitter=0, run_number=1, pcap_manager=None):
    """Run a single test scenario with PCAP capture"""
    print(f"\n{'='*60}")
    print(f"🏁 TEST RUN {run_number}: {scenario_name.upper()}")
    print(f"{'='*60}")
    
    # Clean up first
    simple_cleanup()
    
    # Create results directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_dir = f"test_results/{scenario_name}/run_{run_number}_{timestamp}"
    os.makedirs(results_dir, exist_ok=True)
    
    # Apply network conditions (Linux only)
    if IS_LINUX:
        if not apply_network_conditions(scenario_name):
            print("   ⚠️  Failed to apply network conditions, continuing anyway...")
    
    # Start PCAP capture (PDF requires pcap traces)
    pcap_file = None
    if pcap_manager:
        pcap_file = pcap_manager.start_capture(f"{scenario_name}_run{run_number}")
    
    # Determine test duration based on scenario
    test_duration = 60 if scenario_name == "baseline" else 40
    
    # Start Server
    print(f"\n[1/3] 🚀 Starting Server...")
    server_log_path = f"{results_dir}/server.log"
    
    try:
        server_cmd = [PYTHON_CMD, "-u", SERVER_SCRIPT]
        
        # Add network simulation parameters (software-based fallback for Windows)
        if loss > 0 and not IS_LINUX:
            server_cmd.extend(["--loss", str(loss/100)])  # Convert percentage to decimal
        
        server_proc = subprocess.Popen(
            server_cmd,
            stdout=open(server_log_path, "w"),
            stderr=subprocess.STDOUT,
            bufsize=0
        )
        time.sleep(5)  # Give server time to initialize
        
        if server_proc.poll() is not None:
            print("   ❌ Server failed to start!")
            return None
        
        print(f"   ✅ Server started (PID: {server_proc.pid})")
        
        # Verify server is listening
        time.sleep(2)
        if IS_WINDOWS:
            netstat_result = subprocess.run(['netstat', '-an'], capture_output=True, text=True)
            listening = ":5555" in netstat_result.stdout
        else:
            netstat_result = subprocess.run(['sudo', 'lsof', '-i', ':5555'], 
                                          capture_output=True, text=True)
            listening = netstat_result.returncode == 0
        
        if listening:
            print("   ✅ Server listening on port 5555")
        else:
            print("   ⚠️  Server may not be listening on port 5555")
            
    except Exception as e:
        print(f"   ❌ Failed to start server: {e}")
        return None
    
    # Start 4 Clients
    print(f"\n[2/3] 👥 Starting 4 Clients...")
    client_procs = []
    client_log_paths = []
    
    for i in range(4):
        client_id = i + 1
        client_log_path = f"{results_dir}/client_{client_id}.log"
        client_log_paths.append(client_log_path)
        
        try:
            client_proc = subprocess.Popen(
                [PYTHON_CMD, "-u", CLIENT_SCRIPT, "127.0.0.1", "--headless"],
                stdout=open(client_log_path, "w"),
                stderr=subprocess.STDOUT,
                bufsize=0
            )
            client_procs.append(client_proc)
            
            print(f"   Client {client_id} started (PID: {client_proc.pid})")
            time.sleep(1.5)  # Stagger client connections
            
        except Exception as e:
            print(f"   ❌ Failed to start client {client_id}: {e}")
    
    # Wait for connections
    print(f"\n   Waiting for connections...")
    time.sleep(8)
    
    # Check connections
    connected_clients = 0
    for i, log_path in enumerate(client_log_paths):
        if os.path.exists(log_path):
            try:
                with open(log_path, 'r') as f:
                    content = f.read()
                    if any(indicator in content for indicator in 
                          ["Connected!", "[OK]", "Assigned ID", "player_"]):
                        connected_clients += 1
                        print(f"   ✅ Client {i+1} connected")
                    else:
                        print(f"   ⚠️  Client {i+1} connection status unclear")
            except:
                pass
    
    print(f"   📊 {connected_clients}/4 clients connected")
    
    # Run test
    print(f"\n[3/3] ⏱️  Running test for {test_duration} seconds...")
    start_time = time.time()
    
    try:
        for second in range(test_duration):
            elapsed = second + 1
            remaining = test_duration - elapsed
            
            if second % 10 == 0:
                print(f"   Progress: {elapsed:3d}s / {test_duration}s ({remaining:3d}s remaining)")
            
            time.sleep(1)
        
        print(f"\n   ✅ Test completed")
        
    except KeyboardInterrupt:
        print(f"\n\n⚠️  Test interrupted")
        test_duration = int(time.time() - start_time)
    
    # Stop processes
    print(f"\n🧹 Stopping processes...")
    
    # Stop clients
    for i, client_proc in enumerate(client_procs):
        try:
            client_proc.terminate()
            client_proc.wait(timeout=2)
        except:
            try:
                client_proc.kill()
            except:
                pass
    
    # Stop server
    try:
        server_proc.terminate()
        server_proc.wait(timeout=3)
    except:
        try:
            server_proc.kill()
        except:
            pass
    
    time.sleep(2)
    
    # Collect results
    print(f"\n📂 Collecting results...")
    
    # Collect CSV files
    csv_files = []
    for f in os.listdir("."):
        if f.endswith(".csv") and os.path.isfile(f):
            try:
                dest = os.path.join(results_dir, f)
                shutil.move(f, dest)
                csv_files.append(f)
                print(f"   📄 {f}")
            except Exception as e:
                print(f"   ⚠️  Could not move {f}: {e}")
    
    # Move PCAP file if captured
    if pcap_file and os.path.exists(pcap_file):
        try:
            pcap_dest = os.path.join(results_dir, os.path.basename(pcap_file))
            shutil.move(pcap_file, pcap_dest)
            print(f"   📦 PCAP: {os.path.basename(pcap_file)}")
        except Exception as e:
            print(f"   ⚠️  Could not move PCAP: {e}")
            # Copy instead if move fails
            try:
                pcap_dest = os.path.join(results_dir, os.path.basename(pcap_file))
                shutil.copy(pcap_file, pcap_dest)
                print(f"   📦 PCAP (copied): {os.path.basename(pcap_file)}")
            except:
                pass
    
    # Move log files
    log_files = []
    for f in os.listdir("."):
        if f.endswith(".log") and os.path.isfile(f):
            try:
                dest = os.path.join(results_dir, f)
                shutil.move(f, dest)
                log_files.append(f)
            except:
                pass
    
    # Create metadata
    metadata = {
        "test_name": scenario_name,
        "run_number": run_number,
        "timestamp": timestamp,
        "duration": test_duration,
        "network": {"loss": loss, "delay": delay, "jitter": jitter},
        "clients_connected": connected_clients,
        "files": {
            "csv": csv_files,
            "logs": log_files,
            "pcap": os.path.basename(pcap_file) if pcap_file and os.path.exists(pcap_file) else None
        }
    }
    
    metadata_path = os.path.join(results_dir, "metadata.json")
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    
    # Create summary
    summary_path = os.path.join(results_dir, "summary.txt")
    with open(summary_path, 'w') as f:
        f.write(f"Test: {scenario_name} (Run {run_number})\n")
        f.write(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Duration: {test_duration}s\n")
        f.write(f"Network: Loss={loss}%, Delay={delay}ms, Jitter={jitter}ms\n")
        f.write(f"Clients: {connected_clients}/4 connected\n")
        f.write(f"Files collected: {len(csv_files)} CSV, {len(log_files)} logs\n")
        f.write(f"PCAP captured: {'Yes' if pcap_file and os.path.exists(pcap_file) else 'No'}\n")
    
    print(f"\n✅ {scenario_name} run {run_number} complete!")
    print(f"   Results: {results_dir}")
    
    return {
        "dir": results_dir,
        "connected": connected_clients,
        "pcap": pcap_file if pcap_file and os.path.exists(pcap_file) else None
    }

def run_scenario_with_pcaps(scenario_name, loss=0, delay=0, jitter=0):
    """Run a scenario with PCAP capture (at least 2 runs with PCAP as per PDF)"""
    print(f"\n📊 Running: {scenario_name}")
    print(f"   Will run 5 times total, with PCAP for runs 1 & 2 (PDF requirement)")
    
    results = []
    pcap_manager = PCAPManager()
    
    try:
        # First 2 runs with PCAP (PDF requires at least 2 PCAPs per scenario)
        for run_num in range(1, 3):
            print(f"\n{'#'*80}")
            print(f"📦 RUN {run_num}/2 (WITH PCAP): {scenario_name.upper()}")
            print(f"{'#'*80}")
            
            result = run_single_scenario(scenario_name, loss, delay, jitter, 
                                       run_num, pcap_manager)
            results.append(result)
            
            # Stop PCAP for this run
            pcap_manager.stop_all()
            
            if run_num < 2:
                print(f"\n⏳ Waiting 10 seconds...")
                time.sleep(10)
                simple_cleanup()
        
        # Remaining runs without PCAP (faster)
        for run_num in range(3, 6):
            print(f"\n{'#'*80}")
            print(f"⚡ RUN {run_num}/5 (NO PCAP): {scenario_name.upper()}")
            print(f"{'#'*80}")
            
            result = run_single_scenario(scenario_name, loss, delay, jitter, 
                                       run_num, None)  # No PCAP manager
            results.append(result)
            
            if run_num < 5:
                print(f"\n⏳ Waiting 10 seconds...")
                time.sleep(10)
                simple_cleanup()
    
    finally:
        # Ensure PCAP is stopped
        pcap_manager.stop_all()
    
    # Count PCAPs captured
    pcap_count = sum(1 for r in results if r and r.get('pcap'))
    print(f"\n📦 PCAP Summary: {pcap_count}/2 required PCAPs captured")
    
    return results

def verify_pcap_requirements():
    """Verify we have the tools needed for PCAP capture"""
    print("\n🔍 Verifying PCAP requirements...")
    
    # Check for tshark
    try:
        if IS_WINDOWS:
            result = subprocess.run(['tshark', '--version'], 
                                  capture_output=True, text=True)
        else:
            result = subprocess.run(['which', 'tshark'], 
                                  capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ tshark is available")
            
            # Check if we can capture (need sudo on Linux)
            if not IS_WINDOWS:
                test_capture = subprocess.run(
                    ['sudo', 'tshark', '-D'],
                    capture_output=True, text=True
                )
                if test_capture.returncode == 0:
                    print("✅ Can run tshark with sudo")
                    interfaces = [line for line in test_capture.stdout.split('\n') 
                                if 'lo' in line or 'Loopback' in line]
                    if interfaces:
                        print(f"✅ Loopback interface found: {interfaces[0].split()[1]}")
                    else:
                        print("⚠️  Loopback interface not listed")
                else:
                    print("❌ Cannot run tshark with sudo")
                    print(f"   Error: {test_capture.stderr}")
                    return False
            return True
        else:
            print("❌ tshark not found or not working")
            return False
            
    except FileNotFoundError:
        print("❌ tshark not installed")
        print("\n📦 Install instructions:")
        print("  Ubuntu/Debian: sudo apt-get install tshark")
        print("  macOS: brew install wireshark")
        print("  Windows: Install Wireshark (includes tshark)")
        return False

def check_sudo_access():
    """Check if we have sudo access for netem and tshark"""
    if not IS_LINUX:
        return True
    
    print("\n🔐 Checking sudo access...")
    try:
        # Test sudo for netem
        test_result = subprocess.run(
            ['sudo', 'tc', 'qdisc', 'show', 'dev', 'lo'],
            capture_output=True, text=True
        )
        
        if test_result.returncode == 0:
            print("✅ sudo access granted for network configuration")
            return True
        else:
            print("❌ sudo access failed")
            print(f"   Error: {test_result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ sudo check failed: {e}")
        return False

def main():
    """Main test runner"""
    parser = argparse.ArgumentParser(description="Grid Clash Network Tests with PCAP")
    parser.add_argument("--scenario", choices=["all", "baseline", "loss_2pct", 
                                              "loss_5pct", "delay_100ms", "delay_jitter"],
                       default="all", help="Scenario to test")
    parser.add_argument("--no-pcap", action="store_true", help="Skip PCAP capture")
    parser.add_argument("--interface", default="lo" if IS_LINUX else "1",
                       help="Network interface for capture")
    parser.add_argument("--skip-checks", action="store_true",
                       help="Skip prerequisite checks")
    args = parser.parse_args()
    
    print(f"\n{'='*80}")
    print(f"🕹️  GRID CLASH - COMPLETE TEST SUITE WITH PCAP")
    print(f"{'='*80}")
    print(f"Platform: {platform.system()}")
    print(f"Python: {sys.version.split()[0]}")
    print(f"PCAP Capture: {'Disabled' if args.no_pcap else 'Enabled'}")
    print(f"Interface: {args.interface}")
    print(f"{'='*80}")
    
    # Create directories
    os.makedirs("test_results", exist_ok=True)
    os.makedirs("captures", exist_ok=True)
    
    # Initial cleanup
    simple_cleanup()
    
    # Check prerequisites if not skipped
    if not args.skip_checks:
        # Check PCAP capability if enabled
        if not args.no_pcap and not verify_pcap_requirements():
            print("\n⚠️  PCAP requirements not met. Running tests without PCAP.")
            args.no_pcap = True
        
        # Check sudo on Linux
        if IS_LINUX and not check_sudo_access():
            print("\n⚠️  Sudo access issues. Network simulation may not work.")
    
    # Define scenarios
    scenarios = {
        "baseline": (0, 0, 0),
        "loss_2pct": (2, 0, 0),
        "loss_5pct": (5, 0, 0),
        "delay_100ms": (0, 100, 0),
        "delay_jitter": (0, 100, 10),
    }
    
    all_results = {}
    
    if args.scenario == "all":
        # Run all scenarios
        for scenario_name, (loss, delay, jitter) in scenarios.items():
            print(f"\n{'='*80}")
            print(f"🚀 STARTING SCENARIO: {scenario_name.upper()}")
            print(f"{'='*80}")
            
            # Use PCAP manager only if not disabled
            pcap_manager = None if args.no_pcap else PCAPManager()
            
            scenario_results = run_scenario_with_pcaps(
                scenario_name, loss, delay, jitter
            )
            all_results[scenario_name] = scenario_results
            
            # Cleanup between scenarios
            if scenario_name != list(scenarios.keys())[-1]:
                print(f"\n⏳ Waiting 30 seconds...")
                time.sleep(30)
                simple_cleanup()
    
    else:
        # Run single scenario
        if args.scenario in scenarios:
            loss, delay, jitter = scenarios[args.scenario]
            pcap_manager = None if args.no_pcap else PCAPManager()
            
            results = run_scenario_with_pcaps(
                args.scenario, loss, delay, jitter
            )
            all_results[args.scenario] = results
        else:
            print(f"❌ Unknown scenario: {args.scenario}")
            return
    
    # Generate final summary
    print(f"\n{'='*80}")
    print(f"📊 TESTING COMPLETE - SUMMARY")
    print(f"{'='*80}")
    
    total_pcaps = 0
    for scenario_name, results in all_results.items():
        if results:
            successful = sum(1 for r in results if r and r.get('connected', 0) >= 3)
            pcaps = sum(1 for r in results if r and r.get('pcap'))
            total_pcaps += pcaps
            
            print(f"\n{scenario_name.upper()}:")
            print(f"  Successful runs: {successful}/5")
            print(f"  PCAP files: {pcaps}/2")
            if pcaps < 2:
                print(f"  ⚠️  Warning: Only {pcaps} PCAPs (PDF requires at least 2)")
    
    print(f"\n📦 Total PCAP files captured: {total_pcaps}")
    print(f"📁 Results saved in: test_results/")
    print(f"📦 PCAP files in: captures/")
    
    if total_pcaps > 0:
        print(f"\n🔍 To analyze PCAP files:")
        print(f"   wireshark captures/*.pcap")
        print(f"   Or: tshark -r captures/filename.pcap")
    
    print(f"\n📊 To analyze results: python analyze_results.py")
    print(f"{'='*80}")

if __name__ == "__main__":
    main()