import subprocess
import time
import os
import signal
import sys
import shutil
import platform

# Configuration
SERVER_SCRIPT = "server_optimized.py"
CLIENT_SCRIPT = "client.py"
PYTHON_CMD = sys.executable
DURATION = 40 # Seconds per test

IS_WINDOWS = platform.system() == "Windows"

def start_process(script, args=[]):
    cmd = [PYTHON_CMD, script] + args
    if not IS_WINDOWS:
        return subprocess.Popen(cmd, preexec_fn=os.setsid)
    return subprocess.Popen(cmd)

def kill_process(proc):
    if IS_WINDOWS:
        subprocess.call(['taskkill', '/F', '/T', '/PID', str(proc.pid)], 
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        try: os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except: pass

def run_scenario(name, loss, delay, jitter):
    print(f"\n========================================")
    print(f"STARTING SCENARIO: {name}")
    print(f"Config: Loss={loss}%, Delay={delay}ms")
    print(f"========================================")
    
    # Unique timestamp folder
    timestamp = int(time.time())
    log_dir = f"results/{name}_{timestamp}"
    os.makedirs(log_dir, exist_ok=True)
    
    # --- WINDOWS ARGUMENT GENERATION ---
    server_args = []
    if loss > 0: 
        server_args.extend(["--loss", str(loss/100.0)])
    
    # FIX: Pass Delay argument to server if present
    if delay > 0:
        server_args.extend(["--delay", str(delay/1000.0)])

    # Client args
    client_args = ["--headless"]
    
    # Start Server
    print(f"Starting Server...")
    server_proc = start_process(SERVER_SCRIPT, server_args) 
    time.sleep(2)
    
    # Start Clients
    clients = []
    print("Starting 4 Clients...")
    for i in range(4):
        clients.append(start_process(CLIENT_SCRIPT, client_args))
        time.sleep(0.5)

    # Run
    print(f"Running for {DURATION} seconds...")
    try: time.sleep(DURATION)
    except KeyboardInterrupt: pass

    # Cleanup
    print("Stopping processes...")
    for c in clients: kill_process(c)
    kill_process(server_proc)
    
    # Move Files
    print("Waiting for file release...")
    time.sleep(3) 
    
    print(f"Archiving logs to {log_dir}")
    files_moved = 0
    for attempt in range(5):
        try:
            for f in os.listdir("."):
                if f.endswith(".csv"):
                    try:
                        shutil.move(f, os.path.join(log_dir, f))
                        files_moved += 1
                    except PermissionError: pass
            if files_moved >= 5: break
            time.sleep(1)
        except Exception: pass
            
    if files_moved > 0: print(f"[OK] Moved {files_moved} logs.")
    else: print("[ERROR] No CSV logs generated.")

def main():
    os.makedirs("results", exist_ok=True)
    if IS_WINDOWS: print("!!! WINDOWS MODE: Using Python-Level Simulation !!!")
    
    run_scenario("Baseline", loss=0, delay=0, jitter=0)
    run_scenario("Loss_2_Percent", loss=2, delay=0, jitter=0)
    run_scenario("Loss_5_Percent", loss=5, delay=0, jitter=0)
    run_scenario("Delay_100ms", loss=0, delay=100, jitter=10)
    
    print("\nALL TESTS COMPLETED.")

if __name__ == "__main__":
    main()