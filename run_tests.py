import subprocess
import time
import os
import signal
import sys
import shutil
import platform
import argparse
import threading

# Configuration
SERVER_SCRIPT = "server_optimized.py"
CLIENT_SCRIPT = "client.py"
PYTHON_CMD = sys.executable
DURATION = 40  # Test duration in seconds

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
        if f.endswith((".csv", ".log", ".pcap")) and os.path.isfile(f):
            try:
                os.remove(f)
            except:
                pass
    
    time.sleep(2)
    print("   ✅ Cleanup complete")

def start_wireshark_capture(test_name):
    """Start tshark capture in background"""
    global tshark_process
    
    # Create captures directory
    os.makedirs("captures", exist_ok=True)
    
    timestamp = int(time.time())
    pcap_file = f"captures/{test_name}_{timestamp}.pcap"
    
    print(f"\n📡 Starting network capture...")
    print(f"   Saving to: {pcap_file}")
    
    try:
        if IS_WINDOWS:
            # Windows - find default interface
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

def apply_network_conditions(loss=0, delay=0, jitter=0):
    """Apply network conditions using tc netem (Linux only)"""
    print(f"\n🌐 Applying network conditions:")
    print(f"   Loss: {loss}%, Delay: {delay}ms, Jitter: {jitter}ms")
    
    if not IS_LINUX:
        print("   ⚠️  Network simulation only available on Linux")
        print("   Using built-in client/server simulation")
        return True
    
    # Clean existing rules
    try:
        subprocess.run(['sudo', 'tc', 'qdisc', 'del', 'dev', 'lo', 'root'], 
                      stdout=subprocess.DEVNULL, 
                      stderr=subprocess.DEVNULL)
    except:
        pass
    
    # Apply baseline (no impairment)
    if loss == 0 and delay == 0 and jitter == 0:
        print("   ✅ Baseline network conditions")
        return True
    
    # Build netem command
    netem_cmd = ['sudo', 'tc', 'qdisc', 'add', 'dev', 'lo', 'root', 'netem']
    
    if loss > 0:
        netem_cmd.extend(['loss', f'{loss}%'])
    
    if delay > 0:
        if jitter > 0:
            netem_cmd.extend(['delay', f'{delay}ms', f'{jitter}ms', 'distribution', 'normal'])
        else:
            netem_cmd.extend(['delay', f'{delay}ms'])
    
    try:
        result = subprocess.run(netem_cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"   ✅ Network conditions applied successfully")
            
            # Verify the rules
            subprocess.run(['sudo', 'tc', 'qdisc', 'show', 'dev', 'lo'])
            return True
        else:
            print(f"   ❌ Failed to apply network conditions")
            print(f"   Error: {result.stderr}")
            return False
    except Exception as e:
        print(f"   ❌ Exception: {e}")
        return False

