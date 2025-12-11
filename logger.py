import csv
import time
import threading
import os

class GameLogger:
    def __init__(self, filename, headers):
        self.filename = filename
        self.headers = headers
        self.queue = []
        self.lock = threading.Lock()
        self.running = True
        
        # Create file and write headers (overwrite if exists)
        try:
            with open(self.filename, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
        except PermissionError:
            print(f"[WARN] Could not write to {filename}. File might be open.")
            
        # Start background writer thread
        self.thread = threading.Thread(target=self._flush_loop, daemon=True)
        self.thread.start()

    def log(self, row_data):
        with self.lock:
            self.queue.append(row_data)

    def _flush_loop(self):
        while self.running:
            time.sleep(1.0) # Flush every second to save IO overhead
            self.flush()

    def flush(self):
        with self.lock:
            if not self.queue:
                return
            data_to_write = list(self.queue)
            self.queue.clear()
            
        try:
            with open(self.filename, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerows(data_to_write)
        except Exception as e:
            # Silently ignore errors to avoid crashing game loop
            pass

    def close(self):
        self.running = False
        self.flush()