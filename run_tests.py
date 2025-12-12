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
IS_MAC = platform.system() == "Darwin"

class PCAPManager:
    """Manage PCAP capture processes"""
    def __init__(self, interface="lo"):
        self.processes = []
        self.pcap_files = []
        self.interface = interface
        
    def start_capture(self, test_name, port=5555):
        """Start tshark capture for specific test"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pcap_file = f"captures/{test_name}_{timestamp}.pcap"
        
        # Ensure captures directory exists
        os.makedirs("captures", exist_ok=True)
        
        print(f"📡 Starting PCAP capture: {os.path.basename(pcap_file)}")
        print(f"   Interface: {self.interface}, Port: {port}")
        
        try:
            if IS_WINDOWS:
                # On Windows, use Wireshark's tshark
                cmd = ["tshark", "-i", self.interface, "-f", f"udp port {port}", 
                      "-w", pcap_file, "-q"]
                print(f"   Command: {' '.join(cmd)}")
            elif IS_LINUX:
                # Linux - use sudo for tshark on loopback
                cmd = ["sudo", "tshark", "-i", self.interface, "-f", f"udp port {port}", 
                      "-w", pcap_file, "-q"]
                print(f"   Command: {' '.join(cmd)}")
            else:
                # macOS
                cmd = ["tshark", "-i", self.interface, "-f", f"udp port {port}", 
                      "-w", pcap_file, "-q"]
                print(f"   Command: {' '.join(cmd)}")
            
            # Start process
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            self.processes.append(process)
            self.pcap_files.append(pcap_file)
            
            # Wait a moment for tshark to start
            time.sleep(3)
            
            # Verify it's running
            if process.poll() is None:
                print(f"   ✅ PCAP capture running (PID: {process.pid})")
                
                # Test if capture is working by checking if file is being created
                time.sleep(1)
                if os.path.exists(pcap_file):
                    file_size = os.path.getsize(pcap_file)
                    print(f"   📊 PCAP file created: {file_size} bytes")
                return pcap_file
            else:
                stdout, stderr = process.communicate()
                print(f"   ❌ PCAP failed to start")
                print(f"   stderr: {stderr[:200]}")
                return None
                
        except FileNotFoundError:
            print(f"   ❌ tshark not found. Install Wireshark/tshark first.")
            print(f"   Ubuntu/Debian: sudo apt-get install tshark")
            print(f"   macOS: brew install wireshark")
            print(f"   Windows: Install Wireshark from wireshark.org")
            return None
        except Exception as e:
            print(f"   ❌ PCAP error: {str(e)[:100]}")
            return None
    
    def stop_all(self):
        """Stop all PCAP captures"""
        print("   Stopping PCAP captures...")
        for process in self.processes:
            if process and process.poll() is None:
                try:
                    if IS_WINDOWS:
                        # Send CTRL+C
                        process.send_signal(signal.CTRL_C_EVENT)
                    else:
                        # Send SIGINT
                        process.send_signal(signal.SIGINT)
                    
                    # Wait for graceful shutdown
                    try:
                        process.wait(timeout=5)
                        print(f"   ✅ PCAP process stopped gracefully")
                    except subprocess.TimeoutExpired:
                        print(f"   ⚠️  PCAP process didn't stop, terminating...")
                        process.terminate()
                        try:
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=1)
                except Exception as e:
                    print(f"   ⚠️  Error stopping PCAP: {e}")
        
        self.processes = []
        time.sleep(2)
        
        # List captured PCAP files
        print(f"   Captured PCAP files:")
        for pcap_file in self.pcap_files:
            if os.path.exists(pcap_file):
                size = os.path.getsize(pcap_file)
                print(f"     {os.path.basename(pcap_file)} - {size:,} bytes")
            else:
                print(f"     {os.path.basename(pcap_file)} - NOT FOUND")
    
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
            time.sleep(1)
        except:
            pass
    
    # Remove any leftover .csv files in current directory
    for f in os.listdir("."):
        if f.endswith(".csv") and os.path.isfile(f):
            try:
                os.remove(f)
                print(f"   Removed: {f}")
            except:
                pass
    
    time.sleep(2)
    print("   ✅ Cleanup complete")

def apply_network_conditions(scenario_name):
    """Apply network conditions using tc netem (Linux only) according to PDF specifications"""
    print(f"\n🌐 Applying network conditions for: {scenario_name}")
    
    if not IS_LINUX:
        print("   ⚠️  Network simulation only available on Linux")
        print("   On Windows, use --loss parameter with server.py")
        print("   On macOS, use: sudo dnctl and sudo pfctl")
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
            print(f"   Executing: {' '.join(cmd)}")
            try:
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    print(f"   ✅ Network conditions applied: {scenario_name}")
                    
                    # Verify the rules
                    print("   📋 Verifying network rules...")
                    verify_result = subprocess.run(['sudo', 'tc', 'qdisc', 'show', 'dev', 'lo'], 
                                                  capture_output=True, text=True)
                    if verify_result.returncode == 0:
                        rules = verify_result.stdout.strip()
                        if rules:
                            print(f"      {rules}")
                        else:
                            print("      No rules found (should show netem rules)")
                    return True
                else:
                    print(f"   ❌ Failed to apply network conditions")
                    print(f"   stderr: {result.stderr}")
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

def get_network_interface():
    """Get the appropriate network interface for the current OS"""
    if IS_WINDOWS:
        # Try to find loopback interface on Windows
        try:
            result = subprocess.run(['tshark', '-D'], capture_output=True, text=True)
            if result.returncode == 0:
                interfaces = result.stdout.split('\n')
                for interface in interfaces:
                    if 'loopback' in interface.lower() or 'adapter for loopback' in interface.lower():
                        # Extract interface number (e.g., "1. \\Device\\NPF_Loopback")
                        parts = interface.split('.')
                        if parts and parts[0].isdigit():
                            return parts[0]
                # If no loopback found, use first interface
                for interface in interfaces:
                    parts = interface.split('.')
                    if parts and parts[0].isdigit():
                        return parts[0]
        except:
            pass
        return "1"  # Default to interface 1
    elif IS_LINUX:
        return "lo"  # Linux loopback
    else:
        return "lo0"  # macOS loopback

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
        if not pcap_file:
            print("   ⚠️  PCAP capture failed, continuing without it...")
    
    # Determine test duration based on scenario
    test_duration = 60 if scenario_name == "baseline" else 40
    
    # Start Server with appropriate parameters
    print(f"\n[1/3] 🚀 Starting Server...")
    server_log_path = f"{results_dir}/server.log"
    
    try:
        server_cmd = [PYTHON_CMD, "-u", SERVER_SCRIPT]
        
        # Add network simulation parameters for non-Linux or when netem fails
        if loss > 0 and (not IS_LINUX or scenario_name in ["loss_2pct", "loss_5pct"]):
            # Use software-based loss simulation
            loss_rate = loss / 100.0  # Convert percentage to decimal
            server_cmd.extend(["--loss", str(loss_rate)])
            print(f"   Using software loss simulation: {loss}%")
        
        if delay > 0 and (not IS_LINUX or scenario_name in ["delay_100ms", "delay_jitter"]):
            # Note: server_optimized.py doesn't support delay simulation
            # We rely on netem for Linux
            print(f"   Delay simulation requires Linux netem")
        
        print(f"   Server command: {' '.join(server_cmd)}")
        
        server_proc = subprocess.Popen(
            server_cmd,
            stdout=open(server_log_path, "w"),
            stderr=subprocess.STDOUT,
            bufsize=0
        )
        time.sleep(5)  # Give server time to initialize
        
        if server_proc.poll() is not None:
            print("   ❌ Server failed to start!")
            # Read error from log
            if os.path.exists(server_log_path):
                with open(server_log_path, 'r') as f:
                    errors = f.read()[-500:]
                    print(f"   Last server output: {errors}")
            return None
        
        print(f"   ✅ Server started (PID: {server_proc.pid})")
        
        # Verify server is listening
        time.sleep(2)
        if IS_WINDOWS:
            netstat_cmd = f'netstat -an | findstr ":5555"'
            result = subprocess.run(netstat_cmd, shell=True, capture_output=True, text=True)
            listening = ":5555" in result.stdout
        else:
            lsof_cmd = ['lsof', '-i', ':5555']
            result = subprocess.run(lsof_cmd, capture_output=True, text=True)
            listening = result.returncode == 0
        
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
    connection_details = []
    for i, log_path in enumerate(client_log_paths):
        if os.path.exists(log_path) and os.path.getsize(log_path) > 0:
            try:
                with open(log_path, 'r') as f:
                    content = f.read()
                    
                    # Check for connection success indicators
                    success_indicators = [
                        "Connected!", "[OK]", "Assigned ID", 
                        "player_", "Connected! Assigned ID"
                    ]
                    
                    connected = False
                    for line in content.split('\n'):
                        if any(indicator in line for indicator in success_indicators):
                            connected = True
                            break
                    
                    if connected:
                        connected_clients += 1
                        connection_details.append(f"Client {i+1}: ✅ Connected")
                    else:
                        connection_details.append(f"Client {i+1}: ⚠️  No clear success indicator")
                        
                        # Show last few lines for debugging
                        lines = content.strip().split('\n')[-3:]
                        if lines:
                            connection_details.append(f"      Last output: {' | '.join(lines)}")
            except Exception as e:
                connection_details.append(f"Client {i+1}: ❌ Error reading log: {e}")
        else:
            connection_details.append(f"Client {i+1}: ❌ Log file missing or empty")
    
    # Print connection details
    for detail in connection_details:
        print(f"   {detail}")
    
    print(f"\n   📊 Summary: {connected_clients}/4 clients connected")
    
    # Run test
    print(f"\n[3/3] ⏱️  Running test for {test_duration} seconds...")
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
            
            print(f"\r   Elapsed: {elapsed:3d}s", end='', flush=True)
            time.sleep(1)
        
        print(f"\n   ✅ Test completed ({test_duration} seconds)")
        
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
    
    # Wait for everything to settle
    time.sleep(3)
    
    # Collect results
    print(f"\n📂 Collecting results...")
    
    # Collect CSV files (client logs and server logs)
    csv_files = []
    current_files = os.listdir(".")
    
    for f in current_files:
        if f.endswith(".csv") and os.path.isfile(f):
            try:
                dest = os.path.join(results_dir, f)
                shutil.move(f, dest)
                csv_files.append(f)
                print(f"   📄 Moved: {f}")
            except Exception as e:
                print(f"   ⚠️  Could not move {f}: {e}")
                # Try copying instead
                try:
                    dest = os.path.join(results_dir, f)
                    shutil.copy(f, dest)
                    csv_files.append(f)
                    print(f"   📄 Copied: {f}")
                except:
                    print(f"   ❌ Failed to copy {f}")
    
    # Move PCAP file if captured
    if pcap_file and os.path.exists(pcap_file):
        try:
            pcap_dest = os.path.join(results_dir, os.path.basename(pcap_file))
            shutil.move(pcap_file, pcap_dest)
            print(f"   📦 PCAP moved: {os.path.basename(pcap_file)}")
            pcap_file = pcap_dest  # Update path to new location
        except Exception as e:
            print(f"   ⚠️  Could not move PCAP: {e}")
            # Try copying
            try:
                pcap_dest = os.path.join(results_dir, os.path.basename(pcap_file))
                shutil.copy(pcap_file, pcap_dest)
                print(f"   📦 PCAP copied: {os.path.basename(pcap_file)}")
                pcap_file = pcap_dest
            except Exception as e2:
                print(f"   ❌ Failed to copy PCAP: {e2}")
                pcap_file = None
    elif pcap_manager and pcap_manager.get_pcap_files():
        # Try to get PCAP from manager
        for pcap in pcap_manager.get_pcap_files():
            if os.path.exists(pcap):
                try:
                    pcap_dest = os.path.join(results_dir, os.path.basename(pcap))
                    shutil.move(pcap, pcap_dest)
                    pcap_file = pcap_dest
                    print(f"   📦 PCAP from manager: {os.path.basename(pcap)}")
                    break
                except:
                    pass
    
    # Move log files
    log_files = []
    for f in current_files:
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
        "network": {
            "loss_percent": loss,
            "delay_ms": delay, 
            "jitter_ms": jitter,
            "simulation": "netem" if IS_LINUX else "software"
        },
        "clients_connected": connected_clients,
        "files": {
            "csv": csv_files,
            "logs": log_files,
            "pcap": os.path.basename(pcap_file) if pcap_file and os.path.exists(pcap_file) else None
        },
        "system": {
            "platform": platform.system(),
            "python": sys.version.split()[0]
        }
    }
    
    metadata_path = os.path.join(results_dir, "metadata.json")
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    
    # Create a simple summary file
    summary_path = os.path.join(results_dir, "summary.txt")
    with open(summary_path, 'w') as f:
        f.write(f"Test: {scenario_name} (Run {run_number})\n")
        f.write(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Duration: {test_duration}s\n")
        f.write(f"Network: Loss={loss}%, Delay={delay}ms, Jitter={jitter}ms\n")
        f.write(f"Clients: {connected_clients}/4 connected\n")
        f.write(f"CSV files: {len(csv_files)}\n")
        f.write(f"Log files: {len(log_files)}\n")
        f.write(f"PCAP captured: {'Yes' if pcap_file and os.path.exists(pcap_file) else 'No'}\n")
        if pcap_file and os.path.exists(pcap_file):
            size = os.path.getsize(pcap_file)
            f.write(f"PCAP size: {size:,} bytes\n")
    
    print(f"\n✅ {scenario_name} run {run_number} complete!")
    print(f"   Results directory: {results_dir}")
    print(f"   CSV files: {len(csv_files)}")
    print(f"   PCAP file: {'Yes' if pcap_file and os.path.exists(pcap_file) else 'No'}")
    
    return {
        "dir": results_dir,
        "connected": connected_clients,
        "pcap": pcap_file if pcap_file and os.path.exists(pcap_file) else None,
        "csv_count": len(csv_files)
    }

def run_scenario_with_pcaps(scenario_name, loss=0, delay=0, jitter=0):
    """Run a scenario with PCAP capture (at least 2 runs with PCAP as per PDF)"""
    print(f"\n📊 Running scenario: {scenario_name}")
    print(f"   Will run 5 times total, with PCAP for runs 1 & 2 (PDF requirement)")
    print(f"   Network conditions: Loss={loss}%, Delay={delay}ms, Jitter={jitter}ms")
    
    results = []
    pcap_manager = None
    
    try:
        # First 2 runs with PCAP
        for run_num in range(1, 3):
            print(f"\n{'#'*80}")
            print(f"📦 RUN {run_num}/2 (WITH PCAP): {scenario_name.upper()}")
            print(f"{'#'*80}")
            
            # Create new PCAP manager for each run
            interface = get_network_interface()
            pcap_manager = PCAPManager(interface=interface)
            
            result = run_single_scenario(scenario_name, loss, delay, jitter, 
                                       run_num, pcap_manager)
            results.append(result)
            
            # Stop PCAP for this run
            if pcap_manager:
                pcap_manager.stop_all()
                pcap_manager = None
            
            if run_num < 2:
                print(f"\n⏳ Waiting 15 seconds before next run...")
                time.sleep(15)
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
                print(f"\n⏳ Waiting 10 seconds before next run...")
                time.sleep(10)
                simple_cleanup()
    
    finally:
        # Ensure PCAP is stopped
        if pcap_manager:
            pcap_manager.stop_all()
    
    # Count PCAPs captured
    pcap_count = sum(1 for r in results if r and r.get('pcap'))
    successful_runs = sum(1 for r in results if r and r.get('connected', 0) >= 2)
    
    print(f"\n📊 {scenario_name} Summary:")
    print(f"   Successful runs: {successful_runs}/5")
    print(f"   PCAP files captured: {pcap_count}/2")
    
    if pcap_count < 2:
        print(f"   ⚠️  Warning: Only {pcap_count} PCAPs (PDF requires at least 2)")
    
    return results

def verify_pcap_requirements():
    """Verify we have the tools needed for PCAP capture"""
    print("\n🔍 Verifying PCAP requirements...")
    
    # Check for tshark
    try:
        if IS_WINDOWS:
            result = subprocess.run(['tshark', '--version'], 
                                  capture_output=True, text=True, timeout=5)
        else:
            result = subprocess.run(['which', 'tshark'], 
                                  capture_output=True, text=True, timeout=5)
        
        if result.returncode == 0:
            print("✅ tshark is available")
            
            # Get interface list
            try:
                if IS_WINDOWS:
                    interface_cmd = ['tshark', '-D']
                else:
                    interface_cmd = ['tshark', '-D']
                
                interface_result = subprocess.run(
                    interface_cmd, capture_output=True, text=True, timeout=5
                )
                
                if interface_result.returncode == 0:
                    print("✅ Can list network interfaces")
                    interfaces = interface_result.stdout.split('\n')
                    print(f"   Found {len(interfaces)} interface(s)")
                    for iface in interfaces[:3]:  # Show first 3
                        if iface.strip():
                            print(f"     {iface}")
                    
                    # Check for loopback
                    loopback_found = any('loopback' in iface.lower() or 'lo' in iface.lower() 
                                       for iface in interfaces)
                    if loopback_found:
                        print("✅ Loopback interface available")
                    else:
                        print("⚠️  Loopback interface not found in list")
                else:
                    print("⚠️  Cannot list interfaces")
            except:
                print("⚠️  Could not check interfaces")
            
            return True
        else:
            print("❌ tshark not found or not working")
            return False
            
    except FileNotFoundError:
        print("❌ tshark not installed")
        print("\n📦 Install instructions:")
        print("  Ubuntu/Debian: sudo apt-get install tshark")
        print("  macOS: brew install wireshark")
        print("  Windows: Install Wireshark from https://www.wireshark.org/")
        print("\n   After installing, make sure tshark is in your PATH")
        return False
    except subprocess.TimeoutExpired:
        print("❌ tshark check timed out")
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
            capture_output=True, text=True, timeout=5
        )
        
        if test_result.returncode == 0:
            print("✅ sudo access granted for network configuration")
            return True
        else:
            print("❌ sudo access failed for 'tc' command")
            print(f"   Error: {test_result.stderr[:200]}")
            return False
            
    except subprocess.TimeoutExpired:
        print("❌ sudo check timed out")
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
    parser.add_argument("--interface", help="Network interface for capture (auto-detected if not specified)")
    parser.add_argument("--skip-checks", action="store_true",
                       help="Skip prerequisite checks")
    parser.add_argument("--runs", type=int, default=5,
                       help="Number of runs per scenario (default: 5)")
    args = parser.parse_args()
    
    print(f"\n{'='*80}")
    print(f"🕹️  GRID CLASH - COMPLETE TEST SUITE WITH PCAP")
    print(f"{'='*80}")
    print(f"Platform: {platform.system()} {platform.release()}")
    print(f"Python: {sys.executable}")
    print(f"Server: {SERVER_SCRIPT}")
    print(f"Client: {CLIENT_SCRIPT}")
    print(f"PCAP Capture: {'Disabled' if args.no_pcap else 'Enabled'}")
    print(f"Runs per scenario: {args.runs}")
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
            print("   Using software-based loss simulation instead.")
    
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
            print(f"   Loss: {loss}%, Delay: {delay}ms, Jitter: {jitter}ms")
            print(f"{'='*80}")
            
            # Run scenario
            scenario_results = run_scenario_with_pcaps(
                scenario_name, loss, delay, jitter
            )
            all_results[scenario_name] = scenario_results
            
            # Cleanup between scenarios (except after last)
            if scenario_name != list(scenarios.keys())[-1]:
                print(f"\n⏳ Waiting 30 seconds before next scenario...")
                time.sleep(30)
                simple_cleanup()
    
    else:
        # Run single scenario
        if args.scenario in scenarios:
            loss, delay, jitter = scenarios[args.scenario]
            
            results = run_scenario_with_pcaps(
                args.scenario, loss, delay, jitter
            )
            all_results[args.scenario] = results
        else:
            print(f"❌ Unknown scenario: {args.scenario}")
            return
    
    # Generate final summary
    print(f"\n{'='*80}")
    print(f"📊 TESTING COMPLETE - FINAL SUMMARY")
    print(f"{'='*80}")
    
    total_pcaps = 0
    total_successful = 0
    total_runs = 0
    
    for scenario_name, results in all_results.items():
        if results:
            successful = sum(1 for r in results if r and r.get('connected', 0) >= 2)
            pcaps = sum(1 for r in results if r and r.get('pcap'))
            total_pcaps += pcaps
            total_successful += successful
            total_runs += len(results)
            
            print(f"\n{scenario_name.upper()}:")
            print(f"  Successful runs: {successful}/{len(results)}")
            print(f"  PCAP files: {pcaps}/2")
            if pcaps < 2:
                print(f"  ⚠️  Only {pcaps} PCAPs (PDF requires at least 2)")
    
    print(f"\n📈 OVERALL SUMMARY:")
    print(f"  Total runs: {total_runs}")
    print(f"  Successful runs: {total_successful}/{total_runs}")
    print(f"  Total PCAP files: {total_pcaps}")
    print(f"  Results directory: test_results/")
    print(f"  PCAP directory: captures/")
    
    if total_pcaps > 0:
        print(f"\n🔍 To analyze PCAP files:")
        print(f"   tshark -r captures/*.pcap")
        print(f"   Or: wireshark captures/*.pcap")
    
    print(f"\n📊 To analyze CSV results: python analyze_results.py")
    print(f"{'='*80}")
    
    # Final cleanup
    simple_cleanup()

if __name__ == "__main__":
    main()