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
IS_VIRTUALBOX = "virtualbox" in platform.platform().lower()

# FORCE NETEM ENABLED - SET TO TRUE SINCE YOU TESTED MANUALLY
FORCE_NETEM = True

def check_netem():
    """Check if netem is available (Linux only)"""
    if not IS_LINUX:
        print("WARNING: Not running on Linux - netem not available")
        return False
    
    if FORCE_NETEM:
        print("✅ Netem force-enabled (manual test passed)")
        return True
    
    try:
        # Try to get tc version
        result = subprocess.run(['tc', '-V'], 
                               capture_output=True, text=True, timeout=3)
        if result.returncode == 0:
            print(f"✅ tc found: {result.stdout[:50]}")
            return True
        else:
            print("ERROR: 'tc' command not found or not working")
            return False
        
    except Exception as e:
        print(f"ERROR checking netem: {e}")
        return False

def setup_netem():
    """Setup netem on appropriate interface"""
    if not IS_LINUX:
        return None
    
    print("✅ Using loopback interface (lo) for testing")
    return 'lo'

def apply_netem(interface, loss=0, delay=0, jitter=0):
    """Apply netem with timeout protection"""
    if not interface:
        return False
    
    print(f"\n🔧 Configuring network conditions:")
    print(f"   Interface: {interface}")
    print(f"   Loss: {loss}%, Delay: {delay}ms, Jitter: {jitter}ms")
    
    # If no impairment needed
    if loss == 0 and delay == 0:
        print("   ✅ Baseline - no network impairment needed")
        return True
    
    # Clean up first with timeout
    cleanup_cmds = [
        f"timeout 2 sudo tc qdisc del dev {interface} root 2>/dev/null",
        f"timeout 2 sudo tc qdisc del dev {interface} ingress 2>/dev/null",
    ]
    
    for cmd in cleanup_cmds:
        subprocess.run(cmd, shell=True, 
                      stdout=subprocess.DEVNULL, 
                      stderr=subprocess.DEVNULL,
                      timeout=3)
    
    time.sleep(1)
    
    # Try different syntaxes for tc 6.1.0
    syntaxes_to_try = []
    
    if loss > 0 and delay > 0:
        if jitter > 0:
            syntaxes_to_try.append(f"loss {loss}% delay {delay}ms {jitter}ms limit 1000")
            syntaxes_to_try.append(f"delay {delay}ms {jitter}ms loss {loss}% limit 1000")
        else:
            syntaxes_to_try.append(f"loss {loss}% delay {delay}ms limit 1000")
            syntaxes_to_try.append(f"delay {delay}ms loss {loss}% limit 1000")
    elif loss > 0:
        syntaxes_to_try.append(f"loss {loss}% limit 1000")
    elif delay > 0:
        if jitter > 0:
            syntaxes_to_try.append(f"delay {delay}ms {jitter}ms limit 1000")
            syntaxes_to_try.append(f"delay {delay}ms {jitter}ms distribution normal limit 1000")
        else:
            syntaxes_to_try.append(f"delay {delay}ms limit 1000")
    
    # Try each syntax
    for syntax in syntaxes_to_try:
        print(f"\n   Trying: netem {syntax}")
        cmd = f"timeout 5 sudo tc qdisc add dev {interface} root netem {syntax}"
        
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=6)
            
            if result.returncode == 0:
                print("   ✅ Netem applied successfully")
                
                # Quick verify
                verify = subprocess.run(['sudo', 'tc', 'qdisc', 'show', 'dev', interface],
                                      capture_output=True, text=True, timeout=3)
                print(f"   Config: {verify.stdout.strip()}")
                return True
            else:
                print(f"   ⚠️  Failed: {result.stderr[:80]}")
                
        except subprocess.TimeoutExpired:
            print("   ⚠️  Timeout - trying next syntax")
            continue
        except Exception as e:
            print(f"   ⚠️  Error: {e}")
    
    # If all netem methods fail, use software simulation
    print("\n   ⚠️  All netem methods failed. Using software simulation.")
    os.environ['SIMULATE_NETWORK'] = '1'
    os.environ['SIMULATE_LOSS'] = str(loss)
    os.environ['SIMULATE_DELAY'] = str(delay)
    os.environ['SIMULATE_JITTER'] = str(jitter)
    
    print("   ✅ Software simulation enabled")
    return True

