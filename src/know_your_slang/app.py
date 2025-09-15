import random
import json
import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW
import asyncio
import websockets
from datetime import datetime
import uuid
from .storage import load_json, save_json

APP_TITLE = "Know Your Slang - Multiplayer"
QUESTION_TIME = 20
SERVER_URL = "ws://localhost:8765"  # Local server for testing

class NetworkManager:
    def __init__(self, app_instance):
        self.app = app_instance
        self.websocket = None
        self.connected = False
        self.game_id = None
        self.player_name = None
        self.is_host = False

    async def connect(self, game_id, player_name, is_host=False):
        try:
            self.game_id = game_id
            self.player_name = player_name
            self.is_host = is_host
            
            self.websocket = await websockets.connect(f"{SERVER_URL}/ws/{game_id}/{player_name}")
            self.connected = True
            
            # Send join message
            await self.send_message({
                "action": "join",
                "player_name": player_name,
                "is_host": is_host
            })
            
            # Start listening for messages
            asyncio.create_task(self.listen())
            return True
        except Exception as e:
            print(f"Connection failed: {e}")
            self.app.show_error(f"Connection failed: {str(e)}")
            return False

    async def listen(self):
        try:
            async for message in self.websocket:
                data = json.loads(message)
                await self.handle_server_message(data)
        except websockets.exceptions.ConnectionClosed:
            print("Connection closed")
            self.connected = False
            self.app.show_error("Disconnected from server")

    async def handle_server_message(self, data):
        message_type = data.get("type")
        
        if message_type == "game_state":
            await self.app.update_game_state(data)
        elif message_type == "new_question":
            await self.app.present_question(data)
        elif message_type == "answer_result":
            await self.app.show_answer_feedback(data)
        elif message_type == "game_over":
            await self.app.finish_game(data)
        elif message_type == "player_joined":
            await self.app.player_joined(data)
        elif message_type == "player_left":
            await self.app.player_left(data)
        elif message_type == "error":
            self.app.show_error(data.get("message", "Unknown error"))

    async def send_message(self, message):
        if self.websocket and self.connected:
            try:
                await self.websocket.send(json.dumps(message))
            except Exception as e:
                print(f"Failed to send message: {e}")

    async def submit_answer(self, answer):
        await self.send_message({
            "action": "submit_answer",
            "answer": answer,
            "player_name": self.player_name
        })

    async def start_game(self):
        await self.send_message({
            "action": "start_game"
        })

    async def disconnect(self):
        if self.websocket:
            await self.websocket.close()
        self.connected = False

def load_slang():
    """Load slang data from JSON file"""
    try:
        with open("src/know_your_slang/data/slang_en_za.json", "r", encoding="utf-8") as f:
            items = json.load(f)
        random.shuffle(items)
        return items
    except FileNotFoundError:
        print("Slang data file not found. Using sample data.")
        return [
            {"term": "awe", "meaning": "friendly greeting", "distractors": ["goodbye", "please"]},
            {"term": "braai", "meaning": "barbecue", "distractors": ["bake", "fry"]}
        ]

