import asyncio
import websockets
import json
import random
import uuid
from datetime import datetime

class GameServer:
    def __init__(self):
        self.games = {}
        self.connections = {}

    async def handle_connection(self, websocket, path):
        try:
            # Extract game_id and player_name from path
            path_parts = path.split('/')
            if len(path_parts) < 4:
                await websocket.close()
                return
            
            game_id = path_parts[2]
            player_name = path_parts[3]
            
            print(f"Player {player_name} connecting to game {game_id}")
            
            # Initialize game if it doesn't exist
            if game_id not in self.games:
                self.games[game_id] = {
                    'players': {},
                    'state': 'lobby',
                    'host': player_name,
                    'current_question': None,
                    'scores': {},
                    'question_index': 0,
                    'questions': self.load_questions()
                }
            
            game = self.games[game_id]
            
            # Add player to game
            game['players'][player_name] = {
                'websocket': websocket,
                'ready': False
            }
            game['scores'][player_name] = 0
            
            self.connections[websocket] = (game_id, player_name)
            
            # Notify all players about new player
            await self.broadcast_game_state(game_id)
            
            # Main message loop
            async for message in websocket:
                await self.handle_message(websocket, message, game_id, player_name)
                
        except Exception as e:
            print(f"Connection error: {e}")
        finally:
            await self.handle_disconnect(websocket)

    def load_questions(self):
        """Load sample questions - in real app, load from JSON"""
        return [
            {
                "term": "awe",
                "meaning": "friendly greeting; hey/what's up",
                "distractors": ["goodbye", "please", "thank you"],
                "difficulty": "easy"
            },
            {
                "term": "braai",
                "meaning": "barbecue; cook meat over coals",
                "distractors": ["bake bread", "stir-fry veggies", "drink tea"],
                "difficulty": "easy"
            },
            {
                "term": "howzit",
                "meaning": "hello; how are you?",
                "distractors": ["goodbye", "please", "congrats"],
                "difficulty": "easy"
            }
        ]

    async def handle_message(self, websocket, message, game_id, player_name):
        try:
            data = json.loads(message)
            action = data.get('action')
            game = self.games.get(game_id)
            
            if not game:
                return
            
            if action == 'join':
                game['players'][player_name]['ready'] = True
                await self.broadcast_game_state(game_id)
                
            elif action == 'start_game':
                if player_name == game['host']:
                    await self.start_game(game_id)
                    
            elif action == 'submit_answer':
                await self.handle_answer(game_id, player_name, data.get('answer'))
                
            elif action == 'play_again':
                if player_name == game['host']:
                    await self.reset_game(game_id)
                    
        except Exception as e:
            print(f"Message handling error: {e}")

    async def handle_disconnect(self, websocket):
        if websocket in self.connections:
            game_id, player_name = self.connections[websocket]
            
            if game_id in self.games:
                game = self.games[game_id]
                if player_name in game['players']:
                    del game['players'][player_name]
                    del game['scores'][player_name]
                    
                    # Notify other players
                    await self.broadcast({
                        'type': 'player_left',
                        'player_name': player_name
                    }, game_id, exclude=[websocket])
                    
                    # Update game state
                    await self.broadcast_game_state(game_id)
            
            del self.connections[websocket]

    async def start_game(self, game_id):
        game = self.games[game_id]
        game['state'] = 'playing'
        game['question_index'] = 0
        
        # Reset scores
        for player in game['scores']:
            game['scores'][player] = 0
        
        await self.next_question(game_id)

    async def next_question(self, game_id):
        game = self.games[game_id]
        
        if game['question_index'] >= len(game['questions']):
            await self.end_game(game_id)
            return
        
        question = game['questions'][game['question_index']]
        game['current_question'] = question
        game['question_index'] += 1
        
        # Prepare choices
        choices = [question['meaning']] + question['distractors'][:3]
        random.shuffle(choices)
        
        # Send question to all players
        await self.broadcast({
            'type': 'new_question',
            'term': question['term'],
            'choices': choices,
            'time_limit': 20,
            'question_number': game['question_index']
        }, game_id)
        
        # Set timeout for question
        asyncio.create_task(self.question_timeout(game_id))

    async def question_timeout(self, game_id):
        await asyncio.sleep(20)
        game = self.games.get(game_id)
        if game and game['state'] == 'playing' and game['current_question']:
            await self.broadcast({
                'type': 'answer_result',
                'player': 'System',
                'correct': False,
                'correct_answer': game['current_question']['meaning']
            }, game_id)
            await asyncio.sleep(3)
            await self.next_question(game_id)

    async def handle_answer(self, game_id, player_name, answer):
        game = self.games[game_id]
        question = game['current_question']
        
        if not question:
            return
        
        is_correct = answer == question['meaning']
        
        if is_correct:
            game['scores'][player_name] += 10
        
        await self.broadcast({
            'type': 'answer_result',
            'player': player_name,
            'correct': is_correct,
            'correct_answer': question['meaning']
        }, game_id)
        
        # Move to next question after a short delay
        await asyncio.sleep(3)
        await self.next_question(game_id)

    async def end_game(self, game_id):
        game = self.games[game_id]
        game['state'] = 'finished'
        
        await self.broadcast({
            'type': 'game_over',
            'scores': game['scores'],
            'winner': max(game['scores'].items(), key=lambda x: x[1])[0] if game['scores'] else None
        }, game_id)

    async def reset_game(self, game_id):
        game = self.games[game_id]
        game['state'] = 'lobby'
        game['current_question'] = None
        game['question_index'] = 0
        
        # Reset scores but keep players
        for player in game['scores']:
            game['scores'][player] = 0
        
        await self.broadcast_game_state(game_id)

    async def broadcast_game_state(self, game_id):
        game = self.games[game_id]
        await self.broadcast({
            'type': 'game_state',
            'players': {p: {'ready': game['players'][p]['ready']} for p in game['players']},
            'scores': game['scores'],
            'game_state': game['state'],
            'host': game['host']
        }, game_id)

    async def broadcast(self, message, game_id, exclude=None):
        if game_id not in self.games:
            return
        
        exclude = exclude or []
        game = self.games[game_id]
        
        for player_name, player_data in game['players'].items():
            websocket = player_data['websocket']
            if websocket not in exclude and not websocket.closed:
                try:
                    await websocket.send(json.dumps(message))
                except:
                    pass

async def main():
    server = GameServer()
    async with websockets.serve(server.handle_connection, "localhost", 8765):
        print("Game server started on ws://localhost:8765")
        print("Players can connect using this address")
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())