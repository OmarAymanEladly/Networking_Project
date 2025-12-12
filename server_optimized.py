import socket
import threading
import time
import psutil
from collections import defaultdict
from protocol import GridClashBinaryProtocol
from game_state import GameState
from logger import GameLogger
import argparse
import random
import sys

class GridClashUDPServer:
    def __init__(self, host='0.0.0.0', port=5555, loss_rate=0.0, delay_ms=0, jitter_ms=0):
        self.loss_rate = loss_rate
        self.delay_ms = delay_ms
        self.jitter_ms = jitter_ms
        self.loss_rate = loss_rate
        self.host = host
        self.port = port
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        
        # Critical for handling 4 clients sending data simultaneously
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024 * 1024)
        
        self.clients = {}  
        self.game_state = GameState(grid_size=20)
        self.running = True
        
        # Use RLock to allow re-entry from same thread (Critical for reliability loop)
        self.lock = threading.RLock()
        
        self.snapshot_id = 0
        self.sequence_num = 0
        self.update_rate = 20  # (Send updates every 50ms)
        
        # Reliability Structures (Phase 2 requirement)
        self.retry_queue = {} 
        self.client_last_seen = defaultdict(float)
        
        # Metrics required for Phase 2 Analysis
        self.metrics = {
            'packets_sent': 0,
            'packets_received': 0,
            'bytes_sent': 0,
            'bytes_received': 0,
            'client_count': 0,
            'start_time': time.time()
        }
        
        self.csv_logger = None

    def start_server(self):
        """Main server loop"""
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.settimeout(1.0)
            print(f">>> Grid Clash UDP Server started on {self.host}:{self.port}")
            print(f">>> Update Rate: {self.update_rate}Hz | Loss Simulation: {self.loss_rate*100}%")
            
            # Initialize CSV Logger with Phase 2 required columns
            # We track Player 1's position to compare against what clients see
            self.csv_logger = GameLogger("server_log.csv", 
                ["timestamp", "cpu_percent", "bytes_sent", "player1_pos_x", "player1_pos_y"])
            
            # Start background threads
            threading.Thread(target=self.broadcast_loop, daemon=True).start()
            threading.Thread(target=self.cleanup_loop, daemon=True).start()
            threading.Thread(target=self.metrics_loop, daemon=True).start()
            threading.Thread(target=self.reliability_loop, daemon=True).start()

            while self.running:
                try:
                    data, address = self.server_socket.recvfrom(65536)

                    # Simulate random packet loss (for development testing only)
                    # For final grading, use 'tc netem' instead of this logic
                    if self.loss_rate > 0 and random.random() < self.loss_rate:
                        continue 
                    
                    self.handle_client_message(data, address)
                    
                except socket.timeout:
                    continue
                except ConnectionResetError:
                    # Common UDP issue on Windows if a client closes forcibly
                    continue
                except OSError as e:
                    # Windows-Specific Fix: Ignore WSAEMSGSIZE (10040) errors
                    if hasattr(e, 'winerror') and e.winerror == 10040:
                        continue
                    if self.running:
                        print(f"Server OS warning: {e}")
                    continue
                except Exception as e:
                    if self.running:
                        print(f"Server loop error: {e}")
                    
        except Exception as e:
            print(f"[ERROR] Server fatal error: {e}")
        finally:
            self.shutdown_server()

    def handle_client_message(self, data, address):
        self.metrics['packets_received'] += 1
        self.metrics['bytes_received'] += len(data)
        
        message = GridClashBinaryProtocol.decode_message(data)
        if not message:
            # Handle raw CONNECT strings if protocol fails (fallback)
            if b"CONNECT" in data:
                self.handle_new_client(address)
            return
            
        header = message['header']
        payload = message['payload']
        msg_type = header['msg_type']
        
        self.client_last_seen[address] = time.time()
        
        with self.lock:
            if msg_type == GridClashBinaryProtocol.MSG_ACK:
                self.handle_ack(address, payload)
            elif msg_type == GridClashBinaryProtocol.MSG_ACQUIRE_REQUEST:
                self.handle_acquire_request(address, payload, header['seq_num'])
            elif msg_type == GridClashBinaryProtocol.MSG_PLAYER_MOVE:
                self.handle_player_move(address, payload)
            elif msg_type == GridClashBinaryProtocol.MSG_CONNECT_REQUEST:
                self.handle_new_client(address)
            elif address not in self.clients and msg_type == GridClashBinaryProtocol.MSG_WELCOME:
                # Sometimes clients might re-send welcome related packets
                self.handle_new_client(address)

    def handle_new_client(self, address):
        with self.lock:
            if address in self.clients: return 

            # Assign slots: player_1 to player_4
            taken_ids = set(c['id'] for c in self.clients.values())
            assigned_id = None
            for i in range(1, 5):
                candidate_id = f"player_{i}"
                if candidate_id not in taken_ids:
                    assigned_id = candidate_id
                    break
            
            if assigned_id:
                self.clients[address] = {
                    'id': assigned_id,
                    'controlled_players': [assigned_id], 
                    'last_seq': 0,
                    'join_time': time.time()
                }
                
                self.metrics['client_count'] = len(self.clients)
                print(f">> New connection: {address} assigned to {assigned_id}")
                
                # Send immediate Welcome
                current_state = self.game_state.get_game_data(reset_dirty=False)
                welcome_msg = GridClashBinaryProtocol.encode_welcome(assigned_id, current_state)
                self.send_to_client(address, welcome_msg)
            else:
                print(f"[REJECT] Server full. Active IDs: {taken_ids}")

    def handle_acquire_request(self, address, payload, seq_num):
        if address not in self.clients: 
            return
            
        player_id = payload.get('player_id')
        cell_id = payload.get('cell_id')
        timestamp = payload.get('timestamp', time.time())
        
        # Validation
        if player_id not in self.clients[address]['controlled_players']: 
            return
        
        # Get player color for logging
        player_colors = {
            'player_1': 'RED',
            'player_2': 'BLUE', 
            'player_3': 'GREEN',
            'player_4': 'YELLOW'
        }
        color = player_colors.get(player_id, 'UNKNOWN')
        
        print(f"[ACQUIRE] Player {player_id} ({color}) attempting to claim cell {cell_id}")
        
        # Game State Logic
        success, result = self.game_state.process_acquire_request(player_id, cell_id, timestamp)
        
        # Always ACK the request so client stops sending it
        self.send_ack(address, seq_num)
        
        if success:
            # If successful, this is a CRITICAL event
            self.send_reliable(address, GridClashBinaryProtocol.encode_acquire_response, 
                            cell_id, True, player_id)
            print(f"✅ Player {player_id} ({color}) SUCCESSFULLY claimed cell {cell_id}")
            self.check_game_end()
        else:
            # Send failure response
            if isinstance(result, str) and result.startswith('player_'):
                # Cell already owned by another player
                other_color = player_colors.get(result, 'UNKNOWN')
                print(f"❌ Player {player_id} ({color}) FAILED - cell {cell_id} already owned by {result} ({other_color})")
                response_msg = GridClashBinaryProtocol.encode_acquire_response(cell_id, False, result)
            else:
                print(f"❌ Player {player_id} ({color}) FAILED - {result}")
                response_msg = GridClashBinaryProtocol.encode_acquire_response(cell_id, False, None)
            
            self.send_to_client(address, response_msg)

    def handle_player_move(self, address, payload):
        """Handle movement. No ACK needed (fire-and-forget for speed)."""
        if address not in self.clients: return
        player_id = payload.get('player_id')
        position = payload.get('position')
        
        if player_id not in self.clients[address]['controlled_players']: return
        self.game_state.move_player(player_id, position)

    def handle_ack(self, address, payload):
        """Remove item from retry queue if ACK received"""
        acked_seq = payload.get('acked_seq')
        if acked_seq in self.retry_queue:
            del self.retry_queue[acked_seq]

    def check_game_end(self):
        if self.game_state.game_over:
            self.broadcast_game_over()

    def broadcast_loop(self):
        """Sends Game State Snapshots at fixed Hz"""
        snapshot_interval = 1.0 / self.update_rate
        
        while self.running:
            start_time = time.time()
            
            if self.game_state.game_started and not self.game_state.game_over:
                with self.lock:
                    self.broadcast_game_state()
            elif self.game_state.game_over:
                self.broadcast_game_over()
                time.sleep(5)
                with self.lock:
                    if len(self.clients) > 0:
                        self.game_state.reset_game()
                        print("UPDATE Game reset for new round!")
            
            # --- METRICS LOGGING (Phase 2 Requirement) ---
            try:
                # Log Player 1's position for "Perceived Position Error" calculation
                if 'player_1' in self.game_state.players:
                    p1_pos = self.game_state.players['player_1']['position']
                    self.csv_logger.log([
                        time.time(), 
                        psutil.cpu_percent(), 
                        self.metrics['bytes_sent'],
                        p1_pos[0], p1_pos[1]
                    ])
                else:
                    # Log zeros if player 1 hasn't joined yet to keep CSV format valid
                    self.csv_logger.log([
                        time.time(), 
                        psutil.cpu_percent(), 
                        self.metrics['bytes_sent'],
                        0, 0
                    ])
            except Exception as e:
                # Don't crash thread on logging error
                pass 
            
            elapsed = time.time() - start_time
            sleep_time = max(0, snapshot_interval - elapsed)
            time.sleep(sleep_time)

    def broadcast_game_state(self):
        self.snapshot_id += 1
        self.sequence_num += 1
        
        # Get Delta State (only changes since last broadcast)
        game_state_data = self.game_state.get_game_data(reset_dirty=True)
        
        # Encode
        snapshot_data = GridClashBinaryProtocol.encode_game_state(
            self.snapshot_id, self.sequence_num, game_state_data, full_grid=False)
        
        # Send to all
        for client_addr in list(self.clients.keys()):
            try:
                self.server_socket.sendto(snapshot_data, client_addr)
                self.metrics['packets_sent'] += 1
                self.metrics['bytes_sent'] += len(snapshot_data)
            except: pass

    def broadcast_game_over(self):
        scoreboard = self.game_state.get_scoreboard()
        game_over_msg = GridClashBinaryProtocol.encode_game_over(
            self.game_state.winner_id, scoreboard)
        for client_addr in list(self.clients.keys()):
            try: self.server_socket.sendto(game_over_msg, client_addr)
            except: pass

    def send_reliable(self, address, message_func, *args):
        """Send a message and add to retry queue for reliability"""
        self.sequence_num += 1
        seq = self.sequence_num
        # Create message with explicit seq_num
        message = message_func(*args, seq_num=seq)
        
        with self.lock:
            self.retry_queue[seq] = {
                'addr': address,
                'data': message,
                'time': time.time(),
                'retries': 0
            }
        
        try:
            self.server_socket.sendto(message, address)
            self.metrics['packets_sent'] += 1
            self.metrics['bytes_sent'] += len(message)
        except: pass

    def send_to_client(self, address, message):
        """Send "Fire and Forget" message"""
        try:
            self.server_socket.sendto(message, address)
            self.metrics['packets_sent'] += 1
            self.metrics['bytes_sent'] += len(message)
        except: pass

    def send_ack(self, address, seq_num):
        ack_msg = GridClashBinaryProtocol.encode_ack(seq_num)
        self.send_to_client(address, ack_msg)

    def cleanup_loop(self):
        """Remove inactive clients (30s timeout)"""
        while self.running:
            current_time = time.time()
            stale = [addr for addr, last in self.client_last_seen.items() if current_time - last > 30]
            for addr in stale: self.disconnect_client(addr)
            time.sleep(1)

    def reliability_loop(self):
        """Retransmit un-ACKed messages (Phase 2 Requirement)"""
        while self.running:
            current_time = time.time()
            with self.lock:
                to_delete = []
                for seq, item in self.retry_queue.items():
                    # Retry every 200ms, up to 10 times
                    if current_time - item['time'] > 0.2: 
                        if item['retries'] < 10: 
                            try:
                                self.server_socket.sendto(item['data'], item['addr'])
                                item['time'] = current_time
                                item['retries'] += 1
                                # print(f"DEBUG: Retrying seq {seq} to {item['addr']}")
                            except: pass
                        else:
                            to_delete.append(seq)
                
                for seq in to_delete:
                    del self.retry_queue[seq]
            time.sleep(0.05)    

    def metrics_loop(self):
        while self.running:
            time.sleep(10)
            uptime = time.time() - self.metrics['start_time']
            print(f"\n>> SERVER METRICS [Uptime: {uptime:.1f}s]")
            print(f"   Clients: {self.metrics['client_count']}")
            print(f"   Packets Sent: {self.metrics['packets_sent']}")
            print(f"   Data Sent: {self.metrics['bytes_sent'] / 1024:.1f} KB")

    def disconnect_client(self, address):
        with self.lock:
            if address in self.clients:
                print(f"--- Client {self.clients[address]['id']} disconnected")
                del self.clients[address]
            if address in self.client_last_seen: del self.client_last_seen[address]
            self.metrics['client_count'] = len(self.clients)

    def shutdown_server(self):
        print("STOP Shutting down UDP server...")
        self.running = False
        if self.csv_logger:
            self.csv_logger.close()
        self.server_socket.close()
        print("[OK] UDP Server shutdown complete")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--loss", type=float, default=0.0, help="Packet loss rate (0.0 - 1.0)")
    parser.add_argument("--delay", type=int, default=0, help="Delay in milliseconds")
    parser.add_argument("--jitter", type=int, default=0, help="Jitter in milliseconds")
    args = parser.parse_args()

    server = GridClashUDPServer(loss_rate=args.loss, delay_ms=args.delay, jitter_ms=args.jitter)
    server.start_server()