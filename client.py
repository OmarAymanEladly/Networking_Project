import pygame
import socket
import threading
import sys
import time
import random 
import os
import argparse
from protocol import GridClashBinaryProtocol
from logger import GameLogger

class GridClashUDPClient:
    def __init__(self, server_host='127.0.0.1', server_port=5555):
        self.server_host = server_host
        self.server_port = server_port
        self.server_address = (self.server_host, self.server_port)
        
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.client_socket.settimeout(0.01)  # Non-blocking
        
        # INCREASE BUFFER SIZE for 20Hz updates
        self.client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
        
        self.last_snapshot_id = -1
        self.sequence_num = 0
        self.player_id = f"unknown_{random.randint(1000,9999)}" 
        
        # Phase 2 Reliability (ARQ) for critical events
        self.pending_requests = {} 
        
        self.game_data = {
            'grid': {}, 'players': {}, 
            'game_started': False, 'game_over': False, 'winner_id': None
        }
        self.running = False
        self.headless = False
        
        self.grid_size = 20
        self.cell_size = 30
        self.screen_width = self.grid_size * self.cell_size + 450
        self.screen_height = self.grid_size * self.cell_size
        self.screen = None
        
        self.COLORS = {
            'black': (0, 0, 0), 'white': (255, 255, 255), 'dark_gray': (50, 50, 50),
            'grid_line': (80, 80, 80), 'unclaimed': (200, 200, 200),
            'player1': (255, 50, 50), 'player2': (50, 50, 255),
            'player3': (50, 255, 50), 'player4': (255, 255, 50),    
        }
        
        self.my_predicted_pos = [0, 0]
        self.target_positions = {}
        self.render_positions = {} 
        self.smoothing_factor = 0.2 
        self.last_action_time = 0
        self.action_delay = 0.15 
        
        # Bot variables
        self.last_bot_move = 0
        self.last_bot_acquire = 0
        
        # Track update rate
        self.last_update_time = 0
        self.update_intervals = []
        self.last_game_state_time = None

        # Time tracking for accurate latency measurement
        self.client_start_time = time.perf_counter()
        self.server_time_offset = 0  # For clock synchronization
        
        # Acquisition tracking for RTT measurement
        self.acquisition_attempts = []
        
        # Metrics
        self.metrics = {
            'latency_samples': [],
            'lost_packets': 0,
            'update_intervals': [],
            'start_time': time.perf_counter()
        }

        # --- FIXED: Simplified CSV Logging ---
        pid = os.getpid()
        # FIXED: Only log essential data for latency and position analysis
        self.csv_logger = GameLogger(f"client_data_{pid}.csv", 
            ["client_id", "snapshot_id", "seq_num", 
             "recv_time_ms", "latency_ms", "render_x", "render_y"])

    def connect_to_server(self):
        try:
            connect_msg = b"CONNECT"
            self.client_socket.sendto(connect_msg, self.server_address)
            print(f">> Connecting to {self.server_host}:{self.server_port}...")
            
            start_time = time.time()
            while time.time() - start_time < 5:
                try:
                    data, addr = self.client_socket.recvfrom(65536)
                    message = GridClashBinaryProtocol.decode_message(data)
                    if message and message['header']['msg_type'] == GridClashBinaryProtocol.MSG_WELCOME:
                        self.handle_server_message(message, time.time())
                        if self.player_id and "unknown" not in self.player_id:
                            print(f"[OK] Connected! Assigned ID: {self.player_id}")
                            return True
                except:
                    continue
            return False
        except Exception as e:
            print(f"[ERROR] Connection failed: {e}")
            return False

    def start_network_thread(self):
        t = threading.Thread(target=self.receive_data)
        t.daemon = True
        t.start()

    def receive_data(self):
        packet_count = 0
        while self.running:
            try:
                data, addr = self.client_socket.recvfrom(65536)
                recv_time = time.perf_counter()  # Use perf_counter for accurate timing
                message = GridClashBinaryProtocol.decode_message(data)
                
                if message:
                    packet_count += 1
                    # Debug: print every 20th packet
                    if packet_count % 20 == 0:
                        msg_type_name = GridClashBinaryProtocol.get_message_type_name(
                            message['header']['msg_type'])
                        print(f"[CLIENT {self.player_id}] Received packet {packet_count}, type: {msg_type_name}")
                    
                    self.handle_server_message(message, recv_time)
                    
            except socket.timeout: 
                continue
            except Exception as e:
                print(f"[CLIENT {self.player_id}] Receive error: {e}")
                continue

    def handle_server_message(self, message, recv_time):
        header = message['header']
        payload = message['payload']
        msg_type = header['msg_type']
        
        # 1. FIXED: Calculate accurate latency
        if 'server_timestamp' in header:
            # Server timestamp is in milliseconds since server start
            server_time_ms = header['server_timestamp']
            client_time_ms = (recv_time - self.client_start_time) * 1000
            
            # One-way latency estimate (half RTT)
            # For critical events, we'll use actual RTT from acquisition attempts
            latency_ms = (client_time_ms - server_time_ms)
            
            # For game state updates, estimate one-way latency
            # This is reasonable if clocks are roughly synchronized
            if latency_ms < 0:
                latency_ms = 1  # Minimum 1ms
            elif latency_ms > 5000:
                latency_ms = 5000  # Cap at 5 seconds
        else:
            # Fallback if no server timestamp
            latency_ms = 1
        
        # For acquisition responses, use actual RTT
        if msg_type == GridClashBinaryProtocol.MSG_ACQUIRE_RESPONSE:
            # Find matching acquisition request for accurate RTT
            for attempt in self.acquisition_attempts:
                if (attempt['cell_id'] == payload.get('cell_id') and 
                    not attempt['response_received'] and
                    attempt['seq_num'] == header.get('seq_num', 0)):
                    
                    actual_rtt = (recv_time - attempt['request_time']) * 1000
                    latency_ms = actual_rtt / 2  # One-way latency
                    
                    attempt['response_time'] = recv_time
                    attempt['response_received'] = True
                    attempt['success'] = payload.get('success', False)
                    attempt['latency_ms'] = actual_rtt
                    
                    print(f"[CLIENT] Acquisition RTT: {actual_rtt:.1f}ms, One-way: {latency_ms:.1f}ms")
                    break
        
        # Track latency samples
        self.metrics['latency_samples'].append(latency_ms)
        if len(self.metrics['latency_samples']) > 100:
            self.metrics['latency_samples'].pop(0)
        
        # 2. FIXED: Simplified CSV Logging
        try:
            p1_render = self.render_positions.get('player_1', [0, 0])
            log_id = self.player_id if self.player_id else "unknown"
            
            self.csv_logger.log([
                log_id,
                header.get('snapshot_id', 0),
                header.get('seq_num', 0),
                int((recv_time - self.client_start_time) * 1000),  # recv_time_ms
                int(latency_ms),  # latency_ms
                p1_render[0],  # render_x
                p1_render[1]   # render_y
            ])
        except Exception as e:
            print(f"[ERROR] Failed to log CSV: {e}")
        
        # 3. Track update rate statistics
        if msg_type == GridClashBinaryProtocol.MSG_GAME_STATE:
            current_time = time.perf_counter()
            if self.last_game_state_time:
                interval = (current_time - self.last_game_state_time) * 1000
                self.update_intervals.append(interval)
                
                if len(self.update_intervals) > 200:
                    self.update_intervals.pop(0)
                
                # Log update rate every 100 packets
                if len(self.update_intervals) % 100 == 0:
                    avg_interval = sum(self.update_intervals) / len(self.update_intervals)
                    rate = 1000.0 / avg_interval if avg_interval > 0 else 0
                    avg_latency = sum(self.metrics['latency_samples'][-50:]) / min(50, len(self.metrics['latency_samples']))
                    print(f"[CLIENT {self.player_id}] Update: {rate:.1f}Hz, Latency: {avg_latency:.1f}ms")
            
            self.last_game_state_time = current_time
        
        # 4. Game Logic
        if msg_type == GridClashBinaryProtocol.MSG_WELCOME:
            self.player_id = payload.get('player_id')
            print(f"[CLIENT] Assigned player ID: {self.player_id}")
            
            if payload: 
                self.game_data['grid'] = {}
                self.game_data.update(payload)
                
                if 'grid' in payload:
                    for cell_id, cell_data in payload['grid'].items():
                        self.game_data['grid'][cell_id] = cell_data.copy()
                        
                if 'player_positions' in payload:
                    self.target_positions = payload['player_positions'].copy()
                    for pid, pos in self.target_positions.items():
                        self.render_positions[pid] = list(pos)
                        
                if not hasattr(self, 'last_target_pos'):
                    self.last_target_pos = {}
                    
                if self.player_id in self.target_positions:
                    self.my_predicted_pos = list(self.target_positions[self.player_id])
                    self.last_target_pos[self.player_id] = list(self.target_positions[self.player_id])
                
            print(f"[CLIENT] Welcome complete. Grid size: {len(self.game_data.get('grid', {}))} cells")
                
        elif msg_type == GridClashBinaryProtocol.MSG_GAME_STATE:
            snapshot_id = header['snapshot_id']
            
            if snapshot_id < self.last_snapshot_id - 5:
                print(f"[CLIENT] Skipping old snapshot: {snapshot_id} (current: {self.last_snapshot_id})")
                return 
                
            self.last_snapshot_id = max(self.last_snapshot_id, snapshot_id)

            if payload:
                if 'players' in payload:
                    self.game_data['players'] = payload.get('players', {})
                    
                self.game_data['game_over'] = payload.get('game_over', False)
                self.game_data['winner_id'] = payload.get('winner_id', None)
                
                if 'grid' in payload:
                    for cell_id, cell_data in payload.get('grid', {}).items():
                        self.game_data['grid'][cell_id] = cell_data
                
                if 'player_positions' in payload:
                    new_positions = payload['player_positions']
                    for pid, pos in new_positions.items():
                        if pid in self.target_positions:
                            if not hasattr(self, 'last_target_pos'):
                                self.last_target_pos = {}
                            self.last_target_pos[pid] = list(self.target_positions[pid])
                        
                        self.target_positions[pid] = pos
                        
                        if pid not in self.render_positions:
                            self.render_positions[pid] = list(pos)
                
            # Track packet loss
            if hasattr(self, 'expected_snapshot_id'):
                if snapshot_id > self.expected_snapshot_id + 1:
                    lost_packets = snapshot_id - self.expected_snapshot_id - 1
                    print(f"[CLIENT] Detected {lost_packets} lost packets")
                    self.metrics['lost_packets'] = self.metrics.get('lost_packets', 0) + lost_packets
            
            self.expected_snapshot_id = snapshot_id + 1
            
        elif msg_type == GridClashBinaryProtocol.MSG_ACQUIRE_RESPONSE:
            if payload.get('success'):
                cell_id = payload['cell_id']
                owner_id = payload.get('owner_id')
                if 'grid' not in self.game_data: 
                    self.game_data['grid'] = {}
                self.game_data['grid'][cell_id] = {'owner_id': owner_id}
                print(f"[CLIENT] Cell {cell_id} acquired by {owner_id}")
            else:
                cell_id = payload['cell_id']
                owner_id = payload.get('owner_id')
                print(f"[CLIENT] Failed to acquire cell {cell_id} (owned by {owner_id})")
                    
        elif msg_type == GridClashBinaryProtocol.MSG_GAME_OVER:
            self.game_data['game_over'] = True
            self.game_data['winner_id'] = payload.get('winner_id')
            print(f"[CLIENT] Game Over! Winner: {self.game_data['winner_id']}")
            
            if 'scoreboard' in payload:
                print(f"Final scores: {payload['scoreboard']}")
            
            if self.metrics['latency_samples']:
                avg_latency = sum(self.metrics['latency_samples']) / len(self.metrics['latency_samples'])
                print(f"Average latency: {avg_latency:.1f}ms")
        
        elif msg_type == GridClashBinaryProtocol.MSG_HEARTBEAT:
            # Server heartbeat - just acknowledge
            pass

    def update_interpolation(self):
        current_time = time.time()
        
        for pid in self.target_positions:
            if pid not in self.render_positions:
                self.render_positions[pid] = list(self.target_positions[pid])
                continue
                
            target = self.target_positions[pid]
            current = self.render_positions[pid]
            
            if pid == self.player_id:
                # For local player, use prediction
                if hasattr(self, 'last_target_pos') and pid in self.last_target_pos:
                    old_pos = self.last_target_pos[pid]
                    time_diff = current_time - self.last_update_time
                    if time_diff > 0:
                        # Simple velocity prediction
                        velocity = [(target[0] - old_pos[0]) / time_diff,
                                (target[1] - old_pos[1]) / time_diff]
                        
                        # Predict current position
                        pred_x = target[0] + velocity[0] * 0.025
                        pred_y = target[1] + velocity[1] * 0.025
                        self.render_positions[pid] = [pred_x, pred_y]
                
                self.last_target_pos[pid] = list(target)
                continue
            
            # For other players, use interpolation
            fast_smoothing = 0.4
            
            dx = target[0] - current[0]
            dy = target[1] - current[1]
            
            if abs(dx) < 0.1 and abs(dy) < 0.1:
                current[0] = target[0]
                current[1] = target[1]
            else:
                current[0] += dx * fast_smoothing
                current[1] += dy * fast_smoothing

    def handle_input(self):
        if not self.player_id or "unknown" in self.player_id: 
            if not self.headless:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self.running = False
            return

        # --- BOT LOGIC (For Headless/Testing) ---
        if self.headless:
            self.handle_bot_input()
            return

        # --- HUMAN INPUT (Pygame) ---
        current_time = time.time()
        keys = pygame.key.get_pressed()
        
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
                return
            elif event.type == pygame.KEYDOWN:
                if event.key in [pygame.K_SPACE, pygame.K_RETURN]:
                    pos = self.my_predicted_pos
                    cell_id = f"{int(pos[0])}_{int(pos[1])}"
                    self.send_acquire_request(self.player_id, cell_id)

        if current_time - self.last_action_time >= self.action_delay:
            current_pos = list(self.my_predicted_pos)
            original = list(current_pos)
            
            if keys[pygame.K_w] or keys[pygame.K_UP]: 
                if current_pos[0] > 0:
                    current_pos[0] -= 1
            elif keys[pygame.K_s] or keys[pygame.K_DOWN]: 
                if current_pos[0] < self.grid_size - 1:
                    current_pos[0] += 1
            elif keys[pygame.K_a] or keys[pygame.K_LEFT]: 
                if current_pos[1] > 0:
                    current_pos[1] -= 1
            elif keys[pygame.K_d] or keys[pygame.K_RIGHT]: 
                if current_pos[1] < self.grid_size - 1:
                    current_pos[1] += 1
            elif keys[pygame.K_SPACE]:
                cell_id = f"{int(current_pos[0])}_{int(current_pos[1])}"
                self.send_acquire_request(self.player_id, cell_id)
                self.last_action_time = current_time
                return
            
            if current_pos != original:
                self.my_predicted_pos = current_pos
                self.send_player_move(self.player_id, current_pos)
                self.last_action_time = current_time

    def handle_bot_input(self):
        """Simulate random movement and acquisition for automated tests"""
        current_time = time.time()
        
        # Move every 0.2 seconds
        if current_time - self.last_bot_move > 0.2:
            current_pos = list(self.my_predicted_pos)
            move_dir = random.choice(['up', 'down', 'left', 'right', 'none'])
            
            if move_dir == 'up' and current_pos[0] > 0:
                current_pos[0] -= 1
            elif move_dir == 'down' and current_pos[0] < self.grid_size - 1:
                current_pos[0] += 1
            elif move_dir == 'left' and current_pos[1] > 0:
                current_pos[1] -= 1
            elif move_dir == 'right' and current_pos[1] < self.grid_size - 1:
                current_pos[1] += 1
            
            self.my_predicted_pos = current_pos
            self.send_player_move(self.player_id, current_pos)
            self.last_bot_move = current_time
            
        # Try to acquire every 1.0 seconds
        if current_time - self.last_bot_acquire > 1.0:
            pos = self.my_predicted_pos
            cell_id = f"{int(pos[0])}_{int(pos[1])}"
            self.send_acquire_request(self.player_id, cell_id)
            self.last_bot_acquire = current_time

    def send_acquire_request(self, player_id, cell_id):
        self.sequence_num += 1
        request_time = time.perf_counter()  # Store exact send time
        
        # Track acquisition attempt for RTT measurement
        self.acquisition_attempts.append({
            'cell_id': cell_id,
            'request_time': request_time,
            'seq_num': self.sequence_num,
            'response_received': False,
            'response_time': None,
            'success': False,
            'latency_ms': None
        })
        
        # Keep only recent attempts
        if len(self.acquisition_attempts) > 20:
            self.acquisition_attempts.pop(0)
        
        msg = GridClashBinaryProtocol.encode_acquire_request(
            player_id, cell_id, time.time(), self.sequence_num)
        
        # Reliability: Store for retry
        self.pending_requests[self.sequence_num] = {
            'data': msg, 'time': time.time(), 'retries': 0
        }
        
        try: 
            self.client_socket.sendto(msg, self.server_address)
        except Exception as e:
            print(f"[ERROR] Failed to send acquire request: {e}")

    def send_player_move(self, player_id, position):
        self.sequence_num += 1
        msg = GridClashBinaryProtocol.encode_player_move(player_id, position, self.sequence_num)
        try: 
            self.client_socket.sendto(msg, self.server_address)
        except Exception as e:
            print(f"[ERROR] Failed to send player move: {e}")

    def send_heartbeat(self):
        msg = GridClashBinaryProtocol.encode_heartbeat()
        try: 
            self.client_socket.sendto(msg, self.server_address)
        except Exception as e:
            print(f"[ERROR] Failed to send heartbeat: {e}")

    def initialize_graphics(self):
        try:
            pygame.init()
            self.screen = pygame.display.set_mode((self.screen_width, self.screen_height))
            pygame.display.set_caption(f"Grid Clash Client - {self.player_id}")
            self.font = pygame.font.Font(None, 24)
            return True
        except Exception as e:
            print(f"Graphics Init Failed: {e}")
            return False

    def draw_grid(self):
        if not self.screen:
            return
            
        for row in range(self.grid_size):
            for col in range(self.grid_size):
                cell_id = f"{row}_{col}"
                cell_color = self.COLORS['unclaimed']
                
                if 'grid' in self.game_data and cell_id in self.game_data['grid']:
                    cell_data = self.game_data['grid'][cell_id]
                    if 'owner_id' in cell_data:
                        owner = cell_data['owner_id']
                        
                        if owner == 'player_1':
                            cell_color = self.COLORS['player1']
                        elif owner == 'player_2':
                            cell_color = self.COLORS['player2']
                        elif owner == 'player_3':
                            cell_color = self.COLORS['player3']
                        elif owner == 'player_4':
                            cell_color = self.COLORS['player4']
                        else:
                            cell_color = self.COLORS['dark_gray']
                
                rect = pygame.Rect(col*self.cell_size, row*self.cell_size, 
                                 self.cell_size, self.cell_size)
                pygame.draw.rect(self.screen, cell_color, rect)
                pygame.draw.rect(self.screen, self.COLORS['grid_line'], rect, 1)
        
        for pid, pos in self.render_positions.items():
            r, c = pos[0], pos[1]
            if pid == 'player_1':
                color = self.COLORS['player1']
            elif pid == 'player_2':
                color = self.COLORS['player2']
            elif pid == 'player_3':
                color = self.COLORS['player3']
            elif pid == 'player_4':
                color = self.COLORS['player4']
            else:
                color = self.COLORS['white']
                
            cursor_rect = pygame.Rect(c * self.cell_size, r * self.cell_size, 
                                    self.cell_size, self.cell_size)
            width = 3 if pid != self.player_id else 5
            pygame.draw.rect(self.screen, color, cursor_rect, width)

    def draw_ui(self):
        if not self.screen:
            return
            
        panel = pygame.Rect(self.grid_size * self.cell_size, 0, 450, self.screen_height)
        pygame.draw.rect(self.screen, self.COLORS['dark_gray'], panel)
        
        # Draw player info
        y_offset = 20
        for pid, player_data in self.game_data.get('players', {}).items():
            if pid in self.COLORS:
                color = self.COLORS[pid]
            else:
                color = self.COLORS['white']
                
            text = f"{pid}: {player_data.get('score', 0)} points"
            if pid == self.player_id:
                text = f">> {text} << (YOU)"
                
            txt_surface = self.font.render(text, True, color)
            self.screen.blit(txt_surface, (self.grid_size * self.cell_size + 20, y_offset))
            y_offset += 30
        
        # Draw latency info
        if self.metrics['latency_samples']:
            recent_samples = self.metrics['latency_samples'][-20:]  # Last 20 samples
            if recent_samples:
                avg = sum(recent_samples) / len(recent_samples)
                txt = self.font.render(f"Ping: {avg:.0f}ms", True, (255,255,255))
                self.screen.blit(txt, (self.grid_size * self.cell_size + 20, 150))
        
        # Draw update rate
        if self.update_intervals:
            recent_intervals = self.update_intervals[-20:]  # Last 20 intervals
            if recent_intervals:
                avg_interval = sum(recent_intervals) / len(recent_intervals)
                rate = 1000.0 / avg_interval if avg_interval > 0 else 0
                txt = self.font.render(f"Update Rate: {rate:.1f} Hz", True, (255,255,255))
                self.screen.blit(txt, (self.grid_size * self.cell_size + 20, 180))
        
        # Draw game status
        if self.game_data['game_over']:
            status_text = f"GAME OVER! Winner: {self.game_data['winner_id']}"
            txt = self.font.render(status_text, True, (255, 255, 0))
            self.screen.blit(txt, (self.grid_size * self.cell_size + 20, 200))
        elif self.game_data['game_started']:
            txt = self.font.render("Game in progress", True, (0, 255, 0))
            self.screen.blit(txt, (self.grid_size * self.cell_size + 20, 200))

    def run(self):
        # Always init pygame for event loop/timers, even if headless
        pygame.init()
        
        if not self.connect_to_server(): 
            print("❌ Connection failed!")
            return
        
        self.headless = "--headless" in sys.argv
        if not self.headless:
            if not self.initialize_graphics():
                return
        else:
            print(f"[{self.player_id}] Running in HEADLESS BOT mode")
        
        self.running = True
        self.start_network_thread()
        clock = pygame.time.Clock()
        last_hb = time.time()
        
        while self.running:
            self.handle_input()
            self.update_interpolation()
            
            if time.time() - last_hb > 1.0:
                self.send_heartbeat()
                last_hb = time.time()

            # Retry Logic
            current_time = time.time()
            to_delete = []
            for seq, req in self.pending_requests.items():
                if current_time - req['time'] > 0.1:
                    if req['retries'] < 10:
                        try:
                            self.client_socket.sendto(req['data'], self.server_address)
                            req['time'] = current_time
                            req['retries'] += 1
                        except:
                            pass
                    else: 
                        to_delete.append(seq)
            
            for s in to_delete: 
                del self.pending_requests[s]
            
            if not self.headless and self.screen:
                self.screen.fill(self.COLORS['black'])
                self.draw_grid()
                self.draw_ui()
                pygame.display.flip()
                clock.tick(60)
            else:
                # Save CPU in headless mode
                time.sleep(0.005)
                
        if self.csv_logger:
            self.csv_logger.close()
        pygame.quit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("host", nargs="?", default="127.0.0.1")
    parser.add_argument("--loss", type=float, default=0.0)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    GridClashUDPClient(server_host=args.host).run()