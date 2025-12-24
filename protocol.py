import struct
import time
import json
import zlib

class GridClashBinaryProtocol:
    """Complete Binary protocol for Grid Clash game state synchronization"""
    
    # Protocol constants
    PROTOCOL_ID = b'GRID'
    VERSION = 1
    
    # Message types
    MSG_WELCOME = 0x01
    MSG_GAME_STATE = 0x02
    MSG_ACQUIRE_REQUEST = 0x03
    MSG_ACQUIRE_RESPONSE = 0x04
    MSG_GAME_OVER = 0x05
    MSG_PLAYER_MOVE = 0x06
    MSG_ACK = 0x07
    MSG_NACK = 0x08
    MSG_HEARTBEAT = 0x09
    MSG_CONNECT_REQUEST = 0x0A

    # Header format: < (little-endian), 4s (ID), B (Ver), B (Type), I (SnapID), I (SeqNum), Q (Timestamp), H (PayloadLen)
    HEADER_FORMAT = '<4s B B I I Q H'
    HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
    MAX_PAYLOAD_SIZE = 1200 # Recommended for UDP to avoid fragmentation

    @staticmethod
    def create_header(msg_type, snapshot_id, seq_num, payload_len):
        """Create binary header with current millisecond timestamp"""
        ts_ms = int(time.time() * 1000) 
        return struct.pack(
            GridClashBinaryProtocol.HEADER_FORMAT, 
            GridClashBinaryProtocol.PROTOCOL_ID, 
            GridClashBinaryProtocol.VERSION,
            msg_type, 
            snapshot_id, 
            seq_num, 
            ts_ms, 
            payload_len)

    @staticmethod
    def _encode_compressed(msg_type, data, snapshot_id=0, seq_num=0):
        """Helper to JSON-ify, compress, and wrap with a header"""
        payload = json.dumps(data, separators=(',', ':')).encode('utf-8')
        compressed = zlib.compress(payload)
        header = GridClashBinaryProtocol.create_header(msg_type, snapshot_id, seq_num, len(compressed))
        return header + compressed

    @staticmethod
    def encode_connect_request():
        return GridClashBinaryProtocol._encode_compressed(GridClashBinaryProtocol.MSG_CONNECT_REQUEST, {})

    @staticmethod
    def encode_heartbeat():
        return GridClashBinaryProtocol._encode_compressed(GridClashBinaryProtocol.MSG_HEARTBEAT, {})

    @staticmethod
    def encode_welcome(player_id, game_state):
        """Encode welcome message with optimized grid data"""
        full_grid = game_state.get('grid', {})
        # Remove timestamps from grid to save massive space
        optimized_grid = {cid: {'owner_id': data['owner_id']} for cid, data in full_grid.items()}

        data = {
            'player_id': player_id,
            'players': game_state['players'],
            'grid': optimized_grid,
            'player_positions': game_state.get('player_positions', {}),
            'game_started': game_state['game_started'],
            'grid_size': game_state.get('grid_size', 20)
        }
        return GridClashBinaryProtocol._encode_compressed(GridClashBinaryProtocol.MSG_WELCOME, data)
    
    @staticmethod
    def encode_game_state(snapshot_id, seq_num, game_state):
        """Encode game state snapshot using delta (dirty) updates"""
        data = {
            'players': game_state['players'], 
            'player_positions': game_state['player_positions'],
            'grid_updates': game_state.get('grid_updates', {}), 
            'game_over': game_state['game_over'],
            'winner_id': game_state['winner_id']
        }
        return GridClashBinaryProtocol._encode_compressed(GridClashBinaryProtocol.MSG_GAME_STATE, data, snapshot_id, seq_num)
    
    @staticmethod
    def encode_acquire_request(player_id, cell_id, timestamp, seq_num):
        data = {'player_id': player_id, 'cell_id': cell_id, 'timestamp': timestamp}
        return GridClashBinaryProtocol._encode_compressed(GridClashBinaryProtocol.MSG_ACQUIRE_REQUEST, data, 0, seq_num)
    
    @staticmethod
    def encode_acquire_response(cell_id, success, owner_id=None, seq_num=0):
        data = {'cell_id': cell_id, 'success': success, 'owner_id': owner_id}
        return GridClashBinaryProtocol._encode_compressed(GridClashBinaryProtocol.MSG_ACQUIRE_RESPONSE, data, 0, seq_num)

    @staticmethod
    def encode_player_move(player_id, position, seq_num):
        data = {'player_id': player_id, 'position': position}
        return GridClashBinaryProtocol._encode_compressed(GridClashBinaryProtocol.MSG_PLAYER_MOVE, data, 0, seq_num)

    @staticmethod
    def encode_game_over(winner_id, scoreboard):
        data = {'winner_id': winner_id, 'scoreboard': scoreboard}
        return GridClashBinaryProtocol._encode_compressed(GridClashBinaryProtocol.MSG_GAME_OVER, data)
    
    @staticmethod
    def encode_ack(acked_seq_num):
        return GridClashBinaryProtocol._encode_compressed(GridClashBinaryProtocol.MSG_ACK, {'acked_seq': acked_seq_num})

    @staticmethod
    def decode_message(data):
        """Parse header, decompress payload, and return structured dict"""
        if len(data) < GridClashBinaryProtocol.HEADER_SIZE:
            return None
            
        try:
            h_data = data[:GridClashBinaryProtocol.HEADER_SIZE]
            fields = struct.unpack(GridClashBinaryProtocol.HEADER_FORMAT, h_data)
            
            # Validation: Check Protocol ID
            if fields[0] != GridClashBinaryProtocol.PROTOCOL_ID:
                return None

            payload_len = fields[6]
            raw_payload = data[GridClashBinaryProtocol.HEADER_SIZE : GridClashBinaryProtocol.HEADER_SIZE + payload_len]
            
            payload = {}
            if payload_len > 0:
                decompressed = zlib.decompress(raw_payload)
                payload = json.loads(decompressed.decode('utf-8'))

            return {
                'header': {
                    'protocol_id': fields[0],
                    'version': fields[1],
                    'msg_type': fields[2], 
                    'snapshot_id': fields[3], 
                    'seq_num': fields[4], 
                    'timestamp': fields[5],
                    'payload_len': payload_len
                }, 
                'payload': payload
            }
        except Exception: 
            return None

    @staticmethod
    def get_message_type_name(msg_type):
        """Helper for logging"""
        type_names = {
            0x01: "WELCOME", 0x02: "GAME_STATE", 0x03: "ACQUIRE_REQUEST",
            0x04: "ACQUIRE_RESPONSE", 0x05: "GAME_OVER", 0x06: "PLAYER_MOVE",
            0x07: "ACK", 0x08: "NACK", 0x09: "HEARTBEAT", 0x0A: "CONNECT_REQUEST"
        }
        return type_names.get(msg_type, f"UNKNOWN({msg_type})")