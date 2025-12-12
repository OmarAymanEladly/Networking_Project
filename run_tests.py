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

# Global for tshark process
tshark_process = None

def simple_cleanup():
    """Clean up any running processes and files"""
    print("\n🧹 Cleaning up...")
    
    # Kill processes
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
    
    # Remove temporary files
    for f in os.listdir("."):
        if f.endswith((".csv", ".log", ".pcap", ".json")) and os.path.isfile(f):
            try:
                os.remove(f)
            except:
                pass
    
    time.sleep(2)
    print("   ✅ Cleanup complete")

def start_wireshark_capture(test_name):
    """Start tshark capture in background - PDF requires at least two pcap traces per test"""
    global tshark_process
    
    # Create captures directory
    os.makedirs("captures", exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pcap_file = f"captures/{test_name}_{timestamp}.pcap"
    
    print(f"\n📡 Starting network capture...")
    print(f"   Saving to: {pcap_file}")
    
    try:
        if IS_WINDOWS:
            # Windows - use Clumsy for network impairment
            print("   ⚠️  On Windows, use Clumsy for network simulation")
            tshark_process = subprocess.Popen(
                ["tshark", "-i", "1", "-f", "udp port 5555", 
                 "-w", pcap_file, "-q"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
        else:
            # Linux/Mac - use loopback
            tshark_process = subprocess.Popen(
                ["sudo", "tshark", "-i", "lo", "-f", "udp port 5555", 
                 "-w", pcap_file, "-q"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
        time.sleep(3)  # Give tshark time to start
        return pcap_file
    except Exception as e:
        print(f"   ⚠️  Could not start capture: {e}")
        print("   Continuing without packet capture...")
        return None

def stop_wireshark_capture():
    """Stop tshark capture"""
    global tshark_process
    
    if tshark_process and tshark_process.poll() is None:
        try:
            if IS_WINDOWS:
                tshark_process.send_signal(signal.CTRL_C_EVENT)
            else:
                tshark_process.send_signal(signal.SIGINT)
            tshark_process.wait(timeout=5)
        except:
            try:
                tshark_process.terminate()
                tshark_process.wait(timeout=2)
            except:
                try:
                    tshark_process.kill()
                except:
                    pass
        tshark_process = None
        time.sleep(2)

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
                    print("   Current network rules:")
                    subprocess.run(['sudo', 'tc', 'qdisc', 'show', 'dev', 'lo'])
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

def run_single_scenario(scenario_name, loss=0, delay=0, jitter=0, run_number=1):
    """Run a single test scenario - PDF requires 5 repetitions"""
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
    
    # Start Wireshark capture - PDF requires pcap traces
    pcap_file = start_wireshark_capture(f"{scenario_name}_run{run_number}")
    
    # Start Server with appropriate parameters
    print(f"\n[1/3] 🚀 Starting Server...")
    server_log_path = f"{results_dir}/server.log"
    
    # Determine test duration based on scenario
    test_duration = 60  # Default 60 seconds (PDF baseline requirement)
    if scenario_name == "baseline":
        test_duration = 60  # PDF: "1s interval, 60s test"
    
    try:
        server_cmd = [PYTHON_CMD, "-u", SERVER_SCRIPT]
        
        # Add network simulation parameters (software-based fallback)
        if loss > 0:
            server_cmd.extend(["--loss", str(loss)])
        
        server_proc = subprocess.Popen(
            server_cmd,
            stdout=open(server_log_path, "w"),
            stderr=subprocess.STDOUT,
            bufsize=0
        )
        time.sleep(5)  # Give server time to fully initialize
        
        # Check if server is running
        if server_proc.poll() is not None:
            print("   ❌ Server failed to start!")
            if os.path.exists(server_log_path):
                with open(server_log_path, 'r') as f:
                    errors = f.read()
                    print(f"   Server errors: {errors[:500]}")
            return None
        
        print(f"   ✅ Server started (PID: {server_proc.pid})")
        
        # Verify server is listening
        time.sleep(2)
        if IS_WINDOWS:
            netstat_result = subprocess.run(['netstat', '-an'], capture_output=True, text=True)
            listening = ":5555" in netstat_result.stdout and "UDP" in netstat_result.stdout
        else:
            netstat_result = subprocess.run(['sudo', 'netstat', '-tulpn'], capture_output=True, text=True)
            listening = ":5555" in netstat_result.stdout
        
        if listening:
            print("   ✅ Server listening on port 5555")
        else:
            print("   ⚠️  Server may not be listening on port 5555")
            
    except Exception as e:
        print(f"   ❌ Failed to start server: {e}")
        return None
    
    # Start 4 Clients (PDF requirement: "at least 4 concurrent clients")
    print(f"\n[2/3] 👥 Starting 4 Clients...")
    clients = []
    client_procs = []
    
    for i in range(4):
        client_id = i + 1
        client_log_path = f"{results_dir}/client_{client_id}.log"
        
        try:
            # Start client with headless mode and explicit port
            client_proc = subprocess.Popen(
                [PYTHON_CMD, "-u", CLIENT_SCRIPT, "127.0.0.1", "--headless"],
                stdout=open(client_log_path, "w"),
                stderr=subprocess.STDOUT,
                bufsize=0
            )
            client_procs.append(client_proc)
            clients.append(f"player_{client_id}")
            
            print(f"   Client {client_id} started (PID: {client_proc.pid})")
            time.sleep(2)  # Stagger client connections (important!)
            
        except Exception as e:
            print(f"   ❌ Failed to start client {client_id}: {e}")
    
    # Wait for clients to connect
    print(f"\n   Waiting for connections to establish...")
    time.sleep(10)  # Longer wait for all clients to connect properly
    
    # Check connection status
    connected_clients = 0
    for i in range(4):
        client_id = i + 1
        client_log_path = f"{results_dir}/client_{client_id}.log"
        
        if os.path.exists(client_log_path) and os.path.getsize(client_log_path) > 50:
            try:
                with open(client_log_path, 'r') as f:
                    content = f.read()
                    
                    # Check for connection success indicators
                    success_indicators = ["Connected!", "[OK]", "Assigned ID", "player_"]
                    if any(indicator in content for indicator in success_indicators):
                        print(f"   ✅ Client {client_id} connected successfully")
                        connected_clients += 1
                    elif "ERROR" in content or "failed" in content.lower():
                        print(f"   ❌ Client {client_id} failed")
                    else:
                        # Check last few lines
                        lines = content.strip().split('\n')[-5:]
                        if any("player_" in line for line in lines):
                            print(f"   ✅ Client {client_id} appears connected")
                            connected_clients += 1
                        else:
                            print(f"   ⚠️  Client {client_id} no clear connection indicator")
            except Exception as e:
                print(f"   ❌ Error reading client {client_id} log: {e}")
        else:
            print(f"   ⚠️  Client {client_id} log missing or empty")
    
    if connected_clients < 4:
        print(f"   ⚠️  Only {connected_clients}/4 clients connected")
        if connected_clients == 0:
            # Check server logs for clues
            if os.path.exists(server_log_path):
                with open(server_log_path, 'r') as f:
                    server_log = f.read()[-1000:]
                    print(f"   Last server output:\n{server_log}")
    
    # Run test for specified duration
    print(f"\n[3/3] ⏱️  Running test for {test_duration} seconds...")
    print(f"   Scenario: {scenario_name}")
    print(f"   Network: Loss={loss}%, Delay={delay}ms, Jitter={jitter}ms")
    
    start_time = time.time()
    last_update = start_time
    
    try:
        while time.time() - start_time < test_duration:
            current_time = time.time()
            elapsed = int(current_time - start_time)
            remaining = test_duration - elapsed
            
            # Print progress every 10 seconds
            if current_time - last_update >= 10:
                print(f"   Progress: {elapsed:3d}s / {test_duration}s ({remaining:3d}s remaining)")
                last_update = current_time
            
            print(f"\r   Time: {elapsed:3d}s / {test_duration}s", end='', flush=True)
            time.sleep(1)
        
        print(f"\n   ✅ Test duration completed")
        
    except KeyboardInterrupt:
        print(f"\n\n⚠️  Test interrupted by user")
        test_duration = int(time.time() - start_time)
    
    # Stop processes
    print(f"\n🧹 Stopping processes...")
    
    # Stop clients
    for i, client_proc in enumerate(client_procs):
        try:
            client_proc.terminate()
            client_proc.wait(timeout=2)
            print(f"   Client {i+1} stopped")
        except:
            try:
                client_proc.kill()
                print(f"   Client {i+1} killed")
            except:
                pass
    
    # Stop server
    try:
        server_proc.terminate()
        server_proc.wait(timeout=3)
        print("   Server stopped")
    except:
        try:
            server_proc.kill()
            print("   Server killed")
        except:
            pass
    
    time.sleep(3)
    
    # Stop Wireshark capture
    stop_wireshark_capture()
    
    # Collect results
    print(f"\n📂 Collecting test results...")
    
    # Move CSV files (generated by client.py and server_optimized.py)
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
    
    # Move pcap file
    if pcap_file and os.path.exists(pcap_file):
        try:
            dest = os.path.join(results_dir, os.path.basename(pcap_file))
            shutil.move(pcap_file, dest)
            print(f"   📄 {os.path.basename(pcap_file)}")
        except:
            pass
    
    # Collect log files
    log_files = []
    for f in os.listdir("."):
        if f.endswith(".log") and os.path.isfile(f):
            try:
                dest = os.path.join(results_dir, f)
                shutil.move(f, dest)
                log_files.append(f)
            except:
                pass
    
    # Create a test metadata file
    metadata = {
        "test_name": scenario_name,
        "run_number": run_number,
        "timestamp": timestamp,
        "duration": test_duration,
        "network_conditions": {
            "loss_percent": loss,
            "delay_ms": delay,
            "jitter_ms": jitter
        },
        "clients_connected": connected_clients,
        "files_collected": {
            "csv_files": csv_files,
            "log_files": log_files,
            "pcap_file": os.path.basename(pcap_file) if pcap_file and os.path.exists(pcap_file) else None
        }
    }
    
    metadata_path = os.path.join(results_dir, "test_metadata.json")
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    
    # Create a summary file
    summary_path = os.path.join(results_dir, "test_summary.txt")
    with open(summary_path, 'w') as f:
        f.write(f"Test: {scenario_name} (Run {run_number})\n")
        f.write(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Duration: {test_duration}s\n")
        f.write(f"Network: Loss={loss}%, Delay={delay}ms, Jitter={jitter}ms\n")
        f.write(f"Connected clients: {connected_clients}/4\n")
        f.write(f"CSV files: {len(csv_files)}\n")
        f.write(f"Log files: {len(log_files)}\n")
        f.write(f"PCAP file: {'Yes' if pcap_file and os.path.exists(pcap_file) else 'No'}\n")
        f.write("\nFiles:\n")
        for file in sorted(csv_files + log_files):
            f.write(f"  {file}\n")
    
    print(f"\n✅ {scenario_name} test (run {run_number}) completed!")
    print(f"   Results saved in: {results_dir}")
    print(f"   CSV files: {len(csv_files)}")
    print(f"   Summary: {os.path.basename(summary_path)}")
    
    return {
        "directory": results_dir,
        "connected_clients": connected_clients,
        "metadata": metadata
    }

def run_scenario_with_repetitions(scenario_name, loss=0, delay=0, jitter=0):
    """Run a scenario multiple times (PDF requires at least 5 repetitions)"""
    print(f"\n📊 Running scenario: {scenario_name}")
    print(f"   Repetitions: 5 (as per PDF requirements)")
    print(f"   Network: Loss={loss}%, Delay={delay}ms, Jitter={jitter}ms")
    
    results = []
    
    for run_num in range(1, 6):  # 5 repetitions
        print(f"\n{'#'*80}")
        print(f"🚀 REPETITION {run_num}/5: {scenario_name.upper()}")
        print(f"{'#'*80}")
        
        result = run_single_scenario(scenario_name, loss, delay, jitter, run_num)
        results.append(result)
        
        # Clean up between runs (except after last)
        if run_num < 5:
            print(f"\n⏳ Waiting 15 seconds before next repetition...")
            time.sleep(15)
            simple_cleanup()
    
    return results

def run_all_scenarios():
    """Run all test scenarios from the PDF with 5 repetitions each"""
    # Test scenarios as specified in PDF Project 2
    scenarios = [
        # (name, loss%, delay_ms, jitter_ms)
        ("baseline", 0, 0, 0),
        ("loss_2pct", 2, 0, 0),      # LAN-like loss
        ("loss_5pct", 5, 0, 0),      # WAN-like loss
        ("delay_100ms", 0, 100, 0),   # WAN delay
        ("delay_jitter", 0, 100, 10), # Delay with jitter
    ]
    
    print(f"\n📋 Running {len(scenarios)} test scenarios")
    print(f"Each scenario will run 5 times (as per PDF requirements)")
    print(f"Baseline test duration: 60 seconds")
    print(f"Other tests: 40 seconds")
    
    all_results = {}
    
    for scenario in scenarios:
        name, loss, delay, jitter = scenario
        
        print(f"\n{'='*80}")
        print(f"🚀 STARTING SCENARIO: {name.upper()}")
        print(f"   Loss: {loss}%, Delay: {delay}ms, Jitter: {jitter}ms")
        print(f"{'='*80}")
        
        scenario_results = run_scenario_with_repetitions(name, loss, delay, jitter)
        all_results[name] = scenario_results
        
        # Clean up between scenarios (except after last)
        if scenario != scenarios[-1]:
            print(f"\n⏳ Waiting 30 seconds before next scenario...")
            time.sleep(30)
            simple_cleanup()
    
    return all_results

def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="Grid Clash Network Test Suite - PDF Compliant")
    parser.add_argument("--scenario", choices=["all", "baseline", "loss_2pct", "loss_5pct", 
                                              "delay_100ms", "delay_jitter"], 
                       default="all", help="Test scenario to run")
    parser.add_argument("--repetitions", type=int, default=5, 
                       help="Number of repetitions (PDF requires at least 5)")
    parser.add_argument("--duration", type=int, default=60, 
                       help="Test duration in seconds (baseline should be 60s)")
    parser.add_argument("--interface", default="lo" if not IS_WINDOWS else "1",
                       help="Network interface for capture")
    parser.add_argument("--skip-capture", action="store_true",
                       help="Skip packet capture (for faster testing)")
    args = parser.parse_args()
    
    global DURATION
    DURATION = args.duration
    
    print(f"\n{'='*80}")
    print(f"🕹️  GRID CLASH - PDF COMPLIANT NETWORK TEST SUITE")
    print(f"{'='*80}")
    print(f"Platform: {platform.system()} {platform.release()}")
    print(f"Python: {sys.executable}")
    print(f"Server: {SERVER_SCRIPT}")
    print(f"Client: {CLIENT_SCRIPT}")
    print(f"Test duration: {args.duration} seconds")
    print(f"Repetitions: {args.repetitions} (PDF minimum: 5)")
    print(f"Network interface: {args.interface}")
    print(f"{'='*80}")
    
    # Create directories
    os.makedirs("test_results", exist_ok=True)
    os.makedirs("captures", exist_ok=True)
    
    # Initial cleanup
    simple_cleanup()
    
    # Run tests
    if args.scenario == "all":
        results = run_all_scenarios()
        
        print(f"\n{'='*80}")
        print(f"🎉 ALL TESTS COMPLETED!")
        print(f"{'='*80}")
        
        print(f"\n📊 Summary of results:")
        for scenario_name, scenario_results in results.items():
            successful_runs = sum(1 for r in scenario_results if r and r.get('connected_clients', 0) >= 3)
            print(f"   {scenario_name}: {successful_runs}/5 runs successful")
        
        print(f"\n📁 All results saved in: test_results/")
        print(f"📊 Run analysis: python analyze_results.py")
        
        # Save overall summary
        summary_path = "test_results/test_summary_overall.json"
        with open(summary_path, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"📄 Overall summary: {summary_path}")
        
    else:
        # Run single scenario with repetitions
        scenario_map = {
            "baseline": ("baseline", 0, 0, 0),
            "loss_2pct": ("loss_2pct", 2, 0, 0),
            "loss_5pct": ("loss_5pct", 5, 0, 0),
            "delay_100ms": ("delay_100ms", 0, 100, 0),
            "delay_jitter": ("delay_jitter", 0, 100, 10),
        }
        
        if args.scenario in scenario_map:
            name, loss, delay, jitter = scenario_map[args.scenario]
            run_scenario_with_repetitions(name, loss, delay, jitter)
        else:
            print(f"❌ Unknown scenario: {args.scenario}")
    
    print(f"\n{'='*80}")
    print(f"🏁 TESTING COMPLETE")
    print(f"{'='*80}")
    
    # Final cleanup
    simple_cleanup()

if __name__ == "__main__":
    main()