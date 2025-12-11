#!/usr/bin/env python3
"""
phase1_baseline_test.py
Phase 1 Baseline Test for Grid Clash UDP Protocol
Tests: 20 updates/sec, ≤50ms latency, <60% CPU
"""

import socket
import time
import csv
import threading
import psutil
import subprocess
import sys
import os
from protocol import GridClashBinaryProtocol


class Phase1BaselineTest:
    def __init__(self):
        self.server_host = "127.0.0.1"
        self.server_port = 5555
        self.test_duration = 30  # seconds
        self.expected_update_rate = 20  # Hz
        self.max_latency = 50  # ms
        self.max_cpu = 60  # %

        self.results = {
            'update_rate_achieved': 0,
            'avg_latency': 0,
            'max_latency': 0,
            'avg_cpu': 0,
            'max_cpu': 0,
            'packets_received': 0,
            'packets_expected': 0,
            'packet_loss': 0,
            'packet_loss_percent': 0,
            'test_passed': False
        }

        self.server_process = None
        self.cpu_readings = []

    # ---------- Utility ----------
    def print_status(self, msg):
        print(f"[TEST] {msg}")

    def print_error(self, msg):
        print(f"[ERROR] {msg}")

    def cleanup_processes(self):
        """Kill any remaining test or server processes"""
        self.print_status("Cleaning up processes...")
        if self.server_process and self.server_process.poll() is None:
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server_process.kill()

        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.info['name'] and 'python' in proc.info['name'].lower():
                    cmd = ' '.join(proc.info.get('cmdline', []))
                    if 'server_optimized.py' in cmd or 'server.py' in cmd:
                        proc.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        time.sleep(1)

    # ---------- Server ----------
    def start_server(self):
        self.print_status("Starting Grid Clash server...")
        try:
            self.server_process = subprocess.Popen(
                [sys.executable, 'server_optimized.py'],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            # Give server time to initialize its socket
            time.sleep(2.0)

            self.print_status("🔍 Checking if server responds to CONNECT...")

            server_ready = False
            start_time = time.time()

            while time.time() - start_time < 10:
                if self.server_process.poll() is not None:
                    self.print_error("Server process died during startup.")
                    return False

                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    sock.settimeout(1.0)
                    sock.sendto(b"CONNECT", (self.server_host, self.server_port))
                    try:
                        data, _ = sock.recvfrom(1024)
                        if data:
                            server_ready = True
                            sock.close()
                            break
                    except socket.timeout:
                        pass
                    sock.close()
                except ConnectionResetError:
                    # Server not ready yet; wait and retry
                    time.sleep(0.5)
                    continue
                except Exception as e:
                    # Catch transient socket errors
                    self.print_status(f"Waiting for server... ({e})")
                    time.sleep(0.5)
                    continue

                time.sleep(0.5)

            if not server_ready:
                self.print_error("❌ Server did not respond to CONNECT after 10s.")
                return False

            self.print_status("✅ Server is ready.")
            return True

        except Exception as e:
            self.print_error(f"Failed to start server: {e}")
            return False


    # ---------- CPU Monitoring ----------
    def monitor_server_cpu(self, duration):
        readings = []
        start_time = time.time()

        if not self.server_process:
            return readings

        try:
            proc = psutil.Process(self.server_process.pid)
            children = proc.children(recursive=True)
            all_procs = [proc] + children
            for p in all_procs:
                try:
                    p.cpu_percent(interval=None)
                except Exception:
                    pass

            while time.time() - start_time < duration:
                total_cpu = 0
                for p in all_procs:
                    try:
                        if p.is_running():
                            total_cpu += p.cpu_percent(interval=0.2) / psutil.cpu_count(logical=True)
                    except Exception:
                        continue
                readings.append(min(total_cpu, 100.0))
        except Exception:
            pass
        return readings


    # ---------- Network Performance ----------
    def measure_network_performance(self):
        """Connects to the server and measures packet rate, latency, etc."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(2.0)

        self.print_status("📊 Connecting and measuring packets...")

        # connect to server
        try:
            sock.sendto(b"CONNECT", (self.server_host, self.server_port))
            data, addr = sock.recvfrom(1024)
            if not data:
                self.print_error("❌ No response from server after CONNECT.")
                sock.close()
                return {}
            self.print_status("✅ Connected to server successfully.")
        except Exception as e:
            self.print_error(f"❌ Connection failed: {e}")
            sock.close()
            return {}

        # measure updates
        packets = 0
        latencies = []
        start_time = time.time()

        while time.time() - start_time < self.test_duration:
            try:
                data, _ = sock.recvfrom(4096)
                recv_time = time.time()

                msg = GridClashBinaryProtocol.decode_message(data)
                if not msg:
                    continue
                header = msg['header']
                if header['msg_type'] == GridClashBinaryProtocol.MSG_GAME_STATE:
                    packets += 1
                    server_ts = header.get('timestamp', 0)
                    latency = int(recv_time * 1000) - server_ts
                    latencies.append(latency)

                    if packets % 100 == 0:
                        rate = packets / (time.time() - start_time)
                        self.print_status(f"📦 {packets} packets received ({rate:.1f} Hz)")

            except socket.timeout:
                continue
            except Exception:
                continue

        sock.close()

        duration = time.time() - start_time
        self.print_status(f"Measurement complete: {packets} packets in {duration:.1f}s")
        return {
            'game_state_packets': packets,
            'latencies': latencies,
            'duration': duration
        }

    # ---------- Metrics ----------
    def calculate_results(self, data):
        if not data or not data.get('game_state_packets'):
            self.print_error("No packets received — test failed.")
            self.results['test_passed'] = False
            return

        packets = data['game_state_packets']
        duration = data['duration']
        update_rate = packets / duration if duration > 0 else 0

        latencies = data['latencies']
        avg_latency = sum(latencies) / len(latencies) if latencies else 0
        max_latency = max(latencies) if latencies else 0

        valid_cpu = [x for x in self.cpu_readings if x > 0]
        avg_cpu = sum(valid_cpu) / len(valid_cpu) if valid_cpu else 0
        max_cpu = max(valid_cpu) if valid_cpu else 0

        expected = self.expected_update_rate * duration
        loss = max(0, expected - packets)
        loss_percent = (loss / expected * 100) if expected > 0 else 0

        update_ok = update_rate >= (self.expected_update_rate * 0.9)
        latency_ok = avg_latency <= self.max_latency
        cpu_ok = avg_cpu < self.max_cpu

        self.results.update({
            'update_rate_achieved': update_rate,
            'avg_latency': avg_latency,
            'max_latency': max_latency,
            'avg_cpu': avg_cpu,
            'max_cpu': max_cpu,
            'packets_received': packets,
            'packets_expected': expected,
            'packet_loss': loss,
            'packet_loss_percent': loss_percent,
            'test_passed': update_ok and latency_ok and cpu_ok
        })

    # ---------- Report ----------
    def generate_report(self):
        r = self.results
        report = []
        report.append("=" * 60)
        report.append("PHASE 1 BASELINE TEST RESULTS - GRID CLASH UDP")
        report.append("=" * 60)
        report.append("")
        report.append("PERFORMANCE METRICS:")
        report.append("-" * 40)
        report.append(f"Update Rate:    {r['update_rate_achieved']:.1f} Hz (Target: {self.expected_update_rate} Hz)")
        report.append(f"Avg Latency:    {r['avg_latency']:.1f} ms (Target: <= {self.max_latency} ms)")
        report.append(f"Max Latency:    {r['max_latency']:.1f} ms")
        report.append(f"Avg CPU:        {r['avg_cpu']:.1f}% (Target: < {self.max_cpu}%)")
        report.append(f"Max CPU:        {r['max_cpu']:.1f}%")
        report.append(f"Packets:        {r['packets_received']}/{int(r['packets_expected'])} received")
        report.append(f"Packet Loss:    {r['packet_loss_percent']:.1f}%")
        report.append("")
        report.append("ACCEPTANCE CRITERIA:")
        report.append("-" * 40)
        report.append(f"Update Rate >= {self.expected_update_rate * 0.9:.1f} Hz: {'✅ PASS' if r['update_rate_achieved'] >= (self.expected_update_rate * 0.9) else '❌ FAIL'}")
        report.append(f"Latency <= {self.max_latency} ms: {'✅ PASS' if r['avg_latency'] <= self.max_latency else '❌ FAIL'}")
        report.append(f"CPU < {self.max_cpu}%: {'✅ PASS' if r['avg_cpu'] < self.max_cpu else '❌ FAIL'}")
        report.append("")
        report.append("OVERALL RESULT:")
        report.append("-" * 40)
        if r['test_passed']:
            report.append("🎉 PHASE 1 BASELINE TEST: PASSED")
            report.append("All requirements met - Protocol is working correctly")
        else:
            report.append("❌ PHASE 1 BASELINE TEST: FAILED")
            report.append("Some requirements not met - Review implementation")
        report.append("=" * 60)
        return "\n".join(report)

    def save_results_csv(self):
        fn = "phase1_baseline_results.csv"
        r = self.results
        with open(fn, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['Metric', 'Value', 'Target', 'Status'])
            w.writerow(['Update Rate (Hz)', f"{r['update_rate_achieved']:.1f}", f"{self.expected_update_rate}", 'PASS' if r['update_rate_achieved'] >= (self.expected_update_rate * 0.9) else 'FAIL'])
            w.writerow(['Avg Latency (ms)', f"{r['avg_latency']:.1f}", f"<= {self.max_latency}", 'PASS' if r['avg_latency'] <= self.max_latency else 'FAIL'])
            w.writerow(['Avg CPU (%)', f"{r['avg_cpu']:.1f}", f"< {self.max_cpu}", 'PASS' if r['avg_cpu'] < self.max_cpu else 'FAIL'])
            w.writerow(['Packet Loss (%)', f"{r['packet_loss_percent']:.1f}", 'Minimal', 'PASS' if r['packet_loss_percent'] < 5 else 'FAIL'])
            w.writerow(['Overall Test', 'PASSED' if r['test_passed'] else 'FAILED', 'All Criteria', 'PASS' if r['test_passed'] else 'FAIL'])
        return fn

    # ---------- Runner ----------
    def run_test(self):
        self.print_status("=== GRID CLASH PHASE 1 BASELINE TEST ===")
        self.cleanup_processes()

        if not self.start_server():
            return False

        self.print_status("Running performance measurements...")
        cpu_thread = threading.Thread(target=lambda: self.cpu_readings.extend(self.monitor_server_cpu(self.test_duration + 2)))
        cpu_thread.start()

        data = self.measure_network_performance()
        cpu_thread.join()
        self.calculate_results(data)

        report = self.generate_report()
        print("\n" + report)
        csv_file = self.save_results_csv()
        self.print_status(f"Results saved to: {csv_file}")

        self.cleanup_processes()
        return self.results['test_passed']


def main():
    test = Phase1BaselineTest()
    ok = test.run_test()
    print("\n" + "=" * 60)
    if ok:
        print("🎉 PHASE 1 TEST COMPLETED SUCCESSFULLY")
        print("Your Grid Clash UDP protocol meets all baseline requirements!")
    else:
        print("⚠️  PHASE 1 TEST COMPLETED WITH ISSUES")
        print("Review the results above and fix any failing criteria")
    print("=" * 60)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
