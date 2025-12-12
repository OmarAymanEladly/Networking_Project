import pandas as pd
import numpy as np
import glob
import os
import sys
import matplotlib.pyplot as plt

class Logger(object):
    def __init__(self, filename):
        self.terminal = sys.stdout
        try:
            self.log = open(filename, "w", encoding='utf-8')
        except:
            self.log = open(filename, "w")
    
    def write(self, message):
        self.terminal.write(message)
        try:
            self.log.write(message)
        except UnicodeEncodeError:
            cleaned = ''.join(c if ord(c) < 128 else '?' for c in message)
            self.log.write(cleaned)
    
    def flush(self):
        self.terminal.flush()
        self.log.flush()

def analyze_scenario(folder_path):
    print(f"\n{'='*60}")
    print(f"ANALYZING: {os.path.basename(folder_path)}")
    print(f"{'='*60}")
    
    # Find server log (new name)
    server_files = glob.glob(os.path.join(folder_path, "server_metrics.csv"))
    if not server_files:
        # Try old name for backward compatibility
        server_files = glob.glob(os.path.join(folder_path, "server_log*.csv"))
    
    if not server_files:
        print("  [SKIP] No server logs found.")
        return None
    
    server_file = server_files[0]
    
    try:
        df_server = pd.read_csv(server_file)
        print(f"  Server log: {os.path.basename(server_file)}")
        print(f"  Server columns: {list(df_server.columns)}")
        print(f"  Server rows: {len(df_server)}")
        
        if not df_server.empty:
            print(f"  Sample server data (first row):")
            for col in df_server.columns[:5]:
                print(f"    {col}: {df_server[col].iloc[0]}")
        
        df_server = df_server.dropna()
        if df_server.empty:
            print("  [ERR] Empty server log after cleaning.")
            return None
            
    except Exception as e:
        print(f"  [ERR] Corrupt server log: {e}")
        return None

    # Find client logs (new name)
    client_files = glob.glob(os.path.join(folder_path, "client_data_*.csv"))
    if not client_files:
        # Try old name for backward compatibility
        client_files = glob.glob(os.path.join(folder_path, "client_log_*.csv"))
    
    if not client_files:
        print("  [SKIP] No client logs found.")
        return None
    
    print(f"  Found {len(client_files)} client logs")
    
    scenario_metrics = {
        'name': os.path.basename(folder_path),
        'latency': {'all': [], 'means': []},
        'position_error': {'all': [], 'means': []},
        'update_rate': [],
        'cpu_usage': [],
        'bandwidth': [],
        'jitter': [],
        'packet_loss': 0
    }
    
    # Read test config if exists
    config_file = os.path.join(folder_path, "test_config.txt")
    if os.path.exists(config_file):
        with open(config_file, 'r') as f:
            print("  Test Configuration:")
            for line in f:
                if line.strip():
                    print(f"    {line.strip()}")
    
    # Find player_1 data
    player_1_data = None
    for c_file in client_files:
        try:
            df_client = pd.read_csv(c_file)
            if df_client.empty: 
                continue
            
            if 'client_id' in df_client.columns:
                unique_ids = df_client['client_id'].unique()
                print(f"  File {os.path.basename(c_file)} has client IDs: {unique_ids}")
                
                if 'player_1' in unique_ids:
                    player_1_data = df_client[df_client['client_id'] == 'player_1'].copy()
                    print(f"  [OK] Found player_1 data in {os.path.basename(c_file)}")
                    print(f"    Player_1 rows: {len(player_1_data)}")
                    break
        except Exception as e:
            print(f"  [WARN] Error reading {os.path.basename(c_file)}: {e}")
            continue
    
    # Process metrics from all clients
    for c_file in client_files:
        try:
            df_client = pd.read_csv(c_file)
            
            # Latency metrics
            if 'latency_ms' in df_client.columns:
                valid_latencies = df_client['latency_ms'][
                    (df_client['latency_ms'] >= 0) & 
                    (df_client['latency_ms'] <= 5000)
                ]
                
                if len(valid_latencies) > 0:
                    scenario_metrics['latency']['all'].extend(valid_latencies.tolist())
                    scenario_metrics['latency']['means'].append(valid_latencies.mean())
                    
                    # Calculate jitter
                    if len(valid_latencies) > 1:
                        jitter = valid_latencies.std()
                        scenario_metrics['jitter'].append(jitter)
            
            # Update rate
            if 'recv_time_ms' in df_client.columns and len(df_client) > 1:
                df_sorted = df_client.sort_values('recv_time_ms')
                time_diffs = df_sorted['recv_time_ms'].diff().dropna()
                if len(time_diffs) > 0:
                    avg_interval_ms = time_diffs.mean()
                    update_rate_hz = 1000.0 / avg_interval_ms if avg_interval_ms > 0 else 0
                    scenario_metrics['update_rate'].append(update_rate_hz)
            
        except Exception as e:
            print(f"  [WARN] Error processing client data: {e}")
            continue
    
    # Position error calculation for player_1
    if player_1_data is not None and not player_1_data.empty and not df_server.empty:
        print(f"\n  Calculating position error for player_1...")
        
        # Prepare client data
        df_p1 = player_1_data.copy()
        
        if 'render_x' not in df_p1.columns or 'render_y' not in df_p1.columns:
            print(f"  [WARN] No render_x/render_y columns in player_1 data")
        else:
            # Find server position columns
            server_x_col = None
            server_y_col = None
            
            if 'player1_pos_x' in df_server.columns and 'player1_pos_y' in df_server.columns:
                server_x_col = 'player1_pos_x'
                server_y_col = 'player1_pos_y'
                print(f"  Found server position columns: {server_x_col}, {server_y_col}")
            
            # Find server timestamp column
            server_time_col = 'timestamp' if 'timestamp' in df_server.columns else None
            if not server_time_col and len(df_server.columns) > 0:
                server_time_col = df_server.columns[0]
            
            if server_x_col and server_y_col and server_time_col:
                # Prepare server data
                df_server_clean = df_server.copy()
                df_server_clean = df_server_clean.rename(columns={
                    server_time_col: 'server_time',
                    server_x_col: 'server_x',
                    server_y_col: 'server_y'
                })
                
                # Ensure numeric
                for col in ['server_time', 'server_x', 'server_y']:
                    df_server_clean[col] = pd.to_numeric(df_server_clean[col], errors='coerce')
                
                df_server_clean = df_server_clean.dropna(subset=['server_time', 'server_x', 'server_y'])
                
                if not df_server_clean.empty:
                    # Convert server epoch time to relative
                    server_start = df_server_clean['server_time'].min()
                    df_server_clean['server_time_relative'] = df_server_clean['server_time'] - server_start
                    
                    # Prepare client time (already in ms, convert to seconds)
                    df_p1['client_time_sec'] = df_p1['recv_time_ms'] / 1000.0
                    
                    # Align time ranges
                    client_start = df_p1['client_time_sec'].min()
                    df_server_clean['server_time_aligned'] = df_server_clean['server_time_relative'] - client_start
                    
                    print(f"  Server time range: {df_server_clean['server_time_aligned'].min():.2f} to {df_server_clean['server_time_aligned'].max():.2f}")
                    print(f"  Client time range: {df_p1['client_time_sec'].min():.2f} to {df_p1['client_time_sec'].max():.2f}")
                    
                    # Merge on closest time
                    df_p1_sorted = df_p1.sort_values('client_time_sec')
                    df_server_sorted = df_server_clean.sort_values('server_time_aligned')
                    
                    df_merged = pd.merge_asof(
                        df_p1_sorted,
                        df_server_sorted,
                        left_on='client_time_sec',
                        right_on='server_time_aligned',
                        direction='nearest',
                        tolerance=0.2
                    )
                    
                    print(f"  Merged {len(df_merged)} samples")
                    
                    if not df_merged.empty and 'server_x' in df_merged.columns and 'server_y' in df_merged.columns:
                        df_merged_clean = df_merged.dropna(subset=['render_x', 'render_y', 'server_x', 'server_y'])
                        
                        if len(df_merged_clean) > 0:
                            # DEBUG: Show sample comparison
                            sample = df_merged_clean.iloc[0]
                            print(f"  Sample comparison:")
                            print(f"    Client pos: ({sample['render_x']:.2f}, {sample['render_y']:.2f})")
                            print(f"    Server pos: ({sample['server_x']:.2f}, {sample['server_y']:.2f})")
                            
                            dx = df_merged_clean['render_x'] - df_merged_clean['server_x']
                            dy = df_merged_clean['render_y'] - df_merged_clean['server_y']
                            position_errors = np.sqrt(dx**2 + dy**2)
                            
                            # Filter reasonable errors
                            valid_errors = position_errors[(position_errors >= 0) & (position_errors <= 10)]
                            
                            if len(valid_errors) > 0:
                                print(f"  [OK] Calculated {len(valid_errors)} position error samples")
                                print(f"    Mean error: {valid_errors.mean():.4f} units")
                                print(f"    Std dev: {valid_errors.std():.4f} units")
                                print(f"    Min: {valid_errors.min():.4f}, Max: {valid_errors.max():.4f}")
                                
                                scenario_metrics['position_error']['all'].extend(valid_errors.tolist())
                                scenario_metrics['position_error']['means'].append(valid_errors.mean())
                            else:
                                print(f"  [WARN] No valid position errors")
                        else:
                            print(f"  [WARN] No matching data after cleaning")
                    else:
                        print(f"  [WARN] Merge failed")
                else:
                    print(f"  [WARN] Server data empty after cleaning")
            else:
                print(f"  [WARN] Missing server columns")
    else:
        print(f"  [WARN] No player_1 data found")
    
    # CPU usage
    if 'cpu_percent' in df_server.columns:
        cpu_avg = df_server['cpu_percent'].mean()
        scenario_metrics['cpu_usage'].append(cpu_avg)
    
    # Bandwidth
    bytes_cols = [col for col in df_server.columns if 'byte' in col.lower()]
    if bytes_cols and len(df_server) > 1:
        bytes_col = bytes_cols[0]
        if 'timestamp' in df_server.columns:
            time_span = df_server['timestamp'].iloc[-1] - df_server['timestamp'].iloc[0]
            if time_span > 0:
                total_bytes = df_server[bytes_col].iloc[-1] - df_server[bytes_col].iloc[0]
                bandwidth_kbps = (total_bytes * 8 / 1024) / time_span
                scenario_metrics['bandwidth'].append(bandwidth_kbps)
    
    # Calculate statistics
    print(f"\n  [METRICS] COMPREHENSIVE METRICS:")
    
    # Latency
    if scenario_metrics['latency']['all']:
        latencies = np.array(scenario_metrics['latency']['all'])
        print(f"    Latency:")
        print(f"      Mean: {latencies.mean():.1f} ms")
        print(f"      Median: {np.median(latencies):.1f} ms")
        print(f"      95th percentile: {np.percentile(latencies, 95):.1f} ms")
        print(f"      Std Dev: {latencies.std():.1f} ms")
        
        if latencies.mean() <= 50:
            print(f"      [PASS] Meets ≤50ms requirement")
        else:
            print(f"      [FAIL] Exceeds ≤50ms requirement")
    else:
        print(f"    Latency: No data")
    
    # Position error
    if scenario_metrics['position_error']['all']:
        errors = np.array(scenario_metrics['position_error']['all'])
        print(f"\n    Position Error:")
        print(f"      Mean: {errors.mean():.4f} grid units")
        print(f"      Std Dev: {errors.std():.4f} grid units")
        print(f"      95th percentile: {np.percentile(errors, 95):.4f} grid units")
        print(f"      Max: {errors.max():.4f} grid units")
        print(f"      Min: {errors.min():.4f} grid units")
        print(f"      Samples: {len(errors)}")
        
        mean_ok = errors.mean() <= 0.5
        percentile_ok = np.percentile(errors, 95) <= 1.5
        
        if mean_ok and percentile_ok:
            print(f"      [PASS] Meets position error requirements")
        else:
            print(f"      [WARN] Position error exceeds requirements")
    else:
        print(f"\n    Position Error: No data")
    
    # Update rate
    if scenario_metrics['update_rate']:
        rates = np.array(scenario_metrics['update_rate'])
        print(f"\n    Update Rate:")
        print(f"      Average: {rates.mean():.1f} Hz")
        print(f"      Target: 20 Hz")
        
        if 18 <= rates.mean() <= 22:
            print(f"      [PASS] Within 20±2 Hz target")
        else:
            print(f"      [WARN] Update rate outside target range")
    else:
        print(f"\n    Update Rate: No data")
    
    # CPU usage
    if scenario_metrics['cpu_usage']:
        cpu_avg = np.mean(scenario_metrics['cpu_usage'])
        print(f"\n    Server CPU Usage:")
        print(f"      Average: {cpu_avg:.1f}%")
        
        if cpu_avg < 60:
            print(f"      [PASS] Below 60% threshold")
        else:
            print(f"      [WARN] CPU usage above 60%")
    else:
        print(f"\n    Server CPU Usage: No data")
    
    # Jitter
    if scenario_metrics['jitter']:
        jitter_avg = np.mean(scenario_metrics['jitter'])
        print(f"\n    Jitter:")
        print(f"      Average: {jitter_avg:.1f} ms")
    else:
        print(f"\n    Jitter: No data")
    
    return scenario_metrics

