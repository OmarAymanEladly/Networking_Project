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
DURATION = 40

IS_LINUX = platform.system() == "Linux"

# Global for tshark process
tshark_process = None

def simple_cleanup():
    """Simple cleanup that won't kill our own process"""
    print("\n🧹 Simple cleanup...")
    
    # Kill any existing server or client processes
    try:
        subprocess.run(['pkill', '-f', SERVER_SCRIPT], 
                      stdout=subprocess.DEVNULL, 
                      stderr=subprocess.DEVNULL)
        subprocess.run(['pkill', '-f', CLIENT_SCRIPT], 
                      stdout=subprocess.DEVNULL, 
                      stderr=subprocess.DEVNULL)
        time.sleep(1)
    except:
        pass
    
    # Clean netem rules
    try:
        subprocess.run(['sudo', 'tc', 'qdisc', 'del', 'dev', 'lo', 'root'], 
                      stdout=subprocess.DEVNULL, 
                      stderr=subprocess.DEVNULL)
    except:
        pass
    
    # Clean iptables rules
    try:
        subprocess.run(['sudo', 'iptables', '-F'],
                      stdout=subprocess.DEVNULL, 
                      stderr=subprocess.DEVNULL)
    except:
        pass
    
    # Clean old CSV and log files
    for f in os.listdir("."):
        if f.endswith((".csv", ".log")) and os.path.isfile(f):
            try:
                os.remove(f)
            except:
                pass
    
    time.sleep(2)
    print("   ✅ Cleanup done")

