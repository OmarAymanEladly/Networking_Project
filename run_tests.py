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
DURATION = 40

IS_LINUX = platform.system() == "Linux"

def simple_cleanup():
    """Simple cleanup that won't kill our own process"""
    print("\n🧹 Simple cleanup...")
    
    # Only clean netem, not processes
    try:
        subprocess.run(['sudo', 'tc', 'qdisc', 'del', 'dev', 'lo', 'root'], 
                      stdout=subprocess.DEVNULL, 
                      stderr=subprocess.DEVNULL,
                      timeout=2)
        print("   Cleaned netem rules")
    except:
        pass
    
    # FIXED: Also clean iptables rules
    try:
        subprocess.run(['sudo', 'iptables', '-F'],  # Flush all iptables rules
                      stdout=subprocess.DEVNULL, 
                      stderr=subprocess.DEVNULL,
                      timeout=2)
        print("   Cleaned iptables rules")
    except:
        pass
    
    # Clean old CSV files
    for f in os.listdir("."):
        if f.endswith(".csv") and os.path.isfile(f):
            try:
                os.remove(f)
            except:
                pass
    
    time.sleep(1)
    print("   ✅ Cleanup done")

def apply_netem_working(loss=0, delay=0, jitter=0):
    """Apply netem to enp0s3 - this WILL work!"""
    interface = "enp0s3"
    
    print(f"📡 Applying netem to {interface}")
    
    # Clean FIRST
    cleanup_cmds = [
        f"sudo tc qdisc del dev {interface} root 2>/dev/null",
        f"sudo tc qdisc del dev {interface} ingress 2>/dev/null",
        f"sudo iptables -F 2>/dev/null",
        f"sudo iptables -t mangle -F 2>/dev/null"
    ]
    
    for cmd in cleanup_cmds:
        subprocess.run(cmd, shell=True, 
                      stdout=subprocess.DEVNULL, 
                      stderr=subprocess.DEVNULL)
    
    time.sleep(1)
    
    # Apply delay (MOST IMPORTANT FOR YOUR TEST)
    if delay > 0:
        # EXACT command from PDF Appendix A
        if jitter > 0:
            cmd = f"sudo tc qdisc add dev {interface} root netem delay {delay}ms {jitter}ms"
            print(f"Running: {cmd}  (PDF Example: delay 100ms 10ms)")
        else:
            cmd = f"sudo tc qdisc add dev {interface} root netem delay {delay}ms"
            print(f"Running: {cmd}")
        
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"✅ SUCCESS! Applied {delay}ms delay to {interface}")
            
            # Verify
            check = subprocess.run(f"sudo tc qdisc show dev {interface}", 
                                 shell=True, capture_output=True, text=True)
            print(f"Verification: {check.stdout.strip()}")
            
            # Quick test to confirm it's working
            test_delay_applied(interface, delay)
            return True
        else:
            print(f"❌ Failed: {result.stderr}")
            return False
    
    # Apply loss if needed
    if loss > 0:
        cmd = f"sudo tc qdisc add dev {interface} root netem loss {loss}%"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"✅ Applied {loss}% loss")
            return True
    
    return True


def test_delay_applied(interface, expected_delay_ms):
    """Quick test to verify delay is applied"""
    print(f"\n🔍 Testing if {expected_delay_ms}ms delay is working...")
    
    try:
        import socket
        import threading
        
        # Create a simple echo server
        def echo_server():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(('127.0.0.1', 9999))
            sock.settimeout(2.0)
            try:
                data, addr = sock.recvfrom(1024)
                sock.sendto(b"echo", addr)
            except:
                pass
        
        # Start echo server
        server_thread = threading.Thread(target=echo_server, daemon=True)
        server_thread.start()
        time.sleep(0.5)
        
        # Send and measure RTT
        client_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client_sock.settimeout(2.0)
        
        start = time.time()
        client_sock.sendto(b"test", ('127.0.0.1', 9999))
        
        try:
            data, addr = client_sock.recvfrom(1024)
            rtt_ms = (time.time() - start) * 1000
            
            # With netem delay, RTT should be ~2x the one-way delay
            expected_rtt = expected_delay_ms * 2
            
            print(f"   Measured RTT: {rtt_ms:.1f}ms")
            print(f"   Expected RTT with {expected_delay_ms}ms delay: ~{expected_rtt}ms")
            
            if rtt_ms > expected_rtt * 0.7:  # At least 70% of expected
                print(f"   ✅ Netem delay is WORKING correctly!")
            else:
                print(f"   ⚠️  Delay may not be fully applied")
                
        except socket.timeout:
            print(f"   ⚠️  Timeout - check if echo server received packet")
            
    except Exception as e:
        print(f"   ⚠️  Test error: {e}")


