import pandas as pd
import numpy as np
import glob
import os
import sys
import matplotlib.pyplot as plt
from scipy import stats

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
    print(f"\n{'='*60}")
    print(f"ANALYZING: {os.path.basename(folder_path)}")
    print(f"{'='*60}")
    
    # Find all log files
    server_files = glob.glob(os.path.join(folder_path, "server_log*.csv"))
    if not server_files:
        print("  [SKIP] No server logs found.")
        return None
    
    server_file = server_files[0]  # Take the first server log
    
    try:
        # Read server log
        df_server = pd.read_csv(server_file)
        
        print(f"  Server log: {os.path.basename(server_file)}")
        print(f"  Server columns: {list(df_server.columns)}")
        print(f"  Server rows: {len(df_server)}")
        
        if len(df_server) > 0:
            print(f"  First server row:\n{df_server.iloc[0]}")
        
        # Clean server data
        df_server = df_server.dropna()
        if df_server.empty:
            print("  [ERR] Empty server log after cleaning.")
            return None
            
    except Exception as e:
        print(f"  [ERR] Corrupt server log: {e}")
        return None

    client_files = glob.glob(os.path.join(folder_path, "client_log_*.csv"))
    if not client_files:
        print("  [SKIP] No client logs found.")
        return None
    
    print(f"  Found {len(client_files)} client logs")
    
    critical_event_files = glob.glob(os.path.join(folder_path, "critical_events_*.csv"))
    
    # Initialize metrics dictionary
    scenario_metrics = {
        'name': os.path.basename(folder_path),
        'latency': {'all': [], 'means': []},
        'position_error': {'all': [], 'means': []},
        'update_rate': [],
        'critical_events': [],
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
    
    # First, let's examine what data we have in client logs
    all_client_data = []
    for c_file in client_files:
        try:
            df_client = pd.read_csv(c_file)
            if df_client.empty: 
                continue
            
            # Check what columns we have
            print(f"\n  Processing: {os.path.basename(c_file)}")
            print(f"    Columns: {list(df_client.columns)}")
            print(f"    Rows: {len(df_client)}")
            
            if 'client_id' in df_client.columns:
                unique_ids = df_client['client_id'].unique()
                print(f"    Client IDs: {unique_ids}")
            
            all_client_data.append(df_client)
            
        except Exception as e:
            print(f"  [WARN] Error reading {os.path.basename(c_file)}: {e}")
            continue
    
    if not all_client_data:
        print("  [ERR] No valid client data found.")
        return scenario_metrics
    
    # Process each client log
    for i, df_client in enumerate(all_client_data):
        try:
            print(f"\n  Analyzing client {i+1}...")
            
            # 1. METRIC: Latency (with filtering)
            if 'latency_ms' in df_client.columns:
                valid_latencies = df_client['latency_ms'][
                    (df_client['latency_ms'] >= 0) & 
                    (df_client['latency_ms'] <= 5000)
                ]
                
                if len(valid_latencies) > 0:
                    scenario_metrics['latency']['all'].extend(valid_latencies.tolist())
                    scenario_metrics['latency']['means'].append(valid_latencies.mean())
                    
                    # Calculate jitter (variation in latency)
                    if len(valid_latencies) > 1:
                        jitter = valid_latencies.std()
                        scenario_metrics['jitter'].append(jitter)
                    
                    print(f"    Latency samples: {len(valid_latencies)}, Mean: {valid_latencies.mean():.1f}ms")
            else:
                print(f"    ⚠️  No latency_ms column")
            
            # 2. METRIC: Update Rate (20Hz verification)
            if 'recv_time_ms' in df_client.columns and len(df_client) > 1:
                # Calculate time between consecutive snapshots
                df_sorted = df_client.sort_values('recv_time_ms')
                time_diffs = df_sorted['recv_time_ms'].diff().dropna()
                if len(time_diffs) > 0:
                    avg_interval_ms = time_diffs.mean()
                    update_rate_hz = 1000.0 / avg_interval_ms if avg_interval_ms > 0 else 0
                    scenario_metrics['update_rate'].append(update_rate_hz)
                    print(f"    Update rate: {update_rate_hz:.1f} Hz")
            
            # 3. METRIC: Position Error (PDF Requirement)
            # Check if we have render position data
            if 'render_x' in df_client.columns and 'render_y' in df_client.columns:
                print(f"    Has render positions: Yes")
                
                # Try to find matching player in server log
                if 'client_id' in df_client.columns:
                    client_id = df_client['client_id'].iloc[0]
                    print(f"    Client ID: {client_id}")
                    
                    # Try to map client ID to server player position
                    # Server likely has columns like: 'player1_x', 'player1_y', etc.
                    # Or numbered columns for positions
                    
                    # Determine player number from client_id
                    player_num = None
                    if 'player_1' in str(client_id) or 'player1' in str(client_id):
                        player_num = 1
                    elif 'player_2' in str(client_id) or 'player2' in str(client_id):
                        player_num = 2
                    elif 'player_3' in str(client_id) or 'player3' in str(client_id):
                        player_num = 3
                    elif 'player_4' in str(client_id) or 'player4' in str(client_id):
                        player_num = 4
                    
                    if player_num:
                        print(f"    Player number: {player_num}")
                        
                        # Look for position columns in server log
                        server_x_col = None
                        server_y_col = None
                        
                        # Try pattern matching
                        for col in df_server.columns:
                            col_lower = col.lower()
                            if f'player{player_num}' in col_lower or f'player_{player_num}' in col_lower:
                                if 'x' in col_lower or '_x' in col or col.endswith('_0'):
                                    server_x_col = col
                                elif 'y' in col_lower or '_y' in col or col.endswith('_1'):
                                    server_y_col = col
                        
                        # If not found by name, try by position (common format)
                        if not server_x_col or not server_y_col:
                            # Server log format is often: timestamp, cpu, bytes, p1_x, p1_y, p2_x, p2_y, etc.
                            # Player 1 positions are typically at index 3 and 4
                            # Player 2 at 5 and 6, etc.
                            pos_idx = 2 + (player_num * 2)  # Calculate column index
                            if len(df_server.columns) > pos_idx + 1:
                                server_x_col = df_server.columns[pos_idx + 1]
                                server_y_col = df_server.columns[pos_idx + 2]
                                print(f"    Using indexed columns: {server_x_col}, {server_y_col}")
                        
                        if server_x_col and server_y_col and server_x_col in df_server.columns and server_y_col in df_server.columns:
                            print(f"    Server position columns found: {server_x_col}, {server_y_col}")
                            
                            # Now calculate position error
                            # We need to match timestamps between client and server
                            
                            # Find timestamp column in server
                            server_time_col = None
                            for col in df_server.columns:
                                if 'time' in col.lower() or 'timestamp' in col.lower():
                                    server_time_col = col
                                    break
                            
                            if not server_time_col and len(df_server.columns) > 0:
                                server_time_col = df_server.columns[0]  # Assume first column is timestamp
                            
                            if server_time_col:
                                print(f"    Server timestamp column: {server_time_col}")
                                
                                # Prepare client data
                                df_client_clean = df_client.copy()
                                df_client_clean['client_time_sec'] = df_client_clean['recv_time_ms'] / 1000.0
                                
                                # Prepare server data
                                df_server_clean = df_server.copy()
                                df_server_clean = df_server_clean.rename(columns={
                                    server_time_col: 'server_time_sec',
                                    server_x_col: 'server_x',
                                    server_y_col: 'server_y'
                                })
                                
                                # Ensure numeric columns
                                for col in ['server_time_sec', 'server_x', 'server_y']:
                                    if col in df_server_clean.columns:
                                        df_server_clean[col] = pd.to_numeric(df_server_clean[col], errors='coerce')
                                
                                # Drop rows with NaN
                                df_server_clean = df_server_clean.dropna(subset=['server_time_sec', 'server_x', 'server_y'])
                                
                                if not df_server_clean.empty and len(df_client_clean) > 0:
                                    # Merge based on closest timestamps
                                    df_client_sorted = df_client_clean.sort_values('client_time_sec')
                                    df_server_sorted = df_server_clean.sort_values('server_time_sec')
                                    
                                    # Use merge_asof for nearest timestamp matching
                                    df_merged = pd.merge_asof(
                                        df_client_sorted,
                                        df_server_sorted,
                                        left_on='client_time_sec',
                                        right_on='server_time_sec',
                                        direction='nearest',
                                        tolerance=0.1  # Match within 100ms
                                    )
                                    
                                    if not df_merged.empty and 'server_x' in df_merged.columns and 'server_y' in df_merged.columns:
                                        # Calculate position error
                                        df_merged = df_merged.dropna(subset=['render_x', 'render_y', 'server_x', 'server_y'])
                                        
                                        if len(df_merged) > 0:
                                            dx = df_merged['render_x'] - df_merged['server_x']
                                            dy = df_merged['render_y'] - df_merged['server_y']
                                            position_errors = np.sqrt(dx**2 + dy**2)
                                            
                                            # Filter reasonable errors
                                            valid_errors = position_errors[(position_errors >= 0) & (position_errors <= 10)]
                                            
                                            if len(valid_errors) > 0:
                                                print(f"    ✅ Calculated {len(valid_errors)} position error samples")
                                                print(f"       Error mean: {valid_errors.mean():.4f}, std: {valid_errors.std():.4f}")
                                                scenario_metrics['position_error']['all'].extend(valid_errors.tolist())
                                                scenario_metrics['position_error']['means'].append(valid_errors.mean())
                                            else:
                                                print(f"    ⚠️  No valid position errors after filtering")
                                        else:
                                            print(f"    ⚠️  No matching data after merging")
                                    else:
                                        print(f"    ⚠️  Merge failed or missing columns")
                                else:
                                    print(f"    ⚠️  Not enough data for position error calculation")
                            else:
                                print(f"    ⚠️  Could not find server timestamp column")
                        else:
                            print(f"    ⚠️  Could not find server position columns for player {player_num}")
                    else:
                        print(f"    ⚠️  Could not determine player number from ID: {client_id}")
                else:
                    print(f"    ⚠️  No client_id column")
            else:
                print(f"    ⚠️  No render position data (render_x, render_y)")
            
            # 4. METRIC: CPU Usage (from server log)
            if 'cpu_percent' in df_server.columns:
                cpu_avg = df_server['cpu_percent'].mean()
                scenario_metrics['cpu_usage'].append(cpu_avg)
            else:
                # Try to find CPU column by name pattern
                cpu_cols = [col for col in df_server.columns if 'cpu' in col.lower()]
                if cpu_cols:
                    cpu_avg = df_server[cpu_cols[0]].mean()
                    scenario_metrics['cpu_usage'].append(cpu_avg)
            
            # 5. METRIC: Bandwidth (approximate)
            bytes_cols = [col for col in df_server.columns if 'byte' in col.lower()]
            if bytes_cols and len(df_server) > 1:
                bytes_col = bytes_cols[0]
                time_span = df_server['timestamp'].iloc[-1] - df_server['timestamp'].iloc[0]
                if time_span > 0:
                    total_bytes = df_server[bytes_col].iloc[-1] - df_server[bytes_col].iloc[0]
                    bandwidth_kbps = (total_bytes * 8 / 1024) / time_span
                    scenario_metrics['bandwidth'].append(bandwidth_kbps)
            
            # 6. METRIC: Packet Loss Estimation
            if 'snapshot_id' in df_client.columns:
                snapshot_ids = df_client['snapshot_id'].dropna().astype(int)
                if len(snapshot_ids) > 1:
                    expected_ids = set(range(snapshot_ids.min(), snapshot_ids.max() + 1))
                    received_ids = set(snapshot_ids)
                    lost_packets = len(expected_ids - received_ids)
                    scenario_metrics['packet_loss'] += lost_packets
                    print(f"    Estimated lost packets: {lost_packets}")
                    
        except Exception as e:
            print(f"  [WARN] Error processing client data: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    # 7. METRIC: Critical Event Delivery (PDF Requirement: ≥99% within 200ms)
    critical_event_data = []
    for ce_file in critical_event_files:
        try:
            df_critical = pd.read_csv(ce_file)
            if not df_critical.empty and 'latency_ms' in df_critical.columns:
                # Filter valid latencies
                valid_events = df_critical[
                    (df_critical['latency_ms'] >= 0) & 
                    (df_critical['latency_ms'] <= 2000)
                ]
                if len(valid_events) > 0:
                    critical_event_data.extend(valid_events['latency_ms'].tolist())
        except:
            pass
    
    # Calculate statistics
    print(f"\n  📊 COMPREHENSIVE METRICS:")
    
    # Latency statistics
    if scenario_metrics['latency']['all']:
        latencies = np.array(scenario_metrics['latency']['all'])
        print(f"    Latency:")
        print(f"      Mean: {latencies.mean():.1f} ms")
        print(f"      Median: {np.median(latencies):.1f} ms")
        print(f"      95th percentile: {np.percentile(latencies, 95):.1f} ms")
        print(f"      Std Dev: {latencies.std():.1f} ms")
        
        # PDF Requirement: ≤50 ms average
        if latencies.mean() <= 50:
            print(f"      ✅ PASS: Meets ≤50ms requirement")
        else:
            print(f"      ❌ FAIL: Exceeds ≤50ms requirement")
    else:
        print(f"    Latency: No data")
    
    # Position error statistics
    if scenario_metrics['position_error']['all']:
        errors = np.array(scenario_metrics['position_error']['all'])
        print(f"\n    Position Error:")
        print(f"      Mean: {errors.mean():.4f} grid units")
        print(f"      Std Dev: {errors.std():.4f} grid units")
        print(f"      95th percentile: {np.percentile(errors, 95):.4f} grid units")
        print(f"      Max: {errors.max():.4f} grid units")
        print(f"      Min: {errors.min():.4f} grid units")
        print(f"      Samples: {len(errors)}")
        
        # PDF Requirements:
        # Loss 2%: Mean ≤ 0.5 units, 95th ≤ 1.5 units
        mean_ok = errors.mean() <= 0.5
        percentile_ok = np.percentile(errors, 95) <= 1.5
        
        if mean_ok and percentile_ok:
            print(f"      ✅ PASS: Meets position error requirements")
        else:
            print(f"      ⚠️  WARNING: Position error exceeds requirements")
    else:
        print(f"\n    Position Error: No data")
        print(f"      Possible reasons:")
        print(f"      1. Client logs don't have render_x/render_y columns")
        print(f"      2. Server logs don't have matching player position columns")
        print(f"      3. Timestamps don't align between client and server")
        print(f"      4. No player_1/client_1 data found")
    
    # Update rate statistics
    if scenario_metrics['update_rate']:
        rates = np.array(scenario_metrics['update_rate'])
        print(f"\n    Update Rate:")
        print(f"      Average: {rates.mean():.1f} Hz")
        print(f"      Target: 20 Hz")
        
        if 18 <= rates.mean() <= 22:
            print(f"      ✅ PASS: Within 20±2 Hz target")
        else:
            print(f"      ⚠️  WARNING: Update rate outside target range")
    else:
        print(f"\n    Update Rate: No data")
    
    # Critical event delivery
    if critical_event_data:
        latencies = np.array(critical_event_data)
        within_200ms = np.sum(latencies <= 200) / len(latencies) * 100
        print(f"\n    Critical Event Delivery:")
        print(f"      Events within 200ms: {within_200ms:.1f}%")
        print(f"      Average latency: {latencies.mean():.1f} ms")
        print(f"      Total events: {len(latencies)}")
        
        # PDF Requirement: ≥99% within 200ms
        if within_200ms >= 99:
            print(f"      ✅ PASS: Meets ≥99% within 200ms requirement")
        else:
            print(f"      ❌ FAIL: Below ≥99% requirement")
    else:
        print(f"\n    Critical Event Delivery: No data")
    
    # CPU usage
    if scenario_metrics['cpu_usage']:
        cpu_avg = np.mean(scenario_metrics['cpu_usage'])
        print(f"\n    Server CPU Usage:")
        print(f"      Average: {cpu_avg:.1f}%")
        
        # PDF Requirement: < 60%
        if cpu_avg < 60:
            print(f"      ✅ PASS: Below 60% threshold")
        else:
            print(f"      ⚠️  WARNING: CPU usage above 60%")
    else:
        print(f"\n    Server CPU Usage: No data")
    
    # Bandwidth
    if scenario_metrics['bandwidth']:
        bw_avg = np.mean(scenario_metrics['bandwidth'])
        print(f"\n    Bandwidth Usage:")
        print(f"      Average: {bw_avg:.1f} Kbps per client")
    else:
        print(f"\n    Bandwidth Usage: No data")
    
    # Jitter
    if scenario_metrics['jitter']:
        jitter_avg = np.mean(scenario_metrics['jitter'])
        print(f"\n    Jitter:")
        print(f"      Average: {jitter_avg:.1f} ms")
    else:
        print(f"\n    Jitter: No data")
    
    # Packet loss
    print(f"\n    Packet Loss Estimation:")
    print(f"      Estimated lost packets: {scenario_metrics['packet_loss']}")
    
    return scenario_metrics

def generate_summary_report(all_metrics):
    """Generate a comprehensive summary report"""
    print(f"\n{'='*80}")
    print("FINAL SUMMARY REPORT")
    print(f"{'='*80}")
    
    if not all_metrics:
        print("No valid metrics collected.")
        return
    
    # Group by scenario type
    scenario_types = {}
    for metrics in all_metrics:
        name = metrics['name']
        # Extract scenario type from name
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
    
    # Print summary table
    print(f"\n{'Scenario':<15} {'Latency (ms)':<15} {'Pos Error':<12} {'Update Rate':<12} {'CPU %':<10}")
    print(f"{'-'*15:<15} {'-'*15:<15} {'-'*12:<12} {'-'*12:<12} {'-'*10:<10}")
    
    for scenario, metrics_list in scenario_types.items():
        if metrics_list:
            # Calculate averages
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
    
    # Generate plots
    generate_plots(all_metrics)

def generate_plots(all_metrics):
    """Generate required plots for the report"""
    if not all_metrics:
        return
    
    try:
        # Plot 1: Latency vs Scenario
        plt.figure(figsize=(10, 6))
        scenarios = []
        latencies = []
        
        for metrics in all_metrics:
            if metrics['latency']['all']:
                scenarios.append(metrics['name'][:20])  # Truncate long names
                latencies.append(np.mean(metrics['latency']['all']))
        
        if scenarios and latencies:
            bars = plt.bar(scenarios, latencies, color='skyblue')
            plt.axhline(y=50, color='red', linestyle='--', label='Max (50ms)')
            plt.title('Average Latency per Scenario')
            plt.ylabel('Latency (ms)')
            plt.xticks(rotation=45, ha='right')
            plt.legend()
            plt.tight_layout()
            plt.savefig('latency_summary.png')
            print(f"\n✅ Generated: latency_summary.png")
        
        # Plot 2: Position Error vs Scenario
        plt.figure(figsize=(10, 6))
        scenarios = []
        errors = []
        
        for metrics in all_metrics:
            if metrics['position_error']['all']:
                scenarios.append(metrics['name'][:20])
                errors.append(np.mean(metrics['position_error']['all']))
        
        if scenarios and errors:
            bars = plt.bar(scenarios, errors, color='lightcoral')
            plt.axhline(y=0.5, color='red', linestyle='--', label='Max (0.5 units)')
            plt.title('Average Position Error per Scenario')
            plt.ylabel('Position Error (grid units)')
            plt.xticks(rotation=45, ha='right')
            plt.legend()
            plt.tight_layout()
            plt.savefig('position_error_summary.png')
            print(f"✅ Generated: position_error_summary.png")
        else:
            print(f"⚠️  Could not generate position error plot - no data")
        
        plt.close('all')
        
    except Exception as e:
        print(f"[WARN] Could not generate plots: {e}")

if __name__ == "__main__":
    # Redirect output to file AND console
    sys.stdout = Logger("analysis_report.txt")
    
    print("GRID CLASH PROTOCOL - COMPREHENSIVE ANALYSIS")
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
    
    # Generate final summary
    generate_summary_report(all_metrics)
    
    print(f"\n{'='*60}")
    print("ANALYSIS COMPLETE")
    print(f"Detailed report saved to: analysis_report.txt")
    print(f"Summary plots saved to: latency_summary.png, position_error_summary.png")
    print(f"{'='*60}")