class KnowYourSlang(toga.App):
    def startup(self):
        self.main_window = toga.MainWindow(title=APP_TITLE)
        self.network = NetworkManager(self)
        
        # Game state
        self.current_question = None
        self.players = {}
        self.scores = {}
        self.game_state = "lobby"
        
        self.home_view = self.build_home()
        self.main_window.content = self.home_view
        self.main_window.show()

    def build_home(self):
        box = toga.Box(style=Pack(direction=COLUMN, padding=20, alignment="center"))
        
        title = toga.Label(APP_TITLE, style=Pack(font_size=24, padding=10))
        
        # Create game section
        create_box = toga.Box(style=Pack(direction=COLUMN, padding=10))
        create_box.add(toga.Label("Create Game", style=Pack(font_size=18, padding=5)))
        
        self.host_name_input = toga.TextInput(placeholder="Your name", style=Pack(padding=5, width=200))
        create_game_btn = toga.Button("Create New Game", on_press=self.create_game, style=Pack(padding=5))
        
        create_box.add(self.host_name_input)
        create_box.add(create_game_btn)
        
        # Join game section
        join_box = toga.Box(style=Pack(direction=COLUMN, padding=10))
        join_box.add(toga.Label("Join Game", style=Pack(font_size=18, padding=5)))
        
        self.player_name_input = toga.TextInput(placeholder="Your name", style=Pack(padding=5, width=200))
        self.game_id_input = toga.TextInput(placeholder="Game ID", style=Pack(padding=5, width=200))
        join_game_btn = toga.Button("Join Game", on_press=self.join_game, style=Pack(padding=5))
        
        join_box.add(self.player_name_input)
        join_box.add(self.game_id_input)
        join_box.add(join_game_btn)
        
        box.add(title)
        box.add(create_box)
        box.add(join_box)
        
        return box

    def build_lobby(self):
        box = toga.Box(style=Pack(direction=COLUMN, padding=20))
        
        box.add(toga.Label(f"Game ID: {self.network.game_id}", style=Pack(font_size=18, padding=10)))
        box.add(toga.Label("Players in lobby:", style=Pack(font_size=16, padding=5)))
        
        self.player_list = toga.Box(style=Pack(direction=COLUMN, padding=5))
        box.add(self.player_list)
        
        if self.network.is_host:
            start_btn = toga.Button("Start Game", on_press=self.start_game, style=Pack(padding=10))
            box.add(start_btn)
        
        back_btn = toga.Button("Leave Lobby", on_press=self.leave_lobby, style=Pack(padding=5))
        box.add(back_btn)
        
        return box

    def build_game_view(self):
        box = toga.Box(style=Pack(direction=COLUMN, padding=15))
        
        # Game info
        info_box = toga.Box(style=Pack(direction=ROW, padding=5))
        self.timer_label = toga.Label("20s", style=Pack(padding=5, flex=1))
        self.score_label = toga.Label("Score: 0", style=Pack(padding=5, flex=1))
        info_box.add(self.timer_label)
        info_box.add(self.score_label)
        
        # Question
        self.question_label = toga.Label("", style=Pack(font_size=18, padding=10, text_align="center"))
        
        # Choices
        self.choice_buttons = []
        choices_box = toga.Box(style=Pack(direction=COLUMN, padding=10, gap=5))
        for i in range(4):
            btn = toga.Button("", on_press=self.answer_clicked, style=Pack(padding=10))
            self.choice_buttons.append(btn)
            choices_box.add(btn)
        
        # Feedback
        self.feedback_label = toga.Label("", style=Pack(padding=10, text_align="center"))
        
        box.add(info_box)
        box.add(self.question_label)
        box.add(choices_box)
        box.add(self.feedback_label)
        
        return box

    async def create_game(self, widget):
        player_name = self.host_name_input.value.strip()
        if not player_name:
            self.show_error("Please enter your name")
            return
        
        game_id = str(uuid.uuid4())[:8].upper()
        success = await self.network.connect(game_id, player_name, is_host=True)
        
        if success:
            self.players[player_name] = {"ready": True}
            self.scores[player_name] = 0
            self.show_lobby()

    async def join_game(self, widget):
        player_name = self.player_name_input.value.strip()
        game_id = self.game_id_input.value.strip().upper()
        
        if not player_name or not game_id:
            self.show_error("Please enter both name and game ID")
            return
        
        success = await self.network.connect(game_id, player_name)
        
        if success:
            self.players[player_name] = {"ready": False}
            self.scores[player_name] = 0
            self.show_lobby()

    def show_lobby(self):
        self.main_window.content = self.build_lobby()
        self.update_player_list()

    def update_player_list(self):
        if hasattr(self, 'player_list'):
            self.player_list.clear()
            for player in self.players:
                status = "✓" if self.players[player].get("ready", False) else "○"
                label = toga.Label(f"{status} {player}", style=Pack(padding=2))
                self.player_list.add(label)

    async def start_game(self, widget):
        if len(self.players) < 1:
            self.show_error("Need at least 1 player to start")
            return
        
        await self.network.start_game()

    async def leave_lobby(self, widget):
        await self.network.disconnect()
        self.main_window.content = self.build_home()

    async def answer_clicked(self, widget):
        if self.game_state != "question":
            return
        
        answer = widget.text
        await self.network.submit_answer(answer)
        
        # Disable buttons after answering
        for btn in self.choice_buttons:
            btn.enabled = False

    async def update_game_state(self, data):
        self.players = data.get("players", {})
        self.scores = data.get("scores", {})
        self.game_state = data.get("game_state", "lobby")
        
        if self.game_state == "lobby":
            self.update_player_list()

    def update_score_display(self):
        score_text = " | ".join([f"{p}: {s}" for p, s in self.scores.items()])
        if hasattr(self, 'score_label'):
            self.score_label.text = score_text

    async def present_question(self, data):
        self.game_state = "question"
        self.current_question = data
        
        if hasattr(self, 'question_label'):
            self.question_label.text = f"What does '{data['term']}' mean?"
        
        choices = data['choices']
        for i, btn in enumerate(self.choice_buttons):
            btn.text = choices[i]
            btn.enabled = True
        
        if hasattr(self, 'feedback_label'):
            self.feedback_label.text = ""
        
        self.start_timer(data.get('time_limit', QUESTION_TIME))

    def start_timer(self, seconds):
        self.remaining_time = seconds
        if hasattr(self, 'timer_label'):
            self.timer_label.text = f"{self.remaining_time}s"
        
        if hasattr(self, 'timer_task'):
            self.timer_task.cancel()
        
        self.timer_task = asyncio.create_task(self.run_timer())

    async def run_timer(self):
        while self.remaining_time > 0:
            await asyncio.sleep(1)
            self.remaining_time -= 1
            if hasattr(self, 'timer_label'):
                self.timer_label.text = f"{self.remaining_time}s"
            
            if self.remaining_time <= 0 and self.game_state == "question":
                if hasattr(self, 'feedback_label'):
                    self.feedback_label.text = "Time's up!"
                for btn in self.choice_buttons:
                    btn.enabled = False

    async def show_answer_feedback(self, data):
        self.game_state = "feedback"
        player = data['player']
        is_correct = data['correct']
        correct_answer = data['correct_answer']
        
        if hasattr(self, 'feedback_label'):
            if is_correct:
                self.feedback_label.text = f"✅ {player} got it right!"
            else:
                self.feedback_label.text = f"❌ {player} was wrong. Correct: {correct_answer}"
        
        self.update_score_display()

    async def finish_game(self, data):
        self.game_state = "finished"
        final_scores = data.get('scores', {})
        
        result_box = toga.Box(style=Pack(direction=COLUMN, padding=20, alignment="center"))
        result_box.add(toga.Label("Game Over!", style=Pack(font_size=24, padding=10)))
        
        # Show final scores
        scores_text = "\n".join([f"{player}: {score}" for player, score in sorted(final_scores.items(), key=lambda x: x[1], reverse=True)])
        result_box.add(toga.Label(scores_text, style=Pack(padding=10)))
        
        play_again_btn = toga.Button("Play Again", on_press=self.play_again, style=Pack(padding=10))
        main_menu_btn = toga.Button("Main Menu", on_press=self.go_to_main_menu, style=Pack(padding=10))
        
        result_box.add(play_again_btn)
        result_box.add(main_menu_btn)
        
        self.main_window.content = result_box

    async def player_joined(self, data):
        player_name = data['player_name']
        self.players[player_name] = {"ready": False}
        self.scores[player_name] = 0
        self.update_player_list()

    async def player_left(self, data):
        player_name = data['player_name']
        if player_name in self.players:
            del self.players[player_name]
            del self.scores[player_name]
        self.update_player_list()

    def show_error(self, message):
        # Simple error display
        error_dialog = toga.Window(title="Error")
        error_box = toga.Box(style=Pack(direction=COLUMN, padding=20))
        error_box.add(toga.Label(f"Error: {message}", style=Pack(color="red")))
        error_box.add(toga.Button("OK", on_press=lambda w: error_dialog.close()))
        error_dialog.content = error_box
        error_dialog.show()

    async def play_again(self, widget):
        await self.network.send_message({
            "action": "play_again"
        })

    async def go_to_main_menu(self, widget):
        await self.network.disconnect()
        self.main_window.content = self.build_home()

def main():
    return KnowYourSlang(APP_TITLE, "za.co.mocodes.know-your-slang")