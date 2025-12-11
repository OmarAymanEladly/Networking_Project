import pandas as pd
import numpy as np
import glob
import os
import sys

# Helper class to write to both Console and File at the same time
class Logger(object):
    def __init__(self, filename):
        self.terminal = sys.stdout
        self.log = open(filename, "w")
    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
    def flush(self):
        self.terminal.flush()
        self.log.flush()

def analyze_scenario(folder_path):
    print(f"\n========================================")
    print(f"ANALYZING: {os.path.basename(folder_path)}")
    
    server_file = os.path.join(folder_path, "server_log.csv")
    if not os.path.exists(server_file):
        print("  [SKIP] No server_log.csv found.")
        return
    
    try:
        df_server = pd.read_csv(server_file)
    except:
        print("  [ERR] Corrupt server log.")
        return

    client_files = glob.glob(os.path.join(folder_path, "client_log_*.csv"))
    if not client_files:
        print("  [SKIP] No client logs found.")
        return
        
    all_latencies = []
    
    for c_file in client_files:
        try:
            df_client = pd.read_csv(c_file)
            if df_client.empty: continue
            
            # Metric 1: Latency
            all_latencies.extend(df_client['latency_ms'].tolist())
            
            # Metric 2: Position Error
            unique_ids = df_client['client_id'].astype(str).unique()
            
            if "player_1" in unique_ids:
                df_p1 = df_client[df_client['client_id'] == 'player_1'].copy()
                df_p1['ts_sec'] = df_p1['recv_time_ms'] / 1000.0
                
                df_merged = pd.merge_asof(
                    df_p1.sort_values('ts_sec'), 
                    df_server.sort_values('timestamp'), 
                    left_on='ts_sec', right_on='timestamp', 
                    direction='nearest', tolerance=0.1
                )
                
                dx = df_merged['render_x'] - df_merged['player1_pos_x']
                dy = df_merged['render_y'] - df_merged['player1_pos_y']
                error = np.sqrt(dx**2 + dy**2)
                
                print(f"  > PLAYER 1 STATS:")
                print(f"    Avg Latency: {df_client['latency_ms'].mean():.2f} ms")
                print(f"    Pos Error Mean: {error.mean():.4f} (Target < 0.5)")
                print(f"    Pos Error 95th: {error.quantile(0.95):.4f}")
                
        except: pass

    if all_latencies:
        print(f"  > SCENARIO AVG LATENCY: {sum(all_latencies)/len(all_latencies):.2f} ms")

if __name__ == "__main__":
    # Redirect output to file AND console
    sys.stdout = Logger("analysis_report.txt")

    if not os.path.exists("results"):
        print("No results folder.")
        sys.exit(1)
        
    subfolders = [f.path for f in os.scandir("results") if f.is_dir()]
    subfolders.sort()
    
    print(f"Found {len(subfolders)} test runs.")
    for folder in subfolders:
        analyze_scenario(folder)