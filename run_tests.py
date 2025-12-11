import subprocess
import time
import os
import signal
import sys
import shutil
import platform
import argparse

# Configuration
SERVER_SCRIPT = "server_optimized.py"
CLIENT_SCRIPT = "client.py"
PYTHON_CMD = sys.executable
DURATION = 40  # Seconds per test (can adjust)

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"

def check_netem():
    """Check if netem is available (Linux only)"""
    if not IS_LINUX:
        print("WARNING: Not running on Linux - netem not available")
        return False
    try:
        result = subprocess.run(['tc', '-Version'], 
                               capture_output=True, text=True)
        return 'iproute2' in result.stdout or 'iproute2' in result.stderr
    except FileNotFoundError:
        print("ERROR: 'tc' command not found. Install iproute2: sudo apt install iproute2")
        return False

def setup_netem():
    """Setup netem on loopback interface"""
    if not IS_LINUX:
        return None
    
    interface = 'lo'  # Use loopback for local testing
    
    # Check if interface exists
    try:
        subprocess.run(['ip', 'link', 'show', interface], 
                      capture_output=True, check=True)
        return interface
    except:
        print(f"ERROR: Interface {interface} not found")
        return None

def apply_netem(interface, loss=0, delay=0, jitter=0):
    """Apply netem network impairment using tc command"""
    if not IS_LINUX or not interface:
        print("WARNING: Cannot apply netem - not on Linux or no interface")
        return False
    
    # Remove any existing qdisc
    try:
        subprocess.run(['sudo', 'tc', 'qdisc', 'del', 'dev', interface, 'root'], 
                      capture_output=True, stderr=subprocess.DEVNULL)
        time.sleep(0.5)
    except:
        pass
    
    # Build netem command
    tc_cmd = ['sudo', 'tc', 'qdisc', 'add', 'dev', interface, 'root', 'netem']
    
    if loss > 0 and delay > 0:
        # Both loss and delay
        tc_cmd.extend(['loss', f'{loss}%', 'delay', f'{delay}ms'])
        if jitter > 0:
            tc_cmd.append(f'{jitter}ms')
    elif loss > 0:
        # Only loss
        tc_cmd.extend(['loss', f'{loss}%'])
    elif delay > 0:
        # Only delay
        tc_cmd.extend(['delay', f'{delay}ms'])
        if jitter > 0:
            tc_cmd.append(f'{jitter}ms')
    else:
        # No impairment needed
        print("No netem parameters needed (baseline)")
        return True
    
    print(f"Applying netem: {' '.join(tc_cmd)}")
    
    try:
        result = subprocess.run(tc_cmd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print("Netem applied successfully")
            
            # Verify the configuration
            verify_cmd = ['sudo', 'tc', 'qdisc', 'show', 'dev', interface]
            result = subprocess.run(verify_cmd, capture_output=True, text=True)
            print(f"Current netem config: {result.stdout.strip()}")
            
            return True
        else:
            print(f"Failed to apply netem: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        print("Timeout applying netem")
        return False
    except Exception as e:
        print(f"Error applying netem: {e}")
        return False

def remove_netem(interface):
    """Remove netem qdisc"""
    if not IS_LINUX or not interface:
        return
    
    try:
        print(f"Removing netem from {interface}")
        subprocess.run(['sudo', 'tc', 'qdisc', 'del', 'dev', interface, 'root'], 
                      capture_output=True, stderr=subprocess.DEVNULL)
        time.sleep(1)
    except Exception as e:
        print(f"Error removing netem: {e}")

def start_process(script, args=[]):
    """Start a Python process"""
    cmd = [PYTHON_CMD, script] + args
    env = os.environ.copy()
    
    if IS_LINUX:
        # Start process in new process group
        return subprocess.Popen(cmd, preexec_fn=os.setsid, env=env, 
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    else:
        return subprocess.Popen(cmd, env=env, 
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def kill_process(proc):
    """Kill a process"""
    if proc is None:
        return
    
    if IS_WINDOWS:
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except:
            proc.kill()
    else:
        try:
            # Kill entire process group
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            time.sleep(0.5)
        except:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except:
                proc.kill()

def run_scenario(name, loss, delay, jitter):
    """Run a single test scenario"""
    print(f"\n{'='*60}")
    print(f"STARTING SCENARIO: {name}")
    print(f"Config: Loss={loss}%, Delay={delay}ms, Jitter={jitter}ms")
    print(f"{'='*60}")
    
    # Create results directory
    timestamp = int(time.time())
    log_dir = f"results/{name}_{timestamp}"
    os.makedirs(log_dir, exist_ok=True)
    
    # Setup netem (Linux only)
    netem_interface = None
    netem_applied = False
    
    if IS_LINUX:
        if not check_netem():
            print("CRITICAL: netem not available. Tests will run without network simulation.")
        else:
            netem_interface = setup_netem()
            if netem_interface:
                # Apply netem configuration
                netem_applied = apply_netem(netem_interface, loss, delay, jitter)
    
    # Start packet capture (optional)
    pcap_proc = None
    pcap_file = os.path.join(log_dir, "network_capture.pcap")
    
    if IS_LINUX and netem_interface:
        try:
            print(f"Starting packet capture on {netem_interface}...")
            pcap_proc = subprocess.Popen(
                ['sudo', 'tcpdump', '-i', netem_interface, 
                 '-w', pcap_file, 'port', '5555', '-n'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            time.sleep(2)
        except:
            print("Warning: Could not start packet capture")
            pcap_proc = None
    
    # Start Server
    print("\n[1/3] Starting Server...")
    server_proc = start_process(SERVER_SCRIPT, [])
    time.sleep(3)  # Give server time to start
    
    # Start Clients
    print("[2/3] Starting 4 Clients...")
    clients = []
    for i in range(4):
        client_args = ["127.0.0.1", "--headless"]
        clients.append(start_process(CLIENT_SCRIPT, client_args))
        time.sleep(0.5)
    
    print(f"[3/3] Running test for {DURATION} seconds...")
    
    # Monitor test duration
    start_time = time.time()
    try:
        while time.time() - start_time < DURATION:
            elapsed = int(time.time() - start_time)
            remaining = DURATION - elapsed
            print(f"\rElapsed: {elapsed:3d}s | Remaining: {remaining:3d}s | Press Ctrl+C to stop", 
                  end='', flush=True)
            time.sleep(1)
        print()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    
    # Cleanup
    print("\nCleaning up...")
    
    # Stop packet capture
    if pcap_proc:
        try:
            pcap_proc.terminate()
            pcap_proc.wait(timeout=2)
            if os.path.exists(pcap_file):
                print(f"Packet capture saved to: {pcap_file}")
        except:
            pass
    
    # Stop clients
    print("Stopping clients...")
    for client in clients:
        kill_process(client)
    
    # Stop server
    print("Stopping server...")
    kill_process(server_proc)
    
    # Remove netem
    if netem_applied and netem_interface:
        remove_netem(netem_interface)
    
    # Move log files
    print("Collecting log files...")
    time.sleep(2)  # Wait for files to be released
    
    files_moved = 0
    for attempt in range(3):
        try:
            for f in os.listdir("."):
                if f.endswith(".csv") and os.path.getsize(f) > 0:
                    try:
                        dest = os.path.join(log_dir, f)
                        shutil.move(f, dest)
                        files_moved += 1
                        print(f"  Moved: {f} -> {dest}")
                    except (PermissionError, shutil.Error) as e:
                        pass
            if files_moved >= 2:
                break
            time.sleep(1)
        except Exception as e:
            print(f"Error moving files: {e}")
    
    # Save test configuration
    config_file = os.path.join(log_dir, "test_config.txt")
    with open(config_file, 'w') as f:
        f.write(f"Test Scenario: {name}\n")
        f.write(f"Loss Rate: {loss}%\n")
        f.write(f"Delay: {delay}ms\n")
        f.write(f"Jitter: {jitter}ms\n")
        f.write(f"Duration: {DURATION}s\n")
        f.write(f"Timestamp: {timestamp}\n")
        f.write(f"Platform: {platform.system()} {platform.release()}\n")
        f.write(f"Python: {sys.version}\n")
        f.write(f"Netem Applied: {netem_applied}\n")
        if netem_interface:
            f.write(f"Interface: {netem_interface}\n")
    
    print(f"\nTest '{name}' completed!")
    print(f"Results saved to: {log_dir}")
    print(f"Files collected: {files_moved}")
    
    # List files in directory
    if os.path.exists(log_dir):
        files = os.listdir(log_dir)
        print(f"Contents: {', '.join(files[:5])}{'...' if len(files) > 5 else ''}")
    
    return log_dir

def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="Grid Clash Network Protocol Tests")
    parser.add_argument("--scenario", choices=["all", "baseline", "loss2", "loss5", "delay100"], 
                       default="all", help="Test scenario to run")
    parser.add_argument("--duration", type=int, default=40, 
                       help="Test duration in seconds (default: 40)")
    args = parser.parse_args()
    
    global DURATION
    DURATION = args.duration
    
    print("\n" + "="*60)
    print("GRID CLASH NETWORK PROTOCOL TEST SUITE")
    print("="*60)
    print(f"Platform: {platform.system()} {platform.release()}")
    print(f"Python: {sys.executable}")
    print(f"Test Duration: {DURATION} seconds per scenario")
    
    if IS_LINUX:
        print("Linux detected - will use netem for network simulation")
        if not check_netem():
            print("\n⚠️  WARNING: netem not properly installed!")
            print("Please install iproute2: sudo apt install iproute2")
            print("Tests will run but without network simulation.\n")
    else:
        print("\n⚠️  WARNING: Not running on Linux")
        print("Network simulation (loss/delay) will not be available")
        print("For proper testing, please run on a Linux system.\n")
    
    # Define test scenarios as per project requirements
    scenarios = {
        "baseline": ("Baseline", 0, 0, 0),
        "loss2": ("Loss_2_Percent", 2, 0, 0),
        "loss5": ("Loss_5_Percent", 5, 0, 0),
        "delay100": ("Delay_100ms", 0, 100, 10)
    }
    
    results = []
    
    if args.scenario == "all":
        # Run all scenarios in order
        for key, params in scenarios.items():
            result_dir = run_scenario(*params)
            results.append(result_dir)
            if key != "delay100":  # Don't wait after last test
                print("\n" + "-"*60)
                print("Waiting 10 seconds before next test...")
                time.sleep(10)
    else:
        # Run specific scenario
        if args.scenario in scenarios:
            result_dir = run_scenario(*scenarios[args.scenario])
            results.append(result_dir)
        else:
            print(f"Error: Unknown scenario '{args.scenario}'")
            return
    
    # Summary
    print("\n" + "="*60)
    print("TESTING COMPLETE!")
    print("="*60)
    
    if results:
        print(f"\nCompleted {len(results)} test scenario(s):")
        for result in results:
            print(f"  • {result}")
        
        print("\nNext steps:")
        print("1. Analyze results: python analyze_results.py")
        print("2. Check log files in 'results/' directory")
        print("3. Review packet captures (if available)")
    else:
        print("No tests were completed.")
    
    print("\n" + "="*60)

if __name__ == "__main__":
    main()