def generate_summary_report(all_metrics):
    """Generate a comprehensive summary report"""
    print(f"\n{'='*80}")
    print("FINAL SUMMARY REPORT")
    print(f"{'='*80}")
    
    if not all_metrics:
        print("No valid metrics collected.")
        return
    
    scenario_types = {}
    for metrics in all_metrics:
        name = metrics['name']
        if 'baseline' in name.lower():
            key = 'Baseline'
        elif 'loss_2' in name.lower():
            key = 'Loss 2%'
        elif 'loss_5' in name.lower():
            key = 'Loss 5%'
        elif 'delay' in name.lower():
            key = 'Delay 100ms'
        else:
            key = 'Other'
        
        if key not in scenario_types:
            scenario_types[key] = []
        scenario_types[key].append(metrics)
    
    print(f"\n{'Scenario':<15} {'Latency (ms)':<15} {'Pos Error':<12} {'Update Rate':<12} {'CPU %':<10}")
    print(f"{'-'*15:<15} {'-'*15:<15} {'-'*12:<12} {'-'*12:<12} {'-'*10:<10}")
    
    for scenario, metrics_list in scenario_types.items():
        if metrics_list:
            latencies = []
            errors = []
            rates = []
            cpus = []
            
            for m in metrics_list:
                if m['latency']['all']:
                    latencies.append(np.mean(m['latency']['all']))
                if m['position_error']['all']:
                    errors.append(np.mean(m['position_error']['all']))
                if m['update_rate']:
                    rates.append(np.mean(m['update_rate']))
                if m['cpu_usage']:
                    cpus.append(np.mean(m['cpu_usage']))
            
            latency_str = f"{np.mean(latencies):.1f}" if latencies else "N/A"
            error_str = f"{np.mean(errors):.4f}" if errors else "N/A"
            rate_str = f"{np.mean(rates):.1f}" if rates else "N/A"
            cpu_str = f"{np.mean(cpus):.1f}" if cpus else "N/A"
            
            print(f"{scenario:<15} {latency_str:<15} {error_str:<12} {rate_str:<12} {cpu_str:<10}")

if __name__ == "__main__":
    sys.stdout = Logger("analysis_fixed_report.txt")
    
    print("GRID CLASH PROTOCOL - FIXED ANALYSIS")
    print("="*60)
    
    if not os.path.exists("results"):
        print("No results folder found.")
        sys.exit(1)
    
    subfolders = [f.path for f in os.scandir("results") if f.is_dir()]
    subfolders.sort()
    
    print(f"Found {len(subfolders)} test run(s).")
    
    all_metrics = []
    for folder in subfolders:
        metrics = analyze_scenario(folder)
        if metrics:
            all_metrics.append(metrics)
    
    generate_summary_report(all_metrics)
    
    print(f"\n{'='*60}")
    print("ANALYSIS COMPLETE")
    print(f"Detailed report saved to: analysis_fixed_report.txt")
    print(f"{'='*60}")