def simple_cleanup():
    """Cleanup for enp0s3"""
    print("\n🧹 Cleaning up enp0s3...")
    
    # Clean tc rules
    try:
        subprocess.run(['sudo', 'tc', 'qdisc', 'del', 'dev', 'enp0s3', 'root'], 
                      stdout=subprocess.DEVNULL, 
                      stderr=subprocess.DEVNULL,
                      timeout=2)
        print("   Cleaned tc rules from enp0s3")
    except:
        pass
    
    # Clean iptables rules
    try:
        subprocess.run(['sudo', 'iptables', '-F'], 
                      stdout=subprocess.DEVNULL, 
                      stderr=subprocess.DEVNULL,
                      timeout=2)
        subprocess.run(['sudo', 'iptables', '-t', 'mangle', '-F'],
                      stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL,
                      timeout=2)
        print("   Cleaned iptables rules")
    except:
        pass
    
    # Clean old CSV files
    for f in os.listdir("."):
        if f.endswith(".csv") and os.path.isfile(f):
            try:
                os.remove(f)
            except:
                pass
    
    time.sleep(1)
    print("   ✅ Cleanup done")

def run_scenario(name, loss, delay, jitter):
    """Run a single test scenario - FIXED"""
    print(f"\n{'='*60}")
    print(f"STARTING: {name}")
    print(f"Loss: {loss}%, Delay: {delay}ms")
    print(f"{'='*60}")
    
    # Simple cleanup - BUT keep existing CSV files for now
    print("\n🧹 Cleaning up...")
    try:
        subprocess.run(['sudo', 'tc', 'qdisc', 'del', 'dev', 'enp0s3', 'root'], 
                      stdout=subprocess.DEVNULL, 
                      stderr=subprocess.DEVNULL,
                      timeout=2)
        subprocess.run(['sudo', 'iptables', '-F'],
                      stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL,
                      timeout=2)
    except:
        pass
    
    # Create results directory FIRST
    timestamp = int(time.time())
    log_dir = f"results/{name}_{timestamp}"
    os.makedirs(log_dir, exist_ok=True)
    print(f"📁 Results will be saved to: {log_dir}")
    
    # Apply network configuration
    apply_netem_working(loss, delay, jitter)
    
    # Clean any OLD CSV files in current directory
    print("🧹 Cleaning old CSV files...")
    for f in os.listdir("."):
        if f.endswith(".csv") and os.path.isfile(f):
            try:
                os.remove(f)
                print(f"   Removed: {f}")
            except:
                pass
    
    time.sleep(2)  # Give time for cleanup
    
    # Start Server
    print(f"\n[1/3] Starting Server...")
    server_proc = subprocess.Popen([PYTHON_CMD, SERVER_SCRIPT],
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
    time.sleep(5)  # Increased to 5 seconds for server to fully start
    
    # Start 4 Clients
    print(f"[2/3] Starting 4 Clients...")
    clients = []
    for i in range(4):
        client_proc = subprocess.Popen([PYTHON_CMD, CLIENT_SCRIPT, "127.0.0.1", "--headless"],
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE)
        clients.append(client_proc)
        time.sleep(1)  # Increased to 1 second between clients
        print(f"   Client {i+1} started (PID: {client_proc.pid})")
    
    # Run test
    print(f"\n[3/3] Running for {DURATION} seconds...")
    start_time = time.time()
    
    try:
        while time.time() - start_time < DURATION:
            elapsed = int(time.time() - start_time)
            remaining = DURATION - elapsed
            print(f"\r⏱️  {elapsed:3d}s / {DURATION}s", end='', flush=True)
            
            # Check if CSV files are being created
            if elapsed % 10 == 0:  # Every 10 seconds
                csv_files = [f for f in os.listdir(".") if f.startswith("client_log_") and f.endswith(".csv")]
                if csv_files:
                    print(f"\n   Found {len(csv_files)} client log(s)")
            
            time.sleep(0.5)
        print("\n   ✅ Test complete")
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted")
    
    # Let processes flush their logs
    print("\n🔄 Letting processes flush logs...")
    time.sleep(3)
    
    # Cleanup - Stop processes GRACEFULLY
    print(f"\n🧹 Stopping processes...")
    
    # First, check what CSV files exist
    print("📊 Checking for log files...")
    all_files = os.listdir(".")
    csv_files = [f for f in all_files if f.endswith(".csv")]
    print(f"   Found {len(csv_files)} CSV files: {csv_files}")
    
    # Stop clients
    for i, client in enumerate(clients):
        try:
            print(f"   Stopping client {i+1}...")
            client.terminate()
            client.wait(timeout=2)
        except:
            try:
                client.kill()
            except:
                pass
    
    # Stop server
    try:
        print("   Stopping server...")
        server_proc.terminate()
        server_proc.wait(timeout=2)
    except:
        try:
            server_proc.kill()
        except:
            pass
    
    time.sleep(3)  # Extra time for file writing
    
    # Collect CSV files - FIXED VERSION
    print(f"\n📂 Collecting results...")
    files_moved = 0
    
    for f in os.listdir("."):
        if f.endswith(".csv"):
            try:
                src = f
                dst = os.path.join(log_dir, f)
                
                # Check file size
                file_size = os.path.getsize(src)
                if file_size > 100:  # At least 100 bytes
                    shutil.move(src, dst)
                    files_moved += 1
                    print(f"   📄 {f} ({file_size} bytes)")
                else:
                    print(f"   ⚠️  Skipping {f} (too small: {file_size} bytes)")
                    # Still move it for debugging
                    shutil.move(src, dst)
                    
            except Exception as e:
                print(f"   ❌ Error moving {f}: {e}")
    
    # Also copy the test configuration
    try:
        config_content = f"Test: {name}\nLoss: {loss}%\nDelay: {delay}ms\nJitter: {jitter}ms\nDuration: {DURATION}s\nTimestamp: {timestamp}"
        with open(os.path.join(log_dir, "test_config.txt"), "w") as f:
            f.write(config_content)
        print(f"   📝 test_config.txt")
        files_moved += 1
    except:
        pass
    
    print(f"\n✅ {name} completed!")
    print(f"   Files saved to: {log_dir}")
    print(f"   Total files: {files_moved}")
    
    # Verify logs exist
    verify_logs_exist(log_dir)
    
    return log_dir


def verify_logs_exist(log_dir):
    """Verify that log files were created"""
    print("\n🔍 Verifying logs...")
    
    if not os.path.exists(log_dir):
        print(f"   ❌ Directory doesn't exist: {log_dir}")
        return
    
    files = os.listdir(log_dir)
    if not files:
        print(f"   ❌ No files in {log_dir}")
        return
    
    print(f"   Found {len(files)} files:")
    for f in files:
        filepath = os.path.join(log_dir, f)
        size = os.path.getsize(filepath)
        print(f"      {f}: {size} bytes")
        
        # Check if file has content
        if size < 100 and f.endswith(".csv"):
            print(f"      ⚠️  WARNING: {f} is very small")
            # Show first few lines for debugging
            try:
                with open(filepath, 'r') as fp:
                    lines = fp.readlines()
                    print(f"      First 3 lines: {lines[:3]}")
            except:
                pass

def main():
    """Main function"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=["all", "baseline", "loss2", "loss5", "delay100"], 
                       default="all")
    parser.add_argument("--duration", type=int, default=40)
    args = parser.parse_args()
    
    global DURATION
    DURATION = args.duration
    
    print("\n" + "="*60)
    print("GRID CLASH TESTS - SIMPLIFIED")
    print("="*60)
    print(f"Duration: {DURATION}s per test")
    print("Using software network simulation")
    
    scenarios = {
        "baseline": ("Baseline", 0, 0, 0),
        "loss2": ("Loss_2_Percent", 2, 0, 0),
        "loss5": ("Loss_5_Percent", 5, 0, 0),
        "delay100": ("Delay_100ms", 0, 100, 10)
    }
    
    results = []
    
    os.makedirs("results", exist_ok=True)
    
    if args.scenario == "all":
        for key, params in scenarios.items():
            print(f"\n📋 Running: {params[0]}")
            result = run_scenario(*params)
            if result:
                results.append(result)
            
            if key != "delay100":
                print(f"\n⏳ Waiting 5 seconds...")
                time.sleep(5)
    else:
        if args.scenario in scenarios:
            run_scenario(*scenarios[args.scenario])
        else:
            print(f"❌ Unknown scenario: {args.scenario}")
    
    print("\n" + "="*60)
    print("✅ ALL TESTS COMPLETE!")
    print("="*60)
    
    if results:
        print(f"\nRun analysis: python analyze_result.py")
        print(f"Check results in: results/")
    
    print("\n" + "="*60)

if __name__ == "__main__":
    main()