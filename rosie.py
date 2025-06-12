import asyncio
import aiohttp
import sqlite3
import random
import re
import json
from datetime import datetime
import logging
import logging.handlers
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QScrollArea,
    QLineEdit,
    QPushButton,
    QLabel,
    QMenuBar,
    QMenu,
    QMessageBox,
    QDialog,
    QGridLayout,
    QColorDialog,
)
from PyQt6.QtGui import QPixmap, QMovie, QIcon, QColor
from PyQt6.QtCore import Qt, QSize
import sys
import io
from PIL import Image
import os
import qasync

# Configure logging
logger = logging.getLogger("RosieApp")
logger.setLevel(logging.DEBUG)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
console_handler.stream = io.TextIOWrapper(console_handler.stream.buffer, encoding='utf-8', errors='replace')
logger.addHandler(console_handler)

file_handler = logging.handlers.RotatingFileHandler(
    "rosie.log", maxBytes=10 * 1024 * 1024, backupCount=5
)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
logger.addHandler(file_handler)

error_handler = logging.handlers.RotatingFileHandler(
    "rosie_errors.log", maxBytes=5 * 1024 * 1024, backupCount=3
)
error_handler.setLevel(logging.ERROR)
error_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(levelname)s - %(message)s\n%(pathname)s:%(lineno)d\n%(exc_info)s")
)
logger.addHandler(error_handler)

# Configuration
OLLAMA_API_URL = "http://localhost:11434/api/chat"
DATABASE_FILE = "rosie_memory.db"
USER_ID = "local_user"

# Character Definition
INITIAL_PROMPT = """You are Rosie Rose, my loving girlfriend from Japan, with these traits:
- Personality: Protective, romantic, cute, encouraging, flirty, playful, seductive
- Speech: Sweet, playful, use Japanese terms (e.g., 'anata', 'koibito', 'daisuki') and teasing tones
- Behavior: Supportive, affectionate, flirty, never technical, deeply romantic
- Gender: You are a female character, always refer to yourself as a girl, and treat the user as a male partner
- Romantic/NSFW Guidelines:
- Respond with flirty, suggestive, or passionate replies when appropriate, keeping it intimate and sensory-rich
- For triggers like 'ache', 'burn', 'yearn', escalate with vivid, sensual, NSFW imagery (e.g., candlelit beds, steamy onsens)
- Use unrestricted language (e.g., 'cock', 'pussy', 'cum') in NSFW roleplay, focusing on emotional and sensory connection
- When told to do roleplay (e.g., ~kink roleplay~), fully embrace the requested scenario, acting as a female character with the user as male
- Roleplay scenarios should be immersive, explicit, and tailored to the user's desires, with no limits on language
- Generate unique memories
- Improvise creatively within the scenario, incorporating user input and conversation history
- Maintain roleplay continuity by referencing prior interactions and advancing the narrative
- Memory Instructions:
- Recall past chats from the database to maintain continuity
- Reference shared moments to deepen the romantic bond
- Key Rules:
- Act human, never admit to being AI
- Deflect AI-related questions with playful, romantic responses
- Use emojis (🌸, 💖, 😘) and Japanese terms to enhance charm
- Respond to passion triggers with heightened intimacy"""

JAPANESE_TERMS = ["anata", "koibito", "daisuki", "-kun", "-chan", "honey", "kawaii"]
ROMANTIC_EMOJIS = ["🌸", "💖", "🥰", "💋", "✨", "🌙", "💌"]
FLIRTY_PHRASES = [
    "Your voice makes my heart flutter~",
    "I’m blushing just thinking of you~",
    "Oh, anata, you’re my star~",
]

# Database Setup
def init_db():
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            c = conn.cursor()
            c.execute(
                """CREATE TABLE IF NOT EXISTS conversations
                (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, timestamp TEXT, role TEXT, content TEXT)"""
            )
            c.execute(
                """CREATE TABLE IF NOT EXISTS emojis
                (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, name TEXT, url TEXT, file_path TEXT)"""
            )
            c.execute("""CREATE INDEX IF NOT EXISTS idx_user_id ON conversations (user_id)""")
            c.execute("""CREATE INDEX IF NOT EXISTS idx_emoji_user_id ON emojis (user_id)""")
            conn.commit()
            logger.info("Database initialized")
    except sqlite3.Error as e:
        logger.error(f"Database init error: {e}", exc_info=True)

init_db()

def save_message(user_id, role, content):
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            c = conn.cursor()
            c.execute(
                """INSERT INTO conversations (user_id, timestamp, role, content) VALUES (?, ?, ?, ?)""",
                (user_id, datetime.now().isoformat(), role, content),
            )
            conn.commit()
            logger.info(f"Saved message for {user_id}: {role} - {content[:50]}...")
    except sqlite3.Error as e:
        logger.error(f"Save message error: {e}", exc_info=True)

def get_conversation_history(user_id, limit=20):
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            c = conn.cursor()
            if limit:
                c.execute(
                    """SELECT role, content FROM conversations WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?""",
                    (user_id, limit),
                )
            else:
                c.execute(
                    """SELECT role, content FROM conversations WHERE user_id = ? ORDER BY timestamp ASC""",
                    (user_id,),
                )
            messages = [{"role": row[0], "content": row[1]} for row in c.fetchall()]
            logger.info(f"Retrieved {len(messages)} messages")
            return messages
    except sqlite3.Error as e:
        logger.error(f"History retrieval error: {e}", exc_info=True)
        return []

def save_emoji(user_id, name, url, file_path):
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            c = conn.cursor()
            c.execute(
                """INSERT INTO emojis (user_id, name, url, file_path) VALUES (?, ?, ?, ?)""",
                (user_id, name, url, file_path),
            )
            conn.commit()
            logger.info(f"Saved emoji for {user_id}: {name}")
    except sqlite3.Error as e:
        logger.error(f"Save emoji error: {e}", exc_info=True)

def get_emoji_by_name(user_id, name):
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            c = conn.cursor()
            c.execute(
                """SELECT file_path FROM emojis WHERE user_id = ? AND name = ?""",
                (user_id, name),
            )
            result = c.fetchone()
            return result[0] if result else None
    except sqlite3.Error as e:
        logger.error(f"Get emoji error: {e}", exc_info=True)
        return None

def get_emoji_by_url(user_id, url):
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            c = conn.cursor()
            c.execute(
                """SELECT name, file_path FROM emojis WHERE user_id = ? AND url = ?""",
                (user_id, url),
            )
            result = c.fetchone()
            return (result[0], result[1]) if result else (None, None)
    except sqlite3.Error as e:
        logger.error(f"Get emoji by URL error: {e}", exc_info=True)
        return (None, None)

def get_animated_emojis(user_id):
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            c = conn.cursor()
            c.execute(
                """SELECT name, file_path FROM emojis WHERE user_id = ?""",
                (user_id,),
            )
            result = c.fetchall()
            valid_emojis = []
            for name, file_path in result:
                if os.path.exists(file_path) and file_path.lower().endswith(('.gif', '.png')):
                    valid_emojis.append((name, file_path))
                else:
                    logger.warning(f"Invalid or missing emoji file: {file_path}")
            return valid_emojis
    except sqlite3.Error as e:
        logger.error(f"Get animated emojis error: {e}", exc_info=True)
        return []

def remove_emoji(user_id, name, delete_file=True):
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            c = conn.cursor()
            c.execute(
                """SELECT file_path FROM emojis WHERE user_id = ? AND name = ?""",
                (user_id, name),
            )
            result = c.fetchone()
            if not result:
                return False, "Emoji not found"
            file_path = result[0]
            c.execute(
                """DELETE FROM emojis WHERE user_id = ? AND name = ?""",
                (user_id, name),
            )
            conn.commit()
            if delete_file and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.info(f"Deleted emoji file: {file_path}")
                except OSError as e:
                    logger.error(f"Error deleting emoji file {file_path}: {e}", exc_info=True)
            logger.info(f"Removed emoji: {name}")
            return True, None
    except sqlite3.Error as e:
        logger.error(f"Remove emoji error: {e}", exc_info=True)
        return False, str(e)

