import socket
import threading
import time
import psutil
from collections import defaultdict
from protocol import GridClashBinaryProtocol
from game_state import GameState
from logger import GameLogger
import argparse

class GridClashUDPServer:
    def __init__(self, host='0.0.0.0', port=5555):
        """Initialize UDP server WITHOUT simulation logic"""
        self.host = host
        self.port = port
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # Buffer tuning
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024 * 1024)
        
        self.clients = {}  
        self.game_state = GameState(grid_size=20)
        self.running = True
        
        # Use RLock to allow re-entry from same thread
        self.lock = threading.RLock()
        
        self.snapshot_id = 0
        self.sequence_num = 0
        self.update_rate = 20  # 20 Hz
        self.game_over_sent = False
        
        # Reliability Structures
        self.retry_queue = {} 
        self.client_last_seen = defaultdict(float)
        
        # Time reference for monotonic timestamps
        self.start_time = time.perf_counter()
        
        # Metrics
        self.metrics = {
            'packets_sent': 0,
            'packets_received': 0,
            'bytes_sent': 0,
            'bytes_received': 0,
            'client_count': 0,
            'start_time': time.time()
        }
        
        self.csv_logger = None
        self.last_log_time = 0
        self.log_interval = 0.05  # Log every 50ms (20Hz)

    def start_server(self):
        """Main server loop"""
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.settimeout(0.05)  # Short timeout for responsiveness
            print(f">>> Grid Clash UDP Server started on {self.host}:{self.port}")
            print(f">>> Update rate: {self.update_rate} Hz")
            
            # CRITICAL: Ensure game is started
            self.game_state.game_started = True
            
            # Initialize CSV Logger
            self.csv_logger = GameLogger("server_metrics.csv", 
                ["timestamp", "cpu_percent", "bytes_sent", "player1_pos_x", "player1_pos_y",
                 "player2_pos_x", "player2_pos_y", "player3_pos_x", "player3_pos_y", 
                 "player4_pos_x", "player4_pos_y"])
            
            # Start background threads
            threading.Thread(target=self.fixed_broadcast_loop, daemon=True).start()
            threading.Thread(target=self.cleanup_loop, daemon=True).start()
            threading.Thread(target=self.metrics_loop, daemon=True).start()
            threading.Thread(target=self.reliability_loop, daemon=True).start()

            while self.running:
                try:
                    data, address = self.server_socket.recvfrom(65536)
                    self.handle_client_message(data, address)
                    
                except socket.timeout:
                    continue
                except ConnectionResetError:
                    continue
                except OSError as e:
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
                self.handle_new_client(address)

    def handle_new_client(self, address):
        with self.lock:
            if address in self.clients:
                return

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
                
                # Get current game state
                current_state = self.game_state.get_game_data(reset_dirty=False)
                
                # Send welcome with monotonic timestamp
                welcome_msg = GridClashBinaryProtocol.encode_welcome(
                    assigned_id, current_state, self.start_time)
                self.send_to_client(address, welcome_msg)

    def handle_acquire_request(self, address, payload, seq_num):
        if address not in self.clients:
            return
            
        player_id = payload.get('player_id')
        cell_id = payload.get('cell_id')
        timestamp = payload.get('timestamp', time.time())
        
        if player_id not in self.clients[address]['controlled_players']:
            return
        
        success, result = self.game_state.process_acquire_request(player_id, cell_id, timestamp)
        
        # Always ACK
        self.send_ack(address, seq_num)
        
        if success:
            # Send reliably
            self.send_reliable(address, GridClashBinaryProtocol.encode_acquire_response, 
                              cell_id, True, player_id, self.start_time)
            self.check_game_end()
        else:
            # If result is a player ID (meaning cell is already owned), send that as owner_id
            if isinstance(result, str) and result.startswith('player_'):
                response_msg = GridClashBinaryProtocol.encode_acquire_response(
                    cell_id, False, result, self.start_time)
            else:
                response_msg = GridClashBinaryProtocol.encode_acquire_response(
                    cell_id, False, None, self.start_time)
            self.send_to_client(address, response_msg)

    def handle_player_move(self, address, payload):
        if address not in self.clients:
            return
            
        player_id = payload.get('player_id')
        position = payload.get('position')
        
        if player_id not in self.clients[address]['controlled_players']:
            return
            
        self.game_state.move_player(player_id, position)

    def handle_ack(self, address, payload):
        acked_seq = payload.get('acked_seq')
        if acked_seq in self.retry_queue:
            del self.retry_queue[acked_seq]

    def check_game_end(self):
        if self.game_state.game_over:
            self.broadcast_game_over()

    def fixed_broadcast_loop(self):
        """ALWAYS broadcast at fixed 20Hz rate, regardless of game state"""
        print("[BROADCAST] Starting fixed 20Hz broadcast loop")
        
        target_interval = 1.0 / self.update_rate  # 0.05s = 50ms
        
        while self.running:
            start_time = time.time()
            
            # ALWAYS send updates when clients are connected
            if len(self.clients) > 0:
                with self.lock:
                    self.snapshot_id += 1
                    self.sequence_num += 1
                    
                    game_state_data = self.game_state.get_game_data(reset_dirty=True)
                    
                    # Send game state with monotonic timestamp
                    snapshot_data = GridClashBinaryProtocol.encode_game_state(
                        self.snapshot_id, self.sequence_num, game_state_data, 
                        False, self.start_time)
                    
                    for client_addr in list(self.clients.keys()):
                        try:
                            self.server_socket.sendto(snapshot_data, client_addr)
                            self.metrics['packets_sent'] += 1
                            self.metrics['bytes_sent'] += len(snapshot_data)
                        except:
                            pass
            
            # Handle game over (send only once)
            if self.game_state.game_over and not self.game_over_sent:
                with self.lock:
                    self.broadcast_game_over()
                    self.game_over_sent = True
            
            # Log metrics REGULARLY (every broadcast cycle)
            current_time = time.time()
            if current_time - self.last_log_time >= self.log_interval:
                self.log_server_metrics()
                self.last_log_time = current_time
            
            # Maintain precise 20Hz timing
            elapsed = time.time() - start_time
            sleep_time = max(0.001, target_interval - elapsed)
            time.sleep(sleep_time)
    
    def log_server_metrics(self):
        """Log server metrics to CSV"""
        try:
            # Get ALL player positions (even if no clients connected)
            player_positions = []
            
            # Default positions for all 4 players
            default_positions = {
                'player_1': [0, 0],
                'player_2': [self.game_state.grid_size-1, self.game_state.grid_size-1],
                'player_3': [0, self.game_state.grid_size-1],
                'player_4': [self.game_state.grid_size-1, 0]
            }
            
            # Use actual positions if available, otherwise defaults
            for player_id in ['player_1', 'player_2', 'player_3', 'player_4']:
                if player_id in self.game_state.players:
                    pos = self.game_state.players[player_id]['position']
                    player_positions.extend(pos)  # Add x, y
                else:
                    pos = default_positions[player_id]
                    player_positions.extend(pos)
            
            # Create log entry
            log_entry = [
                time.time(),  # timestamp
                psutil.cpu_percent(),  # cpu_percent
                self.metrics['bytes_sent'],  # bytes_sent
            ]
            
            # Add all player positions
            log_entry.extend(player_positions)
            
            # Log to CSV
            self.csv_logger.log(log_entry)
            
        except Exception as e:
            print(f"[SERVER] Error logging metrics: {e}")

    def broadcast_game_over(self):
        """Broadcast game over message to all clients"""
        scoreboard = self.game_state.get_scoreboard()
        game_over_msg = GridClashBinaryProtocol.encode_game_over(
            self.game_state.winner_id, scoreboard, self.start_time)
        
        print(f"[BROADCAST] Sending GAME OVER to {len(self.clients)} clients")
        
        for client_addr in list(self.clients.keys()):
            try: 
                self.server_socket.sendto(game_over_msg, client_addr)
                self.metrics['packets_sent'] += 1
                self.metrics['bytes_sent'] += len(game_over_msg)
            except:
                pass

    def send_reliable(self, address, message_func, *args):
        self.sequence_num += 1
        seq = self.sequence_num
        message = message_func(*args, seq_num=seq)
        
        with self.lock:
            self.retry_queue[seq] = {
                'addr': address, 'data': message, 'time': time.time(), 'retries': 0
            }
        
        try:
            self.server_socket.sendto(message, address)
            self.metrics['packets_sent'] += 1
            self.metrics['bytes_sent'] += len(message)
        except:
            pass

    def send_to_client(self, address, message):
        try:
            self.server_socket.sendto(message, address)
            self.metrics['packets_sent'] += 1
            self.metrics['bytes_sent'] += len(message)
        except:
            pass

    def send_ack(self, address, seq_num):
        ack_msg = GridClashBinaryProtocol.encode_ack(seq_num, self.start_time)
        self.send_to_client(address, ack_msg)

    def cleanup_loop(self):
        while self.running:
            current_time = time.time()
            stale = [addr for addr, last in self.client_last_seen.items() 
                     if current_time - last > 30]
            for addr in stale:
                self.disconnect_client(addr)
            time.sleep(1)

    def reliability_loop(self):
        while self.running:
            current_time = time.time()
            with self.lock:
                to_delete = []
                for seq, item in self.retry_queue.items():
                    if current_time - item['time'] > 0.2: 
                        if item['retries'] < 10: 
                            try:
                                self.server_socket.sendto(item['data'], item['addr'])
                                item['time'] = current_time
                                item['retries'] += 1
                            except:
                                pass
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
            print(f"   Packets Received: {self.metrics['packets_received']}")
            print(f"   Bytes Sent: {self.metrics['bytes_sent']}")
            print(f"   Bytes Received: {self.metrics['bytes_received']}")

    def disconnect_client(self, address):
        with self.lock:
            if address in self.clients:
                del self.clients[address]
            if address in self.client_last_seen:
                del self.client_last_seen[address]
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
    args = parser.parse_args()

    server = GridClashUDPServer()
    server.start_server()