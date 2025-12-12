# analyze_result.py
#!/usr/bin/env python3
"""
Analyze Grid Clash test results from log files
Reads actual .log files from test_results directory
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
import json
import csv
import re
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')

class GridClashAnalyzer:
    def __init__(self, results_dir="test_results"):
        self.results_dir = Path(results_dir)
        self.metrics_summary = {}
        
        # Color scheme for plots
        self.colors = {
            'baseline': '#2E86AB',
            'loss_2pct': '#A23B72',
            'loss_5pct': '#F18F01',
            'delay_100ms': '#C73E1D',
            'delay_jitter': '#6A994E'
        }
    
    def parse_log_file(self, log_file):
        """Parse a log file to extract metrics"""
        metrics = defaultdict(list)
        
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    
                    # Skip empty lines
                    if not line:
                        continue
                    
                    # Extract latency (multiple patterns)
                    if 'latency' in line.lower() or 'ping' in line.lower() or 'rtt' in line.lower():
                        # Pattern 1: "Latency: 12.3ms"
                        match = re.search(r'[Ll]atency[\s:]+([\d.]+)\s*ms', line)
                        if match:
                            try:
                                metrics['latency'].append(float(match.group(1)))
                            except:
                                pass
                        
                        # Pattern 2: "ping: 12.3ms"
                        match = re.search(r'[Pp]ing[\s:]+([\d.]+)\s*ms', line)
                        if match:
                            try:
                                metrics['latency'].append(float(match.group(1)))
                            except:
                                pass
                        
                        # Pattern 3: "12.3ms latency"
                        match = re.search(r'([\d.]+)\s*ms.*[Ll]atency', line)
                        if match:
                            try:
                                metrics['latency'].append(float(match.group(1)))
                            except:
                                pass
                    
                    # Extract update rate
                    if 'update' in line.lower() and 'hz' in line.lower():
                        match = re.search(r'[Uu]pdate[\s:]+([\d.]+)\s*Hz', line)
                        if match:
                            try:
                                metrics['update_rate'].append(float(match.group(1)))
                            except:
                                pass
                    
                    # Extract packet loss
                    if 'lost' in line.lower() and 'packet' in line.lower():
                        # "Detected 3 lost packets"
                        match = re.search(r'[Dd]etected\s+(\d+)\s+lost packets', line)
                        if match:
                            try:
                                metrics['lost_packets'].append(int(match.group(1)))
                            except:
                                pass
                        
                        # "3 lost packets"
                        match = re.search(r'(\d+)\s+lost packets', line)
                        if match:
                            try:
                                metrics['lost_packets'].append(int(match.group(1)))
                            except:
                                pass
                    
                    # Extract sequence numbers for gap analysis
                    if 'snapshot' in line.lower():
                        match = re.search(r'[Ss]napshot[\s:_]+(\d+)', line)
                        if match:
                            try:
                                metrics['snapshot_ids'].append(int(match.group(1)))
                            except:
                                pass
                    
                    # Extract position data
                    if 'position' in line.lower() or 'pos:' in line.lower():
                        # Pattern: "position: [10, 20]" or "pos: [10, 20]"
                        match = re.search(r'[Pp]os(?:ition)?[\s:]*\[([\d.]+)[,\s]+([\d.]+)\]', line)
                        if match:
                            try:
                                x = float(match.group(1))
                                y = float(match.group(2))
                                metrics['positions'].append((x, y))
                            except:
                                pass
            
        except Exception as e:
            print(f"Error parsing {log_file.name}: {e}")
        
        return metrics
    
    def analyze_test_directory(self, test_dir):
        """Analyze all logs in a test directory"""
        test_name = test_dir.name
        print(f"\nAnalyzing: {test_name}")
        
        # Find all client log files
        client_logs = list(test_dir.glob("client_*.log"))
        
        if not client_logs:
            print(f"  No client log files found!")
            return None
        
        test_metrics = {
            'test_name': test_name,
            'client_count': len(client_logs),
            'clients': {},
            'aggregate': {}
        }
        
        all_latencies = []
        all_update_rates = []
        total_lost_packets = 0
        total_expected_packets = 0
        
        for client_log in client_logs:
            client_id = client_log.stem.split('_')[1]
            print(f"  Client {client_id}: {client_log.name}")
            
            # Parse the log file
            metrics = self.parse_log_file(client_log)
            test_metrics['clients'][client_id] = metrics
            
            # Calculate client metrics
            client_summary = {}
            
            if metrics['latency']:
                latencies = np.array(metrics['latency'])
                client_summary['latency_mean'] = float(np.mean(latencies))
                client_summary['latency_std'] = float(np.std(latencies))
                client_summary['latency_p95'] = float(np.percentile(latencies, 95))
                client_summary['latency_samples'] = len(latencies)
                all_latencies.extend(latencies)
                
                print(f"    Latency: {client_summary['latency_mean']:.1f}ms "
                      f"(±{client_summary['latency_std']:.1f}ms, {client_summary['latency_samples']} samples)")
            
            if metrics['update_rate']:
                rates = np.array(metrics['update_rate'])
                client_summary['update_rate_mean'] = float(np.mean(rates))
                client_summary['update_rate_std'] = float(np.std(rates))
                client_summary['update_rate_samples'] = len(rates)
                all_update_rates.extend(rates)
                
                print(f"    Update rate: {client_summary['update_rate_mean']:.1f}Hz")
            
            # Calculate packet loss from sequence gaps
            if metrics['snapshot_ids'] and len(metrics['snapshot_ids']) > 1:
                snapshot_ids = sorted(set(metrics['snapshot_ids']))
                if len(snapshot_ids) > 1:
                    diffs = np.diff(snapshot_ids)
                    lost_packets = sum(diff - 1 for diff in diffs if diff > 1)
                    expected_packets = snapshot_ids[-1] - snapshot_ids[0] + 1
                    
                    if expected_packets > 0:
                        loss_rate = (lost_packets / expected_packets) * 100
                        client_summary['packet_loss_rate'] = float(loss_rate)
                        client_summary['lost_packets'] = int(lost_packets)
                        client_summary['expected_packets'] = int(expected_packets)
                        
                        total_lost_packets += lost_packets
                        total_expected_packets += expected_packets
                        
                        print(f"    Packet loss: {loss_rate:.1f}% ({lost_packets}/{expected_packets})")
            
            # Add lost packets from direct detection
            if metrics['lost_packets']:
                direct_loss = sum(metrics['lost_packets'])
                print(f"    Direct lost packets: {direct_loss}")
                if 'lost_packets' in client_summary:
                    client_summary['lost_packets'] += direct_loss
                else:
                    client_summary['lost_packets'] = direct_loss
            
            # Store client summary
            test_metrics['clients'][client_id]['summary'] = client_summary
        
        # Calculate aggregate metrics
        if all_latencies:
            test_metrics['aggregate']['latency_mean'] = float(np.mean(all_latencies))
            test_metrics['aggregate']['latency_std'] = float(np.std(all_latencies))
            test_metrics['aggregate']['latency_p95'] = float(np.percentile(all_latencies, 95))
            test_metrics['aggregate']['latency_samples'] = len(all_latencies)
        
        if all_update_rates:
            test_metrics['aggregate']['update_rate_mean'] = float(np.mean(all_update_rates))
            test_metrics['aggregate']['update_rate_std'] = float(np.std(all_update_rates))
            test_metrics['aggregate']['update_rate_samples'] = len(all_update_rates)
        
        if total_expected_packets > 0:
            total_loss_rate = (total_lost_packets / total_expected_packets) * 100
            test_metrics['aggregate']['packet_loss_rate'] = float(total_loss_rate)
            test_metrics['aggregate']['lost_packets'] = total_lost_packets
            test_metrics['aggregate']['expected_packets'] = total_expected_packets
        
        # Estimate position error (simplified)
        all_positions = []
        for client_id, client_data in test_metrics['clients'].items():
            if 'positions' in client_data and client_data['positions']:
                positions = client_data['positions']
                if len(positions) > 1:
                    # Calculate variance as proxy for error
                    positions_array = np.array(positions)
                    position_variance = np.var(positions_array, axis=0)
                    avg_variance = np.mean(position_variance)
                    all_positions.append(avg_variance)
        
        if all_positions:
            test_metrics['aggregate']['position_error_mean'] = float(np.mean(all_positions))
            test_metrics['aggregate']['position_error_std'] = float(np.std(all_positions))
        
        return test_metrics
    
    def analyze_all_tests(self):
        """Analyze all test directories"""
        print("GRID CLASH TEST RESULTS ANALYSIS")
        print("=" * 60)
        
        if not self.results_dir.exists():
            print(f"Error: Directory '{self.results_dir}' not found!")
            return
        
        # Get all test directories
        test_dirs = [d for d in self.results_dir.iterdir() if d.is_dir()]
        
        if not test_dirs:
            print(f"No test directories found in '{self.results_dir}'")
            return
        
        # Analyze each test directory
        for test_dir in test_dirs:
            test_metrics = self.analyze_test_directory(test_dir)
            if test_metrics:
                self.metrics_summary[test_dir.name] = test_metrics
        
        if not self.metrics_summary:
            print("\nNo test data could be analyzed!")
            return
        
        # Generate summary report
        self.generate_summary_report()
        
        # Generate plots
        self.generate_plots()
        
        print("\n" + "=" * 60)
        print("ANALYSIS COMPLETE!")
        print(f"Summary report: {self.results_dir}/analysis_summary.csv")
        print(f"Plots saved in: {self.results_dir}/plots/")
    
    def generate_summary_report(self):
        """Generate summary report"""
        print("\nGenerating summary report...")
        
        summary_data = []
        
        # Define test order for consistent display
        test_order = ['baseline', 'loss_2pct', 'loss_5pct', 'delay_100ms', 'delay_jitter']
        
        for test_name in test_order:
            if test_name in self.metrics_summary:
                test = self.metrics_summary[test_name]
                agg = test.get('aggregate', {})
                
                row = {
                    'Test': test_name,
                    'Description': test_name.replace('_', ' ').title(),
                    'Clients': test.get('client_count', 0),
                    'Latency_Samples': agg.get('latency_samples', 0)
                }
                
                # Add metrics
                if 'latency_mean' in agg:
                    row.update({
                        'Latency_Mean_ms': f"{agg['latency_mean']:.1f}",
                        'Latency_Std_ms': f"{agg['latency_std']:.1f}",
                        'Latency_P95_ms': f"{agg.get('latency_p95', agg['latency_mean']):.1f}"
                    })
                else:
                    row.update({
                        'Latency_Mean_ms': 'N/A',
                        'Latency_Std_ms': 'N/A',
                        'Latency_P95_ms': 'N/A'
                    })
                
                if 'update_rate_mean' in agg:
                    row['Update_Rate_Hz'] = f"{agg['update_rate_mean']:.1f}"
                else:
                    row['Update_Rate_Hz'] = 'N/A'
                
                if 'packet_loss_rate' in agg:
                    row['PacketLoss_%'] = f"{agg['packet_loss_rate']:.1f}"
                else:
                    row['PacketLoss_%'] = 'N/A'
                
                if 'position_error_mean' in agg:
                    row['Position_Error'] = f"{agg['position_error_mean']:.3f}"
                else:
                    row['Position_Error'] = 'N/A'
                
                summary_data.append(row)
        
        # Save to CSV
        if summary_data:
            df = pd.DataFrame(summary_data)
            summary_file = self.results_dir / "analysis_summary.csv"
            df.to_csv(summary_file, index=False)
            
            # Print summary
            print("\n" + "="*80)
            print("SUMMARY OF ALL TESTS")
            print("="*80)
            
            # Create formatted table
            headers = ['Test', 'Clients', 'Latency(ms)', 'Update(Hz)', 'Loss(%)', 'Pos_Err', 'Samples']
            rows = []
            
            for row in summary_data:
                latency = f"{row.get('Latency_Mean_ms', 'N/A')}"
                if row.get('Latency_Std_ms', 'N/A') != 'N/A':
                    latency += f" ±{row['Latency_Std_ms']}"
                
                rows.append([
                    row['Test'],
                    str(row['Clients']),
                    latency,
                    row.get('Update_Rate_Hz', 'N/A'),
                    row.get('PacketLoss_%', 'N/A'),
                    row.get('Position_Error', 'N/A'),
                    str(row['Latency_Samples'])
                ])
            
            # Print table
            col_widths = [12, 8, 15, 10, 10, 10, 10]
            header_fmt = "  ".join(f"{h:<{w}}" for h, w in zip(headers, col_widths))
            print(header_fmt)
            print("-" * 80)
            
            for row in rows:
                row_fmt = "  ".join(f"{str(cell):<{w}}" for cell, w in zip(row, col_widths))
                print(row_fmt)
            
            print("="*80)
            
            # Check acceptance criteria
            self.check_acceptance_criteria()
    
    def check_acceptance_criteria(self):
        """Check acceptance criteria from PDF"""
        print("\nACCEPTANCE CRITERIA CHECK:")
        print("-" * 40)
        
        if 'baseline' in self.metrics_summary:
            baseline = self.metrics_summary['baseline'].get('aggregate', {})
            
            if 'latency_mean' in baseline:
                latency = baseline['latency_mean']
                latency_ok = latency <= 50
                status = '✓' if latency_ok else '✗'
                print(f"Baseline: Latency ≤ 50ms: {status} ({latency:.1f}ms)")
            else:
                print(f"Baseline: Latency ≤ 50ms: ? (No data)")
            
            if 'update_rate_mean' in baseline:
                update_rate = baseline['update_rate_mean']
                update_ok = update_rate >= 18
                status = '✓' if update_ok else '✗'
                print(f"         Update Rate ≥ 18Hz: {status} ({update_rate:.1f}Hz)")
            else:
                print(f"         Update Rate ≥ 18Hz: ? (No data)")
        
        if 'loss_2pct' in self.metrics_summary:
            loss2 = self.metrics_summary['loss_2pct'].get('aggregate', {})
            
            if 'position_error_mean' in loss2:
                error = loss2['position_error_mean']
                error_ok = error <= 0.5
                status = '✓' if error_ok else '✗'
                print(f"Loss 2%: Position Error ≤ 0.5: {status} ({error:.3f})")
            else:
                print(f"Loss 2%: Position Error ≤ 0.5: ? (No data)")
        
        if 'loss_5pct' in self.metrics_summary:
            loss5 = self.metrics_summary['loss_5pct'].get('aggregate', {})
            
            if 'packet_loss_rate' in loss5:
                loss_rate = loss5['packet_loss_rate']
                print(f"Loss 5%: Packet loss ~{loss_rate:.1f}%")
            
            print(f"Loss 5%: Critical events delivered (check logs)")
        
        print("-" * 40)
    
    def generate_plots(self):
        """Generate plots"""
        plots_dir = self.results_dir / "plots"
        plots_dir.mkdir(exist_ok=True)
        
        print(f"\nGenerating plots in: {plots_dir}")
        
        # Prepare data
        test_names = []
        latency_means = []
        latency_stds = []
        update_rates = []
        packet_losses = []
        position_errors = []
        
        test_order = ['baseline', 'loss_2pct', 'loss_5pct', 'delay_100ms', 'delay_jitter']
        
        for test_name in test_order:
            if test_name in self.metrics_summary:
                agg = self.metrics_summary[test_name].get('aggregate', {})
                
                if 'latency_mean' in agg:
                    test_names.append(test_name.replace('_', ' ').title())
                    latency_means.append(agg['latency_mean'])
                    latency_stds.append(agg.get('latency_std', 0))
                    
                    if 'update_rate_mean' in agg:
                        update_rates.append(agg['update_rate_mean'])
                    else:
                        update_rates.append(0)
                    
                    if 'packet_loss_rate' in agg:
                        packet_losses.append(agg['packet_loss_rate'])
                    else:
                        packet_losses.append(0)
                    
                    if 'position_error_mean' in agg:
                        position_errors.append(agg['position_error_mean'])
                    else:
                        position_errors.append(0)
        
        if not test_names:
            print("No data available for plotting")
            return
        
        # 1. Latency plot
        self.plot_metric(test_names, latency_means, latency_stds, 
                        'Latency (ms)', 'latency_comparison.png', 
                        plots_dir, target=50)
        
        # 2. Update rate plot
        if any(r > 0 for r in update_rates):
            self.plot_metric(test_names, update_rates, None,
                           'Update Rate (Hz)', 'update_rate_comparison.png',
                           plots_dir, target=20)
        
        # 3. Packet loss plot
        if any(l > 0 for l in packet_losses):
            self.plot_metric(test_names, packet_losses, None,
                           'Packet Loss (%)', 'packet_loss_comparison.png',
                           plots_dir)
        
        # 4. Combined metrics
        self.plot_combined_metrics(plots_dir, test_names, 
                                  latency_means, update_rates, 
                                  packet_losses, position_errors)
    
    def plot_metric(self, test_names, values, errors, ylabel, filename, plots_dir, target=None):
        """Plot a single metric"""
        plt.figure(figsize=(10, 6))
        
        x_pos = np.arange(len(test_names))
        colors = [self.colors.get(name.lower().replace(' ', '_'), '#666666') 
                 for name in test_names]
        
        if errors:
            plt.bar(x_pos, values, yerr=errors, capsize=5, 
                   color=colors, alpha=0.7, width=0.6)
        else:
            plt.bar(x_pos, values, color=colors, alpha=0.7, width=0.6)
        
        plt.xlabel('Test Scenario')
        plt.ylabel(ylabel)
        plt.title(f'{ylabel} by Test Scenario')
        plt.xticks(x_pos, test_names, rotation=45, ha='right')
        plt.grid(True, alpha=0.3, axis='y')
        
        # Add target line if specified
        if target is not None:
            plt.axhline(y=target, color='red', linestyle='--', alpha=0.5, label=f'Target ({target})')
            plt.legend()
        
        # Add value labels
        for i, v in enumerate(values):
            if v > 0 or ylabel == 'Latency (ms)':  # Always show latency
                y_err = errors[i] if errors and i < len(errors) else 0
                plt.text(i, v + y_err + (v * 0.05 if v > 0 else 1), 
                       f'{v:.1f}', ha='center', va='bottom', fontsize=9)
        
        plt.tight_layout()
        plt.savefig(plots_dir / filename, dpi=150, bbox_inches='tight')
        plt.close()
        
        print(f"  Created: {filename}")
    
    def plot_combined_metrics(self, plots_dir, test_names, latency_means, 
                             update_rates, packet_losses, position_errors):
        """Plot combined metrics"""
        # Determine which metrics have data
        metrics_data = []
        labels = []
        
        if any(l > 0 for l in latency_means):
            metrics_data.append(latency_means)
            labels.append('Latency (ms)')
        
        if any(r > 0 for r in update_rates):
            metrics_data.append(update_rates)
            labels.append('Update Rate (Hz)')
        
        if any(l > 0 for l in packet_losses):
            metrics_data.append(packet_losses)
            labels.append('Packet Loss (%)')
        
        if any(e > 0 for e in position_errors):
            metrics_data.append(position_errors)
            labels.append('Position Error')
        
        if len(metrics_data) == 0:
            return
        
        n_metrics = len(metrics_data)
        fig, axes = plt.subplots(1, n_metrics, figsize=(5*n_metrics, 6))
        if n_metrics == 1:
            axes = [axes]
        
        colors = [self.colors.get(name.lower().replace(' ', '_'), '#666666') 
                 for name in test_names]
        
        for idx, (data, label) in enumerate(zip(metrics_data, labels)):
            ax = axes[idx]
            bars = ax.bar(test_names, data, color=colors, alpha=0.7, width=0.6)
            
            ax.set_xlabel('Test Scenario')
            ax.set_ylabel(label)
            ax.set_title(label)
            ax.set_xticklabels(test_names, rotation=45, ha='right')
            ax.grid(True, alpha=0.3, axis='y')
            
            # Add value labels
            for i, v in enumerate(data):
                if v > 0 or label == 'Latency (ms)':
                    ax.text(i, v + (v * 0.05 if v > 0 else 0.01), 
                           f'{v:.1f}', ha='center', va='bottom', fontsize=8)
        
        plt.tight_layout()
        plt.savefig(plots_dir / 'combined_metrics.png', dpi=150, bbox_inches='tight')
        plt.close()
        
        print(f"  Created: combined_metrics.png")

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Analyze Grid Clash test results from log files')
    parser.add_argument('--dir', '-d', default='test_results',
                       help='Results directory (default: test_results)')
    
    args = parser.parse_args()
    
    analyzer = GridClashAnalyzer(results_dir=args.dir)
    analyzer.analyze_all_tests()

if __name__ == "__main__":
    main()