def run_scenario(name, loss, delay, jitter):
    """Run a single test scenario"""
    print(f"\n{'='*60}")
    print(f"🏁 STARTING TEST: {name}")
    print(f"{'='*60}")
    
    # Clean up first
    simple_cleanup()
    
    # Create results directory
    timestamp = int(time.time())
    results_dir = f"test_results/{name}_{timestamp}"
    os.makedirs(results_dir, exist_ok=True)
    
    # Apply network conditions
    if IS_LINUX:
        if not apply_network_conditions(loss, delay, jitter):
            print("   ⚠️  Continuing with software simulation")
    
    # Start Wireshark capture
    pcap_file = start_wireshark_capture(name)
    
    # Start Server
    print(f"\n[1/3] 🚀 Starting Server...")
    server_log_path = f"{results_dir}/server.log"
    
    try:
        server_proc = subprocess.Popen(
            [PYTHON_CMD, "-u", SERVER_SCRIPT],
            stdout=open(server_log_path, "w"),
            stderr=subprocess.STDOUT,
            bufsize=0
        )
        time.sleep(8)  # Give server time to fully initialize
        
        # Check if server is running
        if server_proc.poll() is not None:
            print("   ❌ Server failed to start!")
            # Read error from log
            if os.path.exists(server_log_path):
                with open(server_log_path, 'r') as f:
                    errors = f.read()
                    print(f"   Server errors: {errors[:500]}")
            return None
        
        print(f"   ✅ Server started (PID: {server_proc.pid})")
        
        # Verify server is listening
        time.sleep(2)
        if IS_WINDOWS:
            netstat_cmd = f"netstat -an | findstr :5555"
        else:
            netstat_cmd = f"sudo netstat -tulpn | grep :5555 || ss -tulpn | grep :5555"
        
        result = subprocess.run(netstat_cmd, shell=True, capture_output=True, text=True)
        if "5555" in result.stdout or ":5555" in result.stdout:
            print("   ✅ Server listening on port 5555")
        else:
            print("   ⚠️  Server may not be listening on port 5555")
            print(f"   Check: {result.stdout[:200]}")
            
    except Exception as e:
        print(f"   ❌ Failed to start server: {e}")
        return None
    
    # Start 4 Clients
    print(f"\n[2/3] 👥 Starting 4 Clients...")
    clients = []
    
    for i in range(4):
        client_id = i + 1
        client_log_path = f"{results_dir}/client_{client_id}.log"
        
        try:
            # Start client with headless mode
            client_proc = subprocess.Popen(
                [PYTHON_CMD, "-u", CLIENT_SCRIPT, "127.0.0.1", "--headless"],
                stdout=open(client_log_path, "w"),
                stderr=subprocess.STDOUT,
                bufsize=0
            )
            clients.append(client_proc)
            
            print(f"   Client {client_id} started (PID: {client_proc.pid})")
            time.sleep(1.5)  # Stagger client connections
            
        except Exception as e:
            print(f"   ❌ Failed to start client {client_id}: {e}")
    
    # Wait for clients to connect
    print(f"\n   Waiting for connections to establish...")
    time.sleep(6)
    
    # Check connection status
    connected_clients = 0
    for i in range(4):
        client_id = i + 1
        client_log_path = f"{results_dir}/client_{client_id}.log"
        
        if os.path.exists(client_log_path) and os.path.getsize(client_log_path) > 50:
            try:
                with open(client_log_path, 'r') as f:
                    content = f.read()
                    
                    if "Connected!" in content or "[OK]" in content or "Assigned player ID" in content:
                        print(f"   ✅ Client {client_id} connected successfully")
                        connected_clients += 1
                    elif "ERROR" in content or "failed" in content.lower():
                        print(f"   ❌ Client {client_id} failed: {content[-200:]}")
                    elif len(content.strip()) > 0:
                        # Check last few lines
                        lines = content.strip().split('\n')[-3:]
                        if any("player_" in line for line in lines):
                            print(f"   ✅ Client {client_id} appears connected")
                            connected_clients += 1
                        else:
                            print(f"   ⚠️  Client {client_id} output: {lines}")
            except Exception as e:
                print(f"   ❌ Error reading client {client_id} log: {e}")
        else:
            print(f"   ⚠️  Client {client_id} log missing or empty")
    
    if connected_clients == 0:
        print("   ⚠️  No clients connected - check server logs")
        # Check server logs
        if os.path.exists(server_log_path):
            with open(server_log_path, 'r') as f:
                server_log = f.read()[-500:]
                print(f"   Last server output: {server_log}")
    
    print(f"\n   {connected_clients}/4 clients connected")
    
    # Run test for specified duration
    print(f"\n[3/3] ⏱️  Running test for {DURATION} seconds...")
    start_time = time.time()
    
    try:
        while time.time() - start_time < DURATION:
            elapsed = int(time.time() - start_time)
            remaining = DURATION - elapsed
            print(f"\r   Time: {elapsed:3d}s / {DURATION}s remaining: {remaining:3d}s", end='', flush=True)
            time.sleep(1)
        print(f"\n   ✅ Test duration completed")
    except KeyboardInterrupt:
        print(f"\n\n⚠️  Test interrupted by user")
    
    # Stop processes
    print(f"\n🧹 Stopping processes...")
    
    # Stop clients
    for i, client in enumerate(clients):
        try:
            client.terminate()
            client.wait(timeout=2)
            print(f"   Client {i+1} stopped")
        except:
            try:
                client.kill()
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
    
    # Move CSV files
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
    
    # Also look for client_data files
    for f in os.listdir("."):
        if f.startswith("client_data_") and f.endswith(".csv"):
            try:
                dest = os.path.join(results_dir, f)
                shutil.move(f, dest)
                csv_files.append(f)
                print(f"   📄 {f}")
            except:
                pass
    
    # Create a summary file
    summary_path = os.path.join(results_dir, "test_summary.txt")
    with open(summary_path, 'w') as f:
        f.write(f"Test: {name}\n")
        f.write(f"Time: {time.ctime()}\n")
        f.write(f"Duration: {DURATION}s\n")
        f.write(f"Network: Loss={loss}%, Delay={delay}ms, Jitter={jitter}ms\n")
        f.write(f"Connected clients: {connected_clients}/4\n")
        f.write(f"CSV files: {len(csv_files)}\n")
        f.write("\nFiles:\n")
        for file in csv_files:
            f.write(f"  {file}\n")
    
    print(f"\n✅ {name} test completed!")
    print(f"   Results saved in: {results_dir}")
    print(f"   CSV files: {len(csv_files)}")
    print(f"   Summary: {os.path.basename(summary_path)}")
    
    return results_dir

