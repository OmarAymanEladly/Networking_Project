import argparse
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import os
import json
import glob
from scipy import stats
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

class ResultsAnalyzer:
    def __init__(self, results_dir="test_results"):
        self.results_dir = results_dir
        self.scenarios = ["baseline", "loss_2pct", "loss_5pct", "delay_100ms", "delay_jitter"]
        
        # Set plotting style
        plt.style.use('seaborn-v0_8-darkgrid')
        sns.set_palette("husl")
        
        # Create analysis directory
        os.makedirs("analysis_plots", exist_ok=True)
        
    def find_csv_files(self, scenario_name):
        """Find all CSV files for a scenario across all runs"""
        csv_files = []
        
        # Pattern to match: test_results/scenario_name/run_*/client_log_*.csv
        client_pattern = os.path.join(self.results_dir, scenario_name, "run_*", "client_log_*.csv")
        server_pattern = os.path.join(self.results_dir, scenario_name, "run_*", "server_log.csv")
        
        client_files = glob.glob(client_pattern)
        server_files = glob.glob(server_pattern)
        
        return {
            'client_files': client_files,
            'server_files': server_files
        }
    
    def load_scenario_data(self, scenario_name):
        """Load all CSV files for a given scenario (new .sh format)"""
        print(f"  Loading data for {scenario_name}...")
        
        data = {
            'client_logs': [],
            'server_logs': [],
            'metadata': [],
            'run_dirs': []
        }
        
        # NEW: Look for directories that start with scenario_name
        scenario_pattern = os.path.join(self.results_dir, f"{scenario_name}_*")
        run_dirs = glob.glob(scenario_pattern)
        
        # Filter out files, keep only directories
        run_dirs = [d for d in run_dirs if os.path.isdir(d)]
        
        if not run_dirs:
            print(f"  Warning: No directories found for {scenario_name}")
            print(f"  Looking for pattern: {scenario_pattern}")
            return data
        
        print(f"  Found {len(run_dirs)} directories")
        
        for run_dir in sorted(run_dirs):
            print(f"    Processing: {os.path.basename(run_dir)}")
            data['run_dirs'].append(run_dir)
            
            # Load client CSV files
            client_pattern = os.path.join(run_dir, "client_*.csv")
            client_files = glob.glob(client_pattern)
            
            for csv_file in client_files:
                try:
                    df = pd.read_csv(csv_file)
                    df['scenario'] = scenario_name
                    df['run_dir'] = run_dir
                    df['run_name'] = os.path.basename(run_dir)
                    data['client_logs'].append(df)
                    print(f"      Loaded client data: {os.path.basename(csv_file)} ({len(df)} rows)")
                except Exception as e:
                    print(f"    Warning: Could not read {csv_file}: {e}")
            
            # Load server CSV files
            server_pattern = os.path.join(run_dir, "server.csv")
            if os.path.exists(server_pattern):
                try:
                    df = pd.read_csv(server_pattern)
                    df['scenario'] = scenario_name
                    df['run_dir'] = run_dir
                    df['run_name'] = os.path.basename(run_dir)
                    data['server_logs'].append(df)
                    print(f"      Loaded server data: server.csv ({len(df)} rows)")
                except Exception as e:
                    print(f"    Warning: Could not read {server_pattern}: {e}")
            
            # Also look for server_log.csv (old naming)
            server_log_pattern = os.path.join(run_dir, "server_log.csv")
            if os.path.exists(server_log_pattern) and len(data['server_logs']) == 0:
                try:
                    df = pd.read_csv(server_log_pattern)
                    df['scenario'] = scenario_name
                    df['run_dir'] = run_dir
                    data['server_logs'].append(df)
                    print(f"      Loaded server data: server_log.csv ({len(df)} rows)")
                except:
                    pass
        
        print(f"  Total client logs: {len(data['client_logs'])}")
        print(f"  Total server logs: {len(data['server_logs'])}")
        
        return data
    
    def calculate_metrics(self, scenario_name, data):
        """Calculate all metrics required by PDF for a scenario"""
        print(f"  Calculating metrics for {scenario_name}...")
        
        metrics = {
            'scenario': scenario_name,
            'runs_analyzed': len(data['run_dirs'])
        }
        
        if not data['client_logs']:
            print(f"  Warning: No client data for {scenario_name}")
            return metrics
        
        # Combine all client logs for this scenario
        try:
            all_client_data = pd.concat(data['client_logs'], ignore_index=True)
            print(f"    Combined client data: {len(all_client_data)} rows")
        except Exception as e:
            print(f"    Error combining client data: {e}")
            return metrics
        
        # Basic metrics
        metrics['total_packets'] = len(all_client_data)
        metrics['unique_clients'] = all_client_data['client_id'].nunique() if 'client_id' in all_client_data.columns else 0
        
        # Check column names (debug)
        print(f"    Available columns: {list(all_client_data.columns)}")
        
        # Latency metrics (PDF requires mean, median, 95th percentile)
        latency_col = None
        for col in ['latency_ms', 'latency', 'latency_ms']:
            if col in all_client_data.columns:
                latency_col = col
                break
        
        if latency_col:
            latency_data = all_client_data[latency_col].dropna()
            if len(latency_data) > 0:
                metrics['latency_mean'] = float(latency_data.mean())
                metrics['latency_median'] = float(latency_data.median())
                metrics['latency_95th'] = float(np.percentile(latency_data, 95))
                metrics['latency_std'] = float(latency_data.std())
                metrics['latency_min'] = float(latency_data.min())
                metrics['latency_max'] = float(latency_data.max())
                metrics['latency_samples'] = int(len(latency_data))
                print(f"    Latency: {metrics['latency_mean']:.1f}ms mean, {metrics['latency_median']:.1f}ms median")
            else:
                print(f"    Warning: No latency data in column {latency_col}")
        else:
            print(f"    Warning: No latency column found. Available: {list(all_client_data.columns)}")
        
        # Jitter calculation
        if 'recv_time_ms' in all_client_data.columns:
            jitters = []
            for client_id in all_client_data['client_id'].unique():
                client_data = all_client_data[all_client_data['client_id'] == client_id]
                if len(client_data) > 10:  # Need enough samples
                    arrival_times = client_data['recv_time_ms'].sort_values().values
                    inter_arrival = np.diff(arrival_times)
                    if len(inter_arrival) > 0:
                        jitter = np.std(inter_arrival)
                        jitters.append(jitter)
            
            if jitters:
                metrics['jitter_mean'] = float(np.mean(jitters))
                metrics['jitter_median'] = float(np.median(jitters))
                metrics['jitter_95th'] = float(np.percentile(jitters, 95))
                metrics['jitter_samples'] = len(jitters)
        
        # Sequence number analysis
        seq_col = None
        for col in ['seq_num', 'seq', 'sequence', 'snapshot_id']:
            if col in all_client_data.columns:
                seq_col = col
                break
        
        if seq_col:
            seq_gaps_total = 0
            total_packets = 0
            
            for client_id in all_client_data['client_id'].unique():
                client_data = all_client_data[all_client_data['client_id'] == client_id]
                if len(client_data) > 1:
                    seq_nums = client_data[seq_col].sort_values().values
                    if len(seq_nums) > 1:
                        gaps = np.diff(seq_nums) - 1
                        seq_gaps = gaps[gaps > 0].sum()
                        seq_gaps_total += seq_gaps
                        total_packets += len(seq_nums)
            
            metrics['sequence_gaps'] = int(seq_gaps_total)
            if total_packets > 0:
                metrics['packet_loss_rate'] = float(seq_gaps_total / total_packets)
        
        # Server metrics
        if data['server_logs']:
            try:
                all_server_data = pd.concat(data['server_logs'], ignore_index=True)
                
                if 'cpu_percent' in all_server_data.columns:
                    cpu_data = all_server_data['cpu_percent'].dropna()
                    if len(cpu_data) > 0:
                        metrics['server_cpu_mean'] = float(cpu_data.mean())
                        metrics['server_cpu_max'] = float(cpu_data.max())
                        metrics['server_cpu_samples'] = int(len(cpu_data))
                
                if 'bytes_sent' in all_server_data.columns:
                    bytes_data = all_server_data['bytes_sent'].dropna()
                    if len(bytes_data) > 0:
                        metrics['total_bytes_sent'] = float(bytes_data.max() - bytes_data.min())
            except Exception as e:
                print(f"    Error processing server data: {e}")
        
        return metrics
    
    def calculate_position_error(self, scenario_name, data):
        """Calculate perceived position error as per PDF requirements"""
        print(f"  Calculating position error for {scenario_name}...")
        
        errors = []
        
        if not data['client_logs'] or not data['server_logs']:
            print(f"    Warning: Insufficient data for position error calculation")
            return errors
        
        # Process each run separately
        for run_dir in data['run_dirs']:
            # Find server log for this run
            server_file = os.path.join(run_dir, "server_log.csv")
            if not os.path.exists(server_file):
                continue
            
            try:
                server_df = pd.read_csv(server_file)
            except:
                continue
            
            # Find client logs for this run
            client_files = glob.glob(os.path.join(run_dir, "client_log_*.csv"))
            if not client_files:
                continue
            
            for client_file in client_files:
                try:
                    client_df = pd.read_csv(client_file)
                except:
                    continue
                
                # Check if we have the right columns
                server_pos_cols = ['player1_pos_x', 'player1_pos_y']
                client_pos_cols = ['render_x', 'render_y']
                
                if all(col in server_df.columns for col in server_pos_cols) and \
                   all(col in client_df.columns for col in client_pos_cols):
                    
                    # Simple matching: take every 10th server position and find closest client position
                    server_samples = server_df.iloc[::10]  # Sample every 10th row
                    
                    for _, server_row in server_samples.iterrows():
                        server_time = server_row.get('timestamp', 0)
                        server_x = server_row.get('player1_pos_x', 0)
                        server_y = server_row.get('player1_pos_y', 0)
                        
                        # Find closest client position in time
                        if 'recv_time_ms' in client_df.columns:
                            time_diffs = np.abs(client_df['recv_time_ms']/1000 - server_time)
                        elif 'timestamp' in client_df.columns:
                            time_diffs = np.abs(client_df['timestamp'] - server_time)
                        else:
                            continue
                        
                        if len(time_diffs) > 0:
                            min_idx = time_diffs.idxmin()
                            if time_diffs[min_idx] < 0.5:  # Within 500ms
                                client_x = client_df.loc[min_idx, 'render_x']
                                client_y = client_df.loc[min_idx, 'render_y']
                                
                                # Calculate Euclidean distance
                                error = np.sqrt((server_x - client_x)**2 + (server_y - client_y)**2)
                                errors.append(error)
        
        print(f"    Position errors calculated: {len(errors)} samples")
        return errors
    
    def generate_plots(self, all_metrics, position_errors):
        """Generate all required plots as per PDF"""
        print("\n📈 Generating plots...")
        
        if not all_metrics:
            print("  Warning: No metrics to plot")
            return
        
        # Prepare data for plotting
        scenarios = []
        latency_means = []
        latency_medians = []
        latency_95th = []
        cpu_means = []
        pos_error_means = []
        pos_error_95th = []
        loss_rates = []
        
        for scenario in self.scenarios:
            if scenario in all_metrics:
                metrics = all_metrics[scenario]
                scenarios.append(scenario.replace('_', '\n'))
                
                latency_means.append(metrics.get('latency_mean', 0))
                latency_medians.append(metrics.get('latency_median', 0))
                latency_95th.append(metrics.get('latency_95th', 0))
                cpu_means.append(metrics.get('server_cpu_mean', 0))
                loss_rates.append(metrics.get('packet_loss_rate', 0) * 100)
                
                errors = position_errors.get(scenario, [])
                if errors:
                    pos_error_means.append(np.mean(errors))
                    pos_error_95th.append(np.percentile(errors, 95))
                else:
                    pos_error_means.append(0)
                    pos_error_95th.append(0)
        
        # 1. Main summary plot
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        fig.suptitle('Grid Clash Protocol Performance Analysis', fontsize=16, fontweight='bold')
        
        # Plot 1: Latency
        ax1 = axes[0, 0]
        x = np.arange(len(scenarios))
        width = 0.25
        
        ax1.bar(x - width, latency_means, width, label='Mean', alpha=0.8, color='steelblue')
        ax1.bar(x, latency_medians, width, label='Median', alpha=0.8, color='lightblue')
        ax1.bar(x + width, latency_95th, width, label='95th %ile', alpha=0.8, color='darkblue')
        
        ax1.set_xlabel('Network Scenario', fontweight='bold')
        ax1.set_ylabel('Latency (ms)', fontweight='bold')
        ax1.set_title('Latency by Scenario', fontweight='bold')
        ax1.set_xticks(x)
        ax1.set_xticklabels(scenarios, rotation=45, ha='right')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # Add latency requirement line (50ms from PDF)
        ax1.axhline(y=50, color='red', linestyle='--', alpha=0.7, linewidth=1.5)
        ax1.text(len(scenarios)-0.5, 52, 'Max (50ms)', color='red', fontsize=9)
        
        # Plot 2: Position Error
        ax2 = axes[0, 1]
        if any(pos_error_means):
            ax2.bar(x - width/2, pos_error_means, width, label='Mean Error', alpha=0.8, color='orange')
            ax2.bar(x + width/2, pos_error_95th, width, label='95th %ile', alpha=0.8, color='darkorange')
            
            ax2.set_xlabel('Network Scenario', fontweight='bold')
            ax2.set_ylabel('Position Error (units)', fontweight='bold')
            ax2.set_title('Perceived Position Error', fontweight='bold')
            ax2.set_xticks(x)
            ax2.set_xticklabels(scenarios, rotation=45, ha='right')
            ax2.legend()
            ax2.grid(True, alpha=0.3)
            
            # Add requirement lines from PDF
            ax2.axhline(y=0.5, color='green', linestyle='--', alpha=0.7, linewidth=1.5, label='LAN req (0.5)')
            ax2.axhline(y=1.5, color='blue', linestyle='--', alpha=0.7, linewidth=1.5, label='WAN req (1.5)')
        
        # Plot 3: Packet Loss
        ax3 = axes[1, 0]
        ax3.bar(x, loss_rates, width=0.6, alpha=0.7, color='purple')
        ax3.set_xlabel('Network Scenario', fontweight='bold')
        ax3.set_ylabel('Packet Loss Rate (%)', color='purple', fontweight='bold')
        ax3.set_title('Packet Loss Analysis', fontweight='bold')
        ax3.set_xticks(x)
        ax3.set_xticklabels(scenarios, rotation=45, ha='right')
        ax3.tick_params(axis='y', labelcolor='purple')
        ax3.grid(True, alpha=0.3)
        
        # Plot 4: Server CPU
        ax4 = axes[1, 1]
        ax4.bar(x, cpu_means, width=0.6, alpha=0.7, color='green')
        ax4.set_xlabel('Network Scenario', fontweight='bold')
        ax4.set_ylabel('CPU Usage (%)', color='green', fontweight='bold')
        ax4.set_title('Server CPU Utilization', fontweight='bold')
        ax4.set_xticks(x)
        ax4.set_xticklabels(scenarios, rotation=45, ha='right')
        ax4.tick_params(axis='y', labelcolor='green')
        ax4.grid(True, alpha=0.3)
        
        # Add CPU requirement line (60% from PDF)
        ax4.axhline(y=60, color='red', linestyle='--', alpha=0.7, linewidth=1.5)
        ax4.text(len(scenarios)-0.5, 62, 'Max (60%)', color='red', fontsize=9)
        
        plt.tight_layout()
        plt.savefig('analysis_plots/summary_analysis.png', dpi=300, bbox_inches='tight')
        plt.savefig('analysis_plots/summary_analysis.pdf', bbox_inches='tight')
        plt.close()
        print("  ✅ Saved: analysis_plots/summary_analysis.png")
        
        # 2. Detailed latency distribution for baseline
        if 'baseline' in all_metrics:
            baseline_data = self.load_scenario_data('baseline')
            if baseline_data['client_logs']:
                try:
                    baseline_df = pd.concat(baseline_data['client_logs'])
                    
                    # Find latency column
                    latency_col = None
                    for col in ['latency_ms', 'latency']:
                        if col in baseline_df.columns:
                            latency_col = col
                            break
                    
                    if latency_col and latency_col in baseline_df.columns:
                        plt.figure(figsize=(10, 6))
                        latency_data = baseline_df[latency_col].dropna()
                        
                        if len(latency_data) > 0:
                            plt.hist(latency_data, bins=50, alpha=0.7, edgecolor='black', color='steelblue')
                            
                            median_val = np.median(latency_data)
                            percentile_95 = np.percentile(latency_data, 95)
                            
                            plt.axvline(median_val, color='red', linestyle='--', 
                                      label=f'Median: {median_val:.1f}ms')
                            plt.axvline(percentile_95, color='orange', linestyle='--', 
                                      label=f'95th %ile: {percentile_95:.1f}ms')
                            
                            plt.xlabel('Latency (ms)', fontweight='bold')
                            plt.ylabel('Frequency', fontweight='bold')
                            plt.title('Baseline Latency Distribution', fontweight='bold')
                            plt.legend()
                            plt.grid(True, alpha=0.3)
                            
                            plt.savefig('analysis_plots/baseline_latency_distribution.png', 
                                      dpi=300, bbox_inches='tight')
                            plt.close()
                            print("  ✅ Saved: analysis_plots/baseline_latency_distribution.png")
                except Exception as e:
                    print(f"  Warning: Could not create baseline plot: {e}")
        
        # 3. Position error vs loss rate
        plt.figure(figsize=(10, 6))
        
        loss_scenarios = ['baseline', 'loss_2pct', 'loss_5pct']
        plot_errors_mean = []
        plot_errors_95th = []
        plot_loss_rates = []
        
        for scenario in loss_scenarios:
            if scenario in all_metrics and scenario in position_errors:
                errors = position_errors[scenario]
                if errors:
                    plot_errors_mean.append(np.mean(errors))
                    plot_errors_95th.append(np.percentile(errors, 95))
                    plot_loss_rates.append(all_metrics[scenario].get('packet_loss_rate', 0) * 100)
        
        if len(plot_errors_mean) > 1:
            x_vals = np.array(plot_loss_rates)
            y_mean = np.array(plot_errors_mean)
            y_95th = np.array(plot_errors_95th)
            
            plt.plot(x_vals, y_mean, 'bo-', linewidth=2, markersize=10, label='Mean Error')
            plt.plot(x_vals, y_95th, 'ro-', linewidth=2, markersize=10, label='95th %ile Error')
            
            # Label each point
            for i, (x, y) in enumerate(zip(x_vals, y_mean)):
                plt.text(x, y + 0.05, f'{loss_scenarios[i]}', fontsize=9, ha='center')
            
            # PDF requirements
            plt.axhline(y=0.5, color='green', linestyle='--', alpha=0.7, 
                       linewidth=1.5, label='LAN Requirement (0.5)')
            plt.axhline(y=1.5, color='orange', linestyle='--', alpha=0.7, 
                       linewidth=1.5, label='WAN Requirement (1.5)')
            
            plt.xlabel('Packet Loss Rate (%)', fontweight='bold')
            plt.ylabel('Position Error (units)', fontweight='bold')
            plt.title('Position Error vs Packet Loss Rate', fontweight='bold')
            plt.legend()
            plt.grid(True, alpha=0.3)
            
            plt.savefig('analysis_plots/position_error_vs_loss.png', dpi=300, bbox_inches='tight')
            plt.close()
            print("  ✅ Saved: analysis_plots/position_error_vs_loss.png")
        
        print("  ✅ All plots generated")
    
    def save_detailed_report(self, all_metrics, position_errors):
        """Save detailed CSV report as per PDF requirements"""
        print("\n📄 Generating detailed report...")
        
        report_data = []
        
        for scenario in self.scenarios:
            if scenario in all_metrics:
                metrics = all_metrics[scenario]
                errors = position_errors.get(scenario, [])
                
                row = {
                    'scenario': scenario,
                    'runs_analyzed': metrics.get('runs_analyzed', 0),
                    'total_packets': metrics.get('total_packets', 0),
                    'unique_clients': metrics.get('unique_clients', 0),
                    'latency_mean_ms': metrics.get('latency_mean', 0),
                    'latency_median_ms': metrics.get('latency_median', 0),
                    'latency_95th_ms': metrics.get('latency_95th', 0),
                    'latency_std_ms': metrics.get('latency_std', 0),
                    'latency_samples': metrics.get('latency_samples', 0),
                    'jitter_mean_ms': metrics.get('jitter_mean', 0),
                    'jitter_95th_ms': metrics.get('jitter_95th', 0),
                    'sequence_gaps': metrics.get('sequence_gaps', 0),
                    'packet_loss_rate_percent': metrics.get('packet_loss_rate', 0) * 100,
                    'server_cpu_mean_percent': metrics.get('server_cpu_mean', 0),
                    'server_cpu_max_percent': metrics.get('server_cpu_max', 0),
                    'total_bytes_sent_mb': metrics.get('total_bytes_sent', 0) / (1024 * 1024) if metrics.get('total_bytes_sent') else 0,
                    'position_error_mean': np.mean(errors) if errors else 0,
                    'position_error_median': np.median(errors) if errors else 0,
                    'position_error_95th': np.percentile(errors, 95) if errors else 0,
                    'position_error_samples': len(errors) if errors else 0,
                }
                report_data.append(row)
        
        df = pd.DataFrame(report_data)
        
        # Save CSV
        csv_path = 'detailed_analysis_report.csv'
        df.to_csv(csv_path, index=False)
        print(f"  ✅ Saved CSV: {csv_path}")
        
        # Save formatted text report with ASCII characters only
        txt_path = 'analysis_summary.txt'
        with open(txt_path, 'w', encoding='utf-8') as f:  # Explicit UTF-8 encoding
            f.write("="*80 + "\n")
            f.write("GRID CLASH - EXPERIMENTAL RESULTS SUMMARY\n")
            f.write("="*80 + "\n")
            f.write(f"Analysis date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Results directory: {self.results_dir}\n")
            f.write("="*80 + "\n\n")
            
            for scenario in self.scenarios:
                if scenario in all_metrics:
                    metrics = all_metrics[scenario]
                    errors = position_errors.get(scenario, [])
                    
                    f.write(f"SCENARIO: {scenario.upper()}\n")
                    f.write("-"*40 + "\n")
                    
                    f.write(f"Runs analyzed: {metrics.get('runs_analyzed', 0)}/5\n")
                    f.write(f"Total packets: {metrics.get('total_packets', 0):,}\n")
                    f.write(f"Unique clients: {metrics.get('unique_clients', 0)}\n")
                    
                    if 'latency_mean' in metrics:
                        f.write(f"Latency: {metrics['latency_mean']:.1f}ms mean, "
                            f"{metrics['latency_median']:.1f}ms median, "
                            f"{metrics['latency_95th']:.1f}ms 95th %ile\n")
                    
                    if 'jitter_mean' in metrics:
                        f.write(f"Jitter: {metrics['jitter_mean']:.1f}ms mean, "
                            f"{metrics['jitter_95th']:.1f}ms 95th %ile\n")
                    
                    if 'packet_loss_rate' in metrics:
                        f.write(f"Packet loss: {metrics['packet_loss_rate']*100:.2f}% "
                            f"({metrics.get('sequence_gaps', 0)} gaps)\n")
                    
                    if 'server_cpu_mean' in metrics:
                        f.write(f"Server CPU: {metrics['server_cpu_mean']:.1f}% mean, "
                            f"{metrics['server_cpu_max']:.1f}% max\n")
                    
                    if errors:
                        f.write(f"Position error: {np.mean(errors):.3f} mean, "
                            f"{np.median(errors):.3f} median, "
                            f"{np.percentile(errors, 95):.3f} 95th %ile\n")
                    
                    # PDF Acceptance Criteria (ASCII only for Windows)
                    f.write("\nPDF ACCEPTANCE CRITERIA:\n")
                    
                    if scenario == "baseline":
                        latency_ok = metrics.get('latency_mean', 999) <= 50
                        cpu_ok = metrics.get('server_cpu_mean', 999) <= 60
                        
                        f.write(f"  Latency <= 50ms: {'[PASS]' if latency_ok else '[FAIL]'} "
                            f"({metrics.get('latency_mean', 0):.1f}ms)\n")
                        f.write(f"  CPU <= 60%: {'[PASS]' if cpu_ok else '[FAIL]'} "
                            f"({metrics.get('server_cpu_mean', 0):.1f}%)\n")
                    
                    elif scenario == "loss_2pct":
                        if errors:
                            error_ok = np.mean(errors) <= 0.5
                            f.write(f"  Position error <= 0.5 units: "
                                f"{'[PASS]' if error_ok else '[FAIL]'} "
                                f"({np.mean(errors):.3f} units)\n")
                    
                    elif scenario == "loss_5pct":
                        # Critical events delivered >=99% within 200ms
                        if 'latency_95th' in metrics:
                            critical_ok = metrics['latency_95th'] <= 200
                            f.write(f"  95th %ile latency <= 200ms: "
                                f"{'[PASS]' if critical_ok else '[FAIL]'} "
                                f"({metrics['latency_95th']:.1f}ms)\n")
                    
                    f.write("\n")
        
        print(f"  ✅ Saved text summary: {txt_path}")
        
        # Save raw metrics JSON
        json_path = 'raw_metrics.json'
        with open(json_path, 'w') as f:
            json.dump(all_metrics, f, indent=2, default=str)
        print(f"  ✅ Saved raw metrics: {json_path}")

