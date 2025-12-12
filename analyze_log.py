# analyze_logs.py
#!/usr/bin/env python3
"""
Analyze Grid Clash log files from test_results subdirectories
"""

import re
import json
import pandas as pd
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from collections import defaultdict
import argparse
import sys

class LogAnalyzer:
    def __init__(self, results_dir="test_results"):
        self.results_dir = Path(results_dir)
        self.test_results = {}
        self.colors = {
            'baseline': '#2E86AB',
            'loss_2pct': '#A23B72',
            'loss_5pct': '#F18F01',
            'delay_100ms': '#C73E1D',
            'delay_jitter': '#6A994E'
        }
        
    def extract_latency_from_line(self, line):
        """Extract latency value from log line"""
        patterns = [
            r'latency[\s:]+([\d.]+)\s*ms',  # "latency: 12.3ms"
            r'Latency[\s:]+([\d.]+)\s*ms',  # "Latency: 12.3ms"
            r'RTT[\s:]+([\d.]+)\s*ms',      # "RTT: 45.2ms"
            r'ping[\s:]+([\d.]+)\s*ms',     # "ping: 12.3ms"
            r'([\d.]+)\s*ms\s+latency',     # "12.3ms latency"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1))
                except:
                    continue
        return None
    
    def extract_update_rate_from_line(self, line):
        """Extract update rate from log line"""
        patterns = [
            r'Update[\s:]+([\d.]+)\s*Hz',    # "Update: 19.8Hz"
            r'rate[\s:]+([\d.]+)\s*Hz',      # "rate: 19.8Hz"
            r'([\d.]+)\s*Hz.*update',        # "19.8Hz update"
            r'(\d+\.?\d*)\s*fps',            # "60.0fps"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1))
                except:
                    continue
        return None
    
    def extract_packet_loss_from_line(self, line):
        """Extract packet loss info from log line"""
        patterns = [
            r'Detected\s+(\d+)\s+lost packets',          # "Detected 3 lost packets"
            r'(\d+)\s+lost packets',                     # "3 lost packets"
            r'packet loss[\s:]+([\d.]+)%',              # "packet loss: 2.5%"
            r'loss[\s:]+([\d.]+)%',                     # "loss: 2.5%"
            r'(\d+\.?\d*)%\s+loss',                     # "2.5% loss"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1))
                except:
                    continue
        return None
    
    def extract_position_data_from_line(self, line):
        """Extract position data from log line"""
        # Look for patterns like "position: [x, y]" or "x: 10, y: 20"
        patterns = [
            r'position[\s:]*\[([\d.]+)\s*,\s*([\d.]+)\]',  # "position: [10.5, 20.3]"
            r'x[\s:]+([\d.]+)[,\s]+y[\s:]+([\d.]+)',       # "x: 10.5, y: 20.3"
            r'pos[\s:]*\(([\d.]+)\s*,\s*([\d.]+)\)',       # "pos: (10.5, 20.3)"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                try:
                    x = float(match.group(1))
                    y = float(match.group(2))
                    return {'x': x, 'y': y}
                except:
                    continue
        return None
    
    def extract_sequence_gap_from_line(self, line):
        """Extract sequence gap information"""
        patterns = [
            r'snapshot[\s:_]+(\d+)',                    # "snapshot: 123" or "snapshot_id: 123"
            r'seq[\s:_]+(\d+)',                         # "seq: 456"
            r'sequence[\s:_]+(\d+)',                    # "sequence: 789"
            r'gap.*?(\d+)',                             # "gap of 3"
            r'missing.*?(\d+)',                         # "missing 3"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                try:
                    return int(match.group(1))
                except:
                    continue
        return None
    
    def analyze_client_log(self, log_file):
        """Analyze a single client log file"""
        print(f"    Analyzing: {log_file.name}")
        
        metrics = {
            'latency_samples': [],
            'update_rate_samples': [],
            'packet_loss_samples': [],
            'position_samples': [],
            'sequence_numbers': [],
            'timestamps': [],
            'error_count': 0,
            'total_lines': 0,
            'metrics_lines': 0
        }
        
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            
            metrics['total_lines'] = len(lines)
            
            for line_num, line in enumerate(lines, 1):
                line = line.strip()
                
                # Skip empty lines
                if not line:
                    continue
                
                # 1. Extract latency
                latency = self.extract_latency_from_line(line)
                if latency is not None:
                    metrics['latency_samples'].append(latency)
                    metrics['metrics_lines'] += 1
                
                # 2. Extract update rate
                update_rate = self.extract_update_rate_from_line(line)
                if update_rate is not None:
                    metrics['update_rate_samples'].append(update_rate)
                
                # 3. Extract packet loss
                packet_loss = self.extract_packet_loss_from_line(line)
                if packet_loss is not None:
                    metrics['packet_loss_samples'].append(packet_loss)
                
                # 4. Extract position data
                position = self.extract_position_data_from_line(line)
                if position is not None:
                    metrics['position_samples'].append(position)
                
                # 5. Extract sequence numbers
                seq_num = self.extract_sequence_gap_from_line(line)
                if seq_num is not None:
                    metrics['sequence_numbers'].append(seq_num)
                
                # 6. Look for timestamp patterns
                timestamp_match = re.search(r'(\d{2}:\d{2}:\d{2}\.\d+)', line)
                if timestamp_match:
                    metrics['timestamps'].append(timestamp_match.group(1))
            
            # Calculate derived metrics
            if metrics['latency_samples']:
                latencies = metrics['latency_samples']
                metrics['latency_mean'] = float(np.mean(latencies))
                metrics['latency_std'] = float(np.std(latencies))
                metrics['latency_p95'] = float(np.percentile(latencies, 95)) if len(latencies) > 1 else latencies[0]
                metrics['latency_samples_count'] = len(latencies)
            
            if metrics['update_rate_samples']:
                rates = metrics['update_rate_samples']
                metrics['update_rate_mean'] = float(np.mean(rates))
                metrics['update_rate_std'] = float(np.std(rates))
                metrics['update_rate_samples_count'] = len(rates)
            
            if metrics['packet_loss_samples']:
                losses = metrics['packet_loss_samples']
                metrics['packet_loss_mean'] = float(np.mean(losses))
                metrics['packet_loss_std'] = float(np.std(losses))
                metrics['packet_loss_samples_count'] = len(losses)
            
            # Calculate packet loss from sequence gaps
            if len(metrics['sequence_numbers']) > 10:
                seq_nums = sorted(set(metrics['sequence_numbers']))
                if len(seq_nums) > 1:
                    diffs = np.diff(seq_nums)
                    lost_packets = sum(diff - 1 for diff in diffs if diff > 1)
                    total_expected = seq_nums[-1] - seq_nums[0] + 1
                    if total_expected > 0:
                        metrics['calculated_loss_rate'] = (lost_packets / total_expected) * 100
                        metrics['lost_packets_count'] = lost_packets
                        metrics['expected_packets'] = total_expected
            
            print(f"      Found: {len(metrics['latency_samples'])} latency samples, "
                  f"{len(metrics['update_rate_samples'])} update rate samples")
            
            return metrics
            
        except Exception as e:
            print(f"      Error analyzing {log_file.name}: {e}")
            metrics['error_count'] += 1
            return metrics
    
    def analyze_server_log(self, log_file):
        """Analyze server log file"""
        print(f"    Analyzing server log: {log_file.name}")
        
        metrics = {
            'client_connections': 0,
            'game_events': 0,
            'broadcast_count': 0,
            'error_count': 0,
            'cpu_mentions': 0,
            'total_lines': 0
        }
        
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            
            metrics['total_lines'] = len(lines)
            
            for line in lines:
                line_lower = line.lower()
                
                # Count connections
                if 'new connection' in line_lower or 'assigned to' in line_lower:
                    metrics['client_connections'] += 1
                
                # Count game events
                if 'claimed' in line_lower or 'acquired' in line_lower or 'game over' in line_lower:
                    metrics['game_events'] += 1
                
                # Count broadcasts
                if 'broadcast' in line_lower or 'sent to' in line_lower or 'snapshot' in line_lower:
                    metrics['broadcast_count'] += 1
                
                # Look for CPU/Memory mentions
                if 'cpu' in line_lower or 'memory' in line_lower or 'usage' in line_lower:
                    metrics['cpu_mentions'] += 1
            
            print(f"      Found: {metrics['client_connections']} connections, "
                  f"{metrics['game_events']} game events, {metrics['broadcast_count']} broadcasts")
            
            return metrics
            
        except Exception as e:
            print(f"      Error analyzing server log {log_file.name}: {e}")
            metrics['error_count'] += 1
            return metrics
    
    def analyze_test_directory(self, test_dir):
        """Analyze all log files in a test directory"""
        test_name = test_dir.name
        print(f"\n{'='*60}")
        print(f"Analyzing test: {test_name}")
        print(f"{'='*60}")
        
        test_analysis = {
            'test_name': test_name,
            'client_logs': {},
            'server_log': None,
            'metadata': {}
        }
        
        # Load metadata if exists
        meta_file = test_dir / "test_metadata.json"
        if meta_file.exists():
            try:
                with open(meta_file, 'r') as f:
                    test_analysis['metadata'] = json.load(f)
            except Exception as e:
                print(f"    Warning: Could not load metadata: {e}")
        
        # Analyze client logs
        client_logs = list(test_dir.glob("client_*.log"))
        if not client_logs:
            print(f"    No client log files found!")
            return None
        
        print(f"    Found {len(client_logs)} client log files")
        
        all_latencies = []
        all_update_rates = []
        all_packet_loss = []
        client_count = 0
        
        for client_log in client_logs:
            client_id = client_log.stem.split('_')[1]
            print(f"  Client {client_id}:")
            
            client_metrics = self.analyze_client_log(client_log)
            test_analysis['client_logs'][client_id] = client_metrics
            
            if client_metrics.get('latency_samples'):
                client_count += 1
                all_latencies.extend(client_metrics['latency_samples'])
                
                if 'latency_mean' in client_metrics:
                    print(f"    Avg latency: {client_metrics['latency_mean']:.1f}ms "
                          f"(±{client_metrics['latency_std']:.1f}ms)")
                
                if 'update_rate_mean' in client_metrics:
                    all_update_rates.append(client_metrics['update_rate_mean'])
                    print(f"    Avg update rate: {client_metrics['update_rate_mean']:.1f}Hz")
                
                if 'calculated_loss_rate' in client_metrics:
                    all_packet_loss.append(client_metrics['calculated_loss_rate'])
                    print(f"    Estimated loss: {client_metrics['calculated_loss_rate']:.1f}%")
        
        # Analyze server log
        server_log = test_dir / "server.log"
        if server_log.exists():
            server_metrics = self.analyze_server_log(server_log)
            test_analysis['server_log'] = server_metrics
        
        # Calculate aggregate metrics
        if all_latencies:
            test_analysis['aggregate'] = {
                'latency_mean': float(np.mean(all_latencies)),
                'latency_std': float(np.std(all_latencies)),
                'latency_p95': float(np.percentile(all_latencies, 95)) if len(all_latencies) > 1 else all_latencies[0],
                'latency_samples': len(all_latencies),
                'client_count': client_count
            }
            
            if all_update_rates:
                test_analysis['aggregate']['update_rate_mean'] = float(np.mean(all_update_rates))
                test_analysis['aggregate']['update_rate_std'] = float(np.std(all_update_rates))
            
            if all_packet_loss:
                test_analysis['aggregate']['packet_loss_mean'] = float(np.mean(all_packet_loss))
                test_analysis['aggregate']['packet_loss_std'] = float(np.std(all_packet_loss))
        
        return test_analysis
    
    def analyze_all_tests(self):
        """Analyze all test directories"""
        print("GRID CLASH LOG FILE ANALYSIS")
        print("=" * 60)
        
        if not self.results_dir.exists():
            print(f"Error: Directory '{self.results_dir}' not found!")
            print(f"Current directory: {Path.cwd()}")
            return
        
        # Get all test directories
        test_dirs = []
        for item in self.results_dir.iterdir():
            if item.is_dir():
                # Check if it looks like a test directory (contains log files)
                log_files = list(item.glob("*.log"))
                if log_files:
                    test_dirs.append(item)
        
        if not test_dirs:
            print(f"No test directories with log files found in '{self.results_dir}'")
            print("\nLooking for test directories...")
            for item in self.results_dir.iterdir():
                if item.is_dir():
                    print(f"  Found: {item.name}")
                    files = list(item.iterdir())
                    print(f"    Files: {[f.name for f in files[:5]]}{'...' if len(files) > 5 else ''}")
            return
        
        print(f"Found {len(test_dirs)} test directories with log files")
        
        # Analyze each test directory
        for test_dir in sorted(test_dirs):
            test_analysis = self.analyze_test_directory(test_dir)
            if test_analysis:
                self.test_results[test_dir.name] = test_analysis
        
        if not self.test_results:
            print("\nNo test data could be analyzed!")
            return
        
        # Generate summary report
        self.generate_summary_report()
        
        # Generate plots
        self.generate_plots()
        
        print("\n" + "=" * 60)
        print("ANALYSIS COMPLETE!")
        print(f"Results saved in: {self.results_dir}/log_analysis/")
    
    def generate_summary_report(self):
        """Generate summary report of all tests"""
        summary_dir = self.results_dir / "log_analysis"
        summary_dir.mkdir(exist_ok=True)
        
        summary_data = []
        
        # Define test order for consistent display
        test_order = ['baseline', 'loss_2pct', 'loss_5pct', 'delay_100ms', 'delay_jitter']
        
        for test_name in test_order:
            if test_name in self.test_results:
                test = self.test_results[test_name]
                agg = test.get('aggregate', {})
                metadata = test.get('metadata', {})
                
                row = {
                    'Test': test_name,
                    'Description': metadata.get('test_name', test_name.replace('_', ' ').title()),
                    'Clients': agg.get('client_count', len(test.get('client_logs', {}))),
                    'Latency_Samples': agg.get('latency_samples', 0)
                }
                
                # Add metrics if available
                if 'latency_mean' in agg:
                    row.update({
                        'Latency_Mean_ms': f"{agg['latency_mean']:.1f}",
                        'Latency_Std_ms': f"{agg['latency_std']:.1f}",
                        'Latency_P95_ms': f"{agg['latency_p95']:.1f}"
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
                
                if 'packet_loss_mean' in agg:
                    row['PacketLoss_%'] = f"{agg['packet_loss_mean']:.1f}"
                else:
                    row['PacketLoss_%'] = 'N/A'
                
                summary_data.append(row)
        
        # Create DataFrame and save
        if summary_data:
            df = pd.DataFrame(summary_data)
            summary_file = summary_dir / "summary_report.csv"
            df.to_csv(summary_file, index=False)
            
            # Also save detailed JSON
            json_file = summary_dir / "detailed_results.json"
            with open(json_file, 'w') as f:
                json.dump(self.test_results, f, indent=2, default=str)
            
            # Print summary
            print("\n" + "="*80)
            print("SUMMARY OF ALL TESTS (Analyzed from Log Files)")
            print("="*80)
            
            # Create a formatted table
            headers = ['Test', 'Description', 'Clients', 'Latency(ms)', 'Update(Hz)', 'Loss(%)', 'Samples']
            rows = []
            
            for row in summary_data:
                latency = f"{row.get('Latency_Mean_ms', 'N/A')}"
                if row.get('Latency_Std_ms', 'N/A') != 'N/A':
                    latency += f" ±{row['Latency_Std_ms']}"
                
                rows.append([
                    row['Test'],
                    row['Description'][:20],
                    str(row['Clients']),
                    latency,
                    row.get('Update_Rate_Hz', 'N/A'),
                    row.get('PacketLoss_%', 'N/A'),
                    str(row['Latency_Samples'])
                ])
            
            # Print table
            col_widths = [15, 20, 8, 15, 10, 10, 10]
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
        """Check against acceptance criteria from PDF"""
        print("\nACCEPTANCE CRITERIA CHECK:")
        print("-" * 40)
        
        if 'baseline' in self.test_results:
            baseline = self.test_results['baseline'].get('aggregate', {})
            
            if 'latency_mean' in baseline:
                latency = baseline['latency_mean']
                latency_ok = latency <= 50
                status = '✓' if latency_ok else '✗'
                print(f"Baseline: Latency ≤ 50ms: {status} ({latency:.1f}ms)")
            else:
                print(f"Baseline: Latency ≤ 50ms: ? (No latency data)")
            
            # Check update rate
            if 'update_rate_mean' in baseline:
                update_rate = baseline['update_rate_mean']
                update_ok = update_rate >= 18  # Close to 20Hz
                status = '✓' if update_ok else '✗'
                print(f"         Update Rate ≥ 18Hz: {status} ({update_rate:.1f}Hz)")
            else:
                print(f"         Update Rate ≥ 18Hz: ? (No update rate data)")
        
        if 'loss_2pct' in self.test_results:
            loss2 = self.test_results['loss_2pct'].get('aggregate', {})
            
            if 'packet_loss_mean' in loss2:
                loss_rate = loss2['packet_loss_mean']
                print(f"Loss 2%: Packet loss ~{loss_rate:.1f}% (target: 2%)")
            
            print(f"Loss 2%: Position error ≤ 0.5: (Need position data from logs)")
        
        if 'loss_5pct' in self.test_results:
            loss5 = self.test_results['loss_5pct'].get('aggregate', {})
            
            if 'packet_loss_mean' in loss5:
                loss_rate = loss5['packet_loss_mean']
                print(f"Loss 5%: Packet loss ~{loss_rate:.1f}% (target: 5%)")
            
            print(f"Loss 5%: Critical events delivered: (Check game events in logs)")
        
        if 'delay_100ms' in self.test_results:
            delay = self.test_results['delay_100ms'].get('aggregate', {})
            
            if 'latency_mean' in delay:
                latency = delay['latency_mean']
                print(f"Delay 100ms: Measured latency ~{latency:.1f}ms (added 100ms + baseline)")
        
        print("-" * 40)
    
    def generate_plots(self):
        """Generate plots from analyzed data"""
        plots_dir = self.results_dir / "log_analysis" / "plots"
        plots_dir.mkdir(exist_ok=True)
        
        print(f"\nGenerating plots in: {plots_dir}")
        
        # Prepare data for plotting
        test_names = []
        latency_means = []
        latency_stds = []
        update_rates = []
        packet_losses = []
        
        test_order = ['baseline', 'loss_2pct', 'loss_5pct', 'delay_100ms', 'delay_jitter']
        
        for test_name in test_order:
            if test_name in self.test_results:
                agg = self.test_results[test_name].get('aggregate', {})
                
                if 'latency_mean' in agg:
                    test_names.append(test_name.replace('_', ' ').title())
                    latency_means.append(agg['latency_mean'])
                    latency_stds.append(agg.get('latency_std', 0))
                    
                    if 'update_rate_mean' in agg:
                        update_rates.append(agg['update_rate_mean'])
                    else:
                        update_rates.append(0)
                    
                    if 'packet_loss_mean' in agg:
                        packet_losses.append(agg['packet_loss_mean'])
                    else:
                        packet_losses.append(0)
        
        if not test_names:
            print("No data available for plotting")
            return
        
        # 1. Latency comparison plot
        if latency_means:
            plt.figure(figsize=(12, 6))
            
            x_pos = np.arange(len(test_names))
            colors = [self.colors.get(name.lower().replace(' ', '_'), '#666666') 
                     for name in test_names]
            
            plt.bar(x_pos, latency_means, yerr=latency_stds, capsize=5, 
                   color=colors, alpha=0.7, width=0.6)
            
            plt.xlabel('Test Scenario')
            plt.ylabel('Latency (ms)')
            plt.title('Mean Latency by Test Scenario (from Log Analysis)')
            plt.xticks(x_pos, test_names, rotation=45, ha='right')
            plt.grid(True, alpha=0.3, axis='y')
            
            # Add target line for baseline
            plt.axhline(y=50, color='red', linestyle='--', alpha=0.5, label='Target (50ms)')
            
            # Add value labels
            for i, v in enumerate(latency_means):
                plt.text(i, v + latency_stds[i] + 2, f'{v:.1f}', 
                        ha='center', va='bottom', fontsize=9)
            
            plt.legend()
            plt.tight_layout()
            plt.savefig(plots_dir / 'latency_comparison.png', dpi=150, bbox_inches='tight')
            plt.close()
            
            print(f"  Created: latency_comparison.png")
        
        # 2. Update rate plot
        if any(r > 0 for r in update_rates):
            plt.figure(figsize=(10, 6))
            
            colors = [self.colors.get(name.lower().replace(' ', '_'), '#666666') 
                     for name in test_names]
            
            bars = plt.bar(test_names, update_rates, color=colors, alpha=0.7)
            plt.xlabel('Test Scenario')
            plt.ylabel('Update Rate (Hz)')
            plt.title('Average Update Rate by Test Scenario')
            plt.xticks(rotation=45, ha='right')
            plt.grid(True, alpha=0.3, axis='y')
            
            # Add target line
            plt.axhline(y=20, color='red', linestyle='--', alpha=0.5, label='Target (20Hz)')
            
            # Add value labels
            for bar, rate in zip(bars, update_rates):
                if rate > 0:
                    height = bar.get_height()
                    plt.text(bar.get_x() + bar.get_width()/2., height + 0.2,
                            f'{rate:.1f}', ha='center', va='bottom', fontsize=9)
            
            plt.legend()
            plt.tight_layout()
            plt.savefig(plots_dir / 'update_rate_comparison.png', dpi=150, bbox_inches='tight')
            plt.close()
            
            print(f"  Created: update_rate_comparison.png")
        
        # 3. Combined metrics plot
        plt.figure(figsize=(14, 8))
        
        metrics_to_plot = []
        if latency_means:
            metrics_to_plot.append(('Latency (ms)', latency_means, latency_stds))
        if any(r > 0 for r in update_rates):
            metrics_to_plot.append(('Update Rate (Hz)', update_rates, None))
        if any(l > 0 for l in packet_losses):
            metrics_to_plot.append(('Packet Loss (%)', packet_losses, None))
        
        n_metrics = len(metrics_to_plot)
        if n_metrics > 0:
            fig, axes = plt.subplots(1, n_metrics, figsize=(5*n_metrics, 6))
            if n_metrics == 1:
                axes = [axes]
            
            colors = [self.colors.get(name.lower().replace(' ', '_'), '#666666') 
                     for name in test_names]
            
            for idx, (title, values, errors) in enumerate(metrics_to_plot):
                ax = axes[idx]
                
                if errors:
                    ax.bar(test_names, values, yerr=errors, capsize=5, 
                          color=colors, alpha=0.7, width=0.6)
                else:
                    bars = ax.bar(test_names, values, color=colors, alpha=0.7, width=0.6)
                
                ax.set_xlabel('Test Scenario')
                ax.set_ylabel(title)
                ax.set_title(title)
                ax.set_xticklabels(test_names, rotation=45, ha='right')
                ax.grid(True, alpha=0.3, axis='y')
                
                # Add value labels
                for i, v in enumerate(values):
                    if v > 0 or title == 'Latency (ms)':  # Always show latency even if 0
                        y_offset = errors[i] if errors and i < len(errors) else 0
                        ax.text(i, v + y_offset + (v * 0.05 if v > 0 else 1), 
                               f'{v:.1f}', ha='center', va='bottom', fontsize=8)
            
            plt.tight_layout()
            plt.savefig(plots_dir / 'combined_metrics.png', dpi=150, bbox_inches='tight')
            plt.close()
            
            print(f"  Created: combined_metrics.png")

def main():
    parser = argparse.ArgumentParser(description='Analyze Grid Clash log files')
    parser.add_argument('--dir', '-d', default='test_results',
                       help='Results directory (default: test_results)')
    parser.add_argument('--test', '-t', 
                       help='Analyze specific test (baseline, loss_2pct, loss_5pct, delay_100ms, delay_jitter)')
    
    args = parser.parse_args()
    
    analyzer = LogAnalyzer(results_dir=args.dir)
    
    if args.test:
        # Analyze single test
        test_dir = Path(args.dir) / args.test
        if test_dir.exists():
            print(f"Analyzing single test: {args.test}")
            test_analysis = analyzer.analyze_test_directory(test_dir)
            if test_analysis:
                analyzer.test_results[args.test] = test_analysis
                analyzer.generate_summary_report()
                analyzer.generate_plots()
        else:
            print(f"Test directory not found: {test_dir}")
    else:
        # Analyze all tests
        analyzer.analyze_all_tests()

if __name__ == "__main__":
    main()