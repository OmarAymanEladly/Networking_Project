# test_server.py
#!/usr/bin/env python3
"""
Simple script to test if server starts properly
"""

import subprocess
import time
import sys

def test_server():
    print("Testing Grid Clash Server...")
    print("=" * 40)
    
    # Kill any existing server
    try:
        subprocess.run(['pkill', '-f', 'server_optimized.py'], 
                     capture_output=True, stderr=subprocess.DEVNULL)
        time.sleep(1)
    except:
        pass
    
    # Start server
    print("Starting server...")
    server_proc = subprocess.Popen(
        ['python3', 'server_optimized.py'],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True
    )
    
    # Read server output for 5 seconds
    print("Server output (5 seconds):")
    print("-" * 40)
    
    start_time = time.time()
    while time.time() - start_time < 5:
        line = server_proc.stdout.readline()
        if line:
            print(line.strip())
    
    print("-" * 40)
    
    # Check if server is still running
    if server_proc.poll() is None:
        print("✓ Server is running!")
        
        # Try to test with a simple client connection
        print("\nTesting client connection...")
        import socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(2)
            sock.sendto(b"CONNECT", ('127.0.0.1', 5555))
            print("✓ Sent connection request")
        except Exception as e:
            print(f"✗ Connection test failed: {e}")
        
        sock.close()
    else:
        print("✗ Server terminated early")
        print("Exit code:", server_proc.poll())
    
    # Cleanup
    print("\nCleaning up...")
    server_proc.terminate()
    server_proc.wait()
    
    print("Test complete!")

if __name__ == "__main__":
    test_server()