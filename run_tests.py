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
        # Try multiple version flags
        version_flags = ['-V', '-Version', '--version', '-v']
        
        for flag in version_flags:
            try:
                result = subprocess.run(['tc', flag], 
                                       capture_output=True, text=True, timeout=3)
                if result.returncode == 0:
                    print(f"✅ tc found (using flag {flag})")
                    # Test actual netem functionality
                    return test_netem_functionality()
            except:
                continue
        
        print("ERROR: 'tc' command not found or not working")
        return False
        
    except Exception as e:
        print(f"ERROR checking netem: {e}")
        return False

def test_netem_functionality():
    """Test if netem actually works"""
    print("   Testing netem functionality...")
    try:
        # Add test rule
        test_cmd = ['sudo', 'tc', 'qdisc', 'add', 'dev', 'lo', 'root', 'netem', 'delay', '1ms']
        result = subprocess.run(test_cmd, capture_output=True, text=True, timeout=5)
        
        if result.returncode == 0:
            # Clean up
            subprocess.run(['sudo', 'tc', 'qdisc', 'del', 'dev', 'lo', 'root'],
                          capture_output=True, text=True, timeout=3)
            print("   ✅ Netem functionality verified")
            return True
        else:
            print(f"   ⚠️  Netem test failed: {result.stderr[:100]}")
            return False
    except Exception as e:
        print(f"   ❌ Netem test error: {e}")
        return False

def setup_netem():
    """Setup netem on appropriate interface"""
    if not IS_LINUX:
        return None
    
    print("✅ Using loopback interface (lo) for testing")
    return 'lo'

