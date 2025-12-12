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
    
    # Clean netem rules on enp0s3 (VirtualBox interface)
    try:
        subprocess.run(['sudo', 'tc', 'qdisc', 'del', 'dev', 'enp0s3', 'root'], 
                      stdout=subprocess.DEVNULL, 
                      stderr=subprocess.DEVNULL,
                      timeout=2)
        print("   Cleaned netem rules from enp0s3")
    except:
        pass
    
    # Clean iptables rules
    try:
        subprocess.run(['sudo', 'iptables', '-F'],
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

def start_wireshark_capture(test_name, interface="enp0s3"):
    """Start tshark capture in background"""
    global tshark_process
    
    # Create captures directory
    os.makedirs("captures", exist_ok=True)
    
    timestamp = int(time.time())
    pcap_file = f"captures/{test_name}_{timestamp}.pcap"
    
    print(f"\n📡 Starting Wireshark capture on {interface}...")
    print(f"   Saving to: {pcap_file}")
    
    # Build tshark command
    tshark_cmd = [
        "sudo", "tshark",
        "-i", interface,
        "-f", "udp port 5555",  # Capture only our game traffic
        "-w", pcap_file,
        "-q"  # Quiet mode
    ]
    
    try:
        tshark_process = subprocess.Popen(
            tshark_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        print(f"   ✅ Capture started (PID: {tshark_process.pid})")
        time.sleep(2)  # Give tshark time to start
        return pcap_file
    except Exception as e:
        print(f"   ❌ Failed to start capture: {e}")
        return None

def stop_wireshark_capture():
    """Stop tshark capture"""
    global tshark_process
    
    if tshark_process and tshark_process.poll() is None:
        print("\n📡 Stopping Wireshark capture...")
        try:
            # Send SIGINT to gracefully stop tshark
            tshark_process.send_signal(signal.SIGINT)
            tshark_process.wait(timeout=5)
            print("   ✅ Capture stopped")
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

def apply_netem_working(interface="enp0s3", loss=0, delay=0, jitter=0):
    """Netem for VirtualBox interface enp0s3"""
    print(f"\n🌐 Applying network conditions on {interface}:")
    print(f"   Loss: {loss}%, Delay: {delay}ms, Jitter: {jitter}ms")
    
    # Clean any existing rules
    subprocess.run(['sudo', 'tc', 'qdisc', 'del', 'dev', interface, 'root'], 
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    if loss == 0 and delay == 0 and jitter == 0:
        print("   ✅ Baseline (no network impairment)")
        return True
    
    # Build netem command
    netem_cmd = ['sudo', 'tc', 'qdisc', 'add', 'dev', interface, 'root', 'netem']
    
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
            print(f"   ✅ Network conditions applied successfully")
            return True
        else:
            print(f"   ❌ Failed to apply network conditions: {result.stderr}")
            return False
    except Exception as e:
        print(f"   ❌ Error applying network conditions: {e}")
        return False

def run_scenario(name, loss, delay, jitter):
    """Run a single test scenario - SIMPLIFIED"""
    print(f"\n{'='*60}")
    print(f"STARTING: {name}")
    print(f"Loss: {loss}%, Delay: {delay}ms, Jitter: {jitter}ms")
    print(f"{'='*60}")
    
    # Simple cleanup
    simple_cleanup()
    
    # Create results directory
    timestamp = int(time.time())
    log_dir = f"test_results/{name}_{timestamp}"
    os.makedirs(log_dir, exist_ok=True)
    
    # Apply network configuration
    apply_netem_working('enp0s3', loss, delay, jitter)
    
    # START WIRESHARK CAPTURE
    pcap_file = start_wireshark_capture(name, interface="enp0s3")
    
    # Start Server
    print(f"\n[1/3] Starting Server...")
    server_proc = subprocess.Popen([PYTHON_CMD, SERVER_SCRIPT],
                                   stdout=open(f"{log_dir}/server.log", "w"),
                                   stderr=subprocess.STDOUT)
    time.sleep(3)
    
    # Start 4 Clients
    print(f"[2/3] Starting 4 Clients...")
    clients = []
    for i in range(4):
        client_log = f"{log_dir}/client_{i+1}.log"
        client_proc = subprocess.Popen([PYTHON_CMD, CLIENT_SCRIPT, "127.0.0.1", "--headless"],
                                       stdout=open(client_log, "w"),
                                       stderr=subprocess.STDOUT)
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
    
    # STOP WIRESHARK CAPTURE
    stop_wireshark_capture()
    
    # Analyze capture if it was created
    if pcap_file and os.path.exists(pcap_file):
        analyze_capture(pcap_file, log_dir)
    
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

def analyze_capture(pcap_file, log_dir):
    """Analyze pcap file and extract metrics"""
    if not os.path.exists(pcap_file):
        print(f"   ❌ PCAP file not found: {pcap_file}")
        return
    
    print(f"\n📊 Analyzing capture: {os.path.basename(pcap_file)}")
    
    # 1. Count packets
    try:
        count_cmd = ["tshark", "-r", pcap_file, "-Y", "udp.port == 5555", "-z", "io,stat,0"]
        result = subprocess.run(count_cmd, capture_output=True, text=True)
        
        # Extract packet count from output
        for line in result.stdout.split('\n'):
            if "|" in line and "Number" not in line and "Duration" not in line:
                parts = line.split('|')
                if len(parts) > 2:
                    packet_count = parts[2].strip()
                    print(f"   Total packets: {packet_count}")
                    
                    # Save to stats file
                    stats_file = os.path.join(log_dir, "capture_stats.txt")
                    with open(stats_file, 'w') as f:
                        f.write(f"Capture File: {os.path.basename(pcap_file)}\n")
                        f.write(f"Total Packets: {packet_count}\n")
                        f.write(f"Filter: udp port 5555\n")
                        f.write(f"Interface: enp0s3\n")
    except Exception as e:
        print(f"   ❌ Error counting packets: {e}")
    
    # 2. Move pcap to results directory
    try:
        dest_pcap = os.path.join(log_dir, os.path.basename(pcap_file))
        shutil.move(pcap_file, dest_pcap)
        print(f"   ✅ PCAP moved to: {dest_pcap}")
    except Exception as e:
        print(f"   ❌ Error moving PCAP: {e}")

def main():
    """Main function"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=["all", "baseline", "loss_2pct", "loss_5pct", "delay_100ms", "delay_jitter"], 
                       default="all")
    parser.add_argument("--duration", type=int, default=40)
    args = parser.parse_args()
    
    global DURATION
    DURATION = args.duration
    
    print("\n" + "="*60)
    print("GRID CLASH TESTS - WITH WIRESHARK CAPTURE")
    print("="*60)
    print(f"Duration: {DURATION}s per test")
    print(f"Using network interface: enp0s3 (VirtualBox)")
    print("Following PDF test scenarios")
    
    # Check if tshark is available
    try:
        result = subprocess.run(["tshark", "--version"], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ tshark/Wireshark is available")
        else:
            print("⚠️  tshark not found, skipping packet capture")
    except:
        print("⚠️  tshark not found, skipping packet capture")
    
    # Define test scenarios from PDF
    scenarios = {
        "baseline": ("baseline", 0, 0, 0),
        "loss_2pct": ("loss_2pct", 2, 0, 0),
        "loss_5pct": ("loss_5pct", 5, 0, 0),
        "delay_100ms": ("delay_100ms", 0, 100, 0),
        "delay_jitter": ("delay_jitter", 0, 100, 10)
    }
    
    results = []
    
    os.makedirs("test_results", exist_ok=True)
    os.makedirs("captures", exist_ok=True)
    
    if args.scenario == "all":
        for key, params in scenarios.items():
            print(f"\n📋 Running: {params[0]}")
            result = run_scenario(*params)
            if result:
                results.append(result)
            
            # Wait between tests
            if key != "delay_jitter":
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
        print(f"Check results in: test_results/")
        print(f"Check PCAP files in: captures/")
    
    print("\n" + "="*60)

if __name__ == "__main__":
    main()