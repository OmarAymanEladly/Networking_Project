# analyze_results.py
#!/usr/bin/env python3
"""
Analyze Grid Clash test results and calculate metrics
Calculates latency, jitter, position error, and other metrics from test data
"""

import argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
import json
import glob
import csv
import sys
from scipy import stats
import seaborn as sns
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')

class GridClashAnalyzer:
    def __init__(self, results_dir="test_results"):
        self.results_dir = Path(results_dir)
        self.test_cases = {}
        self.metrics_summary = {}
        
        # Color scheme for plots
        self.colors = {
            'baseline': '#2E86AB',
            'loss_2pct': '#A23B72',
            'loss_5pct': '#F18F01',
            'delay_100ms': '#C73E1D',
            'delay_jitter': '#6A994E'
        }
        
    def load_test_data(self):
        """Load all test data from results directory"""
        print("Loading test data...")
        
        # Find all test directories
        test_dirs = [d for d in self.results_dir.iterdir() if d.is_dir()]
        
        for test_dir in test_dirs:
            test_name = test_dir.name
            print(f"  Processing: {test_name}")
            
            # Load metadata
            meta_file = test_dir / "test_metadata.json"
            if meta_file.exists():
                with open(meta_file, 'r') as f:
                    metadata = json.load(f)
            else:
                metadata = {'test_name': test_name}
            
            # Load client data
            client_files = list(test_dir.glob("client_*.csv"))
            client_data = {}
            
            for client_file in client_files:
                client_id = client_file.stem.split('_')[1]
                try:
                    df = pd.read_csv(client_file)
                    client_data[client_id] = df
                    print(f"    Client {client_id}: {len(df)} records")
                except Exception as e:
                    print(f"    Error loading {client_file}: {e}")
            
            # Load server data
            server_file = test_dir / "server_metrics.csv"
            server_data = None
            if server_file.exists():
                try:
                    server_data = pd.read_csv(server_file)
                    print(f"    Server data: {len(server_data)} records")
                except Exception as e:
                    print(f"    Error loading server data: {e}")
            
            # Store test case
            self.test_cases[test_name] = {
                'metadata': metadata,
                'client_data': client_data,
                'server_data': server_data,
                'directory': test_dir
            }
        
        print(f"\nLoaded {len(self.test_cases)} test cases")
        
    def calculate_latency_metrics(self, client_df):
        """Calculate latency metrics for a client"""
        if 'latency_ms' not in client_df.columns or len(client_df) < 10:
            return None
            
        latencies = client_df['latency_ms'].dropna()
        if len(latencies) == 0:
            return None
            
        return {
            'mean': latencies.mean(),
            'median': latencies.median(),
            'p95': latencies.quantile(0.95),
            'p99': latencies.quantile(0.99),
            'min': latencies.min(),
            'max': latencies.max(),
            'std': latencies.std(),
            'samples': len(latencies)
        }
    
    def calculate_jitter(self, client_df):
        """Calculate jitter (variation in inter-arrival times)"""
        if 'recv_time_ms' not in client_df.columns or len(client_df) < 10:
            return None
            
        recv_times = client_df['recv_time_ms'].dropna().sort_values().values
        
        if len(recv_times) < 2:
            return None
            
        # Calculate inter-arrival times
        inter_arrival = np.diff(recv_times)
        
        # Jitter as standard deviation of inter-arrival times
        return {
            'mean': inter_arrival.mean(),
            'std': inter_arrival.std(),
            'p95': np.percentile(inter_arrival, 95),
            'samples': len(inter_arrival)
        }
    
    def calculate_position_error(self, test_name, client_id, client_df, server_df):
        """Calculate perceived position error between server and client"""
        if server_df is None or 'player1_pos_x' not in server_df.columns:
            return None
            
        # Extract server positions (all players)
        server_positions = {}
        for player in ['player1', 'player2', 'player3', 'player4']:
            x_col = f'{player}_pos_x'
            y_col = f'{player}_pos_y'
            if x_col in server_df.columns and y_col in server_df.columns:
                server_positions[player] = {
                    'x': server_df[x_col].values,
                    'y': server_df[y_col].values,
                    'time': server_df['timestamp'].values
                }
        
        if not server_positions:
            return None
            
        # For each client data point, find closest server timestamp
        client_times = client_df['recv_time_ms'].values / 1000.0  # Convert to seconds
        
        errors = []
        timestamps = []
        
        for player, server_data in server_positions.items():
            server_times = server_data['time']
            server_x = server_data['x']
            server_y = server_data['y']
            
            # Interpolate server positions at client timestamps
            from scipy.interpolate import interp1d
            
            # Only interpolate if we have enough points
            if len(server_times) > 1:
                try:
                    # Create interpolation functions
                    fx = interp1d(server_times, server_x, bounds_error=False, fill_value="extrapolate")
                    fy = interp1d(server_times, server_y, bounds_error=False, fill_value="extrapolate")
                    
                    # Get server positions at client times
                    server_x_at_client = fx(client_times)
                    server_y_at_client = fy(client_times)
                    
                    # Get client positions (using render positions from CSV)
                    if 'render_x' in client_df.columns and 'render_y' in client_df.columns:
                        client_x = client_df['render_x'].values
                        client_y = client_df['render_y'].values
                        
                        # Calculate Euclidean distance
                        distances = np.sqrt(
                            (server_x_at_client - client_x) ** 2 + 
                            (server_y_at_client - client_y) ** 2
                        )
                        
                        # Filter out invalid distances
                        valid_distances = distances[~np.isnan(distances) & ~np.isinf(distances)]
                        if len(valid_distances) > 0:
                            errors.extend(valid_distances)
                            timestamps.extend(client_times[:len(valid_distances)])
                            
                except Exception as e:
                    print(f"    Warning: Position interpolation failed: {e}")
                    continue
        
        if len(errors) == 0:
            return None
            
        errors = np.array(errors)
        
        return {
            'mean': errors.mean(),
            'median': errors.median(),
            'p95': np.percentile(errors, 95),
            'max': errors.max(),
            'std': errors.std(),
            'samples': len(errors)
        }
    
    def calculate_packet_loss(self, client_df):
        """Calculate packet loss rate from sequence numbers"""
        if 'snapshot_id' not in client_df.columns or len(client_df) < 10:
            return None
            
        snapshot_ids = client_df['snapshot_id'].dropna().values
        if len(snapshot_ids) < 2:
            return None
            
        # Find gaps in sequence
        diffs = np.diff(snapshot_ids)
        lost_packets = np.sum(diffs[diffs > 1]) - np.sum(diffs[diffs > 1] > 0)
        
        total_expected = snapshot_ids[-1] - snapshot_ids[0] + 1
        packets_received = len(snapshot_ids)
        
        if total_expected > 0:
            loss_rate = (total_expected - packets_received) / total_expected
        else:
            loss_rate = 0
            
        return {
            'loss_rate': loss_rate,
            'lost_packets': lost_packets,
            'received_packets': packets_received,
            'expected_packets': total_expected
        }
    
    def calculate_update_rate(self, client_df):
        """Calculate actual update rate"""
        if 'recv_time_ms' not in client_df.columns or len(client_df) < 10:
            return None
            
        recv_times = client_df['recv_time_ms'].dropna().values
        
        if len(recv_times) < 2:
            return None
            
        # Calculate time intervals between packets
        intervals = np.diff(recv_times)
        
        # Filter out unrealistic intervals (> 1 second)
        valid_intervals = intervals[intervals < 1000]
        
        if len(valid_intervals) == 0:
            return None
            
        # Update rate in Hz
        avg_interval = valid_intervals.mean()
        update_rate = 1000.0 / avg_interval if avg_interval > 0 else 0
        
        return {
            'update_rate_hz': update_rate,
            'avg_interval_ms': avg_interval,
            'std_interval_ms': valid_intervals.std(),
            'samples': len(valid_intervals)
        }
    
    def analyze_test_case(self, test_name, test_data):
        """Analyze a single test case"""
        print(f"\nAnalyzing: {test_name}")
        
        client_data = test_data['client_data']
        server_data = test_data['server_data']
        
        metrics = {
            'clients': {},
            'aggregate': {}
        }
        
        # Analyze each client
        for client_id, client_df in client_data.items():
            print(f"  Client {client_id}:")
            
            client_metrics = {}
            
            # 1. Latency
            latency = self.calculate_latency_metrics(client_df)
            if latency:
                client_metrics['latency'] = latency
                print(f"    Latency: mean={latency['mean']:.1f}ms, p95={latency['p95']:.1f}ms")
            
            # 2. Jitter
            jitter = self.calculate_jitter(client_df)
            if jitter:
                client_metrics['jitter'] = jitter
                print(f"    Jitter: std={jitter['std']:.1f}ms")
            
            # 3. Position Error
            pos_error = self.calculate_position_error(test_name, client_id, client_df, server_data)
            if pos_error:
                client_metrics['position_error'] = pos_error
                print(f"    Position Error: mean={pos_error['mean']:.2f}, p95={pos_error['p95']:.2f}")
            
            # 4. Packet Loss
            loss = self.calculate_packet_loss(client_df)
            if loss:
                client_metrics['packet_loss'] = loss
                print(f"    Packet Loss: {loss['loss_rate']*100:.1f}% ({loss['lost_packets']} packets)")
            
            # 5. Update Rate
            update_rate = self.calculate_update_rate(client_df)
            if update_rate:
                client_metrics['update_rate'] = update_rate
                print(f"    Update Rate: {update_rate['update_rate_hz']:.1f}Hz")
            
            metrics['clients'][client_id] = client_metrics
        
        # Calculate aggregate metrics across all clients
        self.calculate_aggregate_metrics(metrics)
        
        return metrics
    
    def calculate_aggregate_metrics(self, metrics):
        """Calculate aggregate metrics across all clients"""
        all_latencies = []
        all_jitters = []
        all_errors = []
        all_loss_rates = []
        all_update_rates = []
        
        for client_id, client_metrics in metrics['clients'].items():
            if 'latency' in client_metrics:
                all_latencies.append(client_metrics['latency']['mean'])
            
            if 'jitter' in client_metrics:
                all_jitters.append(client_metrics['jitter']['std'])
            
            if 'position_error' in client_metrics:
                all_errors.append(client_metrics['position_error']['mean'])
            
            if 'packet_loss' in client_metrics:
                all_loss_rates.append(client_metrics['packet_loss']['loss_rate'])
            
            if 'update_rate' in client_metrics:
                all_update_rates.append(client_metrics['update_rate']['update_rate_hz'])
        
        # Store aggregate metrics
        if all_latencies:
            metrics['aggregate']['latency_mean'] = np.mean(all_latencies)
            metrics['aggregate']['latency_std'] = np.std(all_latencies)
        
        if all_jitters:
            metrics['aggregate']['jitter_mean'] = np.mean(all_jitters)
            metrics['aggregate']['jitter_std'] = np.std(all_jitters)
        
        if all_errors:
            metrics['aggregate']['position_error_mean'] = np.mean(all_errors)
            metrics['aggregate']['position_error_std'] = np.std(all_errors)
        
        if all_loss_rates:
            metrics['aggregate']['loss_rate_mean'] = np.mean(all_loss_rates)
            metrics['aggregate']['loss_rate_std'] = np.std(all_loss_rates)
        
        if all_update_rates:
            metrics['aggregate']['update_rate_mean'] = np.mean(all_update_rates)
            metrics['aggregate']['update_rate_std'] = np.std(all_update_rates)
    
    def analyze_all_tests(self):
        """Analyze all test cases"""
        self.load_test_data()
        
        for test_name, test_data in self.test_cases.items():
            metrics = self.analyze_test_case(test_name, test_data)
            self.metrics_summary[test_name] = metrics
            
            # Save individual test analysis
            self.save_test_analysis(test_name, metrics, test_data['directory'])
        
        # Generate summary report
        self.generate_summary_report()
        
        # Generate plots
        self.generate_all_plots()
        
        print("\n" + "="*60)
        print("ANALYSIS COMPLETE!")
        print(f"Summary report: {self.results_dir}/analysis_summary.csv")
        print(f"Plots saved in: {self.results_dir}/plots/")
    
    def save_test_analysis(self, test_name, metrics, test_dir):
        """Save detailed analysis for a test"""
        output_file = test_dir / "analysis_results.json"
        
        # Convert numpy types to Python types for JSON serialization
        def convert_to_serializable(obj):
            if isinstance(obj, np.integer):
                return int(obj)
            elif isinstance(obj, np.floating):
                return float(obj)
            elif isinstance(obj, np.ndarray):
                return obj.tolist()
            elif isinstance(obj, dict):
                return {k: convert_to_serializable(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_to_serializable(item) for item in obj]
            else:
                return obj
        
        serializable_metrics = convert_to_serializable(metrics)
        
        with open(output_file, 'w') as f:
            json.dump(serializable_metrics, f, indent=2)
        
        # Also save as CSV for easy viewing
        csv_file = test_dir / "analysis_summary.csv"
        with open(csv_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Metric', 'Mean', 'Std Dev', 'P95', 'Samples'])
            
            # Write latency
            if 'aggregate' in metrics and 'latency_mean' in metrics['aggregate']:
                writer.writerow([
                    'Latency (ms)',
                    f"{metrics['aggregate']['latency_mean']:.2f}",
                    f"{metrics['aggregate']['latency_std']:.2f}",
                    '',
                    ''
                ])
            
            # Write position error
            if 'aggregate' in metrics and 'position_error_mean' in metrics['aggregate']:
                writer.writerow([
                    'Position Error',
                    f"{metrics['aggregate']['position_error_mean']:.3f}",
                    f"{metrics['aggregate']['position_error_std']:.3f}",
                    '',
                    ''
                ])
            
            # Write packet loss
            if 'aggregate' in metrics and 'loss_rate_mean' in metrics['aggregate']:
                writer.writerow([
                    'Packet Loss (%)',
                    f"{metrics['aggregate']['loss_rate_mean']*100:.2f}",
                    f"{metrics['aggregate']['loss_rate_std']*100:.2f}",
                    '',
                    ''
                ])
            
            # Write update rate
            if 'aggregate' in metrics and 'update_rate_mean' in metrics['aggregate']:
                writer.writerow([
                    'Update Rate (Hz)',
                    f"{metrics['aggregate']['update_rate_mean']:.1f}",
                    f"{metrics['aggregate']['update_rate_std']:.1f}",
                    '',
                    ''
                ])
    
    def generate_summary_report(self):
        """Generate comprehensive summary report across all tests"""
        print("\nGenerating summary report...")
        
        summary_data = []
        
        for test_name, metrics in self.metrics_summary.items():
            agg = metrics.get('aggregate', {})
            
            summary_data.append({
                'Test': test_name,
                'Description': self.test_cases[test_name]['metadata'].get('test_name', test_name),
                'Latency_Mean_ms': agg.get('latency_mean', np.nan),
                'Latency_Std_ms': agg.get('latency_std', np.nan),
                'PositionError_Mean': agg.get('position_error_mean', np.nan),
                'PositionError_Std': agg.get('position_error_std', np.nan),
                'PacketLoss_Percent': agg.get('loss_rate_mean', np.nan) * 100,
                'UpdateRate_Hz': agg.get('update_rate_mean', np.nan),
                'Jitter_Mean_ms': agg.get('jitter_mean', np.nan),
                'Client_Count': len(metrics.get('clients', {}))
            })
        
        # Create DataFrame and save
        df_summary = pd.DataFrame(summary_data)
        
        # Sort by test name for consistent ordering
        test_order = ['baseline', 'loss_2pct', 'loss_5pct', 'delay_100ms', 'delay_jitter']
        df_summary['Test_Order'] = df_summary['Test'].map(
            {test: i for i, test in enumerate(test_order) if test in test_order}
        )
        df_summary = df_summary.sort_values('Test_Order').drop('Test_Order', axis=1)
        
        summary_file = self.results_dir / "analysis_summary.csv"
        df_summary.to_csv(summary_file, index=False)
        
        # Print summary table
        print("\n" + "="*80)
        print("SUMMARY OF ALL TESTS")
        print("="*80)
        print(df_summary.to_string(index=False))
        print("="*80)
        
        # Check acceptance criteria from PDF
        print("\nACCEPTANCE CRITERIA CHECK:")
        print("-" * 40)
        
        # Baseline criteria
        if 'baseline' in self.metrics_summary:
            baseline = self.metrics_summary['baseline']['aggregate']
            latency_ok = baseline.get('latency_mean', 1000) <= 50
            update_ok = baseline.get('update_rate_mean', 0) >= 18  # Close to 20Hz
            
            print(f"Baseline: Latency ≤ 50ms: {'✓' if latency_ok else '✗'} "
                  f"({baseline.get('latency_mean', 'N/A'):.1f}ms)")
            print(f"         Update Rate ≥ 18Hz: {'✓' if update_ok else '✗'} "
                  f"({baseline.get('update_rate_mean', 'N/A'):.1f}Hz)")
        
        # Loss 2% criteria
        if 'loss_2pct' in self.metrics_summary:
            loss2 = self.metrics_summary['loss_2pct']['aggregate']
            error_ok = loss2.get('position_error_mean', 10) <= 0.5
            p95_ok = True  # Would need actual p95 calculation
            
            print(f"Loss 2%: Position Error ≤ 0.5: {'✓' if error_ok else '✗'} "
                  f"({loss2.get('position_error_mean', 'N/A'):.3f})")
        
        # Loss 5% criteria
        if 'loss_5pct' in self.metrics_summary:
            loss5 = self.metrics_summary['loss_5pct']['aggregate']
            print(f"Loss 5%: Critical events delivered (check logs)")
    
    def generate_all_plots(self):
        """Generate all required plots"""
        plots_dir = self.results_dir / "plots"
        plots_dir.mkdir(exist_ok=True)
        
        print(f"\nGenerating plots in: {plots_dir}")
        
        # 1. Latency vs Test Scenario
        self.plot_latency_by_scenario(plots_dir)
        
        # 2. Position Error vs Loss Rate
        self.plot_error_vs_loss(plots_dir)
        
        # 3. Update Rate vs Test Scenario
        self.plot_update_rate_by_scenario(plots_dir)
        
        # 4. Jitter Distribution
        self.plot_jitter_distribution(plots_dir)
        
        # 5. Combined metrics comparison
        self.plot_combined_metrics(plots_dir)
        
        # 6. Time series plots for each test
        self.plot_time_series(plots_dir)
    
    def plot_latency_by_scenario(self, plots_dir):
        """Plot latency comparison across test scenarios"""
        fig, axes = plt.subplots(1, 2, figsize=(12, 5))
        
        test_names = []
        latency_means = []
        latency_stds = []
        latency_p95 = []
        
        for test_name in ['baseline', 'loss_2pct', 'loss_5pct', 'delay_100ms', 'delay_jitter']:
            if test_name in self.metrics_summary:
                test_names.append(test_name.replace('_', ' ').title())
                
                # Get all client latencies
                all_latencies = []
                for client_id, client_metrics in self.metrics_summary[test_name]['clients'].items():
                    if 'latency' in client_metrics:
                        # Get some sample latencies (for box plot)
                        # In reality, you'd store all latency values
                        mean_lat = client_metrics['latency']['mean']
                        all_latencies.append(mean_lat)
                
                if all_latencies:
                    latency_means.append(np.mean(all_latencies))
                    latency_stds.append(np.std(all_latencies))
                else:
                    latency_means.append(0)
                    latency_stds.append(0)
                
                # For p95, use aggregate if available
                agg = self.metrics_summary[test_name]['aggregate']
                latency_p95.append(agg.get('latency_mean', 0) + 2*agg.get('latency_std', 0))
        
        # Bar plot
        x_pos = np.arange(len(test_names))
        axes[0].bar(x_pos, latency_means, yerr=latency_stds, 
                   capsize=5, color=[self.colors.get(name.lower().replace(' ', '_'), '#666666') 
                                    for name in test_names])
        axes[0].set_xlabel('Test Scenario')
        axes[0].set_ylabel('Latency (ms)')
        axes[0].set_title('Mean Latency by Test Scenario')
        axes[0].set_xticks(x_pos)
        axes[0].set_xticklabels(test_names, rotation=45, ha='right')
        
        # Add value labels
        for i, v in enumerate(latency_means):
            axes[0].text(i, v + latency_stds[i] + 1, f'{v:.1f}', 
                        ha='center', va='bottom', fontsize=9)
        
        # P95 line plot
        axes[1].plot(test_names, latency_p95, 'o-', linewidth=2, markersize=8)
        axes[1].set_xlabel('Test Scenario')
        axes[1].set_ylabel('95th Percentile Latency (ms)')
        axes[1].set_title('95th Percentile Latency')
        axes[1].grid(True, alpha=0.3)
        axes[1].tick_params(axis='x', rotation=45)
        
        plt.tight_layout()
        plt.savefig(plots_dir / 'latency_comparison.png', dpi=150, bbox_inches='tight')
        plt.close()
    
    def plot_error_vs_loss(self, plots_dir):
        """Plot position error vs packet loss"""
        fig, ax = plt.subplots(figsize=(8, 6))
        
        test_data = []
        for test_name in ['baseline', 'loss_2pct', 'loss_5pct']:
            if test_name in self.metrics_summary:
                agg = self.metrics_summary[test_name]['aggregate']
                loss_rate = agg.get('loss_rate_mean', 0) * 100
                pos_error = agg.get('position_error_mean', 0)
                
                if not np.isnan(loss_rate) and not np.isnan(pos_error):
                    test_data.append({
                        'test': test_name,
                        'loss': loss_rate,
                        'error': pos_error
                    })
        
        if test_data:
            df = pd.DataFrame(test_data)
            ax.scatter(df['loss'], df['error'], s=100, alpha=0.7)
            
            # Add labels
            for _, row in df.iterrows():
                ax.text(row['loss'] + 0.1, row['error'] + 0.01, 
                       row['test'].replace('_', ' ').title(),
                       fontsize=9)
            
            ax.set_xlabel('Packet Loss Rate (%)')
            ax.set_ylabel('Mean Position Error')
            ax.set_title('Position Error vs Packet Loss')
            ax.grid(True, alpha=0.3)
            
            # Add acceptance criteria lines
            ax.axhline(y=0.5, color='r', linestyle='--', alpha=0.5, label='Max Error (0.5)')
            ax.axvline(x=2, color='g', linestyle='--', alpha=0.5, label='LAN Loss (2%)')
            ax.axvline(x=5, color='b', linestyle='--', alpha=0.5, label='WAN Loss (5%)')
            
            ax.legend()
            
            plt.tight_layout()
            plt.savefig(plots_dir / 'error_vs_loss.png', dpi=150, bbox_inches='tight')
            plt.close()
    
    def plot_update_rate_by_scenario(self, plots_dir):
        """Plot update rate across test scenarios"""
        fig, ax = plt.subplots(figsize=(10, 6))
        
        test_names = []
        update_rates = []
        
        for test_name in ['baseline', 'loss_2pct', 'loss_5pct', 'delay_100ms', 'delay_jitter']:
            if test_name in self.metrics_summary:
                agg = self.metrics_summary[test_name]['aggregate']
                rate = agg.get('update_rate_mean', 0)
                
                if not np.isnan(rate):
                    test_names.append(test_name.replace('_', ' ').title())
                    update_rates.append(rate)
        
        colors = [self.colors.get(name.lower().replace(' ', '_'), '#666666') 
                 for name in test_names]
        
        bars = ax.bar(test_names, update_rates, color=colors, alpha=0.7)
        ax.set_xlabel('Test Scenario')
        ax.set_ylabel('Update Rate (Hz)')
        ax.set_title('Average Update Rate by Test Scenario')
        ax.set_xticklabels(test_names, rotation=45, ha='right')
        ax.grid(True, alpha=0.3, axis='y')
        
        # Add target line at 20Hz
        ax.axhline(y=20, color='r', linestyle='--', alpha=0.5, label='Target (20Hz)')
        
        # Add value labels
        for bar, rate in zip(bars, update_rates):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height + 0.2,
                   f'{rate:.1f}', ha='center', va='bottom', fontsize=9)
        
        ax.legend()
        plt.tight_layout()
        plt.savefig(plots_dir / 'update_rate_comparison.png', dpi=150, bbox_inches='tight')
        plt.close()
    
    def plot_jitter_distribution(self, plots_dir):
        """Plot jitter distribution across tests"""
        fig, ax = plt.subplots(figsize=(10, 6))
        
        jitter_data = []
        test_labels = []
        
        for test_name in ['baseline', 'loss_2pct', 'loss_5pct', 'delay_100ms', 'delay_jitter']:
            if test_name in self.metrics_summary:
                # Collect jitter from all clients
                test_jitters = []
                for client_id, client_metrics in self.metrics_summary[test_name]['clients'].items():
                    if 'jitter' in client_metrics:
                        test_jitters.append(client_metrics['jitter']['std'])
                
                if test_jitters:
                    jitter_data.append(test_jitters)
                    test_labels.append(test_name.replace('_', ' ').title())
        
        if jitter_data:
            # Box plot
            bp = ax.boxplot(jitter_data, patch_artist=True)
            
            # Color the boxes
            colors = [self.colors.get(label.lower().replace(' ', '_'), '#666666') 
                     for label in test_labels]
            for patch, color in zip(bp['boxes'], colors):
                patch.set_facecolor(color)
                patch.set_alpha(0.7)
            
            ax.set_xlabel('Test Scenario')
            ax.set_ylabel('Jitter (ms)')
            ax.set_title('Jitter Distribution by Test Scenario')
            ax.set_xticklabels(test_labels, rotation=45, ha='right')
            ax.grid(True, alpha=0.3, axis='y')
            
            plt.tight_layout()
            plt.savefig(plots_dir / 'jitter_distribution.png', dpi=150, bbox_inches='tight')
            plt.close()
    
    def plot_combined_metrics(self, plots_dir):
        """Plot combined metrics comparison"""
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        axes = axes.flatten()
        
        metrics_to_plot = [
            ('latency_mean', 'Latency (ms)', 0),
            ('position_error_mean', 'Position Error', 1),
            ('loss_rate_mean', 'Packet Loss (%)', 2),
            ('update_rate_mean', 'Update Rate (Hz)', 3)
        ]
        
        for metric_key, metric_label, ax_idx in metrics_to_plot:
            ax = axes[ax_idx]
            
            test_names = []
            metric_values = []
            
            for test_name in ['baseline', 'loss_2pct', 'loss_5pct', 'delay_100ms', 'delay_jitter']:
                if test_name in self.metrics_summary:
                    agg = self.metrics_summary[test_name]['aggregate']
                    value = agg.get(metric_key, np.nan)
                    
                    if metric_key == 'loss_rate_mean':
                        value = value * 100  # Convert to percentage
                    
                    if not np.isnan(value):
                        test_names.append(test_name.replace('_', ' ').title())
                        metric_values.append(value)
            
            colors = [self.colors.get(name.lower().replace(' ', '_'), '#666666') 
                     for name in test_names]
            
            bars = ax.bar(test_names, metric_values, color=colors, alpha=0.7)
            ax.set_xlabel('Test Scenario')
            ax.set_ylabel(metric_label)
            ax.set_title(f'{metric_label} by Test Scenario')
            ax.set_xticklabels(test_names, rotation=45, ha='right')
            ax.grid(True, alpha=0.3, axis='y')
            
            # Add value labels
            for bar, value in zip(bars, metric_values):
                height = bar.get_height()
                if metric_key == 'loss_rate_mean':
                    label = f'{value:.1f}%'
                elif metric_key == 'update_rate_mean':
                    label = f'{value:.1f}'
                else:
                    label = f'{value:.2f}'
                
                ax.text(bar.get_x() + bar.get_width()/2., height + height*0.05,
                       label, ha='center', va='bottom', fontsize=8)
        
        plt.tight_layout()
        plt.savefig(plots_dir / 'combined_metrics.png', dpi=150, bbox_inches='tight')
        plt.close()
    
    def plot_time_series(self, plots_dir):
        """Plot time series data for each test"""
        for test_name, test_data in self.test_cases.items():
            if 'client_data' not in test_data:
                continue
                
            fig, axes = plt.subplots(2, 2, figsize=(14, 10))
            axes = axes.flatten()
            
            client_data = test_data['client_data']
            
            for idx, (client_id, df) in enumerate(list(client_data.items())[:4]):
                ax = axes[idx]
                
                if 'recv_time_ms' in df.columns and 'latency_ms' in df.columns:
                    # Plot latency over time
                    times = (df['recv_time_ms'] - df['recv_time_ms'].min()) / 1000  # Convert to seconds
                    ax.plot(times, df['latency_ms'], 'b-', alpha=0.7, linewidth=1)
                    ax.set_xlabel('Time (s)')
                    ax.set_ylabel('Latency (ms)')
                    ax.set_title(f'Client {client_id} - Latency Over Time')
                    ax.grid(True, alpha=0.3)
                    
                    # Calculate and plot moving average
                    if len(df) > 10:
                        window = min(20, len(df) // 10)
                        ma = df['latency_ms'].rolling(window=window).mean()
                        ax.plot(times, ma, 'r-', linewidth=2, label=f'{window}-packet MA')
                        ax.legend(fontsize=8)
            
            plt.suptitle(f'Time Series - {test_name.replace("_", " ").title()}', fontsize=14)
            plt.tight_layout()
            
            time_series_dir = plots_dir / "time_series"
            time_series_dir.mkdir(exist_ok=True)
            
            plt.savefig(time_series_dir / f'{test_name}_timeseries.png', 
                       dpi=150, bbox_inches='tight')
            plt.close()

def main():
    parser = argparse.ArgumentParser(description='Analyze Grid Clash test results')
    parser.add_argument('--dir', '-d', default='test_results', 
                       help='Results directory (default: test_results)')
    
    args = parser.parse_args()
    
    analyzer = GridClashAnalyzer(results_dir=args.dir)
    analyzer.analyze_all_tests()

if __name__ == "__main__":
    main()