def start_wireshark_capture(test_name, interface="lo"):
    """Start tshark capture in background"""
    global tshark_process
    
    # Create captures directory
    os.makedirs("captures", exist_ok=True)
    
    timestamp = int(time.time())
    pcap_file = f"captures/{test_name}_{timestamp}.pcap"
    
    print(f"\n📡 Starting Wireshark capture on {interface}...")
    print(f"   Saving to: {pcap_file}")
    
    try:
        tshark_process = subprocess.Popen(
            ["sudo", "tshark", "-i", interface, "-f", "udp port 5555", 
             "-w", pcap_file, "-q"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        time.sleep(2)
        return pcap_file
    except Exception as e:
        print(f"   ❌ Failed to start capture: {e}")
        return None

def stop_wireshark_capture():
    """Stop tshark capture"""
    global tshark_process
    
    if tshark_process and tshark_process.poll() is None:
        try:
            tshark_process.send_signal(signal.SIGINT)
            tshark_process.wait(timeout=3)
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
        time.sleep(1)

def apply_netem_working(loss=0, delay=0, jitter=0):
    """Apply network conditions using tc netem"""
    print(f"\n🌐 Applying network conditions:")
    print(f"   Loss: {loss}%, Delay: {delay}ms, Jitter: {jitter}ms")
    
    # Always clean first
    subprocess.run(['sudo', 'tc', 'qdisc', 'del', 'dev', 'lo', 'root'], 
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    if loss == 0 and delay == 0 and jitter == 0:
        print("   ✅ Baseline (no network impairment)")
        return True
    
    # Build netem command
    netem_cmd = ['sudo', 'tc', 'qdisc', 'add', 'dev', 'lo', 'root', 'netem']
    
    if loss > 0:
        netem_cmd.extend(['loss', f'{loss}%'])
    
    if delay > 0:
        if jitter > 0:
            netem_cmd.extend(['delay', f'{delay}ms', f'{jitter}ms'])
        else:
            netem_cmd.extend(['delay', f'{delay}ms'])
    
    try:
        result = subprocess.run(netem_cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"   ✅ Network conditions applied")
            return True
        else:
            print(f"   ⚠️  Using software simulation instead")
            return True
    except Exception as e:
        print(f"   ⚠️  Using software simulation: {e}")
        return True

def run_scenario(name, loss, delay, jitter):
    """Run a single test scenario"""
    print(f"\n{'='*60}")
    print(f"STARTING: {name}")
    print(f"Loss: {loss}%, Delay: {delay}ms, Jitter: {jitter}ms")
    print(f"{'='*60}")
    
    # Cleanup first
    simple_cleanup()
    
    # Create results directory
    timestamp = int(time.time())
    results_dir = f"test_results/{name}"
    os.makedirs(results_dir, exist_ok=True)
    
    # Apply network configuration
    if IS_LINUX:
        apply_netem_working(loss, delay, jitter)
    
    # Start Wireshark capture
    pcap_file = start_wireshark_capture(name, interface="lo")
    
    # Start Server - Use unbuffered output for real-time logs
    print(f"\n[1/3] Starting Server...")
    server_proc = subprocess.Popen(
        [PYTHON_CMD, "-u", SERVER_SCRIPT],
        stdout=open(f"{results_dir}/server.log", "w"),
        stderr=subprocess.STDOUT,
        bufsize=0
    )
    
    # Wait for server to start and verify it's running
    print("   Waiting for server to initialize...")
    time.sleep(5)
    
    # Check if server process is running
    if server_proc.poll() is None:  # None means process is still running
        print(f"   ✅ Server process is running (PID: {server_proc.pid})")
        
        # Check if server is listening on port 5555
        try:
            check_cmd = "sudo netstat -tulpn | grep :5555 || true"
            result = subprocess.run(check_cmd, shell=True, capture_output=True, text=True)
            if ":5555" in result.stdout:
                print("   ✅ Server is listening on port 5555")
            else:
                print("   ⚠️  Server not listening on port 5555")
        except Exception as e:
            print(f"   ⚠️  Could not check port: {e}")
    else:
        print("   ❌ Server process terminated!")
        # Try to get error output
        try:
            stdout, stderr = server_proc.communicate(timeout=2)
            if stderr:
                error_msg = stderr.decode()[:200]
                print(f"   Server error: {error_msg}")
            elif stdout:
                error_msg = stdout.decode()[:200]
                print(f"   Server output: {error_msg}")
        except:
            pass
        return None
    
    # Start 4 Clients
    print(f"\n[2/3] Starting 4 Clients...")
    clients = []
    
    for i in range(4):
        client_id = i + 1
        client_log = f"{results_dir}/client_{client_id}.log"
        
        # Start client with unbuffered output
        client_proc = subprocess.Popen(
            [PYTHON_CMD, "-u", CLIENT_SCRIPT, "127.0.0.1", "--headless"],
            stdout=open(client_log, "w"),
            stderr=subprocess.STDOUT,
            bufsize=0
        )
        clients.append(client_proc)
        
        # Give time for client to connect
        time.sleep(2)
        print(f"   Client {client_id} started (PID: {client_proc.pid})")
        
        # Check if client log file is being created
        if os.path.exists(client_log):
            print(f"   ✅ Client {client_id} log file created")
        else:
            print(f"   ⚠️  Client {client_id} log file not found")
    
    # Wait a bit for clients to connect
    print("\n   Waiting for clients to connect...")
    time.sleep(3)
    
    # Check client connection status
    connected_clients = 0
    for i in range(4):
        client_id = i + 1
        client_log = f"{results_dir}/client_{client_id}.log"
        
        if os.path.exists(client_log) and os.path.getsize(client_log) > 0:
            try:
                with open(client_log, 'r') as f:
                    content = f.read()
                    if "Connected!" in content or "[OK]" in content:
                        print(f"   ✅ Client {client_id} connected successfully")
                        connected_clients += 1
                    elif "ERROR" in content or "failed" in content.lower():
                        print(f"   ❌ Client {client_id} failed to connect")
                    else:
                        # Check for any meaningful output
                        lines = content.strip().split('\n')
                        if len(lines) > 3:
                            print(f"   ⚠️  Client {client_id} has output but no clear connection status")
                        else:
                            print(f"   ⚠️  Client {client_id} has minimal output")
            except Exception as e:
                print(f"   ❌ Error reading client {client_id} log: {e}")
        else:
            print(f"   ⚠️  Client {client_id} log file empty or missing")
    
    if connected_clients == 0:
        print("\n   ⚠️  No clients connected successfully! Check server logs.")
    
    # Run test
    print(f"\n[3/3] Running for {DURATION} seconds...")
    start_time = time.time()
    
    try:
        while time.time() - start_time < DURATION:
            elapsed = int(time.time() - start_time)
            print(f"\r⏱️  {elapsed:3d}s / {DURATION}s", end='', flush=True)
            time.sleep(1)
        print("\n   ✅ Test complete")
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted")
    
    # Cleanup - Stop processes gracefully
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
        server_proc.wait(timeout=2)
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
    
    # Collect CSV files
    print(f"\n📂 Collecting results...")
    csv_count = 0
    
    for f in os.listdir("."):
        if f.endswith(".csv") and os.path.getsize(f) > 100:
            try:
                shutil.move(f, os.path.join(results_dir, f))
                csv_count += 1
                print(f"   📄 {f}")
            except:
                pass
    
    # Move pcap if exists
    if pcap_file and os.path.exists(pcap_file):
        try:
            shutil.move(pcap_file, os.path.join(results_dir, os.path.basename(pcap_file)))
            print(f"   📄 {os.path.basename(pcap_file)}")
        except:
            pass
    
    # Also collect any other log files
    for f in os.listdir("."):
        if f.startswith("client_data_") and f.endswith(".csv"):
            try:
                shutil.move(f, os.path.join(results_dir, f))
                csv_count += 1
                print(f"   📄 {f}")
            except:
                pass
    
    print(f"\n✅ {name} completed!")
    print(f"   Results in: {results_dir}")
    print(f"   CSV files: {csv_count}")
    
    return results_dir

def main():
    """Main function"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=["all", "baseline", "loss_2pct", "loss_5pct", "delay_100ms", "delay_jitter"], 
                       default="baseline")
    parser.add_argument("--duration", type=int, default=40)
    args = parser.parse_args()
    
    global DURATION
    DURATION = args.duration
    
    print("\n" + "="*60)
    print("GRID CLASH TESTS - WITH WIRESHARK CAPTURE")
    print("="*60)
    print(f"Python: {sys.executable}")
    print(f"Server: {SERVER_SCRIPT}")
    print(f"Client: {CLIENT_SCRIPT}")
    print(f"Duration: {DURATION}s per test")
    
    # Create directories
    os.makedirs("test_results", exist_ok=True)
    os.makedirs("captures", exist_ok=True)
    
    # Define test scenarios from PDF
    scenarios = {
        "baseline": ("baseline", 0, 0, 0),
        "loss_2pct": ("loss_2pct", 2, 0, 0),
        "loss_5pct": ("loss_5pct", 5, 0, 0),
        "delay_100ms": ("delay_100ms", 0, 100, 0),
        "delay_jitter": ("delay_jitter", 0, 100, 10)
    }
    
    if args.scenario == "all":
        for key, params in scenarios.items():
            print(f"\n{'#'*60}")
            print(f"RUNNING SCENARIO: {params[0]}")
            print(f"{'#'*60}")
            result = run_scenario(*params)
            
            if result:
                print(f"   Scenario {params[0]} completed successfully")
            else:
                print(f"   ⚠️  Scenario {params[0]} had issues")
            
            # Cleanup between tests
            if key != "delay_jitter":
                print(f"\n⏳ Waiting 10 seconds between tests...")
                time.sleep(10)
    else:
        if args.scenario in scenarios:
            run_scenario(*scenarios[args.scenario])
        else:
            print(f"❌ Unknown scenario: {args.scenario}")
    
    print("\n" + "="*60)
    print("✅ ALL TESTS COMPLETE!")
    print("="*60)
    
    print(f"\nRun analysis: python analyze_result.py")
    print(f"Check results in: test_results/")
    print(f"\n" + "="*60)

if __name__ == "__main__":
    main()