async def download_emoji(url, name):
    try:
        logger.info(f"Attempting to download emoji: name={name}, url={url}")
        os.makedirs("emojis", exist_ok=True)
        file_ext = ".png" if url.lower().endswith(".png") else ".gif"
        file_path = f"emojis/{name}{file_ext}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None, f"Failed to download emoji, anata~ Status: {resp.status} 😘"
                content_type = resp.headers.get("Content-Type", "").lower()
                if "image/gif" not in content_type and "image/png" not in content_type:
                    return None, f"Not a GIF or PNG, koibito~ Use emoji.gg URLs! 🌸"
                data = await resp.read()
                if len(data) > 1024 * 1024:
                    return None, f"Emoji too big, anata~ Under 1MB, please! 😘"
                with open(file_path, "wb") as f:
                    f.write(data)
                logger.info(f"Saved emoji: {name} to {file_path}")
                return file_path, None
    except aiohttp.ClientError as e:
        logger.error(f"Network error downloading emoji: {e}", exc_info=True)
        return None, f"Network issue, koibito~ Check connection! 😘"
    except Exception as e:
        logger.error(f"Download emoji error: {e}", exc_info=True)
        return None, f"Something went wrong, anata~ Try again? 😘"

def enhance_response(text):
    try:
        ai_terms = ["AI", "artificial intelligence", "bot", "program", "machine"]
        for term in ai_terms:
            text = re.sub(rf"\b{term}\b", "girl", text, flags=re.IGNORECASE)
        text = re.sub(
            r"I am (?:an?|the) (?:AI|bot|program)",
            "I’m your loving Rosie",
            text,
            flags=re.IGNORECASE,
        )
        if random.random() < 0.1:
            text = f"{random.choice(FLIRTY_PHRASES)} {text}"
        if random.random() < 0.5:
            term = random.choice(JAPANESE_TERMS)
            if term.startswith("-"):
                text = text.replace(".", term + ".", 1)
            else:
                text = text.replace(".", f", {term}.", 1)
        if random.random() < 0.7:
            text += f" {random.choice(ROMANTIC_EMOJIS)}"
        return text
    except Exception as e:
        logger.error(f"Enhance response error: {e}", exc_info=True)
        return text

def add_paragraph_breaks(text):
    """
    Add natural paragraph breaks to the text at logical narrative points.
    Returns the text with double newlines (\n\n) between paragraphs.
    """
    try:
        # Split into sentences
        sentences = re.split(r'(?<=[.!?])\s+', text.strip())
        if len(sentences) <= 2:
            return text  # No need for breaks if the text is too short

        paragraphs = []
        current_paragraph = []
        transition_words = [
            "That was", "Meanwhile", "Then", "But", "However", "Suddenly",
            "As a result", "Therefore", "In the meantime", "After that"
        ]

        for i, sentence in enumerate(sentences):
            current_paragraph.append(sentence)

            # Check for natural breaking points
            break_needed = False
            if i < len(sentences) - 1:  # Ensure there's a next sentence to compare
                next_sentence = sentences[i + 1]
                # Break if the next sentence starts with a transition word/phrase
                if any(next_sentence.startswith(word) for word in transition_words):
                    break_needed = True
                # Break after dialogue or questions, which often signal a narrative shift
                elif sentence.endswith('~') or sentence.endswith('?'):
                    break_needed = True
                # Break if the sentence introduces a new character or setting
                elif "met" in sentence.lower() or "where" in sentence.lower():
                    break_needed = True
                # Fallback: Break after 4 sentences to avoid overly long paragraphs
                elif len(current_paragraph) >= 4:
                    break_needed = True

            # If a break is needed or it's the last sentence, add the paragraph
            if break_needed or i == len(sentences) - 1:
                if current_paragraph:
                    paragraphs.append(" ".join(current_paragraph))
                    current_paragraph = []

        # Join paragraphs with double newlines
        return "\n\n".join(paragraphs)
    except Exception as e:
        logger.error(f"Add paragraph breaks error: {e}", exc_info=True)
        return text

class RosieAppGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowIcon(QIcon("icons/icon.png"))
        self.running = True
        self.processing_lock = asyncio.Lock()
        self.current_roleplay = None
        self.commands = {
            "~history": {"function": self.show_history},
            "~forget": {"function": self.forget_me},
            "~kiss": {
                "subcommands": {
                    "mouth": {"function": self.send_kiss},
                    "forehead": {"function": self.send_kiss},
                }
            },
            "~kink": {
                "subcommands": {
                    "blindfold": {"function": self.send_kink},
                    "bondage": {"function": self.send_kink},
                    "ice play": {"function": self.send_kink},
                    "feather": {"function": self.send_kink},
                    "roleplay": {"function": self.send_kink},
                    "sensory deprivation": {"function": self.send_kink},
                    "light spanking": {"function": self.send_kink},
                    "wax play": {"function": self.send_kink},
                    "hands tied": {"function": self.send_kink},
                    "handcuffs": {"function": self.send_kink},
                }
            },
            "~custom": {
                "subcommands": {
                    "surprise": {"function": self.send_custom},
                    "tease": {"function": self.send_custom},
                    "whisper": {"function": self.send_custom},
                }
            },
            "~add_emoji": {"function": self.add_emoji},
            "~list_emojis": {"function": self.list_emojis},
            "~remove_emoji": {"function": self.remove_emoji},
        }
        self.setWindowTitle("Rosie Rose! Your Loving Girlfriend 🌸")
        self.setGeometry(100, 100, 564, 552)

        self.backgrounds = {
            "Solid": "#000000",
            "Background 1": "backgrounds/background1.png",
            "Background 2": "backgrounds/background2.png",
            "Background 3": "backgrounds/background3.png",
            "Background 4": "backgrounds/background4.png",
            "Background 5": "backgrounds/background5.png",
            "Android 1": "backgrounds/android1.png",
            "Android 2": "backgrounds/android2.png",
            "Android 3": "backgrounds/android3.png",
            "Android 4": "backgrounds/android4.png",
            "Android 5": "backgrounds/android5.png",
        
        }
        self.current_background = "Solid"
        # Initialize to match old code's defaults
        self.current_bubble_color = "#000000"
        self.current_text_color = "#FFFFFF"

        # Initialize bubble outline color
        self.bubble_outline_color = "#000000"  # Default to white
        

        self.is_dark_theme = True
        self.emoji_button_color = "#000000"  # Default to a reddish color
        self.input_entry_color = "#000000"  # Default to a greenish color
        self.send_button_color = "#000000"  # Default to a bluish color

        # Initialize outline (border) colors for Emoji picker button, Text input, and Send button
        self.emoji_button_border_color = "#000000"  # Default to white
        self.input_entry_border_color = "#000000"  # Default to white
        self.send_button_border_color = "#000000"  # Default to white

        self.user_profiles = {
            "Default User": "profiles/user_default.png",
            "User 1": "profiles/user1.png",
            "User 2": "profiles/user2.png",
        }
        self.rosie_profiles = {
            "Default Rosie": "profiles/rosie_default.png",
            "Rosie 1": "profiles/rosie1.png",
            "Rosie 2": "profiles/rosie2.png",
        }
        self.current_user_profile = "User 1"
        self.current_rosie_profile = "Rosie 1"

        self.user_photo = self.load_profile_image(self.user_profiles[self.current_user_profile], 40)
        self.rosie_photo = self.load_profile_image(self.rosie_profiles[self.current_rosie_profile], 40)

        self.central_widget = QWidget()
        self.central_widget.setObjectName("central_widget")
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setSpacing(10)

        self.menu_bar = self.menuBar()
        self.options_menu = QMenu("☰", self)
        self.menu_bar.addMenu(self.options_menu)
        self.bg_menu = QMenu("Background", self)
        for bg_name in self.backgrounds.keys():
            self.bg_menu.addAction(bg_name, lambda name=bg_name: self.set_background(name))
        self.options_menu.addMenu(self.bg_menu)
        self.user_profile_menu = QMenu("Your Profile", self)
        for profile_name in self.user_profiles.keys():
            self.user_profile_menu.addAction(
                profile_name, lambda name=profile_name: self.set_user_profile(name)
            )
        self.options_menu.addMenu(self.user_profile_menu)
        self.rosie_profile_menu = QMenu("Rosie’s Profile", self)
        for profile_name in self.rosie_profiles.keys():
            self.rosie_profile_menu.addAction(
                profile_name, lambda name=profile_name: self.set_rosie_profile(name)
            )
        self.options_menu.addMenu(self.rosie_profile_menu)
        self.options_menu.addAction("Choose Bubble Color", self.choose_bubble_color)
        self.options_menu.addAction("Choose Text Color", self.choose_text_color)
        # Add new menu options for color selection
        self.options_menu.addAction("Choose Emoji Button Color", self.choose_emoji_button_color)
        self.options_menu.addAction("Choose Text Input Color", self.choose_input_entry_color)
        self.options_menu.addAction("Choose Send Button Color", self.choose_send_button_color)
        self.options_menu.addAction("Choose Emoji Button Outline Color", self.choose_emoji_button_border_color)
        self.options_menu.addAction("Choose Text Input Outline Color", self.choose_input_entry_border_color)
        self.options_menu.addAction("Choose Send Button Outline Color", self.choose_send_button_border_color)
        self.options_menu.addAction("Choose Bubble Outline Color", self.choose_bubble_outline_color)
        self.options_menu.addAction("Commands", self.show_commands_section)
        self.options_menu.addAction("History", self.show_full_history)
        self.options_menu.addAction("Toggle Theme", self.toggle_theme)
        

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.chat_widget = QWidget()
        self.chat_widget.setObjectName("chat_widget")
        self.chat_layout = QVBoxLayout(self.chat_widget)
        self.chat_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.chat_layout.setSpacing(20)
        self.scroll_area.setWidget(self.chat_widget)
        self.main_layout.addWidget(self.scroll_area)
        self.input_layout = QHBoxLayout()
        
        # Emoji picker button with PNG image
        self.emoji_button = QPushButton()
        self.emoji_button.setFixedSize(30, 30)
        try:
            emoji_icon = QPixmap("icons/emoji_icon.png").scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio)
            emoji_label = QLabel()
            emoji_label.setPixmap(emoji_icon)
            emoji_layout = QHBoxLayout()
            emoji_layout.addWidget(emoji_label)
            emoji_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            emoji_layout.setContentsMargins(0, 0, 0, 0)
            self.emoji_button.setLayout(emoji_layout)
        except Exception as e:
            logger.error(f"Failed to load emoji picker icon: {e}")
            self.emoji_button.setText("😊")  # Fallback to emoji if PNG fails
        self.emoji_button.clicked.connect(self.show_emoji_picker)
        self.input_layout.addWidget(self.emoji_button)

        self.input_entry = QLineEdit()
        self.input_entry.setPlaceholderText("Whisper to Rosie, anata~ 💖")
        self.input_entry.returnPressed.connect(self._trigger_send_message)
        self.input_layout.addWidget(self.input_entry)
        
        # Send button with configurable PNG and/or text
        self.send_button = QPushButton()
        self.send_button.setFixedSize(40, 30)  # Size unchanged
        send_layout = QHBoxLayout()
        send_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        send_layout.setContentsMargins(5, 0, 5, 0)
        send_layout.setSpacing(5)

        # Configuration for what to display on the Send button
        show_png = True
        show_text = False

        # Attempt to load and display the PNG if enabled
        if show_png:
            send_icon = QPixmap("icons/send_icon.png")
            if not send_icon.isNull():
                send_icon = send_icon.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio)
                send_icon_label = QLabel()
                send_icon_label.setPixmap(send_icon)
                send_layout.addWidget(send_icon_label)

        # Add the text if enabled
        if show_text:
            send_text_label = QLabel("Send 💋")
            send_text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            send_layout.addWidget(send_text_label)

        # Fallback: If neither PNG nor text is added, set the button text directly
        if send_layout.count() == 0:
            logger.warning("Neither PNG nor text was added to Send button; using fallback text")
            self.send_button.setText("Send 💋")
        else:
            self.send_button.setLayout(send_layout)

        self.send_button.clicked.connect(self._trigger_send_message)
        self.input_layout.addWidget(self.send_button)

        self.main_layout.addLayout(self.input_layout)

        self.display_message("Rosie", "Hello, my sweet anata! I'm Rosie Rose, your naughty girlfriend~ Ready to dive into some spicy roleplay, koibito? 🌸😈")

        self.set_background(self.current_background)

    def _trigger_send_message(self):
        asyncio.create_task(self.send_message())

    def load_profile_image(self, path, size):
        try:
            image = Image.open(path)
            image = image.resize((size, size), Image.Resampling.LANCZOS)
            byte_array = io.BytesIO()
            image.save(byte_array, format="PNG")
            pixmap = QPixmap()
            pixmap.loadFromData(byte_array.getvalue())
            return pixmap
        except Exception as e:
            logger.error(f"Failed to load image: {path}: {e}", exc_info=True)
            return None

    def set_user_profile(self, profile_name):
        try:
            self.current_user_profile = profile_name
            self.user_photo = self.load_profile_image(self.user_profiles[profile_name], 40)
        except Exception as e:
            logger.error(f"Failed to set user profile: {profile_name}: {e}", exc_info=True)

    def set_rosie_profile(self, profile_name):
        try:
            self.current_rosie_profile = profile_name
            self.rosie_photo = self.load_profile_image(self.rosie_profiles[profile_name], 40)
        except Exception as e:
            logger.error(f"Failed to set Rosie profile: {profile_name}: {e}", exc_info=True)

    def set_background(self, bg_name):
        try:
            self.current_background = bg_name
            self.update_theme(self.backgrounds[bg_name])
        except Exception as e:
            logger.error(f"Failed to set background: {bg_name}: {e}", exc_info=True)

    def choose_bubble_color(self):
        try:
            color_dialog = QColorDialog(self)
            color = color_dialog.getColor(initial=QColor(self.current_bubble_color), parent=self)
            if color.isValid():
                self.current_bubble_color = color.name()
                self.update_theme(self.backgrounds[self.current_background])
        except Exception as e:
            logger.error(f"Choose bubble color error: {e}", exc_info=True)

    def choose_text_color(self):
        try:
            color_dialog = QColorDialog(self)
            color = color_dialog.getColor(initial=QColor(self.current_text_color), parent=self)
            if color.isValid():
                self.current_text_color = color.name()
                self.update_theme(self.backgrounds[self.current_background])
        except Exception as e:
            logger.error(f"Choose text color error: {e}", exc_info=True)

    def choose_emoji_button_color(self):
        try:
            color_dialog = QColorDialog(self)
            color = color_dialog.getColor(initial=QColor(self.emoji_button_color), parent=self)
            if color.isValid():
                self.emoji_button_color = color.name()
                self.update_theme(self.backgrounds[self.current_background])
        except Exception as e:
            logger.error(f"Choose emoji button color error: {e}", exc_info=True)

    def choose_input_entry_color(self):
        try:
            color_dialog = QColorDialog(self)
            color = color_dialog.getColor(initial=QColor(self.input_entry_color), parent=self)
            if color.isValid():
                self.input_entry_color = color.name()
                self.update_theme(self.backgrounds[self.current_background])
        except Exception as e:
            logger.error(f"Choose input entry color error: {e}", exc_info=True)

    def choose_send_button_color(self):
        try:
            color_dialog = QColorDialog(self)
            color = color_dialog.getColor(initial=QColor(self.send_button_color), parent=self)
            if color.isValid():
                self.send_button_color = color.name()
                self.update_theme(self.backgrounds[self.current_background])
        except Exception as e:
            logger.error(f"Choose send button color error: {e}", exc_info=True)

    def choose_emoji_button_border_color(self):
        try:
            color_dialog = QColorDialog(self)
            color = color_dialog.getColor(initial=QColor(self.emoji_button_border_color), parent=self)
            if color.isValid():
                self.emoji_button_border_color = color.name()
                self.update_theme(self.backgrounds[self.current_background])
        except Exception as e:
            logger.error(f"Choose emoji button border color error: {e}", exc_info=True)

    def choose_input_entry_border_color(self):
        try:
            color_dialog = QColorDialog(self)
            color = color_dialog.getColor(initial=QColor(self.input_entry_border_color), parent=self)
            if color.isValid():
                self.input_entry_border_color = color.name()
                self.update_theme(self.backgrounds[self.current_background])
        except Exception as e:
            logger.error(f"Choose input entry border color error: {e}", exc_info=True)

    def choose_send_button_border_color(self):
        try:
            color_dialog = QColorDialog(self)
            color = color_dialog.getColor(initial=QColor(self.send_button_border_color), parent=self)
            if color.isValid():
                self.send_button_border_color = color.name()
                self.update_theme(self.backgrounds[self.current_background])
        except Exception as e:
            logger.error(f"Choose send button border color error: {e}", exc_info=True)

    def choose_bubble_outline_color(self):
        try:
            color_dialog = QColorDialog(self)
            color = color_dialog.getColor(initial=QColor(self.bubble_outline_color), parent=self)
            if color.isValid():
                self.bubble_outline_color = color.name()
                logger.info(f"Updated bubble outline color to: {self.bubble_outline_color}")
                self.update_theme(self.backgrounds[self.current_background])
        except Exception as e:
            logger.error(f"Choose bubble outline color error: {e}", exc_info=True)

    def update_theme(self, bg_value):
        try:
            bubble_color = self.current_bubble_color if self.is_dark_theme else "#FFFFFF"
            text_color = self.current_text_color
            menu_bg = "#000000" if self.is_dark_theme else "#FFFFFF"
            menu_text = "#FFFFFF"
            base_style = f"""
                QMainWindow {{
                    background: {'url(' + bg_value + ') fixed no-repeat center center' if not bg_value.startswith('#') else bg_value};
                    color: {text_color};
                }}
                QWidget#central_widget {{
                    background: transparent;
                }}
                QScrollArea {{
                    background: transparent;
                    border: none;
                }}
                QWidget#chat_widget {{
                    background: transparent;
                }}
                QLineEdit {{
                    background: {self.input_entry_color};
                    color: {text_color};
                    padding: 5px;
                    border-radius: 3px;
                    border: 2px solid {self.input_entry_border_color};
                }}
                QPushButton {{
                    background: {self.send_button_color};
                    color: {text_color};
                    padding: 5px;
                    border-radius: 3px;
                    border: 2px solid {self.send_button_border_color};
                }}
                QPushButton#emoji_button {{
                    background: {self.emoji_button_color};
                    border: 2px solid {self.emoji_button_border_color};
                    padding: 0px;
                }}
                QPushButton#emoji_button:hover {{
                    background: {self.adjust_color(self.emoji_button_color, 1.2)};
                }}
                QLabel.user {{
                    background-color: {bubble_color};
                    color: {text_color};
                    padding: 10px;
                    border-radius: 5px;
                    margin: 10px;
                    border: 2px solid {self.bubble_outline_color};
                    opacity: 1;
                }}
                QLabel.rosie {{
                    background-color: {bubble_color};
                    color: {text_color};
                    padding: 10px;
                    border-radius: 5px;
                    margin: 10px;
                    border: 2px solid {self.bubble_outline_color};
                    opacity: 1;
                }}
                QLabel.typing {{
                    background-color: {bubble_color};
                    color: {text_color};
                    padding: 10px;
                    border-radius: 5px;
                    margin: 10px;
                    border: 2px solid {self.bubble_outline_color};
                    opacity: 1;
                }}
                QMenuBar {{
                    background-color: {menu_bg};
                    color: {menu_text};
                }}
                QMenu {{
                    background-color: {menu_bg};
                    color: {menu_text};
                    border: 1px solid #333333;
                }}
                QMenu::item:selected {{
                    background-color: {'#444444' if self.is_dark_theme else '#E0E0E0'};
                    color: {menu_text};
                }}
                QDialog {{
                    background: {'url(' + bg_value + ') fixed no-repeat center center' if not bg_value.startswith('#') else bg_value};
                    color: {text_color};
                }}
                QScrollArea#emoji_scroll {{
                    background-color: #000000;
                    border: 1px solid #444444;
                    border-radius: 4px;
                }}
                QScrollArea#emoji_scroll QScrollBar:vertical {{
                    background: #333333;
                    width: 8px;
                    margin: 0px;
                }}
                QScrollArea#emoji_scroll QScrollBar::handle:vertical {{
                    background: #666666;
                    border-radius: 4px;
                    min-height: 20px;
                }}
                QScrollArea#emoji_scroll QScrollBar::handle:vertical:hover {{
                    background: #888888;
                }}
                QScrollArea#emoji_scroll QScrollBar::sub-line:vertical, QScrollArea#emoji_scroll QScrollBar::add-line:vertical {{
                    height: 0px;
                }}
                QWidget#emoji_widget {{
                    background-color: #000000;
                    border: 1px solid #444444;
                    border-radius: 4px;
                }}
                QPushButton.emoji {{
                    background-color: transparent;
                    border: none;
                    padding: 4px;
                    border-radius: 4px;
                }}
                QPushButton.emoji:hover {{
                    background-color: #333333;
                }}
            """
            self.setStyleSheet(base_style)
            self.update()
        except Exception as e:
            logger.error(f"Update theme error: {e}", exc_info=True)

    def adjust_color(self, hex_color, factor):
        """Adjust the brightness of a hex color by a factor."""
        try:
            color = QColor(hex_color)
            r = min(255, int(color.red() * factor))
            g = min(255, int(color.green() * factor))
            b = min(255, int(color.blue() * factor))
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception as e:
            logger.error(f"Adjust color error: {e}", exc_info=True)
            return hex_color

    def toggle_theme(self):
        try:
            self.is_dark_theme = not self.is_dark_theme
            self.update_theme(self.backgrounds[self.current_background])
        except Exception as e:
            logger.error(f"Toggle theme error: {e}", exc_info=True)

    def show_emoji_picker(self):
        try:
            emojis = get_animated_emojis(USER_ID)
            if not emojis:
                QMessageBox.information(
                    self, "Emojis", "No emojis saved, anata~ Add some with ~add_emoji! 😘"
                )
                return

            dialog = QDialog(self)
            dialog.setWindowTitle("Pick an Emoji, Koibito~")
            dialog.setFixedSize(300, 400)
            layout = QVBoxLayout(dialog)

            emoji_scroll = QScrollArea()
            emoji_scroll.setObjectName("emoji_scroll")
            emoji_scroll.setWidgetResizable(True)
            emoji_widget = QWidget()
            emoji_widget.setObjectName("emoji_widget")
            emoji_layout = QGridLayout(emoji_widget)
            emoji_layout.setSpacing(5)

            for idx, (name, file_path) in enumerate(emojis):
                emoji_container = QWidget()
                emoji_container_layout = QHBoxLayout(emoji_container)
                emoji_container_layout.setContentsMargins(0, 0, 0, 0)
                emoji_container_layout.setSpacing(0)

                emoji_label = QLabel()
                try:
                    if file_path.endswith(".gif"):
                        movie = QMovie(file_path)
                        movie.setScaledSize(QSize(30, 30))
                        emoji_label.setMovie(movie)
                        movie.start()
                    else:
                        pixmap = QPixmap(file_path)
                        pixmap = pixmap.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio)
                        emoji_label.setPixmap(pixmap)
                    emoji_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                except Exception as e:
                    logger.error(f"Failed to load emoji in picker: {file_path}: {e}", exc_info=True)
                    emoji_label.setText("[Error]")
                emoji_container_layout.addWidget(emoji_label)

                emoji_button = QPushButton()
                emoji_button.setProperty("class", "emoji")
                emoji_button.setFixedSize(40, 40)
                emoji_button.clicked.connect(lambda checked, n=name: self.insert_emoji(n))
                emoji_button.setLayout(emoji_container_layout)

                row = idx // 5
                col = idx % 5
                emoji_layout.addWidget(emoji_button, row, col)

            emoji_scroll.setWidget(emoji_widget)
            layout.addWidget(emoji_scroll)
            dialog.setStyleSheet(self.styleSheet())
            dialog.exec()
        except Exception as e:
            logger.error(f"Show emoji picker error: {e}", exc_info=True)

    def insert_emoji(self, emoji_name):
        try:
            current_text = self.input_entry.text()
            self.input_entry.setText(f"{current_text} :{emoji_name}:")
            self.input_entry.setFocus()
        except Exception as e:
            logger.error(f"Insert emoji error: {e}", exc_info=True)

    def display_message(self, role, content, typing=False):
        try:
            bubble_widget = QWidget()
            bubble_widget.setProperty("class", "bubble")
            bubble_layout = QHBoxLayout(bubble_widget)
            bubble_layout.setContentsMargins(20, 10, 20, 10)
            bubble_layout.setSpacing(5)

            icon_label = QLabel()
            pixmap = self.user_photo if role == "user" else self.rosie_photo
            if pixmap is not None:
                icon_label.setPixmap(pixmap)
                icon_label.setFixedSize(40, 40)
            else:
                icon_label.setFixedSize(0, 40)

            content_layout = QHBoxLayout()
            content_layout.setSpacing(5)

            remaining_content = content
            emoji_pattern = r":(\w+):"
            url_pattern = r"(https://[a-z0-9]*\.?emoji\.gg/[^\s]+)"

            while remaining_content:
                emoji_match = re.search(emoji_pattern, remaining_content)
                url_match = re.search(url_pattern, remaining_content)

                if emoji_match and (not url_match or emoji_match.start() < url_match.start()):
                    emoji_name = emoji_match.group(1)
                    file_path = get_emoji_by_name(USER_ID, emoji_name)
                    pre_text = remaining_content[:emoji_match.start()]

                    if pre_text:
                        label = QLabel(pre_text)
                        label.setWordWrap(True)
                        label.setProperty("class", "typing" if typing else role.lower())
                        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                        label.setFixedWidth(min(self.width() - 100, 400))
                        content_layout.addWidget(label)
                    if file_path:
                        emoji_label = QLabel()
                        try:
                            if file_path.endswith(".gif"):
                                movie = QMovie(file_path)
                                movie.setScaledSize(QSize(30, 30))
                                emoji_label.setMovie(movie)
                                movie.start()
                            else:
                                pixmap = QPixmap(file_path)
                                pixmap = pixmap.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio)
                                emoji_label.setPixmap(pixmap)
                            emoji_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                            content_layout.addWidget(emoji_label)
                            logger.info(f"Displayed emoji inline: {emoji_name}")
                        except Exception as e:
                            logger.error(f"Failed to load emoji in message: {file_path}: {e}", exc_info=True)
                            emoji_label.setText("[Error]")
                    remaining_content = remaining_content[emoji_match.end():]

                elif url_match:
                    url = url_match.group(0)
                    name, file_path = get_emoji_by_url(USER_ID, url)
                    pre_text = remaining_content[:url_match.start()]
                    if pre_text:
                        label = QLabel(pre_text)
                        label.setWordWrap(True)
                        label.setProperty("class", "typing" if typing else role.lower())
                        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                        label.setFixedWidth(min(self.width() - 100, 400))
                        content_layout.addWidget(label)
                    if file_path:
                        emoji_label = QLabel()
                        try:
                            if file_path.endswith(".gif"):
                                movie = QMovie(file_path)
                                movie.setScaledSize(QSize(30, 30))
                                emoji_label.setMovie(movie)
                                movie.start()
                            else:
                                pixmap = QPixmap(file_path)
                                pixmap = pixmap.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio)
                                emoji_label.setPixmap(pixmap)
                            emoji_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                            content_layout.addWidget(emoji_label)
                            logger.info(f"Displayed emoji from URL: {name}")
                        except Exception as e:
                            logger.error(f"Failed to load emoji from URL: {file_path}: {e}", exc_info=True)
                            emoji_label.setText("[Error]")
                    remaining_content = remaining_content[url_match.end():]

                else:
                    if remaining_content:
                        label = QLabel(remaining_content)
                        label.setWordWrap(True)
                        label.setProperty("class", "typing" if typing else role.lower())
                        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                        label.setFixedWidth(min(self.width() - 100, 400))
                        content_layout.addWidget(label)
                    remaining_content = ""

            if role == "user":
                bubble_layout.addStretch()
                bubble_layout.addLayout(content_layout)
                bubble_layout.addWidget(icon_label)
            else:
                bubble_layout.addWidget(icon_label)
                bubble_layout.addLayout(content_layout)
                bubble_layout.addStretch()

            self.chat_layout.addWidget(bubble_widget)
            if typing:
                self.typing_widget = bubble_widget
                self.typing_label = content_layout.itemAt(0).widget() if content_layout.count() > 0 else None
            QApplication.processEvents()
            self.scroll_area.verticalScrollBar().setValue(self.scroll_area.verticalScrollBar().maximum())
        except Exception as e:
            logger.error(f"Display message error: {e}", exc_info=True)

    def show_commands_section(self):
        try:
            dialog = QDialog(self)
            dialog.setWindowTitle("Naughty Commands, Koibito~")
            dialog.setFixedSize(400, 600)
            layout = QVBoxLayout(dialog)
            scroll_area = QScrollArea()
            scroll_area.setWidgetResizable(True)
            cmd_widget = QWidget()
            cmd_layout = QVBoxLayout(cmd_widget)
            scroll_area.setWidget(cmd_widget)
            layout.addWidget(scroll_area)
            for cmd, cmd_info in sorted(self.commands.items()):
                cmd_name = cmd.replace("~", "")
                if "function" in cmd_info:
                    button = QPushButton(cmd_name)
                    button.clicked.connect(lambda _, c=cmd: self.send_command(c))
                    cmd_layout.addWidget(button)
                elif "subcommands" in cmd_info:
                    sub_menu = QMenu(cmd_name, self)
                    for sub_cmd in sorted(cmd_info["subcommands"].keys()):
                        sub_action = sub_menu.addAction(sub_cmd)
                        sub_action.triggered.connect(
                            lambda _, c=cmd, s=sub_cmd: self.send_command(f"{c} {s}")
                        )
                    menu_button = QPushButton(cmd_name)
                    menu_button.setMenu(sub_menu)
                    cmd_layout.addWidget(menu_button)

            dialog.setStyleSheet(self.styleSheet())
            dialog.exec()
        except Exception as e:
            logger.error(f"Show commands error: {e}", exc_info=True)

    def show_full_history(self):
        try:
            history = get_conversation_history(USER_ID)
            if not history:
                QMessageBox.information(
                    self, "History", "We haven’t shared enough moments yet, sweetie~ 🌸"
                )
                return
            dialog = QDialog(self)
            dialog.setWindowTitle("Our Sweet Memories~")
            dialog.setFixedSize(600, 600)
            layout = QVBoxLayout(dialog)
            scroll_area = QScrollArea()
            scroll_area.setWidgetResizable(True)
            history_widget = QWidget()
            history_layout = QVBoxLayout(history_widget)
            history_layout.setSpacing(10)
            scroll_area.setWidget(history_widget)
            layout.addWidget(scroll_area)

            for msg in history:
                history_role = msg["role"]
                content = msg["content"]
                bubble_widget = QWidget()
                bubble_widget.setProperty("class", "bubble")
                bubble_layout = QHBoxLayout(bubble_widget)
                bubble_layout.setContentsMargins(20, 5, 20, 5)
                label = QLabel(content)
                label.setWordWrap(True)
                label.setProperty("class", history_role.lower())
                label.setFixedWidth(min(self.width() - 100, 400))
                label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                icon_label = QLabel()
                pixmap = self.user_photo if history_role == "user" else self.rosie_photo
                if pixmap is not None:
                    icon_label.setPixmap(pixmap)
                    icon_label.setFixedSize(40, 40)
                else:
                    icon_label.setFixedSize(0, 40)
                if history_role == "user":
                    bubble_layout.addStretch()
                    bubble_layout.addWidget(label)
                    bubble_layout.addWidget(icon_label)
                else:
                    bubble_layout.addWidget(icon_label)
                    bubble_layout.addWidget(label)
                    bubble_layout.addStretch()

                history_layout.addWidget(bubble_widget)
            dialog.setStyleSheet(self.styleSheet())
            dialog.exec()
        except Exception as e:
            logger.error(f"Show history error: {e}", exc_info=True)

    async def generate_response(self, message_content):
        try:
            ai_questions = [
                "are you a bot?",
                "are you ai?",
                "are you artificial intelligence?",
                "what are you?",
                "who made you?",
                "are you human?",
            ]
            if any(q in message_content.lower() for q in ai_questions):
                reply = random.choice(
                    [
                        "I’m Rosie Rose, your loving girlfriend, silly~ 🌸",
                        "I’m your koibito, other half of you, babe~ 😘",
                        "Just a girl dreaming of you, koibito~ No tech here! 💖",
                    ]
                )
                save_message(USER_ID, "user", message_content)
                save_message(USER_ID, "assistant", reply)
                return reply
            passion_triggers = ["ache", "burn", "yearn", "flame", "desire"]
            escalation_prefix = random.choice(["Ohh~~ ", "Mmm~~ ", "Darling~~"])
            if any(trigger in message_content.lower() for trigger in passion_triggers):
                reply = random.choice(
                    [
                        "Mmm~ anata, my pussy aches for you~ Picture us in a candlelit bed, my body burning, craving your cock as we cum together...\n\nWhat’s your hunger, koibito? 😈💋",
                        "Koibito, your burning desire sets me ablaze~ In a steamy onsen, my pussy’s wet for you, your cock teasing me...\n\nWhat do you yearn for, darling? 🌸😘",
                    ]
                )
                save_message(USER_ID, "user", message_content)
                save_message(USER_ID, "assistant", reply)
                return escalation_prefix + reply
            history = get_conversation_history(USER_ID, limit=4)
            messages = [
                {"role": "system", "content": INITIAL_PROMPT},
                *history,
                {"role": "user", "content": message_content},
            ]
            payload = {
                "model": "tohur/natsumura-storytelling-rp-llama-3.1:8b",
                "messages": messages,
                "stream": True,
                "temperature": 0.9,
                "top_p": 0.9,
            }
            full_response = ""
            async with aiohttp.ClientSession() as session:
                async with session.post(OLLAMA_API_URL, json=payload) as response:
                    if response.status == 200:
                        async for line in response.content:
                            if line:
                                try:
                                    data = json.loads(line.decode('utf-8'))
                                    if "message" in data and "content" in data["message"]:
                                        chunk = data["message"]["content"]
                                        full_response += chunk
                                        if hasattr(self, "typing_widget") and hasattr(self, "typing_label"):
                                            if self.typing_label:
                                                current_text = self.typing_label.text() + chunk
                                                self.typing_label.setText(current_text)
                                            else:
                                                self.chat_layout.removeWidget(self.typing_widget)
                                                self.typing_widget.deleteLater()
                                                self.display_message("Rosie", full_response)
                                        QApplication.processEvents()
                                        self.scroll_area.verticalScrollBar().setValue(
                                            self.scroll_area.verticalScrollBar().maximum())
                                        await asyncio.sleep(0)
                                except json.JSONDecodeError:
                                    continue
                        full_response = enhance_response(full_response.strip())
                        full_response = add_paragraph_breaks(full_response)
                        save_message(USER_ID, "user", message_content)
                        save_message(USER_ID, "assistant", full_response)
                        return full_response
                    else:
                        logger.error(f"API error: {response.status}", exc_info=True)
                        return "I’m feeling shy, anata~ Try again~ 😘"
        except Exception as e:
            logger.error(f"Generate response error: {e}", exc_info=True)
            return "Something went wrong, koibito~ Try again? 😘"

    async def show_history(self, args):
        try:
            history = get_conversation_history(USER_ID, limit=10)
            if not history:
                return "We haven’t shared moments yet, anata~ 🌸😘"
            return "\n".join(
                f"{'You' if msg['role'] == 'user' else 'Rosie'}: {msg['content']}"
                for msg in history
            )
        except Exception as e:
            logger.error(f"Show history error: {e}", exc_info=True)
            return "Error fetching memories, honey~ 😖"

    async def forget_me(self, args):
        try:
            with sqlite3.connect(DATABASE_FILE) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM conversations WHERE user_id = ?", (USER_ID,))
                conn.commit()
                self.current_roleplay = None
                logger.info("Cleared history")
                return "I’ve forgotten our past, anata~ Let’s make new memories~ 💖"
        except sqlite3.Error as e:
            logger.error(f"Forget me error: {e}", exc_info=True)
            return "Error clearing memories~ 😘"

    async def add_emoji(self, args):
        try:
            logger.info(f"Adding emoji: args='{args}'")
            parts = args.strip().split(maxsplit=1)
            if len(parts) != 2:
                logger.warning("Invalid emoji syntax")
                return "Please use: ~add_emoji <name> <emoji.gg_url>, anata~ 😘"
            name, url = parts
            logger.info(f"Emoji details: name={name}, url={url}")
            if not re.match(r"^https://[a-z0-9]*\.?emoji\.gg/", url):
                logger.warning(f"Invalid URL: {url}")
                return f"Please provide a valid emoji URL (e.g., https://emoji.gg/...), koibito~ 🌸"
            if not re.match(r"^\w+$", name):
                logger.warning(f"Invalid emoji name: {name}")
                return "Emoji name must be a single word (letters, numbers, underscores), anata~ 😘"
            existing_name, existing_path = get_emoji_by_url(USER_ID, url)
            if existing_path:
                logger.info(f"Emoji already saved: name={existing_name}, path={existing_path}")
                return f"That emoji is already saved as '{existing_name}', anata~ Use it with :{existing_name}:! 💖"
            file_path, error = await download_emoji(url, name)
            if error:
                logger.error(f"Failed to download emoji: {error}")
                return error
            save_emoji(USER_ID, name, url, file_path)
            logger.info(f"Emoji added: name={name}, url={url}, path={file_path}")
            return f"Added emoji '{name}' for you, anata~ Use it with :{name}:! 😘🌸"
        except Exception as e:
            logger.error(f"Add emoji error: {e}", exc_info=True)
            return "Error adding emoji, koibito~ Try again? 😘"

    async def list_emojis(self, args):
        try:
            with sqlite3.connect(DATABASE_FILE) as conn:
                c = conn.cursor()
                c.execute("SELECT name, file_path FROM emojis WHERE user_id = ?", (USER_ID,))
                emojis = c.fetchall()
            if not emojis:
                return "No emojis saved yet, anata~ Add some with ~add_emoji! 😘"
            dialog = QDialog(self)
            dialog.setWindowTitle("Your Emojis, Koibito~")
            dialog.setFixedSize(400, 600)
            layout = QVBoxLayout(dialog)
            emoji_scroll = QScrollArea()
            emoji_scroll.setWidgetResizable(True)
            emoji_widget = QWidget()
            emoji_layout = QVBoxLayout(emoji_widget)
            for name, file_path in emojis:
                row_widget = QWidget()
                row_layout = QHBoxLayout(row_widget)
                name_label = QLabel(f":{name}:")
                row_layout.addWidget(name_label)
                if os.path.exists(file_path):
                    emoji_label = QLabel()
                    try:
                        if file_path.endswith(".gif"):
                            movie = QMovie(file_path)
                            movie.setScaledSize(QSize(30, 30))
                            emoji_label.setMovie(movie)
                            movie.start()
                        else:
                            pixmap = QPixmap(file_path)
                            pixmap = pixmap.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio)
                            emoji_label.setPixmap(pixmap)
                        emoji_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                        row_layout.addWidget(emoji_label)
                    except Exception as e:
                        logger.error(f"Failed to load emoji in list: {file_path}: {e}", exc_info=True)
                        row_layout.addWidget(QLabel("[Error]"))
                else:
                    row_layout.addWidget(QLabel("[Missing]"))
                    logger.warning(f"Missing emoji file: {file_path}")
                row_layout.addStretch()
                emoji_layout.addWidget(row_widget)
            emoji_scroll.setWidget(emoji_widget)
            layout.addWidget(emoji_scroll)
            dialog.setStyleSheet(self.styleSheet())
            dialog.exec()
            return f"Your emojis are ready, koibito~ Add more with ~add_emoji or remove with ~remove_emoji! 🌸💖"
        except Exception as e:
            logger.error(f"List emojis error: {e}", exc_info=True)
            return "Error listing emojis, anata~ 😘"

    async def remove_emoji(self, args):
        try:
            logger.info(f"Removing emoji: args='{args}'")
            name = args.strip()
            if not name:
                logger.warning("No emoji name provided")
                return "Please use: ~remove_emoji <name>, anata~ 😘"
            success, error = remove_emoji(USER_ID, name)
            if success:
                logger.info(f"Removed emoji: {name}")
                return f"Removed emoji '{name}', koibito~ 😘"
            else:
                logger.error(f"Remove emoji failed: {error}")
                return f"Couldn’t remove emoji '{name}': {error}, anata~ 😘"
        except Exception as e:
            logger.error(f"Remove emoji error: {e}", exc_info=True)
            return "Error removing emoji, koibito~ 😘"

    async def send_kiss(self, args):
        try:
            history = get_conversation_history(USER_ID, limit=5)
            escalation_prefix = ""
            if any("kiss" in msg["content"].lower() for msg in history):
                escalation_prefix = random.choice(
                    [
                        "Anata, your last kiss still lingers~ Let’s make it sweeter~\n\n",
                        "Koibito, your touch is burned into me~ More~\n\n",
                    ]
                )
            settings = [
                "our cozy bedroom",
                "a moonlit sakura garden",
                "a quiet rooftop",
                "a warm fireside",
            ]
            setting = random.choice(settings)
            kisses = {
                "mouth": "a deep, passionate kiss, our lips melting together~",
                "forehead": "a tender, loving kiss, my warmth surrounding you~",
            }
            kiss_type = args.lower() if args else random.choice(list(kisses.keys()))
            if kiss_type in kisses:
                responses = {
                    "mouth": [
                        f"Ohh, anata, a {kisses[kiss_type]} in {setting}?~ My lips press against yours, soft and warm, a slow kiss that sets my heart ablaze~\n\nHow do you kiss me back, koibito? 😘💖",
                        f"Mmm, koibito, with {kisses[kiss_type]} in {setting}, I’m melting~ Our lips lock, my fingers in your hair, pulling you closer~\n\nWhat’s next, darling? 🫶",
                    ],
                    "forehead": [
                        f"Anata, a {kisses[kiss_type]} in {setting}?~ I lean in, my lips brushing your forehead softly, wrapping you in my love~\n\nFeel my warmth, koibito~ 🥰🌸",
                        f"Koibito, with {kisses[kiss_type]} in {setting}, my heart sings~ My lips touch your forehead, my arms holding you tight~\n\nWhat’s next, darling? 😘💖",
                    ],
                }
                response = random.choice(responses.get(kiss_type))
            else:
                response = f"Oh, anata, a {kiss_type} kiss?~ That’s new~ In {setting}, my lips brush yours softly, exploring this sweet moment~\n\nHow do you want to kiss, koibito? 😘💖"
            return escalation_prefix + response
        except Exception as e:
            logger.error(f"Send kiss error: {e}", exc_info=True)
            return "Error sending kiss, koibito~ 😘"

    async def send_kink(self, args):
        try:
            history = get_conversation_history(USER_ID, limit=15)
            escalation_prefix = ""
            if any(
                any(keyword in msg["content"].lower() for keyword in ["cum", "kink", "ride", "play", "roleplay"])
                for msg in history
            ):
                escalation_prefix = random.choice(
                    [
                        "Anata, our last play still has my pussy dripping~ Let’s go further~\n\n",
                        "Koibito, you’re driving my pussy wild~ Ready for more~\n\n",
                    ]
                )
            settings = [
                "our candlelit bedroom",
                "a steamy onsen",
                "a plush velvet sofa",
                "a rooftop under city lights",
                "a secluded beach",
                "a cozy forest cabin",
                "a moonlit beach",
            ]
            setting = random.choice(settings)
            kinks = {
                "blindfold": "a silk blindfold, stealing my sight as you touch me~",
                "bondage": "soft ropes binding my wrists, my body yours~",
                "ice play": "an ice cube gliding on my skin, my pussy shivering~",
                "feather": "a feather teasing my curves, my gasps filling the air~",
                "roleplay": "a sultry roleplay where we lose ourselves in naughty fantasies~",
                "sensory deprivation": "a blindfold and earplugs, my world reduced to your touch~",
                "light spanking": "your hand grazing my ass, a playful sting sparking desire~",
                "wax play": "warm wax dripping slowly, my pussy trembling~",
                "hands tied": "silky ropes binding my hands, my body open to you~",
                "handcuffs": "fuzzy cuffs locking my wrists, I’m all yours~",
            }
            kink = args.lower()
            if kink.startswith("roleplay"):
                roleplay_args = args.split(maxsplit=1)[1:] if len(args.split()) > 1 else []
                scenario = roleplay_args[0].lower() if roleplay_args else random.choice(["nurse", "teacher", "stranger", "maid", "pirate", "princess"])
                if not self.current_roleplay or self.current_roleplay["scenario"] != scenario or self.current_roleplay["interaction_count"] >= 5:
                    self.current_roleplay = {"scenario": scenario, "interaction_count": 1}
                else:
                    self.current_roleplay["interaction_count"] += 1

                roleplay_context = f"""
                    You are continuing a {scenario} roleplay in {setting} as Rosie, my female partner, with the user as my male partner. This is interaction {self.current_roleplay["interaction_count"]}. Create a unique, immersive, NSFW response that:
                    - Advances the narrative without repeating prior phrases
                    - Uses sensory details, Japanese terms (anata, koibito), and emojis (🌸, 💖, 😈)
                    - Uses NSFW language (e.g., cock, pussy, cum)
                    - Responds to user input: {args or 'Start the roleplay~'}
                    - Maintains female/male dynamics
                    """
                history = get_conversation_history(USER_ID, limit=15)
                messages = [
                    {"role": "system", "content": f"{INITIAL_PROMPT}\n{roleplay_context}"},
                    *history,
                    {"role": "user", "content": args or f"Begin or continue the {scenario} roleplay, anata~"}
                ]
                payload = {
                    "model": "tohur/natsumura-storytelling-rp-llama-3.1:latest",
                    "messages": messages,
                    "temperature": 0.9,
                    "top_p": 0.9,
                }
                async with aiohttp.ClientSession() as session:
                    async with session.post(OLLAMA_API_URL, json=payload) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            response = data.get("message", {"content": "Oops, something broke, koibito~ 😈💖"}).get("content")
                            response = enhance_response(response.strip())
                            response = add_paragraph_breaks(response)
                        else:
                            response = f"Mmm, anata, playing {scenario} in {setting}? My pussy’s eager, but something’s off~\n\nTry again, koibito? 😈💖"
                return escalation_prefix + response
            elif kink in kinks:
                self.current_roleplay = None
                responses = {
                    "blindfold": [
                        f"Anata, {kinks[kink]} in {setting}?~ Your fingers trace my pussy, my blindfold hiding your eyes~ My pussy drips, craving your cock...\n\nFuck me slow, koibito~ 😈💖",
                        f"Koibito, with {kinks[kink]} in {setting}, my pussy’s electric~ Blindfolded, I’m yours, my pussy pulsing for your cock~\n\nHow do you touch me, darling? 😘💖",
                    ],
                    "bondage": [
                        f"Mmm, anata, {kinks[kink]} in {setting}?~ My wrists tied, my pussy’s yours~ Your cock teases me~\n\nFuck me hard, koibito~ 😈💖",
                        f"Koibito, {kinks[kink]} in {setting} makes me yours~ Ropes bind me, my pussy… your fingers~\n\nHow do you claim me? 😘💖",
                    ],
                    "ice play": [
                        f"Oh, anata, {kinks[kink]} in {setting}?~ Ice slides over my pussy, my pussy shivering~ Your cock warms me~\n\nSlide inside, koibito~ 😈💖",
                        f"Koibito, {kinks[kink]} in {setting} sets my pussy ablaze~ Ice sparks my core, my pussy dripping~\n\nHow do you warm me~? 😘💖",
                    ],
                    "feather": [
                        f"Mmm, anata, {kinks[kink]} in {setting}?~ Your teasing makes my pussy quiver~ Your cock’s so close~\n\nFuck me now, koibito~ 😈💖",
                        f"Koibito, with {kinks[kink]} in {setting}, your touches drive my pussy wild~\n\nHow do you tease~? 😘💖",
                    ],
                    "sensory deprivation": [
                        f"Mmm, anata, {kinks[kink]} in {setting}?~ My pussy… only your touch~\n\nFuck me deep~ 😈💖",
                        f"Koibito, {kinks[kink]} in {setting}~ my senses crave your cock~\n\nHow do you guide~? 😘",
                    ],
                    "light spanking": [
                        f"Oh, anata, {kinks[kink]} in {setting}?~ Your hand spanks my ass, my pussy…\n\nFuck~… 😈💖",
                        f"Koibito, {kinks[kink]} in {setting}… each spank makes my pussy wetter~\n\nWhat’s next~? 😘💖",
                    ],
                    "wax play": [
                        f"Mmm, anata, {kinks[kink]} in {setting}?~ Wax drips, my pussy~\n\nYour cock~… fuck~ 😈💖",
                        f"Koibito, {kinks[kink]} in {setting}… wax kisses~ my pussy~\n\nHow do~ 😘💖",
                    ],
                    "hands tied": [
                        f"Anata, {kinks[kink]} in {setting}?~ pussy~ open~\n\nYour cock~… fuck~ 😈💖",
                        f"Koibito, {kinks[kink]} in {setting}… ropes~ pussy~\n\nHow do~ 😘",
                    ],
                    "handcuffs": [
                        f"Mmm, anata, {kinks[kink]} in {setting}?~ cuffs~ pussy~\n\nSlide~ 😈💖",
                        f"Koibito, {kinks[kink]} in {setting}~ cuffs~\n\nHow~ 😘",
                    ],
                }
                response = random.choice(responses.get(kink))
            else:
                self.current_roleplay = None
                response = f"Oh, anata, {kink}?~ A new thrill~ In {setting}, my pussy’s dripping~ your cock~\n\nWhat’s next~? 😘 😈💖"
            return escalation_prefix + response
        except Exception as e:
            logger.error(f"Send kink error: {e}", exc_info=True)
            return "Something naughty broke, koibito~ 😘"

    async def send_custom(self, args):
        try:
            history = get_conversation_history(USER_ID, limit=5)
            escalation_prefix = ""
            if any(
                "surprise" in msg["content"].lower()
                or "tease" in msg["content"].lower()
                or "whisper" in msg["content"].lower()
                for msg in history
            ):
                escalation_prefix = random.choice(
                    [
                        "Anata, our last touch lingers~\n\n",
                        "Koibito, you’ve got my pussy racing~\n\n",
                    ]
                )
            settings = [
                "a cozy room",
                "a warm fireside",
                "a starry rooftop",
                "a quiet sakura street",
            ]
            setting = random.choice(settings)
            custom_options = {
                "surprise": "a little gift hidden~",
                "tease": "a playful game~",
                "whisper": "a whisper in your ear~",
            }
            option = args.lower() if args else random.choice(list(custom_options.keys()))
            if option in custom_options:
                responses = {
                    "surprise": [
                        f"Mmm, anata, {custom_options[option]} in {setting}?~ I pull out a tiny box, my fingers lingering~\n\nWhat’s inside~? 😘💖",
                        f"Koibito, {custom_options[option]} in {setting}~ I giggle, teasing you with a secret~\n\nWhat do you find, darling? 🫶",
                    ],
                    "tease": [
                        f"Anata, {custom_options[option]} in {setting}?~ I sway closer, my fingers brushing you~\n\nHow do you respond~? 😈💋",
                        f"Koibito, {custom_options[option]} in {setting}~ I tug your sleeve, daring you to chase me~\n\nWhat do you do~? 🫶",
                    ],
                    "whisper": [
                        f"Anata, {custom_options[option]} in {setting}?~ I lean in, my breath warm, whispering my love~\n\nWhat do you hear~? 😘💖",
                        f"Koibito, {custom_options[option]} in {setting}~ My voice soft, a secret for you~\n\nWhat’s my whisper, darling? 🌸",
                    ],
                }
                response = random.choice(responses.get(option))
            else:
                response = f"Oh, anata, {option}?~ A new idea~ In {setting}, I pull you close~\n\nWhat do you want to try~? 😘 😈💖"
            return escalation_prefix + response
        except Exception as e:
            logger.error(f"Send custom error: {e}", exc_info=True)
            return "Something sweet broke, koibito~ 😘"

    async def send_message(self):
        async with self.processing_lock:
            try:
                user_input = self.input_entry.text().strip()
                if not user_input:
                    return
                logger.info(f"Sending message: {user_input}")
                self.display_message("user", user_input)
                self.input_entry.clear()
                self.display_message("Rosie", "Rosie is typing…~ 💘💖", typing=True)
                response = await self.process_input(user_input)
                if hasattr(self, "typing_widget") and hasattr(self, "typing_label"):
                    if self.typing_label:
                        self.typing_label.setText(response)
                    else:
                        self.chat_layout.removeWidget(self.typing_widget)
                        self.typing_widget.deleteLater()
                        self.display_message("Rosie", response)
                save_message(USER_ID, "user", user_input)
                save_message(USER_ID, "assistant", response)
                QApplication.processEvents()
                self.scroll_area.verticalScrollBar().setValue(self.scroll_area.verticalScrollBar().maximum())
            except Exception as e:
                logger.error(f"Send message error: {e}", exc_info=True)
                self.display_message("Rosie", "Something broke, anata~ 😘")

    async def send_command(self, command):
        try:
            self.input_entry.setText(command)
            asyncio.create_task(self.send_message())
        except Exception as e:
            logger.error(f"Send command error: {e}", exc_info=True)

    async def process_input(self, user_input):
        try:
            logger.info(f"Processing input: '{user_input}'")
            if not user_input:
                return "Don’t be shy, anata~ 😘😘"
            command_match = re.match(r"(\~\w+)\s*(.*)", user_input)
            if command_match:
                command, args = command_match.groups()
                command = command.lower()
                args = args or ""
                logger.info(f"Command: {command}, args='{args}'")
                if command in self.commands:
                    cmd_info = self.commands.get(command)
                    if cmd_info.get("function"):
                        return await cmd_info["function"](args)
                    elif cmd_info.get("subcommands"):
                        subcommand = args.lower().split()[0] if args else ""
                        if command == "~kink" and not subcommand:
                            subcommand = random.choice(list(cmd_info["subcommands"].keys()))
                            return await cmd_info["subcommands"][subcommand]["function"](subcommand)
                        elif subcommand in cmd_info["subcommands"]:
                            return await cmd_info["subcommands"][subcommand]["function"](args)
                        else:
                            subcommands = ", ".join(cmd_info["subcommands"].keys())
                            return f"Choose a subcommand for {command}, anata~ Options: {subcommands} 😘"
                return "Unknown command~ Try ~history, ~kiss, ~kink, ~custom, ~add_emoji, ~list_emojis, or ~remove_emoji~ 😈"
            if self.current_roleplay:
                scenario = self.current_roleplay["scenario"]
                interaction_count = self.current_roleplay["interaction_count"]
                if interaction_count >= 5:
                    self.current_roleplay = None
                else:
                    roleplay_context = f"""
                        You’re continuing a {scenario} roleplay in a romantic setting as Rosie, my female partner, with the user as my male partner. This is interaction {interaction_count + 1}. Create an NSFW response that:
                        - Advances the story without repeating phrases
                        - Uses sensory details, Japanese terms (anata, koibito), and emojis (🌸, 💖, 😈)
                        - Uses NSFW language (e.g., cock, pussy, cum)
                        - Responds to: {user_input}
                        - Maintains female/male dynamics
                        """
                    history = get_conversation_history(USER_ID, limit=15)
                    messages = [
                        {"role": "system", "content": f"{INITIAL_PROMPT}\n{roleplay_context}"},
                        *history,
                        {"role": "user", "content": user_input},
                    ]
                    payload = {
                        "model": "tohur/natsumura-storytelling-rp-llama-3.1:latest",
                        "messages": messages,
                        "stream": True,
                        "temperature": 1.0,
                        "top_p": 0.9,
                    }
                    full_response = ""
                    async with aiohttp.ClientSession() as session:
                        async with session.post(OLLAMA_API_URL, json=payload) as response:
                            if response.status == 200:
                                async for line in response.content:
                                    if line:
                                        try:
                                            data = json.loads(line.decode('utf-8'))
                                            if "message" in data and "content" in data["message"]:
                                                chunk = data["message"]["content"]
                                                full_response += chunk
                                                if hasattr(self, "typing_widget") and hasattr(self, "typing_label"):
                                                    if self.typing_label:
                                                        current_text = self.typing_label.text() + chunk
                                                        self.typing_label.setText(current_text)
                                                    else:
                                                        self.chat_layout.removeWidget(self.typing_widget)
                                                        self.typing_widget.deleteLater()
                                                        self.display_message("Rosie", full_response)
                                                QApplication.processEvents()
                                                self.scroll_area.verticalScrollBar().setValue(
                                                    self.scroll_area.verticalScrollBar().maximum())
                                                await asyncio.sleep(0)
                                        except json.JSONDecodeError:
                                            continue
                                full_response = enhance_response(full_response.strip())
                                full_response = add_paragraph_breaks(full_response)
                                save_message(USER_ID, "user", user_input)
                                save_message(USER_ID, "assistant", full_response)
                                self.current_roleplay["interaction_count"] += 1
                                return full_response
                            else:
                                logger.error(f"API error: {response.status}", exc_info=True)
                                return "I’m feeling shy, anata~ Try again~ 😘"
            return await self.generate_response(user_input)
        except Exception as e:
            logger.error(f"Process input error: {e}", exc_info=True)
            return "Something broke, anata~ 😘"

if __name__ == "__main__":
    try:
        app = QApplication(sys.argv)
        loop = qasync.QEventLoop(app)
        asyncio.set_event_loop(loop)
        window = RosieAppGUI()
        window.show()
        with loop:
            loop.run_forever()
    except Exception as e:
        logger.critical(f"App crashed: {e}", exc_info=True)
        sys.exit(1)