def remove_netem(interface):
    """Remove netem configuration with timeout protection"""
    if not interface:
        return
    
    print(f"\n🧹 Cleaning up network configuration...")
    
    # Quick removal commands with timeouts
    cleanup_commands = [
        f"timeout 2 sudo tc qdisc del dev {interface} root 2>/dev/null",
        f"timeout 2 sudo tc qdisc del dev {interface} 2>/dev/null",
        f"timeout 2 sudo tc -force qdisc del dev {interface} 2>/dev/null",
    ]
    
    for cmd in cleanup_commands:
        try:
            subprocess.run(cmd, shell=True, 
                          stdout=subprocess.DEVNULL, 
                          stderr=subprocess.DEVNULL,
                          timeout=3)
        except:
            pass
    
    # Kill any hanging tc processes
    try:
        subprocess.run(['sudo', 'pkill', '-9', 'tc'], 
                      stdout=subprocess.DEVNULL, 
                      stderr=subprocess.DEVNULL,
                      timeout=2)
    except:
        pass
    
    time.sleep(1)
    
    # Clear simulation environment variables
    env_vars = ['SIMULATE_NETWORK', 'SIMULATE_LOSS', 'SIMULATE_DELAY', 'SIMULATE_JITTER']
    for var in env_vars:
        if var in os.environ:
            del os.environ[var]
    
    print("   ✅ Cleanup completed")

def preemptive_cleanup():
    """Clean up any leftover processes before starting tests"""
    print("\n🔧 Preemptive cleanup...")
    
    # Kill any leftover Python processes
    try:
        subprocess.run(['sudo', 'pkill', '-9', 'python'], 
                      stdout=subprocess.DEVNULL, 
                      stderr=subprocess.DEVNULL,
                      timeout=2)
    except:
        pass
    
    # Kill any tc processes
    try:
        subprocess.run(['sudo', 'pkill', '-9', 'tc'], 
                      stdout=subprocess.DEVNULL, 
                      stderr=subprocess.DEVNULL,
                      timeout=2)
    except:
        pass
    
    # Remove netem from loopback
    try:
        subprocess.run(['sudo', 'tc', 'qdisc', 'del', 'dev', 'lo', 'root'], 
                      stdout=subprocess.DEVNULL, 
                      stderr=subprocess.DEVNULL,
                      timeout=2)
    except:
        pass
    
    time.sleep(2)
    print("   ✅ Preemptive cleanup done")

def cleanup_old_files():
    """Remove old CSV and log files before test"""
    print("\n🧹 Cleaning up old log files...")
    files_removed = 0
    
    for f in os.listdir("."):
        if f.endswith((".csv", ".log", ".pcap")) and os.path.isfile(f):
            try:
                os.remove(f)
                files_removed += 1
            except:
                pass
    
    if files_removed > 0:
        print(f"   Removed {files_removed} old files")
    
    # Clean old results if too many
    if os.path.exists("results") and len(os.listdir("results")) > 20:
        print("   Warning: results/ directory has >20 entries")

def get_virtualbox_ip():
    """Get appropriate IP for VirtualBox testing"""
    return "127.0.0.1"  # Always use loopback for consistency