def run_all_scenarios():
    """Run all test scenarios from the PDF"""
    # Test scenarios as specified in PDF
    scenarios = [
        # (name, loss%, delay_ms, jitter_ms)
        ("baseline", 0, 0, 0),
        ("loss_2pct", 2, 0, 0),
        ("loss_5pct", 5, 0, 0),
        ("delay_100ms", 0, 100, 0),
        ("delay_jitter", 0, 100, 10),
    ]
    
    print(f"\n📋 Running {len(scenarios)} test scenarios")
    print(f"Each test will run for {DURATION} seconds")
    
    results = []
    
    for scenario in scenarios:
        name, loss, delay, jitter = scenario
        
        print(f"\n{'#'*80}")
        print(f"🚀 STARTING: {name.upper()}")
        print(f"   Loss: {loss}%, Delay: {delay}ms, Jitter: {jitter}ms")
        print(f"{'#'*80}")
        
        result_dir = run_scenario(name, loss, delay, jitter)
        results.append((name, result_dir))
        
        # Clean up between tests (except after last)
        if scenario != scenarios[-1]:
            print(f"\n⏳ Waiting 10 seconds before next test...")
            time.sleep(10)
            simple_cleanup()
    
    return results

def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="Grid Clash Network Test Suite")
    parser.add_argument("--scenario", choices=["all", "baseline", "loss_2pct", "loss_5pct", 
                                              "delay_100ms", "delay_jitter"], 
                       default="all", help="Test scenario to run")
    parser.add_argument("--duration", type=int, default=40, 
                       help="Test duration in seconds")
    parser.add_argument("--interface", default="lo" if not IS_WINDOWS else "1",
                       help="Network interface for capture")
    args = parser.parse_args()
    
    global DURATION
    DURATION = args.duration
    
    print(f"\n{'='*80}")
    print(f"🕹️  GRID CLASH NETWORK PERFORMANCE TEST SUITE")
    print(f"{'='*80}")
    print(f"Platform: {platform.system()} {platform.release()}")
    print(f"Python: {sys.executable}")
    print(f"Server: {SERVER_SCRIPT}")
    print(f"Client: {CLIENT_SCRIPT}")
    print(f"Test duration: {DURATION} seconds")
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
        for name, result_dir in results:
            if result_dir:
                print(f"   ✅ {name}: {os.path.basename(result_dir)}")
            else:
                print(f"   ❌ {name}: FAILED")
        
        print(f"\n📁 All results saved in: test_results/")
        print(f"📊 Run analysis: python analyze_results.py")
        
    else:
        # Run single scenario
        scenario_map = {
            "baseline": ("baseline", 0, 0, 0),
            "loss_2pct": ("loss_2pct", 2, 0, 0),
            "loss_5pct": ("loss_5pct", 5, 0, 0),
            "delay_100ms": ("delay_100ms", 0, 100, 0),
            "delay_jitter": ("delay_jitter", 0, 100, 10),
        }
        
        if args.scenario in scenario_map:
            run_scenario(*scenario_map[args.scenario])
        else:
            print(f"❌ Unknown scenario: {args.scenario}")
    
    print(f"\n{'='*80}")
    print(f"🏁 TESTING COMPLETE")
    print(f"{'='*80}")
    
    # Final cleanup
    simple_cleanup()

if __name__ == "__main__":
    main()