def main():
    """Main analysis function"""
    print("="*80)
    print("GRID CLASH - EXPERIMENTAL RESULTS ANALYZER")
    print("="*80)
    
    parser = argparse.ArgumentParser(description="Analyze Grid Clash test results")
    parser.add_argument("--results-dir", default="test_results", 
                       help="Directory containing test results")
    parser.add_argument("--scenario", choices=["all", "baseline", "loss_2pct", 
                                              "loss_5pct", "delay_100ms", "delay_jitter"],
                       default="all", help="Scenario to analyze")
    args = parser.parse_args()
    
    print(f"Results directory: {args.results_dir}")
    print(f"Scenario: {args.scenario}")
    print("="*80)
    
    # Check if results directory exists
    if not os.path.exists(args.results_dir):
        print(f"❌ Error: Results directory '{args.results_dir}' not found!")
        print(f"   Current directory: {os.getcwd()}")
        print(f"   Available directories: {[d for d in os.listdir('.') if os.path.isdir(d)]}")
        return
    
    analyzer = ResultsAnalyzer(args.results_dir)
    
    # Determine which scenarios to analyze
    if args.scenario == "all":
        scenarios_to_analyze = analyzer.scenarios
    else:
        scenarios_to_analyze = [args.scenario]
    
    # Analyze each scenario
    all_metrics = {}
    position_errors = {}
    
    for scenario in scenarios_to_analyze:
        print(f"\n📊 Analyzing scenario: {scenario}")
        
        # Load data
        data = analyzer.load_scenario_data(scenario)
        
        if not data['client_logs']:
            print(f"  ⚠️  No data found for {scenario}")
            continue
        
        # Calculate metrics
        metrics = analyzer.calculate_metrics(scenario, data)
        all_metrics[scenario] = metrics
        
        # Calculate position error
        errors = analyzer.calculate_position_error(scenario, data)
        position_errors[scenario] = errors
    
    # Generate outputs
    if all_metrics:
        analyzer.generate_plots(all_metrics, position_errors)
        analyzer.save_detailed_report(all_metrics, position_errors)
    else:
        print("\n❌ No data was analyzed. Check that:")
        print(f"   1. Test results exist in '{args.results_dir}'")
        print(f"   2. CSV files are in {args.results_dir}/scenario_name/run_*/")
        print(f"   3. CSV files follow naming: client_log_*.csv and server_log.csv")
    
    print("\n" + "="*80)
    print("ANALYSIS COMPLETE")
    print("="*80)
    print("Output files created:")
    print("  📈 analysis_plots/ - Contains all graphs")
    print("  📊 detailed_analysis_report.csv - Detailed metrics (Excel-friendly)")
    print("  📋 analysis_summary.txt - Human-readable summary")
    print("  📄 raw_metrics.json - Raw data for further analysis")
    print("="*80)

if __name__ == "__main__":
    main()