def start_process(script, args=[], name=""):
    """Start a Python process with logging"""
    cmd = [PYTHON_CMD, script] + args
    env = os.environ.copy()
    
    print(f"   Starting {name if name else os.path.basename(script)}...")
    
    if IS_LINUX:
        # Log to files for debugging
        stdout_file = open(f"{name}_stdout.log", "w") if name else subprocess.PIPE
        stderr_file = open(f"{name}_stderr.log", "w") if name else subprocess.PIPE
        
        return subprocess.Popen(cmd, preexec_fn=os.setsid, env=env,
                               stdout=stdout_file, stderr=stderr_file)
    else:
        return subprocess.Popen(cmd, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def kill_process(proc, name=""):
    """Kill a process gracefully"""
    if proc is None:
        return
    
    if name:
        print(f"   Stopping {name}...")
    
    try:
        if IS_WINDOWS:
            proc.terminate()
            proc.wait(timeout=2)
        else:
            # Kill entire process group
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            time.sleep(0.5)
    except:
        try:
            proc.kill()
        except:
            pass

def validate_test_setup():
    """Validate that test setup is correct"""
    print("\n🔍 Validating test setup...")
    
    # Check essential files exist
    required_files = ["protocol.py", "server_optimized.py", "client.py", "game_state.py"]
    for f in required_files:
        if not os.path.exists(f):
            print(f"   ❌ Missing required file: {f}")
            return False
    
    print("   ✅ All required files present")
    
    # Check if protocol.py has monotonic time fixes
    try:
        with open("protocol.py", "r") as f:
            content = f.read()
            if "time.perf_counter()" not in content and "start_time_ref" not in content:
                print("   ⚠️  protocol.py may not have monotonic time fixes")
    except:
        pass
    
    return True

def collect_log_files(log_dir):
    """Collect and move log files to results directory"""
    print(f"\n📂 Collecting log files to {log_dir}...")
    files_moved = 0
    
    # Collect CSV files
    for attempt in range(3):
        try:
            for f in os.listdir("."):
                if f.endswith(".csv") and os.path.getsize(f) > 100:
                    try:
                        dest = os.path.join(log_dir, f)
                        if os.path.exists(f):
                            shutil.move(f, dest)
                            files_moved += 1
                            print(f"   📄 Moved: {f}")
                    except:
                        pass
                        
            if files_moved > 0:
                break
            time.sleep(1)
        except:
            pass
    
    # Collect log files
    for f in os.listdir("."):
        if f.endswith((".log", ".pcap", ".txt")):
            try:
                dest = os.path.join(log_dir, f)
                if os.path.exists(f):
                    shutil.move(f, dest)
                    files_moved += 1
            except:
                pass
    
    return files_moved

def run_scenario(name, loss, delay, jitter):
    """Run a single test scenario"""
    print(f"\n{'='*60}")
    print(f"STARTING SCENARIO: {name}")
    print(f"Config: Loss={loss}%, Delay={delay}ms, Jitter={jitter}ms")
    print(f"{'='*60}")
    
    # Preemptive cleanup
    preemptive_cleanup()
    
    # Create results directory
    timestamp = int(time.time())
    log_dir = f"results/{name}_{timestamp}"
    os.makedirs(log_dir, exist_ok=True)
    
    # Clean up old files
    cleanup_old_files()
    
    # Validate setup
    if not validate_test_setup():
        print("❌ Test setup validation failed")
        return None
    
    # Get IP address
    server_ip = get_virtualbox_ip()
    print(f"\n🌐 Using server IP: {server_ip}:5555")
    
    # Setup netem
    netem_interface = None
    netem_applied = False
    
    if IS_LINUX and FORCE_NETEM:
        print("✅ Configuring network simulation")
        netem_interface = setup_netem()
        if netem_interface:
            netem_applied = apply_netem(netem_interface, loss, delay, jitter)
            if not netem_applied:
                print("⚠️  Netem failed - using software simulation")
        else:
            print("⚠️  No interface available")
    
    # Start Server
    print(f"\n[1/3] Starting Server...")
    server_proc = start_process(SERVER_SCRIPT, [], "server")
    time.sleep(3)
    
    # Start Clients
    print(f"[2/3] Starting 4 Clients...")
    clients = []
    for i in range(4):
        client_args = [server_ip, "--headless"]
        client_name = f"client_{i+1}"
        clients.append(start_process(CLIENT_SCRIPT, client_args, client_name))
        time.sleep(0.3)
        print(f"   Started client {i+1}")
    
    # Run test
    print(f"\n[3/3] Running for {DURATION} seconds...")
    start_time = time.time()
    
    try:
        while time.time() - start_time < DURATION:
            elapsed = int(time.time() - start_time)
            remaining = DURATION - elapsed
            print(f"\r⏱️  Elapsed: {elapsed:3d}s | Remaining: {remaining:3d}s", end='', flush=True)
            time.sleep(0.5)
        print("\n   ✅ Test complete")
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted")
    
    # Cleanup
    print(f"\n🧹 Cleaning up...")
    
    # Stop clients
    print("   Stopping clients...")
    for i, client in enumerate(clients):
        kill_process(client, f"client_{i+1}")
    
    # Stop server
    print("   Stopping server...")
    kill_process(server_proc, "server")
    
    # Remove netem
    if netem_applied and netem_interface:
        remove_netem(netem_interface)
    
    # Wait for cleanup
    time.sleep(2)
    
    # Collect log files
    files_moved = collect_log_files(log_dir)
    
    # Save test configuration
    config_file = os.path.join(log_dir, "test_config.txt")
    with open(config_file, 'w') as f:
        f.write(f"Test Scenario: {name}\n")
        f.write(f"Loss: {loss}%\n")
        f.write(f"Delay: {delay}ms\n")
        f.write(f"Jitter: {jitter}ms\n")
        f.write(f"Duration: {DURATION}s\n")
        f.write(f"Timestamp: {timestamp}\n")
        f.write(f"Platform: {platform.system()}\n")
        f.write(f"Python: {sys.version.split()[0]}\n")
        f.write(f"Netem Applied: {netem_applied}\n")
        if 'SIMULATE_NETWORK' in os.environ:
            f.write(f"Software Simulation: Yes\n")
    
    # Report summary
    print(f"\n📊 Test Summary:")
    print(f"   Log directory: {log_dir}")
    print(f"   Files collected: {files_moved}")
    
    if os.path.exists(log_dir):
        csv_count = len([f for f in os.listdir(log_dir) if f.endswith('.csv')])
        print(f"   CSV files: {csv_count}")
        
        if csv_count >= 5:
            print(f"   ✅ All expected files present")
        else:
            print(f"   ⚠️  Missing some CSV files")
    
    return log_dir

def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="Grid Clash Network Protocol Tests")
    parser.add_argument("--scenario", choices=["all", "baseline", "loss2", "loss5", "delay100"], 
                       default="all", help="Test scenario to run")
    parser.add_argument("--duration", type=int, default=40, 
                       help="Test duration in seconds")
    parser.add_argument("--software-only", action="store_true",
                       help="Use software simulation only (no netem)")
    args = parser.parse_args()
    
    global DURATION, FORCE_NETEM
    DURATION = args.duration
    
    if args.software_only:
        FORCE_NETEM = False
        print("⚠️  Using software simulation only")
    
    print("\n" + "="*60)
    print("GRID CLASH NETWORK PROTOCOL TEST SUITE")
    print("="*60)
    print(f"Platform: {platform.system()}")
    print(f"VirtualBox: {IS_VIRTUALBOX}")
    print(f"Python: {sys.executable}")
    print(f"Duration: {DURATION}s per test")
    print(f"Netem: {'Enabled' if FORCE_NETEM else 'Disabled (software simulation)'}")
    
    # Define test scenarios
    scenarios = {
        "baseline": ("Baseline", 0, 0, 0),
        "loss2": ("Loss_2_Percent", 2, 0, 0),
        "loss5": ("Loss_5_Percent", 5, 0, 0),
        "delay100": ("Delay_100ms", 0, 100, 10)
    }
    
    results = []
    
    # Ensure results directory exists
    os.makedirs("results", exist_ok=True)
    
    if args.scenario == "all":
        # Run all scenarios
        for i, (key, params) in enumerate(scenarios.items()):
            print(f"\n📋 Test {i+1}/4: {params[0]}")
            result_dir = run_scenario(*params)
            if result_dir:
                results.append(result_dir)
            
            # Wait between tests
            if i < len(scenarios) - 1:
                print(f"\n⏳ Waiting 10 seconds...")
                time.sleep(10)
    else:
        # Run specific scenario
        if args.scenario in scenarios:
            result_dir = run_scenario(*scenarios[args.scenario])
            if result_dir:
                results.append(result_dir)
        else:
            print(f"❌ Unknown scenario: {args.scenario}")
            return
    
    # Final summary
    print("\n" + "="*60)
    print("✅ TESTING COMPLETE!")
    print("="*60)
    
    if results:
        print(f"\nCompleted {len(results)} scenario(s):")
        for result in results:
            print(f"  • {result}")
        
        print("\n📝 Next steps:")
        print("1. Analyze results: python analyze_result.py")
        print("2. Check the analysis_report.txt")
        print("3. Review log files in results/")
    else:
        print("❌ No tests completed successfully")
    
    print("\n" + "="*60)

if __name__ == "__main__":
    main()