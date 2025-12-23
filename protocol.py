import struct
import time
import json
import zlib

class GridClashBinaryProtocol:
    PROTOCOL_ID = b'GRID'
    VERSION = 1
    
    MSG_WELCOME = 0x01
    MSG_GAME_STATE = 0x02
    MSG_ACQUIRE_REQUEST = 0x03
    MSG_ACQUIRE_RESPONSE = 0x04
    MSG_GAME_OVER = 0x05
    MSG_PLAYER_MOVE = 0x06
    MSG_ACK = 0x07
    MSG_HEARTBEAT = 0x09
    MSG_CONNECT_REQUEST = 0x0A

    # PDF Page 4 Requirement: 
    # 4s (ID), B (Ver), B (Type), I (SnapID), I (SeqNum), Q (Timestamp 8b), H (PayloadLen)
    HEADER_FORMAT = '<4s B B I I Q H' 
    HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
    
    @staticmethod
    def create_header(msg_type, snapshot_id, seq_num, payload_len):
        # Using milliseconds since epoch as an 8-byte integer (Q)
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
        data = {
            'player_id': player_id,
            'players': game_state['players'],
            'grid': game_state['grid'],
            'player_positions': game_state.get('player_positions', {}),
            'game_started': game_state['game_started']
        }
        return GridClashBinaryProtocol._encode_compressed(GridClashBinaryProtocol.MSG_WELCOME, data)
    
    @staticmethod
    def encode_game_state(snapshot_id, seq_num, game_state):
        # FIXED: Added 'players' so the scores update on the UI
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
    def encode_ack(acked_seq_num):
        return GridClashBinaryProtocol._encode_compressed(GridClashBinaryProtocol.MSG_ACK, {'acked_seq': acked_seq_num})

    @staticmethod
    def decode_message(data):
        if len(data) < GridClashBinaryProtocol.HEADER_SIZE: return None
        h_data = data[:GridClashBinaryProtocol.HEADER_SIZE]
        fields = struct.unpack(GridClashBinaryProtocol.HEADER_FORMAT, h_data)
        
        payload_len = fields[6]
        raw_payload = data[GridClashBinaryProtocol.HEADER_SIZE : GridClashBinaryProtocol.HEADER_SIZE + payload_len]
        try:
            decompressed = zlib.decompress(raw_payload)
            payload = json.loads(decompressed.decode('utf-8'))
            return {
                'header': {
                    'msg_type': fields[2], 
                    'snapshot_id': fields[3], 
                    'seq_num': fields[4], 
                    'timestamp': fields[5]
                }, 
                'payload': payload
            }
        except: 
            return None