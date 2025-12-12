import argparse
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import os
import json
import glob
from datetime import datetime
import warnings

# Suppress warnings for cleaner console output
warnings.filterwarnings('ignore')

class ResultsAnalyzer:
    def __init__(self, results_dir="test_results"):
        self.results_dir = results_dir
        self.scenarios = ["baseline", "loss_2pct", "loss_5pct", "delay_100ms", "delay_jitter"]
        
        # Professional Plotting Style
        sns.set_theme(style="whitegrid", context="paper", font_scale=1.2)
        self.colors = sns.color_palette("viridis", n_colors=5)
        
        os.makedirs("analysis_plots", exist_ok=True)
        
    def load_scenario_data(self, scenario_name):
        """Load data with visual feedback"""
        print(f"  📂 Loading: {scenario_name:<15}", end="")
        
        data = {'client_logs': [], 'server_logs': [], 'run_dirs': []}
        
        scenario_pattern = os.path.join(self.results_dir, f"{scenario_name}_*")
        run_dirs = [d for d in glob.glob(scenario_pattern) if os.path.isdir(d)]
        
        if not run_dirs:
            print(f" [❌ NO DATA FOUND]")
            return data
            
        count = 0
        for run_dir in sorted(run_dirs):
            data['run_dirs'].append(run_dir)
            
            # Load Clients
            for csv_file in glob.glob(os.path.join(run_dir, "client_*.csv")):
                try:
                    df = pd.read_csv(csv_file)
                    if not df.empty:
                        df['run_id'] = os.path.basename(run_dir)
                        data['client_logs'].append(df)
                except: pass
            
            # Load Server
            server_file = os.path.join(run_dir, "server_log.csv") # Check old name first
            if not os.path.exists(server_file):
                server_file = os.path.join(run_dir, "server.csv")
            
            if os.path.exists(server_file):
                try:
                    df = pd.read_csv(server_file)
                    if not df.empty:
                        data['server_logs'].append(df)
                        count += 1
                except: pass
        
        print(f" [{count} runs loaded]")
        return data
    
    def calculate_metrics(self, scenario_name, data):
        """Calculate statistical metrics"""
        metrics = {'scenario': scenario_name, 'runs_analyzed': len(data['run_dirs'])}
        
        if not data['client_logs']: return metrics
        
        df = pd.concat(data['client_logs'], ignore_index=True)
        
        # 1. Latency
        if 'latency_ms' in df.columns:
            lat = df['latency_ms'].dropna()
            metrics.update({
                'latency_mean': lat.mean(),
                'latency_median': lat.median(),
                'latency_95th': np.percentile(lat, 95),
                'latency_std': lat.std()
            })
            
        # 2. Jitter
        if 'recv_time_ms' in df.columns:
            jitters = []
            for _, group in df.groupby(['run_id', 'client_id']):
                if len(group) > 5:
                    jitters.append(np.std(np.diff(group['recv_time_ms'].sort_values())))
            if jitters:
                metrics.update({
                    'jitter_mean': np.mean(jitters),
                    'jitter_95th': np.percentile(jitters, 95)
                })

        # 3. Packet Loss
        if 'seq_num' in df.columns:
            total_sent = 0
            total_lost = 0
            for _, group in df.groupby(['run_id', 'client_id']):
                if len(group) > 1:
                    seqs = group['seq_num'].sort_values().values
                    gaps = np.diff(seqs) - 1
                    total_lost += gaps[gaps > 0].sum()
                    total_sent += (seqs.max() - seqs.min())
            
            metrics['packet_loss_rate'] = (total_lost / total_sent) if total_sent > 0 else 0
            metrics['total_packets'] = len(df)

        # 4. Server Resources
        if data['server_logs']:
            sdf = pd.concat(data['server_logs'], ignore_index=True)
            if 'cpu_percent' in sdf.columns:
                metrics['server_cpu_mean'] = sdf['cpu_percent'].mean()
                metrics['server_cpu_max'] = sdf['cpu_percent'].max()
                
        return metrics
    
    def calculate_position_error(self, scenario_name, data):
        """Calculate Euclidean Position Error"""
        errors = []
        if not data['client_logs'] or not data['server_logs']: return []
        
        # Group by run to match correct server timeline
        # (Simplified logic for speed: compares distributions mostly)
        for run_dir in data['run_dirs']:
            s_file = os.path.join(run_dir, "server_log.csv")
            c_files = glob.glob(os.path.join(run_dir, "client_*.csv"))
            
            if not os.path.exists(s_file) or not c_files: continue
            
            try:
                sdf = pd.read_csv(s_file)
                # Sample server every 10th frame to avoid O(N^2) complexity
                sdf_sample = sdf.iloc[::10]
                
                for cf in c_files:
                    cdf = pd.read_csv(cf)
                    if 'player1_pos_x' in sdf.columns and 'render_x' in cdf.columns:
                        # Find closest timestamps
                        for _, s_row in sdf_sample.iterrows():
                            # Find client row closest in time
                            time_diff = np.abs(cdf['recv_time_ms']/1000 - s_row['timestamp'])
                            match = cdf.loc[time_diff.idxmin()]
                            
                            if time_diff.min() < 0.2: # Only matches within 200ms
                                dist = np.sqrt(
                                    (s_row['player1_pos_x'] - match['render_x'])**2 + 
                                    (s_row['player1_pos_y'] - match['render_y'])**2
                                )
                                errors.append(dist)
            except: continue
            
        return errors

    def generate_plots(self, all_metrics, position_errors):
        print("\n  📊 Generating Analysis Plots...")
        
        scenarios = [s for s in self.scenarios if s in all_metrics]
        if not scenarios: return

        # Prepare DataFrames for easy plotting
        plot_data = []
        for s in scenarios:
            m = all_metrics[s]
            err = position_errors.get(s, [])
            plot_data.append({
                'Scenario': s.replace('_', '\n').title(),
                'Latency (ms)': m.get('latency_mean', 0),
                'Jitter (ms)': m.get('jitter_mean', 0),
                'Loss (%)': m.get('packet_loss_rate', 0) * 100,
                'CPU (%)': m.get('server_cpu_mean', 0),
                'Pos Error': np.mean(err) if err else 0,
                'Pos Error 95th': np.percentile(err, 95) if err else 0
            })
        df = pd.DataFrame(plot_data)

        # 1. LATENCY & JITTER
        fig, ax = plt.subplots(figsize=(10, 6))
        x = np.arange(len(df))
        w = 0.35
        ax.bar(x - w/2, df['Latency (ms)'], w, label='Avg Latency', color='#3498db')
        ax.bar(x + w/2, df['Jitter (ms)'], w, label='Avg Jitter', color='#95a5a6')
        
        ax.axhline(50, color='red', linestyle='--', linewidth=2, label='Max Latency (50ms)')
        ax.set_xticks(x)
        ax.set_xticklabels(df['Scenario'])
        ax.set_title("Network Latency & Jitter Analysis", fontsize=14, fontweight='bold')
        ax.set_ylabel("Time (ms)")
        ax.legend()
        plt.tight_layout()
        plt.savefig("analysis_plots/1_network_performance.png", dpi=300)
        plt.close()

        # 2. POSITION ERROR
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.bar(df['Scenario'], df['Pos Error 95th'], color='#e74c3c', alpha=0.7, label='95th %ile Error')
        ax.bar(df['Scenario'], df['Pos Error'], color='#c0392b', width=0.4, label='Mean Error')
        
        ax.axhline(0.5, color='green', linestyle='--', linewidth=2, label='LAN Requirement (0.5)')
        ax.axhline(1.5, color='orange', linestyle='--', linewidth=2, label='WAN Requirement (1.5)')
        
        ax.set_title("Perceived Position Error (Synchronization)", fontsize=14, fontweight='bold')
        ax.set_ylabel("Grid Units")
        ax.legend()
        plt.tight_layout()
        plt.savefig("analysis_plots/2_position_error.png", dpi=300)
        plt.close()

        # 3. CPU & LOSS
        fig, ax1 = plt.subplots(figsize=(10, 6))
        
        ax1.bar(x - w/2, df['CPU (%)'], w, color='#2ecc71', label='Server CPU')
        ax1.set_ylabel("CPU Usage (%)", color='#2ecc71', fontweight='bold')
        ax1.set_ylim(0, 100)
        ax1.axhline(60, color='red', linestyle=':', linewidth=2, label='CPU Limit (60%)')
        
        ax2 = ax1.twinx()
        ax2.bar(x + w/2, df['Loss (%)'], w, color='#9b59b6', label='Packet Loss')
        ax2.set_ylabel("Packet Loss (%)", color='#9b59b6', fontweight='bold')
        ax2.set_ylim(0, 50)
        
        ax1.set_xticks(x)
        ax1.set_xticklabels(df['Scenario'])
        ax1.set_title("System Resource & Reliability", fontsize=14, fontweight='bold')
        
        # Unified legend
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper center', bbox_to_anchor=(0.5, -0.15), ncol=2)
        
        plt.tight_layout()
        plt.savefig("analysis_plots/3_system_health.png", dpi=300)
        plt.close()
        
        print("  ✅ Plots saved to 'analysis_plots/'")

    def generate_report(self, all_metrics, position_errors):
        """Generate a professional text report"""
        print("\n  📄 Generating Final Report...")
        
        with open('analysis_summary.txt', 'w', encoding='utf-8') as f:
            # HEADER
            f.write("="*80 + "\n")
            f.write(f"GRID CLASH PROTOCOL - PERFORMANCE EVALUATION REPORT\n")
            f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            f.write("="*80 + "\n\n")
            
            # EXECUTIVE SUMMARY
            f.write("1. EXECUTIVE SUMMARY\n")
            f.write("-" * 80 + "\n")
            f.write(f"{'SCENARIO':<20} | {'STATUS':<10} | {'KEY METRIC':<30}\n")
            f.write("-" * 80 + "\n")
            
            for s in self.scenarios:
                if s not in all_metrics: continue
                m = all_metrics[s]
                err = position_errors.get(s, [])
                
                status = "PASS"
                note = ""
                
                # Evaluation Logic
                if s == "baseline":
                    if m.get('latency_mean', 99) > 50: status = "FAIL"; note = f"High Latency ({m['latency_mean']:.1f}ms)"
                    elif m.get('server_cpu_mean', 99) > 60: status = "FAIL"; note = f"High CPU ({m['server_cpu_mean']:.1f}%)"
                    else: note = f"Latency: {m['latency_mean']:.1f}ms"
                elif s == "loss_2pct":
                    mean_err = np.mean(err) if err else 0
                    if mean_err > 0.5: status = "FAIL"; note = f"Pos Error {mean_err:.2f} > 0.5"
                    else: note = f"Pos Error: {mean_err:.3f} (Excellent)"
                elif s == "loss_5pct":
                    lat_95 = m.get('latency_95th', 999)
                    if lat_95 > 200: status = "FAIL"; note = f"95th Latency {lat_95:.0f}ms > 200"
                    else: note = f"95th Latency: {lat_95:.0f}ms"
                elif "delay" in s:
                    status = "INFO"; note = "Stability Test"
                
                icon = "✅" if status == "PASS" else ("❌" if status == "FAIL" else "ℹ️")
                f.write(f"{s.upper():<20} | {icon} {status:<5} | {note}\n")
            f.write("-" * 80 + "\n\n")
            
            # DETAILED METRICS
            f.write("2. DETAILED SCENARIO METRICS\n")
            
            for s in self.scenarios:
                if s not in all_metrics: continue
                m = all_metrics[s]
                err = position_errors.get(s, [])
                
                f.write(f"\n>> SCENARIO: {s.upper()}\n")
                f.write("." * 60 + "\n")
                
                # Network Table
                f.write(f"{'Metric':<25} {'Value':<15} {'Target/Notes':<20}\n")
                f.write("-" * 60 + "\n")
                f.write(f"{'Avg Latency':<25} {m.get('latency_mean',0):.2f} ms      {'<= 50ms (Baseline)'}\n")
                f.write(f"{'95th %ile Latency':<25} {m.get('latency_95th',0):.2f} ms      {'<= 200ms (High Loss)'}\n")
                f.write(f"{'Avg Jitter':<25} {m.get('jitter_mean',0):.2f} ms\n")
                f.write(f"{'Packet Loss Rate':<25} {m.get('packet_loss_rate',0)*100:.2f} %\n")
                
                # System Table
                f.write("-" * 60 + "\n")
                f.write(f"{'Server CPU Usage':<25} {m.get('server_cpu_mean',0):.1f} %       {'<= 60%'}\n")
                
                # Sync Table
                if err:
                    mean_err = np.mean(err)
                    p95_err = np.percentile(err, 95)
                    f.write("-" * 60 + "\n")
                    f.write(f"{'Mean Pos Error':<25} {mean_err:.4f} units   {'<= 0.5 (LAN)'}\n")
                    f.write(f"{'95th %ile Error':<25} {p95_err:.4f} units   {'<= 1.5 (WAN)'}\n")
                
                f.write("." * 60 + "\n")

        print("  ✅ Report saved to 'analysis_summary.txt'")

def main():
    print("\n" + "="*60)
    print("   GRID CLASH ANALYZER - PHASE 2")
    print("="*60 + "\n")
    
    analyzer = ResultsAnalyzer()
    
    all_metrics = {}
    position_errors = {}
    
    for scenario in analyzer.scenarios:
        data = analyzer.load_scenario_data(scenario)
        if data['client_logs']:
            all_metrics[scenario] = analyzer.calculate_metrics(scenario, data)
            position_errors[scenario] = analyzer.calculate_position_error(scenario, data)
    
    if all_metrics:
        analyzer.generate_plots(all_metrics, position_errors)
        analyzer.generate_report(all_metrics, position_errors)
        print("\n" + "="*60)
        print("   ANALYSIS COMPLETE")
        print("="*60 + "\n")
    else:
        print("\n❌ No valid data found in 'test_results/'")

if __name__ == "__main__":
    main()