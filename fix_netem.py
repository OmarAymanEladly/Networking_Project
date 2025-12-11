# fix_netem.py
import subprocess
import time
import os
import sys

def fix_netem():
    print("🔧 COMPLETELY RESETTING NETEM FOR TESTS")
    print("="*60)
    
    # 1. Kill everything that might interfere
    print("1. Killing all interfering processes...")
    processes = ['python', 'server_optimized', 'client', 'tcpdump']
    for proc in processes:
        subprocess.run(['sudo', 'pkill', '-9', proc], 
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    
    # 2. Remove ALL tc configurations from ALL interfaces
    print("\n2. Removing ALL tc/qdisc configurations...")
    
    # Get all interfaces
    result = subprocess.run(['ip', 'link', 'show'], capture_output=True, text=True)
    interfaces = []
    for line in result.stdout.split('\n'):
        if ':' in line and not 'lo:' in line:
            parts = line.split(':')
            if len(parts) > 1 and parts[1].strip():
                iface = parts[1].strip()
                if not iface.startswith(' '):
                    interfaces.append(iface)
    
    interfaces = ['lo'] + interfaces[:3]  # lo + first 3 other interfaces
    
    for iface in interfaces:
        print(f"   Cleaning {iface}...")
        
        # Multiple removal attempts
        commands = [
            f'sudo tc qdisc del dev {iface} root 2>/dev/null || true',
            f'sudo tc qdisc del dev {iface} ingress 2>/dev/null || true',
            f'sudo tc -force qdisc del dev {iface} 2>/dev/null || true',
        ]
        
        for cmd in commands:
            subprocess.run(cmd, shell=True, timeout=5)
    
    time.sleep(3)
    
    # 3. Add a clean simple qdisc
    print("\n3. Setting up clean baseline...")
    subprocess.run(['sudo', 'tc', 'qdisc', 'add', 'dev', 'lo', 'root', 'pfifo_fast'],
                  capture_output=True, timeout=5)
    time.sleep(2)
    
    # 4. Verify
    print("\n4. Verifying clean state...")
    result = subprocess.run(['sudo', 'tc', 'qdisc', 'show', 'dev', 'lo'],
                          capture_output=True, text=True)
    print(f"   lo interface: {result.stdout.strip()}")
    
    print("\n" + "="*60)
    print("✅ NETEM IS READY FOR TESTING!")
    print("="*60)
    print("\nNow run: sudo python3 run_tests.py --scenario baseline")

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("❌ ERROR: Must run as root!")
        print("Run: sudo python3 fix_netem.py")
        sys.exit(1)
    
    fix_netem()