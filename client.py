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
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.client_socket.settimeout(0.01) # Non-blocking
        
        
        self.client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
        
        self.last_snapshot_id = -1
        self.server_address = (server_host, server_port)
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
            'black': (0, 0, 0), 
            'white': (255, 255, 255), 
            'dark_gray': (50, 50, 50),
            'grid_line': (80, 80, 80), 
            'unclaimed': (200, 200, 200),
            'player_1': (255, 50, 50),      # Red
            'player_2': (50, 50, 255),      # Blue
            'player_3': (50, 255, 50),      # Green
            'player_4': (255, 255, 50),     # Yellow
        }
        
        self.my_predicted_pos = [0, 0]
        self.target_positions = {}
        self.render_positions = {} 
        
        
        self.smoothing_factor = 0.6 
        self.last_action_time = 0
        self.action_delay = 0.15 
        
        # Bot variables
        self.last_bot_move = 0
        self.last_bot_acquire = 0
        
        self.metrics = {
            'latency_samples': [],
            'start_time': time.time()
        }

        # ---  Metrics Logging ---
        pid = os.getpid()
        self.csv_logger = GameLogger(f"client_log_{pid}.csv", 
            ["client_id", "snapshot_id", "seq_num", "server_timestamp_ms", 
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
                except: continue
            return False
        except Exception as e:
            print(f"[ERROR] Connection failed: {e}")
            return False

    def start_network_thread(self):
        t = threading.Thread(target=self.receive_data)
        t.daemon = True
        t.start()

    def receive_data(self):
        while self.running:
            try:
                data, addr = self.client_socket.recvfrom(65536)
                recv_time = time.time()
                message = GridClashBinaryProtocol.decode_message(data)
                
                if message:
                    self.handle_server_message(message, recv_time)
                    
            except socket.timeout: continue
            except: continue

    def handle_server_message(self, message, recv_time):
        header = message['header']
        payload = message['payload']
        msg_type = header['msg_type']
        
        # 1. Metrics Logging (For every packet)
        server_ts_ms = header['timestamp']
        recv_time_ms = int(recv_time * 1000)
        
        latency_ms = 0
        if server_ts_ms > 0:
            latency_ms = recv_time_ms - server_ts_ms
            self.metrics['latency_samples'].append(latency_ms)

        # Log to CSV file
        p1_render = self.render_positions.get('player_1', [0,0])
        
        # Avoid crashing if we don't have an ID yet
        log_id = self.player_id if self.player_id else "unknown"
        
        self.csv_logger.log([
            log_id,
            header['snapshot_id'],
            header['seq_num'],
            server_ts_ms,
            recv_time_ms,
            latency_ms,
            p1_render[0], p1_render[1]
        ])

        # 2. Reliability (Handle ACKs)
        ack_seq = None
        if msg_type == GridClashBinaryProtocol.MSG_ACK:
            ack_seq = payload.get('acked_seq')
        elif msg_type == GridClashBinaryProtocol.MSG_ACQUIRE_RESPONSE:
            # Implicit ACK
            try:
                self.client_socket.sendto(GridClashBinaryProtocol.encode_ack(header['seq_num']), self.server_address)
            except: pass
        
        if ack_seq and ack_seq in self.pending_requests:
            del self.pending_requests[ack_seq]

        # 3. Game Logic
        if msg_type == GridClashBinaryProtocol.MSG_WELCOME:
            self.player_id = payload.get('player_id')
            if payload: 
                self.game_data.update(payload)
                if 'grid' in payload: 
                    self.game_data['grid'] = payload['grid'].copy()
            if 'player_positions' in payload:
                self.target_positions = payload['player_positions'].copy()
                for pid, pos in self.target_positions.items():
                    self.render_positions[pid] = list(pos)
            if self.player_id in self.target_positions:
                self.my_predicted_pos = list(self.target_positions[self.player_id])
            
        elif msg_type == GridClashBinaryProtocol.MSG_GAME_STATE:
            snapshot_id = header['snapshot_id']
            if snapshot_id <= self.last_snapshot_id: return 
            self.last_snapshot_id = snapshot_id

            if payload:
                self.game_data['players'] = payload.get('players', {})
                self.game_data['game_over'] = payload.get('game_over', False)
                self.game_data['winner_id'] = payload.get('winner_id', None)
                
                # Delta Decoding - Update grid with new changes
                for cell_id, cell_data in payload.get('grid', {}).items():
                    self.game_data['grid'][cell_id] = cell_data
                
                if 'player_positions' in payload:
                    new_positions = payload['player_positions']
                    for pid, pos in new_positions.items():
                        self.target_positions[pid] = pos
                        if pid not in self.render_positions:
                            self.render_positions[pid] = list(pos)
                
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

    def update_interpolation(self):
        for pid in self.target_positions:
            if pid not in self.render_positions: continue
            target = self.target_positions[pid]
            current = self.render_positions[pid]
            
            if pid == self.player_id:
                # If we are controlling this player, trust local prediction more (Client-side prediction)
                # But if deviation is too large (reconciliation), snap back.
                dist = ((target[0]-self.my_predicted_pos[0])**2 + (target[1]-self.my_predicted_pos[1])**2)**0.5
                if dist > 2.0:
                     self.my_predicted_pos = list(target)
                
                target = self.my_predicted_pos
                self.render_positions[pid] = [float(target[0]), float(target[1])]
                continue

            # Smoothing for other players
            current[0] += (target[0] - current[0]) * self.smoothing_factor
            current[1] += (target[1] - current[1]) * self.smoothing_factor
            
            if abs(target[0] - current[0]) < 0.01: current[0] = float(target[0])
            if abs(target[1] - current[1]) < 0.01: current[1] = float(target[1])

    def handle_input(self):
        if not self.player_id or "unknown" in self.player_id: 
            if not self.headless:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT: self.running = False
            return

        # --- BOT LOGIC (For Headless/Testing) ---
        if self.headless:
            self.handle_bot_input()
            return

        # --- HUMAN INPUT (Pygame) ---
        current_time = time.time()
        keys = pygame.key.get_pressed()
        
        for event in pygame.event.get():
            if event.type == pygame.QUIT: self.running = False; return
            elif event.type == pygame.KEYDOWN:
                if event.key in [pygame.K_SPACE, pygame.K_RETURN]:
                    pos = self.my_predicted_pos
                    cell_id = f"{int(pos[0])}_{int(pos[1])}"
                    self.send_acquire_request(self.player_id, cell_id)

        if current_time - self.last_action_time >= self.action_delay:
            current_pos = list(self.my_predicted_pos)
            original = list(current_pos)
            
            if keys[pygame.K_w] or keys[pygame.K_UP]: 
                if current_pos[0] > 0: current_pos[0] -= 1
            elif keys[pygame.K_s] or keys[pygame.K_DOWN]: 
                if current_pos[0] < self.grid_size - 1: current_pos[0] += 1
            elif keys[pygame.K_a] or keys[pygame.K_LEFT]: 
                if current_pos[1] > 0: current_pos[1] -= 1
            elif keys[pygame.K_d] or keys[pygame.K_RIGHT]: 
                if current_pos[1] < self.grid_size - 1: current_pos[1] += 1
            
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
            
            if move_dir == 'up' and current_pos[0] > 0: current_pos[0] -= 1
            elif move_dir == 'down' and current_pos[0] < self.grid_size - 1: current_pos[0] += 1
            elif move_dir == 'left' and current_pos[1] > 0: current_pos[1] -= 1
            elif move_dir == 'right' and current_pos[1] < self.grid_size - 1: current_pos[1] += 1
            
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
        msg = GridClashBinaryProtocol.encode_acquire_request(player_id, cell_id, time.time(), self.sequence_num)
        
        # Reliability: Store for retry
        self.pending_requests[self.sequence_num] = {
            'data': msg, 'time': time.time(), 'retries': 0
        }
        try: self.client_socket.sendto(msg, self.server_address)
        except: pass

    def send_player_move(self, player_id, position):
        self.sequence_num += 1
        msg = GridClashBinaryProtocol.encode_player_move(player_id, position, self.sequence_num)
        try: self.client_socket.sendto(msg, self.server_address)
        except: pass

    def send_heartbeat(self):
        msg = GridClashBinaryProtocol.encode_heartbeat()
        try: self.client_socket.sendto(msg, self.server_address)
        except: pass

    def initialize_graphics(self):
        try:
            pygame.init() # Already called in run, but safe to call again
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
                cell_color = self.COLORS['unclaimed']  # Default: unclaimed
                
                if 'grid' in self.game_data and cell_id in self.game_data['grid']:
                    cell_data = self.game_data['grid'][cell_id]
                    if 'owner_id' in cell_data:
                        owner = cell_data['owner_id']
                        # Map owner_id to color
                        if owner in self.COLORS:
                            cell_color = self.COLORS[owner]
                        else:
                            # Fallback: use color based on player number
                            if owner == 'player_1':
                                cell_color = (255, 50, 50)      # Red
                            elif owner == 'player_2':
                                cell_color = (50, 50, 255)      # Blue
                            elif owner == 'player_3':
                                cell_color = (50, 255, 50)      # Green
                            elif owner == 'player_4':
                                cell_color = (255, 255, 50)     # Yellow
                            else:
                                cell_color = self.COLORS['dark_gray']
                
                # Draw the cell
                rect = pygame.Rect(col*self.cell_size, row*self.cell_size, 
                                 self.cell_size, self.cell_size)
                pygame.draw.rect(self.screen, cell_color, rect)
                pygame.draw.rect(self.screen, self.COLORS['grid_line'], rect, 1)
        
        # Draw players (cursors)
        for pid, pos in self.render_positions.items():
            r, c = pos[0], pos[1]
            
            # Get color for this player
            if pid in self.COLORS:
                color = self.COLORS[pid]
            else:
                # Default colors if not found
                if pid == 'player_1':
                    color = (255, 50, 50)      # Red
                elif pid == 'player_2':
                    color = (50, 50, 255)      # Blue
                elif pid == 'player_3':
                    color = (50, 255, 50)      # Green
                elif pid == 'player_4':
                    color = (255, 255, 50)     # Yellow
                else:
                    color = self.COLORS['white']
            
            # Draw thicker border for local player
            width = 3 if pid != self.player_id else 5
            cursor_rect = pygame.Rect(c * self.cell_size, r * self.cell_size, 
                                    self.cell_size, self.cell_size)
            pygame.draw.rect(self.screen, color, cursor_rect, width)

    def draw_ui(self):
        if not self.screen: 
            return
            
        # Side panel
        panel = pygame.Rect(self.grid_size * self.cell_size, 0, 450, self.screen_height)
        pygame.draw.rect(self.screen, self.COLORS['dark_gray'], panel)
        
        # Draw player info with scores
        y_offset = 20
        player_colors = {
            'player_1': (255, 50, 50),      # Red
            'player_2': (50, 50, 255),      # Blue  
            'player_3': (50, 255, 50),      # Green
            'player_4': (255, 255, 50),     # Yellow
        }
        
        for pid in ['player_1', 'player_2', 'player_3', 'player_4']:
            # Get score from game data
            score = 0
            if pid in self.game_data.get('players', {}):
                score = self.game_data['players'][pid].get('score', 0)
            elif pid in self.game_data.get('grid', {}):
                # Count cells owned by this player
                owned_cells = sum(1 for cell_data in self.game_data['grid'].values() 
                               if cell_data.get('owner_id') == pid)
                score = owned_cells
            
            color = player_colors.get(pid, (255, 255, 255))
            text = f"{pid}: {score} cells"
            
            # Highlight current player
            if pid == self.player_id:
                text = f">> {text} << (YOU)"
                
            txt_surface = self.font.render(text, True, color)
            self.screen.blit(txt_surface, (self.grid_size * self.cell_size + 20, y_offset))
            y_offset += 30
        
        # Draw latency info
        if self.metrics['latency_samples']:
            avg = sum(self.metrics['latency_samples'])/len(self.metrics['latency_samples'])
            txt = self.font.render(f"Ping: {avg:.0f}ms", True, (255,255,255))
            self.screen.blit(txt, (self.grid_size * self.cell_size + 20, 150))
        
        # Game status
        if self.game_data['game_over']:
            winner = self.game_data['winner_id']
            if winner == 'tie':
                status = "GAME OVER! It's a TIE!"
            else:
                status = f"GAME OVER! Winner: {winner}"
            txt = self.font.render(status, True, (255, 255, 0))
            self.screen.blit(txt, (self.grid_size * self.cell_size + 20, 180))
        elif self.game_data['game_started']:
            txt = self.font.render("Game in progress", True, (0, 255, 0))
            self.screen.blit(txt, (self.grid_size * self.cell_size + 20, 180))

    def run(self):
        # Disable video driver in headless mode to save massive CPU usage
        self.headless = "--headless" in sys.argv
        if self.headless:
            os.environ["SDL_VIDEODRIVER"] = "dummy"

        pygame.init()
        
        if not self.connect_to_server(): 
            print("❌ Connection failed!")
            return
        
        if not self.headless:
            if not self.initialize_graphics(): return
        else:
            print(f"[{self.player_id}] Running in HEADLESS BOT mode (Optimized)")
        
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

            # Retry Logic for pending requests
            current_time = time.time()
            to_delete = []
            for seq, req in self.pending_requests.items():
                if current_time - req['time'] > 0.1:
                    if req['retries'] < 10:
                        try:
                            self.client_socket.sendto(req['data'], self.server_address)
                            req['time'] = current_time
                            req['retries'] += 1
                        except: pass
                    else: to_delete.append(seq)
            for s in to_delete: del self.pending_requests[s]
            
            # Only draw if screen exists and not headless
            if not self.headless and self.screen:
                self.screen.fill(self.COLORS['black'])
                self.draw_grid()
                self.draw_ui()
                pygame.display.flip()
                clock.tick(60)
            else:
                
                time.sleep(0.06)
                
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