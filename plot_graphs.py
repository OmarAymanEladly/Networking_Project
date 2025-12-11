import matplotlib.pyplot as plt
import pandas as pd
import os
import glob
import numpy as np

def get_metrics(folder_path):
    server_file = os.path.join(folder_path, "server_log.csv")
    client_files = glob.glob(os.path.join(folder_path, "client_log_*.csv"))
    
    if not os.path.exists(server_file) or not client_files: return None, None

    try:
        df_server = pd.read_csv(server_file)
        for c_file in client_files:
            df_client = pd.read_csv(c_file)
            if df_client.empty: continue
            
            # Find Player 1
            if 'player_1' in df_client['client_id'].astype(str).values:
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
                
                return error.mean(), df_client['latency_ms'].mean()
    except: pass
    return None, None

def main():
    # Define the folders based on your most recent run timestamps
    # The script looks for the LAST folder matching these names
    base_names = ["Baseline", "Loss_2_Percent", "Loss_5_Percent"]
    
    errors = []
    latencies = []
    labels = ["Baseline (0%)", "Loss (2%)", "Loss (5%)"]

    for name in base_names:
        # Find all folders matching this name
        candidates = [f.path for f in os.scandir("results") if f.is_dir() and name in f.name]
        candidates.sort() # Get the newest one
        
        if candidates:
            err, lat = get_metrics(candidates[-1])
            if err is not None:
                errors.append(err)
                latencies.append(lat)
            else:
                errors.append(0)
                latencies.append(0)

    # Plot 1: Position Error
    plt.figure(figsize=(8, 5))
    bars = plt.bar(labels, errors, color=['green', 'orange', 'red'])
    plt.axhline(y=0.5, color='black', linestyle='--', label='Max Allowed (0.5)')
    plt.title('Perceived Position Error vs Packet Loss')
    plt.ylabel('Mean Error (Grid Units)')
    plt.legend()
    
    # Add numbers on bars
    for bar in bars:
        height = bar.get_height()
        plt.text(bar.get_x() + bar.get_width()/2., height, f'{height:.4f}', ha='center', va='bottom')
        
    plt.savefig('graph_position_error.png')
    print("Generated graph_position_error.png")

    # Plot 2: Latency
    plt.figure(figsize=(8, 5))
    plt.plot(labels, latencies, marker='o', linewidth=2)
    plt.title('Average Latency vs Packet Loss')
    plt.ylabel('Latency (ms)')
    plt.grid(True)
    plt.savefig('graph_latency.png')
    print("Generated graph_latency.png")

if __name__ == "__main__":
    try:
        main()
    except ImportError:
        print("Please install matplotlib: pip install matplotlib")