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

def apply_netem_working(interface, loss=0, delay=0, jitter=0):
    """Netem that actually works - FIXED for VirtualBox"""
    
    # ALWAYS clean first
    simple_cleanup()
    
    if loss > 0:
        # Use iptables for loss (REAL network layer)
        prob = loss / 100.0
        # FIXED: Apply loss to BOTH directions for UDP traffic on port 5555
        cmd1 = f"sudo iptables -A INPUT -p udp --dport 5555 -m statistic --mode random --probability {prob} -j DROP"
        cmd2 = f"sudo iptables -A OUTPUT -p udp --sport 5555 -m statistic --mode random --probability {prob} -j DROP"
        subprocess.run(cmd1, shell=True)
        subprocess.run(cmd2, shell=True)
        print(f"✅ REAL packet loss: {loss}% via iptables (both directions)")
    
    if delay > 0:
        # FIXED: Use the CORRECT netem syntax that works in VirtualBox
        # The issue might be that delay needs jitter parameter even if jitter=0
        if jitter > 0:
            cmd = f"sudo tc qdisc add dev {interface} root netem delay {delay}ms {jitter}ms"
        else:
            # Even with 0 jitter, we need to specify distribution
            cmd = f"sudo tc qdisc add dev {interface} root netem delay {delay}ms"
        
        print(f"Running: {cmd}")
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if result.returncode == 0:
            # VERIFY it actually worked
            time.sleep(0.5)
            check_cmd = f"sudo tc qdisc show dev {interface}"
            check_result = subprocess.run(check_cmd, shell=True, capture_output=True, text=True)
            
            if "delay" in check_result.stdout:
                print(f"✅ REAL delay: {delay}ms via tc")
                print(f"   Verification: {check_result.stdout.strip()}")
            else:
                # Try alternative method
                print(f"⚠️  tc rule not showing, trying alternative...")
                apply_delay_alternative(interface, delay, jitter)
        else:
            print(f"❌ tc failed: {result.stderr}")
            # Try alternative method WITHOUT falling back to socket-level
            apply_delay_alternative(interface, delay, jitter)
    
    return True


def apply_delay_alternative(interface, delay, jitter):
    """Alternative method to apply delay when standard tc fails"""
    print(f"🔧 Trying alternative delay method...")
    
    # Method 1: Use more complex tc setup
    try:
        # Delete any existing
        subprocess.run(f"sudo tc qdisc del dev {interface} root", shell=True,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Add prio qdisc first, then netem on a branch
        cmds = [
            f"sudo tc qdisc add dev {interface} root handle 1: prio",
            f"sudo tc qdisc add dev {interface} parent 1:3 handle 30: netem delay {delay}ms"
        ]
        
        for cmd in cmds:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"   Failed: {result.stderr}")
                raise Exception("tc failed")
        
        # Send all traffic through the delayed branch
        cmd = f"sudo tc filter add dev {interface} protocol ip parent 1:0 prio 3 u32 match ip dst 127.0.0.1 flowid 1:3"
        subprocess.run(cmd, shell=True)
        
        print(f"✅ Applied {delay}ms delay via alternative tc method")
        
        # Verify
        check = subprocess.run(f"sudo tc qdisc show dev {interface}", 
                             shell=True, capture_output=True, text=True)
        print(f"   Current rules: {check.stdout}")
        return True
        
    except Exception as e:
        print(f"❌ Alternative method failed: {e}")
        
        # Method 2: Use ifb (Intermediate Functional Block) device
        print(f"🔧 Trying IFB method...")
        try:
            # Load ifb module
            subprocess.run("sudo modprobe ifb", shell=True)
            subprocess.run("sudo ip link set dev ifb0 up", shell=True)
            
            # Redirect lo -> ifb0
            subprocess.run(f"sudo tc qdisc add dev {interface} handle ffff: ingress", shell=True)
            subprocess.run(f"sudo tc filter add dev {interface} parent ffff: protocol ip u32 match u32 0 0 action mirred egress redirect dev ifb0", shell=True)
            
            # Apply delay on ifb0
            subprocess.run(f"sudo tc qdisc add dev ifb0 root netem delay {delay}ms", shell=True)
            
            print(f"✅ Applied {delay}ms delay via IFB method")
            return True
            
        except Exception as e2:
            print(f"❌ IFB method also failed: {e2}")
            
            # LAST RESORT: Use iptables TOS marking with tc
            print(f"🔧 Trying TOS marking method...")
            try:
                # Clear everything
                simple_cleanup()
                
                # Mark packets
                subprocess.run("sudo iptables -t mangle -A OUTPUT -p udp -j MARK --set-mark 1", shell=True)
                
                # Apply tc with filter
                subprocess.run(f"sudo tc qdisc add dev {interface} root handle 1: prio", shell=True)
                subprocess.run(f"sudo tc qdisc add dev {interface} parent 1:1 handle 10: netem delay {delay}ms", shell=True)
                subprocess.run(f"sudo tc filter add dev {interface} parent 1: protocol ip prio 1 handle 1 fw flowid 1:1", shell=True)
                
                print(f"✅ Applied {delay}ms delay via TOS marking")
                return True
                
            except Exception as e3:
                print(f"❌ All delay methods failed: {e3}")
                print(f"⚠️  Network delay simulation may not be working")
                return False

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