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
    
    # Clean old CSV files
    for f in os.listdir("."):
        if f.endswith(".csv") and os.path.isfile(f):
            try:
                os.remove(f)
            except:
                pass
    
    time.sleep(1)
    print("   ✅ Cleanup done")

def apply_netem_working(interface, loss=0, delay=0, jitter=0):
    """Netem that actually works"""
    # ALWAYS use these exact commands that work:
    
    if loss > 0:
        # Use iptables for loss (REAL network layer)
        prob = loss / 100.0
        cmd = f"sudo iptables -A INPUT -p udp --dport 5555 -m statistic --mode random --probability {prob} -j DROP"
        subprocess.run(cmd, shell=True)
        print(f"✅ REAL packet loss: {loss}% via iptables")
    
    if delay > 0:
        # Use tc for delay (REAL network layer)
        cmd = f"sudo tc qdisc add dev {interface} root netem delay {delay}ms"
        result = subprocess.run(cmd, shell=True, capture_output=True)
        if result.returncode == 0:
            print(f"✅ REAL delay: {delay}ms via tc")
        else:
            print(f"❌ tc failed: {result.stderr}")
            # Fallback: socket options for delay
            os.environ['SOCKET_DELAY'] = str(delay)
            print(f"⚠️  Using socket-level delay simulation")
    
    return True

def run_scenario(name, loss, delay, jitter):
    """Run a single test scenario - SIMPLIFIED"""
    print(f"\n{'='*60}")
    print(f"STARTING: {name}")
    print(f"Loss: {loss}%, Delay: {delay}ms")
    print(f"{'='*60}")
    
    # Simple cleanup
    simple_cleanup()
    
    # Create results directory
    timestamp = int(time.time())
    log_dir = f"results/{name}_{timestamp}"
    os.makedirs(log_dir, exist_ok=True)
    
    # Apply network configuration (software simulation)
    apply_netem_working(loss, delay, jitter)
    
    # Start Server
    print(f"\n[1/3] Starting Server...")
    server_proc = subprocess.Popen([PYTHON_CMD, SERVER_SCRIPT],
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
    time.sleep(3)
    
    # Start 4 Clients
    print(f"[2/3] Starting 4 Clients...")
    clients = []
    for i in range(4):
        client_proc = subprocess.Popen([PYTHON_CMD, CLIENT_SCRIPT, "127.0.0.1", "--headless"],
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE)
        clients.append(client_proc)
        time.sleep(0.5)
        print(f"   Client {i+1} started")
    
    # Run test
    print(f"\n[3/3] Running for {DURATION} seconds...")
    start_time = time.time()
    
    try:
        while time.time() - start_time < DURATION:
            elapsed = int(time.time() - start_time)
            remaining = DURATION - elapsed
            print(f"\r⏱️  {elapsed:3d}s / {DURATION}s", end='', flush=True)
            time.sleep(0.5)
        print("\n   ✅ Test complete")
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted")
    
    # Cleanup
    print(f"\n🧹 Stopping processes...")
    
    # Stop clients
    for client in clients:
        try:
            client.terminate()
            client.wait(timeout=1)
        except:
            try:
                client.kill()
            except:
                pass
    
    # Stop server
    try:
        server_proc.terminate()
        server_proc.wait(timeout=1)
    except:
        try:
            server_proc.kill()
        except:
            pass
    
    time.sleep(2)
    
    # Collect CSV files
    print(f"\n📂 Collecting results...")
    files_moved = 0
    
    for f in os.listdir("."):
        if f.endswith(".csv") and os.path.getsize(f) > 100:
            try:
                shutil.move(f, os.path.join(log_dir, f))
                files_moved += 1
                print(f"   📄 {f}")
            except:
                pass
    
    print(f"\n✅ {name} completed!")
    print(f"   Files saved to: {log_dir}")
    print(f"   CSV files: {files_moved}")
    
    return log_dir

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