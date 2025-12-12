import subprocess
import time
import os
import signal
import sys
import shutil
import platform
import argparse
import threading
import netifaces  # You'll need to install: pip install netifaces

# Configuration
SERVER_SCRIPT = "server_optimized.py"
CLIENT_SCRIPT = "client.py"
PYTHON_CMD = sys.executable
DURATION = 40

IS_LINUX = platform.system() == "Linux"

# Global for tshark process
tshark_process = None

def get_interface_ip(interface="enp0s3"):
    """Get the IP address of the specified interface"""
    try:
        # First try using netifaces
        import netifaces
        return netifaces.ifaddresses(interface)[netifaces.AF_INET][0]['addr']
    except:
        try:
            # Fallback method using ip command
            result = subprocess.run(['ip', 'addr', 'show', interface], 
                                  capture_output=True, text=True)
            for line in result.stdout.split('\n'):
                if 'inet ' in line and '127.0.0.1' not in line:
                    return line.strip().split()[1].split('/')[0]
        except:
            pass
        return None

def simple_cleanup():
    """Simple cleanup that won't kill our own process"""
    print("\n🧹 Simple cleanup...")
    
    # Clean netem on enp0s3 (CORRECT INTERFACE)
    try:
        subprocess.run(['sudo', 'tc', 'qdisc', 'del', 'dev', 'enp0s3', 'root'], 
                      stdout=subprocess.DEVNULL, 
                      stderr=subprocess.DEVNULL,
                      timeout=2)
        print("   Cleaned netem rules from enp0s3")
    except:
        pass
    
    # Also clean loopback just in case
    try:
        subprocess.run(['sudo', 'tc', 'qdisc', 'del', 'dev', 'lo', 'root'], 
                      stdout=subprocess.DEVNULL, 
                      stderr=subprocess.DEVNULL,
                      timeout=2)
        print("   Cleaned netem rules from lo")
    except:
        pass
    
    # Clean iptables rules
    try:
        subprocess.run(['sudo', 'iptables', '-F'],  # Flush all iptables rules
                      stdout=subprocess.DEVNULL, 
                      stderr=subprocess.DEVNULL,
                      timeout=2)
        subprocess.run(['sudo', 'iptables', '-t', 'nat', '-F'],  # Flush NAT rules
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
    """Start tshark capture in background on enp0s3"""
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
        time.sleep(3)  # Give tshark time to start
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

def analyze_capture(pcap_file, log_dir):
    """Analyze pcap file and extract metrics - FIXED VERSION"""
    if not os.path.exists(pcap_file):
        print(f"   ❌ PCAP file not found: {pcap_file}")
        return
    
    print(f"\n📊 Analyzing capture: {os.path.basename(pcap_file)}")
    print(f"   File size: {os.path.getsize(pcap_file)} bytes")
    
    # First, check what's in the pcap file
    try:
        # Count UDP packets on port 5555
        count_cmd = ["tshark", "-r", pcap_file, "-Y", "udp.port == 5555", "-T", "fields", "-e", "frame.number"]
        result = subprocess.run(count_cmd, capture_output=True, text=True, timeout=10)
        packets = [line for line in result.stdout.split('\n') if line.strip()]
        print(f"   UDP packets on port 5555: {len(packets)}")
        
        if len(packets) == 0:
            print(f"   ⚠️  NO UDP packets on port 5555 found!")
            print(f"   Checking all UDP packets...")
            all_udp_cmd = ["tshark", "-r", pcap_file, "-Y", "udp", "-T", "fields", "-e", "udp.srcport", "-e", "udp.dstport"]
            result = subprocess.run(all_udp_cmd, capture_output=True, text=True, timeout=10)
            udp_packets = [line for line in result.stdout.split('\n') if line.strip()]
            print(f"   All UDP packets in capture: {len(udp_packets)}")
            if udp_packets:
                print(f"   First 5 UDP ports:")
                for line in udp_packets[:5]:
                    print(f"     {line}")
            return
        
    except Exception as e:
        print(f"   ❌ Error analyzing pcap: {e}")
        return
    
    # Now extract packet timing info
    try:
        csv_file = os.path.join(log_dir, "packet_timing.csv")
        print(f"\n   Extracting packet timing to: {csv_file}")
        
        # FIXED: Use proper field names and include client-server IPs
        analysis_cmd = [
            "tshark",
            "-r", pcap_file,
            "-T", "fields",
            "-E", "separator=,",
            "-E", "header=y",
            "-e", "frame.number",
            "-e", "frame.time_epoch",
            "-e", "ip.src",
            "-e", "ip.dst",
            "-e", "udp.srcport",
            "-e", "udp.dstport",
            "-e", "udp.length",
            "-e", "frame.time_delta",
            "-Y", "udp.port == 5555"
        ]
        
        print(f"   Running: {' '.join(analysis_cmd)}")
        
        with open(csv_file, 'w') as f:
            result = subprocess.run(analysis_cmd, stdout=f, stderr=subprocess.PIPE, text=True, timeout=30)
        
        if result.returncode != 0:
            print(f"   ❌ tshark error: {result.stderr[:200]}")
        
        # Check the output
        if os.path.exists(csv_file):
            with open(csv_file, 'r') as f:
                lines = f.readlines()
            
            if len(lines) > 1:
                print(f"   ✅ Packet timing CSV created with {len(lines)-1} packets")
                print(f"   Sample (first 2 lines):")
                for i in range(min(3, len(lines))):
                    print(f"     {lines[i].strip()}")
                
                # Also create a summary CSV
                summary_file = os.path.join(log_dir, "packet_summary.csv")
                summary_cmd = [
                    "tshark",
                    "-r", pcap_file,
                    "-z", "io,stat,1",
                    "-q",
                    "-Y", "udp.port == 5555"
                ]
                
                with open(summary_file, 'w') as f:
                    subprocess.run(summary_cmd, stdout=f, stderr=subprocess.PIPE, text=True, timeout=10)
                
                print(f"   ✅ Packet summary saved to: {summary_file}")
            else:
                print(f"   ⚠️  CSV file created but only contains headers")
                print(f"   File content: {lines}")
        else:
            print(f"   ❌ CSV file was not created")
            
    except Exception as e:
        print(f"   ❌ Error creating timing CSV: {e}")
        import traceback
        traceback.print_exc()
    
    # Move pcap to results directory
    try:
        dest_pcap = os.path.join(log_dir, os.path.basename(pcap_file))
        shutil.move(pcap_file, dest_pcap)
        print(f"   ✅ PCAP moved to: {dest_pcap}")
    except Exception as e:
        print(f"   ❌ Error moving PCAP: {e}")

def apply_netem_working(loss=0, delay=0, jitter=0):
    """Apply netem to enp0s3 - ALL TESTS USE enp0s3"""
    interface = "enp0s3"
    
    print(f"📡 Applying netem to {interface}")
    
    # Clean FIRST
    try:
        subprocess.run(f"sudo tc qdisc del dev {interface} root", 
                      shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except:
        pass
    
    time.sleep(1)
    
    if loss > 0:
        # Use iptables for loss (REAL network layer)
        prob = loss / 100.0
        # Apply loss to BOTH directions for UDP traffic on port 5555
        cmd1 = f"sudo iptables -A INPUT -p udp --dport 5555 -m statistic --mode random --probability {prob} -j DROP"
        cmd2 = f"sudo iptables -A OUTPUT -p udp --sport 5555 -m statistic --mode random --probability {prob} -j DROP"
        subprocess.run(cmd1, shell=True)
        subprocess.run(cmd2, shell=True)
        print(f"✅ Applied {loss}% packet loss via iptables (both directions)")
    
    if delay > 0:
        # Use tc for delay (REAL network layer) on enp0s3
        if jitter > 0:
            cmd = f"sudo tc qdisc add dev {interface} root netem delay {delay}ms {jitter}ms"
        else:
            cmd = f"sudo tc qdisc add dev {interface} root netem delay {delay}ms"
        
        print(f"Running: {cmd}")
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"✅ REAL delay: {delay}ms via tc on {interface}")
            
            # Verify
            check_cmd = f"sudo tc qdisc show dev {interface}"
            check_result = subprocess.run(check_cmd, shell=True, capture_output=True, text=True)
            print(f"   Verification: {check_result.stdout.strip()}")
        else:
            print(f"❌ tc failed: {result.stderr}")
            # Fallback: socket options for delay
            os.environ['SOCKET_DELAY'] = str(delay)
            print(f"⚠️  Using socket-level delay simulation")
    
    return True

def run_scenario(name, loss, delay, jitter):
    """Run a single test scenario - ALL TESTS USE enp0s3"""
    print(f"\n{'='*60}")
    print(f"STARTING: {name}")
    print(f"Loss: {loss}%, Delay: {delay}ms, Jitter: {jitter}ms")
    print(f"{'='*60}")
    
    # Get the actual IP address of enp0s3
    interface_ip = get_interface_ip("enp0s3")
    if not interface_ip:
        print(f"❌ Could not get IP address for enp0s3 interface!")
        print(f"   Using 127.0.0.1 as fallback (traffic may not be captured on enp0s3)")
        interface_ip = "127.0.0.1"
    else:
        print(f"📡 Using interface enp0s3 IP: {interface_ip}")
    
    # Simple cleanup
    simple_cleanup()
    
    # Create results directory
    timestamp = int(time.time())
    log_dir = f"results/{name}_{timestamp}"
    os.makedirs(log_dir, exist_ok=True)
    
    # Apply network configuration to enp0s3
    apply_netem_working(loss, delay, jitter)
    
    # START WIRESHARK CAPTURE ON enp0s3
    pcap_file = start_wireshark_capture(name, interface="enp0s3")
    
    # Start Server - bind to the interface IP
    print(f"\n[1/3] Starting Server on {interface_ip}:5555...")
    server_proc = subprocess.Popen(
        [PYTHON_CMD, SERVER_SCRIPT, "--bind", interface_ip],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    time.sleep(3)
    
    # Debug: Check if server is running
    try:
        check_cmd = ["pgrep", "-f", "server_optimized.py"]
        result = subprocess.run(check_cmd, capture_output=True, text=True)
        if result.stdout.strip():
            print(f"   ✅ Server is running (PID: {result.stdout.strip()})")
        else:
            print(f"   ⚠️  Server may not be running")
    except:
        pass
    
    # Start 4 Clients - connect to the interface IP (NOT 127.0.0.1)
    print(f"[2/3] Starting 4 Clients connecting to {interface_ip}:5555...")
    clients = []
    for i in range(4):
        client_proc = subprocess.Popen(
            [PYTHON_CMD, CLIENT_SCRIPT, interface_ip, "--headless"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        clients.append(client_proc)
        time.sleep(0.5)
        print(f"   Client {i+1} started (PID: {client_proc.pid})")
    
    # Verify traffic is being sent on enp0s3
    print(f"\n[DEBUG] Checking for UDP traffic on enp0s3...")
    try:
        # Run tcpdump briefly to verify packets
        check_cmd = ["sudo", "timeout", "5", "tcpdump", "-i", "enp0s3", "-c", "10", "udp port 5555"]
        result = subprocess.run(check_cmd, capture_output=True, text=True)
        if result.returncode == 0:
            if "packets captured" in result.stderr:
                packets_line = result.stderr.split('\n')[0]
                packets = int(packets_line.split()[0])
                print(f"   ✅ Captured {packets} UDP packets on enp0s3 port 5555")
                if packets > 0:
                    print(f"   Sample packets:")
                    for line in result.stdout.split('\n')[:3]:
                        if line.strip():
                            print(f"     {line}")
            else:
                print(f"   ❌ No packets captured on enp0s3")
        else:
            print(f"   ⚠️  tcpdump exited with code {result.returncode}")
    except Exception as e:
        print(f"   ❌ tcpdump failed: {e}")
    
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
        if f.endswith(".csv") and os.path.isfile(f):
            try:
                shutil.move(f, os.path.join(log_dir, f))
                files_moved += 1
                print(f"   📄 {f}")
            except:
                pass
    
    # Also copy the test configuration
    try:
        config_content = f"Test: {name}\nLoss: {loss}%\nDelay: {delay}ms\nJitter: {jitter}ms\nDuration: {DURATION}s\nTimestamp: {timestamp}\nInterface: enp0s3\nInterface IP: {interface_ip}"
        with open(os.path.join(log_dir, "test_config.txt"), "w") as f:
            f.write(config_content)
        print(f"   📝 test_config.txt")
        files_moved += 1
    except:
        pass
    
    print(f"\n✅ {name} completed!")
    print(f"   Files saved to: {log_dir}")
    print(f"   Total files: {files_moved}")
    
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
    print("GRID CLASH TESTS - ALL ON enp0s3 WITH WIRESHARK")
    print("="*60)
    print(f"Duration: {DURATION}s per test")
    print("Network interface: enp0s3")
    print("Wireshark capture enabled on enp0s3 interface")
    
    # Install netifaces if not available
    try:
        import netifaces
    except ImportError:
        print("\n⚠️  netifaces module not found. Installing...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "netifaces"])
            import netifaces
            print("✅ netifaces installed successfully")
        except:
            print("❌ Failed to install netifaces. Using fallback method.")
    
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
    
    scenarios = {
        "baseline": ("Baseline", 0, 0, 0),
        "loss2": ("Loss_2_Percent", 2, 0, 0),
        "loss5": ("Loss_5_Percent", 5, 0, 0),
        "delay100": ("Delay_100ms", 0, 100, 10)
    }
    
    results = []
    
    os.makedirs("results", exist_ok=True)
    os.makedirs("captures", exist_ok=True)
    
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
        print(f"Check PCAP files in: captures/")
        print(f"\nSummary of all tests run:")
        for result in results:
            print(f"  - {os.path.basename(result)}")
    
    print("\n" + "="*60)

if __name__ == "__main__":
    main()