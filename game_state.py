from collections import defaultdict

class GameState:
    def __init__(self, grid_size=20):
        self.grid_size = grid_size
        self.total_cells = grid_size * grid_size
        
        # Grid data structure - using string cell IDs "row_col"
        self.grid = {}  # {cell_id: {'owner_id': str, 'timestamp': float}}
        
        # Delta Encoding: Track cells changed since last broadcast
        self.dirty_cells = {} 
        
        # Player data - 4 Players at corners
        self.players = {
            'player_1': {'score': 0, 'position': [0, 0], 'color': (255, 50, 50)},
            'player_2': {'score': 0, 'position': [grid_size-1, grid_size-1], 'color': (50, 50, 255)},
            'player_3': {'score': 0, 'position': [0, grid_size-1], 'color': (50, 255, 50)},
            'player_4': {'score': 0, 'position': [grid_size-1, 0], 'color': (255, 255, 50)}
        }

        # Initialize quick lookup for positions
        self.player_positions = {pid: p['position'] for pid, p in self.players.items()}

        # Game state - CRITICAL FIX: Game starts immediately
        self.game_started = True  # Changed from False to True
        self.game_over = False
        self.winner_id = None

    def process_acquire_request(self, player_id, cell_id, timestamp):
        """Process cell acquisition request"""
        if self.game_over:
            return False, "Game over"
            
        if player_id not in self.players:
            return False, "Invalid player"
            
        # Validate cell_id (should be in "row_col" format)
        try:
            # Try to parse the cell_id
            if isinstance(cell_id, str) and '_' in cell_id:
                row, col = map(int, cell_id.split('_'))
                if not (0 <= row < self.grid_size and 0 <= col < self.grid_size):
                    return False, "Invalid cell"
            else:
                return False, "Invalid cell format"
        except (ValueError, AttributeError):
            return False, "Invalid cell format"
            
        # Check if cell is already owned
        if cell_id in self.grid:
            current_owner = self.grid[cell_id]['owner_id']
            if current_owner == player_id:
                return False, "Already owned by you"
            else:
                return False, current_owner  # Return the current owner's ID
        
        # Claim the cell
        cell_data = {
            'owner_id': player_id,
            'timestamp': timestamp
        }
        self.grid[cell_id] = cell_data
        
        # Mark as dirty for next broadcast (Delta Encoding)
        self.dirty_cells[cell_id] = cell_data
        
        # Update player score
        self.players[player_id]['score'] += 1
        
        print(f"✅ {player_id} claimed cell {cell_id}. Score: {self.players[player_id]['score']}")
        
        # Check if game should end
        self.check_game_end()
        
        return True, player_id

    def move_player(self, player_id, position):
        """Move player to new position"""
        if player_id not in self.players:
            return False
            
        # Validate position within grid bounds
        if not (0 <= position[0] < self.grid_size and 0 <= position[1] < self.grid_size):
            return False
            
        self.players[player_id]['position'] = position.copy()
        self.player_positions[player_id] = position.copy()
        return True

    def check_game_end(self):
        """Check if all cells are claimed and end game"""
        claimed_cells = len(self.grid)
        
        if claimed_cells >= self.total_cells:
            self.game_over = True
            
            # Determine winner among all active players
            max_score = -1
            winners = []
            
            for pid, data in self.players.items():
                if data['score'] > max_score:
                    max_score = data['score']
                    winners = [pid]
                elif data['score'] == max_score:
                    winners.append(pid)
            
            if len(winners) > 1:
                self.winner_id = 'tie'
            else:
                self.winner_id = winners[0] if winners else None
                
            print("🎉 GAME OVER - All cells claimed!")
            print(f"🏆 Winner: {self.winner_id}")
            print(f"📊 Final scores: {self.get_scoreboard()}")

    def get_scoreboard(self):
        """Get current scoreboard"""
        return {
            player_id: player_data['score'] 
            for player_id, player_data in self.players.items()
        }

    def get_game_data(self, reset_dirty=True):
        """
        Get complete game state for broadcasting.
        reset_dirty: If True, clears the dirty_cells list after reading.
        """
        # IMPORTANT: Ensure we include all necessary data
        data = {
            'grid': self.grid.copy(),  # Send full grid copy
            'grid_updates': self.dirty_cells.copy(), # Send only changed cells for delta
            'players': {pid: {
                'score': p['score'],
                'position': p['position'].copy()
            } for pid, p in self.players.items()},
            'player_positions': self.player_positions.copy(),
            'game_started': self.game_started,
            'game_over': self.game_over,
            'winner_id': self.winner_id,
            'grid_size': self.grid_size,
            'total_cells': self.total_cells
        }
        
        if reset_dirty:
            self.dirty_cells.clear()
            
        return data

    def reset_game(self):
        """Reset game for new round"""
        self.grid = {}
        self.dirty_cells = {}
        self.game_over = False
        self.winner_id = None
        self.game_started = True
        
        # Reset scores
        for player_id in self.players:
            self.players[player_id]['score'] = 0
            
        # Reset positions to corners (Updated for 4 players)
        self.player_positions = {
            'player_1': [0, 0],
            'player_2': [self.grid_size-1, self.grid_size-1],
            'player_3': [0, self.grid_size-1],
            'player_4': [self.grid_size-1, 0]
        }
        
        # Sync back to players dict
        for pid, pos in self.player_positions.items():
            if pid in self.players:
                self.players[pid]['position'] = pos.copy()