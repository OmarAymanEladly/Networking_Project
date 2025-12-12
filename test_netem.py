#!/usr/bin/env python3
import subprocess
import sys

def test_netem():
    print("Testing netem installation...")
    
    # Test 1: tc exists
    result = subprocess.run(['which', 'tc'], capture_output=True, text=True)
    if result.returncode != 0:
        print("❌ 'tc' command not found")
        return False
    print(f"✅ tc found at: {result.stdout.strip()}")
    
    # Test 2: Check version
    result = subprocess.run(['tc', '-Version'], capture_output=True, text=True)
    print(f"✅ tc version: {result.stdout[:50]}...")
    
    # Test 3: Try actual netem command
    print("\nTrying actual netem command...")
    cmds = [
        ['sudo', 'tc', 'qdisc', 'add', 'dev', 'lo', 'root', 'netem', 'delay', '10ms'],
        ['sudo', 'tc', 'qdisc', 'show', 'dev', 'lo'],
        ['sudo', 'tc', 'qdisc', 'del', 'dev', 'lo', 'root']
    ]
    
    for cmd in cmds:
        print(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ Failed: {result.stderr[:100]}")
            return False
        print(f"✅ Success")
    
    print("\n🎉 Netem is fully functional!")
    return True

if __name__ == "__main__":
    if test_netem():
        print("\nNow run: sudo python run_tests.py --scenario baseline")
        sys.exit(0)
    else:
        print("\nFix netem issues first!")
        sys.exit(1)