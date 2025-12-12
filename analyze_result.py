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
    
    server_file = os.path.join(folder_path, "server_log.csv")
    if not os.path.exists(server_file):
        print("  [SKIP] No server_log.csv found.")
        return None
    
    try:
        # Read server log - check column names
        df_server = pd.read_csv(server_file)
        
        # DEBUG: Print server columns to see what we have
        print(f"  Server columns: {list(df_server.columns)}")
        
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
    
    for c_file in client_files:
        try:
            df_client = pd.read_csv(c_file)
            if df_client.empty: 
                continue
            
            # DEBUG: Print client columns
            print(f"  Client columns: {list(df_client.columns)}")
            
            # Clean client data
            df_client = df_client.dropna()
            
            # 1. METRIC: Latency (with filtering)
            # Remove outliers and invalid values
            valid_latencies = df_client['latency_ms'][
                (df_client['latency_ms'] >= 0) & 
                (df_client['latency_ms'] <= 5000)  # Reasonable max
            ]
            
            if len(valid_latencies) > 0:
                scenario_metrics['latency']['all'].extend(valid_latencies.tolist())
                scenario_metrics['latency']['means'].append(valid_latencies.mean())
                
                # Calculate jitter (variation in latency)
                if len(valid_latencies) > 1:
                    jitter = valid_latencies.std()
                    scenario_metrics['jitter'].append(jitter)
            
            # 2. METRIC: Update Rate (20Hz verification)
            if 'snapshot_id' in df_client.columns:
                # Calculate time between consecutive snapshots
                df_sorted = df_client.sort_values('recv_time_ms')
                time_diffs = df_sorted['recv_time_ms'].diff().dropna()
                if len(time_diffs) > 0:
                    avg_interval_ms = time_diffs.mean()
                    update_rate_hz = 1000.0 / avg_interval_ms if avg_interval_ms > 0 else 0
                    scenario_metrics['update_rate'].append(update_rate_hz)
            
            # 3. METRIC: Position Error (PDF Requirement)
            client_id = df_client['client_id'].iloc[0] if 'client_id' in df_client.columns else 'unknown'
            
            # Try to calculate position error for player_1
            if 'player_1' in df_client['client_id'].astype(str).values:
                df_p1 = df_client[df_client['client_id'] == 'player_1'].copy()
                
                if len(df_p1) > 0 and not df_server.empty:
                    # Convert timestamps to seconds
                    df_p1['ts_sec'] = df_p1['recv_time_ms'] / 1000.0
                    
                    # DEBUG: Print what columns are available in server log
                    print(f"  Server columns available: {list(df_server.columns)}")
                    
                    # Find timestamp column in server log (most important first)
                    server_time_col = None
                    for col in df_server.columns:
                        if 'time' in col.lower() or 'timestamp' in col.lower():
                            server_time_col = col
                            break
                    
                    # Try multiple approaches to find position data in server log
                    server_positions_found = False
                    
                    # Approach 1: Check for specific position columns
                    if 'player1_x' in df_server.columns and 'player1_y' in df_server.columns:
                        server_x_col = 'player1_x'
                        server_y_col = 'player1_y'
                        server_positions_found = True
                        print(f"  Found position columns: {server_x_col}, {server_y_col}")
                    
                    # Approach 2: Check for numbered columns (common format)
                    elif len(df_server.columns) >= 7:  # timestamp, cpu, bytes, then positions
                        # Try to identify position columns by index
                        # Usually format: timestamp, cpu, bytes, p1_x, p1_y, p2_x, p2_y, p3_x, p3_y, p4_x, p4_y
                        server_x_col = df_server.columns[3]  # Usually player1_x
                        server_y_col = df_server.columns[4]  # Usually player1_y
                        server_positions_found = True
                        print(f"  Using indexed position columns: {server_x_col}, {server_y_col}")
                    
                    # Approach 3: Check for any columns containing position-like data
                    else:
                        # Look for columns with numeric data that could be positions
                        potential_x_cols = []
                        potential_y_cols = []
                        
                        for col in df_server.columns:
                            if col in ['timestamp', 'cpu_percent', 'total_bytes_sent']:
                                continue
                            
                            # Check if column has numeric data in reasonable range (0-19 for 20x20 grid)
                            try:
                                sample_value = df_server[col].iloc[0]
                                if isinstance(sample_value, (int, float)):
                                    if 0 <= sample_value <= 19:
                                        if len(potential_x_cols) == 0:
                                            potential_x_cols.append(col)
                                        else:
                                            potential_y_cols.append(col)
                            except:
                                continue
                        
                        if len(potential_x_cols) > 0 and len(potential_y_cols) > 0:
                            server_x_col = potential_x_cols[0]
                            server_y_col = potential_y_cols[0]
                            server_positions_found = True
                            print(f"  Inferred position columns: {server_x_col}, {server_y_col}")
                    
                    if server_positions_found and server_time_col:
                        try:
                            # Create clean server dataframe
                            df_server_clean = df_server.copy()
                            
                            # Ensure columns exist
                            if server_x_col not in df_server_clean.columns or server_y_col not in df_server_clean.columns:
                                print(f"  ERROR: Position columns not found: {server_x_col}, {server_y_col}")
                                continue
                            
                            # Rename for clarity
                            df_server_clean = df_server_clean.rename(columns={
                                server_x_col: 'player1_pos_x',
                                server_y_col: 'player1_pos_y',
                                server_time_col: 'timestamp_sec'
                            })
                            
                            # Ensure timestamp is numeric
                            df_server_clean['timestamp_sec'] = pd.to_numeric(df_server_clean['timestamp_sec'], errors='coerce')
                            
                            # Drop rows with NaN timestamps
                            df_server_clean = df_server_clean.dropna(subset=['timestamp_sec'])
                            
                            # Sort by timestamp
                            df_server_clean = df_server_clean.sort_values('timestamp_sec')
                            
                            # Merge client and server data based on timestamp
                            # Use merge_asof to match closest timestamps
                            df_merged = pd.merge_asof(
                                df_p1.sort_values('ts_sec'), 
                                df_server_clean.sort_values('timestamp_sec'), 
                                left_on='ts_sec', 
                                right_on='timestamp_sec', 
                                direction='nearest',
                                tolerance=0.5  # Match within 0.5 seconds
                            )
                            
                            if not df_merged.empty and 'player1_pos_x' in df_merged.columns:
                                # Calculate Euclidean distance error
                                dx = df_merged['render_x'] - df_merged['player1_pos_x']
                                dy = df_merged['render_y'] - df_merged['player1_pos_y']
                                
                                # Filter out NaN values
                                mask = dx.notna() & dy.notna()
                                if mask.any():
                                    position_errors = np.sqrt(dx[mask]**2 + dy[mask]**2)
                                    
                                    # Filter out extreme outliers (should be < 10 grid units)
                                    valid_mask = (position_errors >= 0) & (position_errors <= 10)
                                    valid_errors = position_errors[valid_mask]
                                    
                                    if len(valid_errors) > 0:
                                        print(f"  ✅ Calculated {len(valid_errors)} position error samples")
                                        print(f"     Error range: {valid_errors.min():.4f} to {valid_errors.max():.4f}")
                                        scenario_metrics['position_error']['all'].extend(valid_errors.tolist())
                                        scenario_metrics['position_error']['means'].append(valid_errors.mean())
                                    else:
                                        print(f"  ⚠️  No valid position errors after filtering")
                                else:
                                    print(f"  ⚠️  All position calculations resulted in NaN")
                            else:
                                print(f"  ⚠️  No matching position data found after merge")
                                
                        except Exception as e:
                            print(f"  ❌ Error calculating position error: {e}")
                            import traceback
                            traceback.print_exc()
                    else:
                        print(f"  ❌ Could not find position data in server log")
                        print(f"     Need timestamp column and at least 2 position columns")
            else:
                print(f"  ⚠️  No player_1 data in this client log")
            
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
                    
        except Exception as e:
            print(f"  [WARN] Error processing {os.path.basename(c_file)}: {e}")
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
        print(f"\n    Position Error: No data (check column names)")
    
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