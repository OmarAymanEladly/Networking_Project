# test_simple.py
#!/usr/bin/env python
"""
Simple test to verify server and client can start
"""

import subprocess
import time
import sys
from pathlib import Path

def test_basic():
    print("🧪 Basic Grid Clash Test")
    print("=" * 50)
    
    # Check if scripts exist
    server_script = Path("server_optimized.py")
    client_script = Path("client.py")
    
    if not server_script.exists():
        print(f"❌ {server_script} not found!")
        return False
    
    if not client_script.exists():
        print(f"❌ {client_script} not found!")
        return False
    
    print(f"✅ Found server script: {server_script}")
    print(f"✅ Found client script: {client_script}")
    
    # Try to start server
    print("\n🚀 Testing server startup...")
    server_proc = subprocess.Popen(
        [sys.executable, str(server_script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    
    # Wait a bit and check
    time.sleep(3)
    
    if server_proc.poll() is None:
        print("✅ Server is running")
        
        # Try to start a quick client
        print("\n🎮 Testing client connection...")
        client_proc = subprocess.Popen(
            [sys.executable, str(client_script), "127.0.0.1", "--headless"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        # Let client run for 2 seconds
        time.sleep(2)
        
        if client_proc.poll() is None:
            print("✅ Client is running")
        else:
            print("⚠️  Client terminated")
        
        # Cleanup
        print("\n🧹 Cleaning up...")
        client_proc.terminate()
        server_proc.terminate()
        
        client_proc.wait(timeout=2)
        server_proc.wait(timeout=2)
        
    else:
        print("❌ Server terminated")
        # Read output
        output, _ = server_proc.communicate()
        print(f"Server output:\n{output}")
        return False
    
    print("\n✅ Basic test passed!")
    return True

if __name__ == "__main__":
    if test_basic():
        print("\n🎉 Ready to run full tests!")
        print("Run: python run_tests.py")
    else:
        print("\n❌ Basic test failed. Check your scripts.")