def apply_netem(interface, loss=0, delay=0, jitter=0):
    """Apply netem configuration with validation"""
    if not interface:
        return False
    
    # If no impairment needed
    if loss == 0 and delay == 0:
        print("✅ Baseline - no network impairment needed")
        return True
    
    print(f"\n🔧 Applying netem configuration:")
    print(f"   Interface: {interface}")
    print(f"   Loss: {loss}%")
    print(f"   Delay: {delay}ms")
    print(f"   Jitter: {jitter}ms")
    
    # Try multiple methods
    methods = [
        ("Standard netem add", ['sudo', 'tc', 'qdisc', 'add', 'dev', interface, 'root', 'netem']),
        ("Netem replace", ['sudo', 'tc', 'qdisc', 'replace', 'dev', interface, 'root', 'netem']),
        ("Netem with handle", ['sudo', 'tc', 'qdisc', 'add', 'dev', interface, 'root', 'handle', '1:', 'netem'])
    ]
    
    for method_name, base_cmd in methods:
        print(f"\n   Trying {method_name}...")
        
        # Remove existing first
        subprocess.run(['sudo', 'tc', 'qdisc', 'del', 'dev', interface, 'root', '2>/dev/null'],
                      shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
        
        # Build command with parameters
        cmd = base_cmd.copy()
        if loss > 0:
            cmd.extend(['loss', f'{loss}%'])
        if delay > 0:
            if jitter > 0:
                cmd.extend(['delay', f'{delay}ms', f'{jitter}ms'])
            else:
                cmd.extend(['delay', f'{delay}ms'])
        
        print(f"   Command: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                print(f"   ✅ {method_name} succeeded")
                
                # Verify configuration
                verify = subprocess.run(['sudo', 'tc', 'qdisc', 'show', 'dev', interface],
                                      capture_output=True, text=True)
                config = verify.stdout.strip()
                print(f"   Current config: {config}")
                
                # Validate
                if loss > 0 and 'loss' not in config.lower():
                    print(f"   ⚠️  Warning: Loss not in config")
                if delay > 0 and 'delay' not in config.lower():
                    print(f"   ⚠️  Warning: Delay not in config")
                
                return True
            else:
                print(f"   ❌ Failed: {result.stderr[:100]}")
                
        except Exception as e:
            print(f"   ❌ Error: {e}")
    
    print(f"\n   ⚠️  All netem methods failed")
    print(f"   Will continue with software simulation")
    
    # Set environment variables for software simulation
    os.environ['SIMULATE_NETWORK'] = '1'
    os.environ['SIMULATE_LOSS'] = str(loss)
    os.environ['SIMULATE_DELAY'] = str(delay)
    os.environ['SIMULATE_JITTER'] = str(jitter)
    
    return True  # Return True for software simulation

def remove_netem(interface):
    """Remove netem configuration"""
    if not interface:
        return
    
    print(f"\n🧹 Removing netem from {interface}...")
    
    # Try multiple removal methods
    removal_attempts = [
        ['sudo', 'tc', 'qdisc', 'del', 'dev', interface, 'root'],
        ['sudo', 'tc', 'qdisc', 'del', 'dev', interface],
        ['sudo', 'tc', '-force', 'qdisc', 'del', 'dev', interface, '2>/dev/null'],
    ]
    
    for attempt in removal_attempts:
        try:
            result = subprocess.run(attempt, 
                                   stdout=subprocess.DEVNULL, 
                                   stderr=subprocess.DEVNULL,
                                   timeout=3)
            if result.returncode == 0 or result.returncode == 2:  # 2 means no existing qdisc
                print(f"   ✅ Cleaned with: {' '.join(attempt)}")
                break
        except:
            pass
    
    time.sleep(1)
    
    # Verify removal
    verify = subprocess.run(['sudo', 'tc', 'qdisc', 'show', 'dev', interface],
                          capture_output=True, text=True, timeout=3)
    if 'netem' not in verify.stdout.lower():
        print("   ✅ Netem completely removed")
    else:
        print(f"   ⚠️  Warning: Netem might still be present")
        print(f"   Current: {verify.stdout.strip()}")
    
    # Clear simulation environment variables
    env_vars = ['SIMULATE_NETWORK', 'SIMULATE_LOSS', 'SIMULATE_DELAY', 'SIMULATE_JITTER']
    for var in env_vars:
        if var in os.environ:
            del os.environ[var]

def cleanup_old_files():
    """Remove old CSV files before test"""
    print("\n🧹 Cleaning up old log files...")
    files_removed = 0
    
    for f in os.listdir("."):
        if f.endswith((".csv", ".log")) and os.path.isfile(f):
            try:
                os.remove(f)
                files_removed += 1
            except:
                pass
    
    if files_removed > 0:
        print(f"   Removed {files_removed} old files")
    
    # Also clean old results if too many
    if os.path.exists("results") and len(os.listdir("results")) > 20:
        print("   Warning: results/ directory has >20 entries")

def get_virtualbox_ip():
    """Get appropriate IP for VirtualBox testing"""
    if IS_VIRTUALBOX:
        print("⚠️  VirtualBox detected")
        
        # For loopback testing, use 127.0.0.1
        print("   Using loopback (127.0.0.1) for testing")
        return "127.0.0.1"
    
    # For native Linux
    return "127.0.0.1"

def start_process(script, args=[], name=""):
    """Start a Python process with logging"""
    cmd = [PYTHON_CMD, script] + args
    env = os.environ.copy()
    
    # Add environment variable for headless mode
    if "--headless" in args:
        env['HEADLESS_MODE'] = '1'
    
    print(f"   Starting {name if name else script}: {' '.join(cmd[:3])}...")  # Truncate for display
    
    if IS_LINUX:
        # Capture output to log files
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
    
    if IS_WINDOWS:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except:
            try:
                proc.kill()
            except:
                pass
    else:
        try:
            # Kill entire process group
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            time.sleep(1)
        except:
            try:
                proc.terminate()
                proc.wait(timeout=3)
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
    
    # Check Python dependencies
    try:
        import pandas
        import numpy
        import psutil
        print("   ✅ Python dependencies installed")
    except ImportError as e:
        print(f"   ⚠️  Missing dependency: {e}")
    
    return True

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
    
    # Clean up old files before starting
    cleanup_old_files()
    
    # Validate setup
    if not validate_test_setup():
        print("❌ Test setup validation failed. Aborting.")
        return None
    
    # Get appropriate IP address
    server_ip = get_virtualbox_ip()
    print(f"\n🌐 Network Configuration:")
    print(f"   Server IP: {server_ip}")
    print(f"   Port: 5555")
    
    # Setup netem (Linux only) - BYPASS CHECK SINCE FORCE_NETEM = True
    netem_interface = None
    netem_applied = False
    
    if IS_LINUX:
        print("✅ Linux detected - configuring network simulation")
        netem_interface = setup_netem()
        if netem_interface:
            netem_applied = apply_netem(netem_interface, loss, delay, jitter)
            if not netem_applied:
                print("⚠️  Using software simulation for network conditions")
        else:
            print("⚠️  No interface available for netem")
    else:
        print("⚠️  Not Linux - using software simulation")
    
    # Start packet capture
    pcap_proc = None
    pcap_file = os.path.join(log_dir, "network_capture.pcap")
    
    if IS_LINUX and netem_interface and netem_applied and 'SIMULATE_NETWORK' not in os.environ:
        try:
            print(f"\n📡 Starting packet capture on {netem_interface}...")
            pcap_proc = subprocess.Popen(
                ['sudo', 'tcpdump', '-i', netem_interface, 
                 '-w', pcap_file, 'port', '5555', '-n', '-s', '0', '-c', '1000'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            time.sleep(2)
            print("   ✅ Packet capture started")
        except Exception as e:
            print(f"   ⚠️  Could not start packet capture: {e}")
            pcap_proc = None
    
    # Start Server
    print(f"\n[1/3] Starting Server on {server_ip}:5555...")
    server_proc = start_process(SERVER_SCRIPT, [], "server")
    
    # Wait for server to start
    print("   Waiting for server to initialize...")
    time.sleep(3)
    
    # Start Clients
    print(f"\n[2/3] Starting 4 Clients...")
    clients = []
    for i in range(4):
        client_args = [server_ip, "--headless"]
        client_name = f"client_{i+1}"
        clients.append(start_process(CLIENT_SCRIPT, client_args, client_name))
        time.sleep(0.5)  # Reduced delay
        print(f"   Started client {i+1}")
    
    print(f"\n[3/3] Running test for {DURATION} seconds...")
    print("   Press Ctrl+C to stop early")
    
    # Monitor test duration with progress bar
    start_time = time.time()
    last_progress = 0
    
    try:
        while time.time() - start_time < DURATION:
            elapsed = time.time() - start_time
            progress = int((elapsed / DURATION) * 50)
            
            if progress > last_progress:
                bar = "[" + "=" * progress + " " * (50 - progress) + "]"
                percent = (elapsed / DURATION) * 100
                print(f"\rProgress: {bar} {percent:.1f}%", end='', flush=True)
                last_progress = progress
            
            time.sleep(0.5)
        
        print("\n   ✅ Test duration complete")
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
    
    # Cleanup
    print(f"\n🧹 Cleaning up...")
    
    # Stop packet capture
    if pcap_proc:
        try:
            pcap_proc.terminate()
            pcap_proc.wait(timeout=3)
            if os.path.exists(pcap_file) and os.path.getsize(pcap_file) > 0:
                print(f"   ✅ Packet capture saved: {pcap_file}")
            else:
                print(f"   ⚠️  Packet capture file empty or missing")
        except:
            print(f"   ⚠️  Error stopping packet capture")
    
    # Stop clients
    print("   Stopping clients...")
    for i, client in enumerate(clients):
        kill_process(client, f"client_{i+1}")
        time.sleep(0.2)
    
    # Stop server
    print("   Stopping server...")
    kill_process(server_proc, "server")
    
    # Remove netem
    if netem_applied and netem_interface:
        remove_netem(netem_interface)
    
    # Wait for processes to fully exit
    time.sleep(2)
    
    # Collect log files
    print(f"\n📂 Collecting log files...")
    files_moved = 0
    
    # Collect stdout/stderr logs
    for i in range(1, 5):
        for suffix in ['stdout.log', 'stderr.log']:
            log_file = f"client_{i}_{suffix}"
            if os.path.exists(log_file):
                try:
                    shutil.move(log_file, os.path.join(log_dir, log_file))
                    files_moved += 1
                except:
                    pass
    
    # Collect server logs
    for suffix in ['stdout.log', 'stderr.log']:
        log_file = f"server_{suffix}"
        if os.path.exists(log_file):
            try:
                shutil.move(log_file, os.path.join(log_dir, log_file))
                files_moved += 1
            except:
                pass
    
    # Collect CSV files
    for attempt in range(3):
        try:
            for f in os.listdir("."):
                if f.endswith(".csv") and os.path.getsize(f) > 100:  # At least 100 bytes
                    try:
                        dest = os.path.join(log_dir, f)
                        shutil.move(f, dest)
                        files_moved += 1
                        print(f"   Moved: {f} ({os.path.getsize(dest)} bytes)")
                    except (PermissionError, shutil.Error) as e:
                        pass
            if files_moved >= 5:  # Expect at least 5 files (server + 4 clients)
                break
            time.sleep(1)
        except Exception as e:
            print(f"   Error moving files: {e}")
    
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
        f.write(f"VirtualBox: {IS_VIRTUALBOX}\n")
        f.write(f"Server IP: {server_ip}\n")
        f.write(f"Python: {sys.version}\n")
        f.write(f"Netem Applied: {netem_applied}\n")
        if netem_interface:
            f.write(f"Interface: {netem_interface}\n")
        if 'SIMULATE_NETWORK' in os.environ:
            f.write(f"Software Simulation: Yes\n")
    
    # Validate collected data
    print(f"\n📊 Test Results Summary:")
    print(f"   Log directory: {log_dir}")
    print(f"   Files collected: {files_moved}")
    
    if os.path.exists(log_dir):
        files = os.listdir(log_dir)
        csv_files = [f for f in files if f.endswith('.csv')]
        print(f"   CSV files: {len(csv_files)}")
        
        # Check if we have the essential files
        essential_files = ['server_log.csv'] + [f'client_log_{i}.csv' for i in range(1, 5)]
        missing = [f for f in essential_files if f not in files]
        
        if missing:
            print(f"   ⚠️  Missing essential files: {missing}")
        else:
            print(f"   ✅ All essential files present")
    
    return log_dir

def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="Grid Clash Network Protocol Tests")
    parser.add_argument("--scenario", choices=["all", "baseline", "loss2", "loss5", "delay100"], 
                       default="all", help="Test scenario to run")
    parser.add_argument("--duration", type=int, default=40, 
                       help="Test duration in seconds (default: 40)")
    parser.add_argument("--no-netem", action="store_true",
                       help="Disable netem even if available")
    args = parser.parse_args()
    
    global DURATION, FORCE_NETEM
    DURATION = args.duration
    
    if args.no_netem:
        FORCE_NETEM = False
        print("⚠️  Netem disabled by user flag")
    
    print("\n" + "="*60)
    print("GRID CLASH NETWORK PROTOCOL TEST SUITE")
    print("="*60)
    print(f"Platform: {platform.system()} {platform.release()}")
    print(f"VirtualBox: {IS_VIRTUALBOX}")
    print(f"Python: {sys.executable}")
    print(f"Test Duration: {DURATION} seconds per scenario")
    print(f"Netem Enabled: {FORCE_NETEM}")
    
    if IS_LINUX:
        print("✅ Linux detected")
        if FORCE_NETEM:
            print("✅ Netem force-enabled (will attempt to use)")
        else:
            netem_available = check_netem()
            if not netem_available:
                print("⚠️  Netem not available - using software simulation")
    else:
        print("⚠️  Not Linux - using software simulation")
    
    # Define test scenarios as per project requirements
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
        # Run all scenarios in order
        scenarios_to_run = list(scenarios.items())
        
        for i, (key, params) in enumerate(scenarios_to_run):
            print(f"\n📋 Running scenario {i+1}/{len(scenarios_to_run)}")
            result_dir = run_scenario(*params)
            if result_dir:
                results.append(result_dir)
            
            # Wait between tests (except after last one)
            if i < len(scenarios_to_run) - 1:
                print(f"\n⏳ Waiting 10 seconds before next test...")
                time.sleep(10)
    else:
        # Run specific scenario
        if args.scenario in scenarios:
            result_dir = run_scenario(*scenarios[args.scenario])
            if result_dir:
                results.append(result_dir)
        else:
            print(f"❌ Error: Unknown scenario '{args.scenario}'")
            return
    
    # Summary
    print("\n" + "="*60)
    print("TESTING COMPLETE!")
    print("="*60)
    
    if results:
        print(f"\n✅ Completed {len(results)} test scenario(s):")
        for result in results:
            print(f"  • {result}")
        
        print("\n📝 Next steps:")
        print("1. Analyze results: python analyze_result.py")
        print("2. Check log files in 'results/' directory")
        print("3. Review the analysis_report.txt")
        print("4. Check generated plots (if matplotlib installed)")
    else:
        print("❌ No tests were successfully completed.")
    
    print("\n" + "="*60)

if __name__ == "__main__":
    main()