import struct
import time
import json

class GridClashBinaryProtocol:
    """Binary protocol for Grid Clash game state synchronization"""

    _start_time = time.perf_counter()
    
    # Protocol constants
    PROTOCOL_ID = b'GRID'  # 4-byte ASCII identifier
    VERSION = 1
    
    # Message types (1 byte each)
    MSG_WELCOME = 0x01
    MSG_GAME_STATE = 0x02
    MSG_ACQUIRE_REQUEST = 0x03
    MSG_ACQUIRE_RESPONSE = 0x04
    MSG_GAME_OVER = 0x05
    MSG_PLAYER_MOVE = 0x06
    MSG_ACK = 0x07
    MSG_NACK = 0x08
    MSG_HEARTBEAT = 0x09
    MSG_CONNECT_REQUEST = 0x0A  # Simple connection request
    
    # Header format: < little-endian, 4s=4byte string, B=1byte, I=4byte, Q=8byte, H=2byte
    HEADER_FORMAT = '<4s B B I I Q H I'
    HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
    
    # Class variables for redundancy
    last_game_state = None
    last_snapshot_id = 0
    MAX_PAYLOAD_SIZE = 1200
    
    @staticmethod
    def create_header(msg_type, snapshot_id, seq_num, payload_len):
        """Create binary header"""
        elapsed_ms = int((time.perf_counter() - GridClashBinaryProtocol._start_time) * 1000)
        

        checksum = 0
        
        header = struct.pack(
            GridClashBinaryProtocol.HEADER_FORMAT,
            GridClashBinaryProtocol.PROTOCOL_ID,
            GridClashBinaryProtocol.VERSION,
            msg_type,
            snapshot_id,
            seq_num,
            elapsed_ms,
            payload_len,
            checksum
        )
            
        return header
    
    @staticmethod
    def parse_header(data):
        """Parse binary header from received data"""
        if len(data) < GridClashBinaryProtocol.HEADER_SIZE:
            return None
            
        try:
            header_data = data[:GridClashBinaryProtocol.HEADER_SIZE]
            fields = struct.unpack(GridClashBinaryProtocol.HEADER_FORMAT, header_data)
            
            if fields[0] != GridClashBinaryProtocol.PROTOCOL_ID:
                return None
                
            return {
                'protocol_id': fields[0],
                'version': fields[1],
                'msg_type': fields[2],
                'snapshot_id': fields[3],
                'seq_num': fields[4],
                'timestamp': fields[5],
                'payload_len': fields[6]
            }
        except struct.error:
            return None
    
    @staticmethod
    def encode_connect_request():
        """Encode simple connection request (small message)"""
        payload = json.dumps({'type': 'connect'}).encode('utf-8')
        
        header = GridClashBinaryProtocol.create_header(
            GridClashBinaryProtocol.MSG_CONNECT_REQUEST,
            snapshot_id=0,
            seq_num=0,
            payload_len=len(payload)
        )
        
        return header + payload
    
    @staticmethod
    def encode_welcome(player_id, game_state):
        """Encode welcome message with FULL game state for new clients"""
        # IMPORTANT: Send the FULL grid for new clients
        full_grid = game_state.get('grid', {})
        # Ensure we include all grid cells
        optimized_grid = {}
        for cid, data in full_grid.items():
            if isinstance(data, dict) and 'owner_id' in data:
                optimized_grid[cid] = {'owner_id': data['owner_id']}
            else:
                # Handle different data formats
                optimized_grid[cid] = {'owner_id': data}
        
        # Ensure we have player positions
        player_positions = game_state.get('player_positions', {})
        if not player_positions and 'players' in game_state:
            # Extract positions from players dict if not directly available
            player_positions = {}
            for pid, pdata in game_state['players'].items():
                if 'position' in pdata:
                    player_positions[pid] = pdata['position']

        compressed_state = {
            'player_id': player_id,
            'players': {
                pid: {
                    'score': data.get('score', 0),
                    'position': data.get('position', [0, 0])
                } for pid, data in game_state.get('players', {}).items()
            },
            'player_positions': player_positions,
            'game_started': game_state.get('game_started', False),
            'game_over': game_state.get('game_over', False),
            'grid_size': game_state.get('grid_size', 20),
            'grid': optimized_grid  # Send FULL grid for new clients
        }
        
        payload = json.dumps(compressed_state).encode('utf-8')
        
        # If payload is too big, we need to split it or compress
        if len(payload) > GridClashBinaryProtocol.MAX_PAYLOAD_SIZE:
            print(f"[WARN] Welcome payload {len(payload)} bytes, truncating for {player_id}")
            # Send at least some grid data
            # Take first 100 cells to stay within limit
            limited_grid = {}
            count = 0
            for cid, data in optimized_grid.items():
                if count < 100:
                    limited_grid[cid] = data
                    count += 1
            
            compressed_state['grid'] = limited_grid
            payload = json.dumps(compressed_state).encode('utf-8')
            print(f"[INFO] Truncated to {len(limited_grid)} cells, {len(payload)} bytes")
        
        header = GridClashBinaryProtocol.create_header(
            GridClashBinaryProtocol.MSG_WELCOME,
            snapshot_id=0,
            seq_num=0,
            payload_len=len(payload)
        )
        
        return header + payload
    
    @staticmethod
    def encode_game_state(snapshot_id, seq_num, game_state, full_grid=False):
        """Encode game state snapshot with redundancy for loss tolerance"""
        
        # Include LAST snapshot data for redundancy (helps with packet loss)
        redundancy = {}
        if GridClashBinaryProtocol.last_game_state is not None:
            last_state = GridClashBinaryProtocol.last_game_state
            # Include critical data from last state (player positions only)
            # This adds minimal overhead but helps clients when packets are lost
            redundancy = {
                'prev_player_positions': last_state.get('player_positions', {}),
                'prev_snapshot_id': GridClashBinaryProtocol.last_snapshot_id
            }
        
        # Store current state for next update
        GridClashBinaryProtocol.last_game_state = game_state.copy()
        GridClashBinaryProtocol.last_snapshot_id = snapshot_id
        
        # IMPORTANT: Send grid updates if available, otherwise send full grid
        grid_data = {}
        if not full_grid and 'grid_updates' in game_state and game_state['grid_updates']:
            grid_data = game_state['grid_updates']
        else:
            grid_data = game_state.get('grid', {})
        
        # Ensure player positions are included
        player_positions = game_state.get('player_positions', {})
        if not player_positions and 'players' in game_state:
            player_positions = {}
            for pid, pdata in game_state['players'].items():
                if 'position' in pdata:
                    player_positions[pid] = pdata['position']

        compressed_state = {
            'players': {
                pid: {
                    'score': data.get('score', 0),
                    'position': data.get('position', [0, 0])
                } for pid, data in game_state.get('players', {}).items()
            },
            'player_positions': player_positions,
            'game_over': game_state.get('game_over', False),
            'winner_id': game_state.get('winner_id', None),
            'grid': grid_data,  # This contains DELTA updates or full grid
            'redundancy': redundancy,  # Add redundancy data
            'snapshot_id': snapshot_id  # Explicitly include snapshot ID in payload
        }
        
        payload = json.dumps(compressed_state).encode('utf-8')
        
        # Check payload size
        if len(payload) > GridClashBinaryProtocol.MAX_PAYLOAD_SIZE:
            print(f"[WARN] Game state payload {len(payload)} bytes, removing redundancy")
            # Remove redundancy if payload is too large
            compressed_state.pop('redundancy', None)
            payload = json.dumps(compressed_state).encode('utf-8')
            
            if len(payload) > GridClashBinaryProtocol.MAX_PAYLOAD_SIZE:
                print(f"[WARN] Still too large {len(payload)} bytes, truncating grid")
                # Keep only player positions and essential data
                minimal_state = {
                    'players': compressed_state['players'],
                    'player_positions': compressed_state['player_positions'],
                    'game_over': compressed_state['game_over'],
                    'snapshot_id': snapshot_id
                }
                payload = json.dumps(minimal_state).encode('utf-8')
        
        header = GridClashBinaryProtocol.create_header(
            GridClashBinaryProtocol.MSG_GAME_STATE,
            snapshot_id=snapshot_id,
            seq_num=seq_num,
            payload_len=len(payload)
        )
        
        return header + payload
    
    @staticmethod
    def encode_acquire_request(player_id, cell_id, timestamp, seq_num):
        payload = json.dumps({
            'player_id': player_id,
            'cell_id': cell_id,
            'timestamp': timestamp
        }).encode('utf-8')
        
        header = GridClashBinaryProtocol.create_header(
            GridClashBinaryProtocol.MSG_ACQUIRE_REQUEST,
            snapshot_id=0,
            seq_num=seq_num,
            payload_len=len(payload)
        )
        
        return header + payload
    
    @staticmethod
    def encode_acquire_response(cell_id, success, owner_id=None, seq_num=0):
        payload = json.dumps({
            'cell_id': cell_id,
            'success': success,
            'owner_id': owner_id
        }).encode('utf-8')
        
        header = GridClashBinaryProtocol.create_header(
            GridClashBinaryProtocol.MSG_ACQUIRE_RESPONSE,
            snapshot_id=0,
            seq_num=seq_num, # Now uses the actual sequence number
            payload_len=len(payload)
        )
        
        return header + payload

    @staticmethod
    def encode_player_move(player_id, position, seq_num):
        payload = json.dumps({
            'player_id': player_id,
            'position': position
        }).encode('utf-8')
        
        header = GridClashBinaryProtocol.create_header(
            GridClashBinaryProtocol.MSG_PLAYER_MOVE,
            snapshot_id=0,
            seq_num=seq_num,
            payload_len=len(payload)
        )
        
        return header + payload
    
    @staticmethod
    def encode_game_over(winner_id, scoreboard):
        payload = json.dumps({
            'winner_id': winner_id,
            'scoreboard': scoreboard
        }).encode('utf-8')
        
        header = GridClashBinaryProtocol.create_header(
            GridClashBinaryProtocol.MSG_GAME_OVER,
            snapshot_id=0,
            seq_num=0,
            payload_len=len(payload)
        )
        
        return header + payload
    
    @staticmethod
    def encode_ack(acked_seq_num):
        payload = json.dumps({
            'acked_seq': acked_seq_num
        }).encode('utf-8')
        
        header = GridClashBinaryProtocol.create_header(
            GridClashBinaryProtocol.MSG_ACK,
            snapshot_id=0,
            seq_num=0,
            payload_len=len(payload)
        )
        
        return header + payload
    
    @staticmethod
    def encode_heartbeat():
        header = GridClashBinaryProtocol.create_header(
            GridClashBinaryProtocol.MSG_HEARTBEAT,
            snapshot_id=0,
            seq_num=0,
            payload_len=0
        )
        return header
    
    @staticmethod
    def decode_message(data):
        header = GridClashBinaryProtocol.parse_header(data)
        if not header:
            return None
            
        payload_start = GridClashBinaryProtocol.HEADER_SIZE
        payload_end = payload_start + header['payload_len']
        
        if len(data) < payload_end:
            return None 
            
        payload_data = {}
        if header['payload_len'] > 0:
            try:
                payload_bytes = data[payload_start:payload_end]
                payload_data = json.loads(payload_bytes.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return None
                
        return {
            'header': header,
            'payload': payload_data
        }
    
    @staticmethod
    def get_message_type_name(msg_type):
        type_names = {
            GridClashBinaryProtocol.MSG_WELCOME: "WELCOME",
            GridClashBinaryProtocol.MSG_GAME_STATE: "GAME_STATE",
            GridClashBinaryProtocol.MSG_ACQUIRE_REQUEST: "ACQUIRE_REQUEST",
            GridClashBinaryProtocol.MSG_ACQUIRE_RESPONSE: "ACQUIRE_RESPONSE",
            GridClashBinaryProtocol.MSG_GAME_OVER: "GAME_OVER",
            GridClashBinaryProtocol.MSG_PLAYER_MOVE: "PLAYER_MOVE",
            GridClashBinaryProtocol.MSG_ACK: "ACK",
            GridClashBinaryProtocol.MSG_NACK: "NACK",
            GridClashBinaryProtocol.MSG_HEARTBEAT: "HEARTBEAT",
            GridClashBinaryProtocol.MSG_CONNECT_REQUEST: "CONNECT_REQUEST"
        }
        return type_names.get(msg_type, f"UNKNOWN({msg_type})")
    
    @staticmethod
    def use_redundancy_if_needed(payload, last_received_payload):
        """
        Client-side method to use redundancy data when current packet
        seems corrupted or incomplete
        """
        if 'redundancy' in payload and last_received_payload:
            redundancy = payload['redundancy']
            
            # Check if we're missing player positions in current payload
            if 'player_positions' not in payload or not payload['player_positions']:
                if 'prev_player_positions' in redundancy:
                    print("[CLIENT] Using redundant player positions")
                    payload['player_positions'] = redundancy['prev_player_positions']
            
            # Check if snapshot ID has a gap (missing packets)
            current_id = payload.get('snapshot_id', 0)
            prev_id = redundancy.get('prev_snapshot_id', 0)
            
            if current_id - prev_id > 1:
                print(f"[CLIENT] Detected missing packets: {prev_id+1} to {current_id-1}")
                # Could trigger NACK request here if implemented
        
        return payload