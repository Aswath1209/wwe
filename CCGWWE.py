import logging
import random
import asyncio
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

import nest_asyncio
nest_asyncio.apply()

from motor.motor_asyncio import AsyncIOMotorClient

# --- Config ---
TOKEN = "8156231369:AAHDFvjD9Aur9y5QjB5YWzvCQp7bUdLuuEc"
MONGO_URL = "mongodb://mongo:GhpHMiZizYnvJfKIQKxoDbRyzBCpqEyC@mainline.proxy.rlwy.net:54853"
COINS_EMOJI = "🪙"

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# --- Database ---
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client.ccl_handcricket
users_collection = db.users

# --- Global Data ---
USERS = {}     # user_id -> user dict
MATCHES = {}   # chat_id -> match dict

# --- Allowed values ---
ALLOWED_BATSMAN_RUNS = {0, 1, 2, 3, 4, 6}
BOWLER_VARIATIONS_MAP = {
    "rs": 0,
    "bouncer": 1,
    "yorker": 2,
    "short": 3,
    "slower": 4,
    "knuckle": 6,
}
ALLOWED_BOWLER_VARIATIONS = set(BOWLER_VARIATIONS_MAP.keys())

GIFS = {
    0: "https://media.giphy.com/media/3o6Zt481isNVuQI1l6/giphy.gif",
    4: "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif",
    6: "https://media.giphy.com/media/26ufdipQqU2lhNA4g/giphy.gif",
    "half_century": "https://media.giphy.com/media/3o6Zt6ML6BklcajjsA/giphy.gif",
    "century": "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif",
}

def ensure_user(user):
    if user.id not in USERS:
        USERS[user.id] = {
            "user_id": user.id,
            "name": user.first_name or user.username or "Player",
            "username": user.username,
            "coins": 0,
            "wins": 0,
            "losses": 0,
            "ties": 0,
            "registered": False,
            "last_daily": None,
            "runs_scored": 0,
            "balls_faced": 0,
        }
    else:
        if user.username and USERS[user.id].get("username") != user.username:
            USERS[user.id]["username"] = user.username

async def save_user(user_id):
    try:
        user = USERS[user_id]
        await users_collection.update_one(
            {"user_id": user_id},
            {"$set": user},
            upsert=True,
        )
    except Exception as e:
        logger.error(f"Error saving user {user_id}: {e}", exc_info=True)

async def load_users():
    try:
        cursor = users_collection.find({})
        async for user in cursor:
            user_id = user.get("user_id") or user.get("_id")
            if not user_id:
                continue
            if "username" not in user:
                user["username"] = None
            USERS[user_id] = user
        logger.info("Users loaded successfully.")
    except Exception as e:
        logger.error(f"Error loading users: {e}", exc_info=True)

def mention_player(player):
    return f"[{player['name']}](tg://user?id={player['user_id']})"

def get_variation_name(variation_num):
    for k, v in BOWLER_VARIATIONS_MAP.items():
        if v == variation_num:
            return k.upper()
    return "UNKNOWN"

def find_player(identifier):
    identifier = identifier.strip()
    try:
        identifier_num = int(identifier)
        for u in USERS.values():
            if int(u["user_id"]) == identifier_num:
                return u
    except Exception:
        pass
    username = identifier.lstrip("@").lower()
    for u in USERS.values():
        if u.get("username") and u["username"].lower() == username:
            return u
    return None

# Core commands with confirmations
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        ensure_user(user)
        await save_user(user.id)
        await update.message.reply_text(
            "🏏 *Welcome to CCL HandCricket Bot!*\n\n"
            "1️⃣ Use /register to get 4000 🪙 and start playing\n"
            "2️⃣ Use /help for full instructions\n"
            "3️⃣ Hosts: Create matches with /cclgroup",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in /start: {e}", exc_info=True)
async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        ensure_user(user)
        u = USERS[user.id]
        u["username"] = user.username
        if u["registered"]:
            await save_user(user.id)
            await update.message.reply_text("✅ You have already registered.")
            return
        u["coins"] += 4000
        u["registered"] = True
        await save_user(user.id)
        await update.message.reply_text(f"✅ Registered! You received 4000 {COINS_EMOJI}.")
    except Exception as e:
        logger.error(f"Error in /register: {e}", exc_info=True)

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        ensure_user(user)
        u = USERS[user.id]
        text = (
            f"👤 *{u['name']}'s Profile*\n"
            f"ID: `{user.id}`\n"
            f"Username: @{u.get('username','')}\n"
            f"Purse: {u['coins']}{COINS_EMOJI}\n"
            f"Wins: {u['wins']}   Losses: {u['losses']}   Ties: {u['ties']}\n"
            f"Runs Scored: {u.get('runs_scored', 0)}   Balls Faced: {u.get('balls_faced', 0)}"
        )
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in /profile: {e}", exc_info=True)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text(
            "🏏 *HandCricket Commands*\n"
            "• /register - Register and get coins\n"
            "• /profile - View your stats\n"
            "• /cclgroup - Host: Start a new match\n"
            "• /add_A <username|user_id> - Add to Team A\n"
            "• /add_B <username|user_id> - Add to Team B\n"
            "• /remove_A <num> - Remove player from Team A\n"
            "• /remove_B <num> - Remove player from Team B\n"
            "• /teams - Show teams\n"
            "• /cap_A <num> - Assign Team A captain\n"
            "• /cap_B <num> - Assign Team B captain\n"
            "• /setovers <num> - Set overs (1-20)\n"
            "• /startmatch - Start match\n"
            "• /toss - Start toss\n"
            "• /bat <striker> <non_striker> - Assign batsmen\n"
            "• /bowl <bowler> - Assign bowler\n"
            "• /score - Show score\n"
            "• /bonus <A|B> <runs> - Add bonus\n"
            "• /penalty <A|B> <runs> - Deduct runs\n"
            "• /inningswap - Swap innings\n"
            "• /endmatch - End match\n"
            "• Players will be DM'd when it's their turn to bat/bowl!\n"
            "• All ball-by-ball results and confirmations will appear in the group chat.\n"
            "• Host can remove striker/non-striker at any time.\n",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in /help: {e}", exc_info=True)

async def cclgroup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user
        ensure_user(user)
        if chat.id in MATCHES:
            await update.message.reply_text(
                "⚠️ A match is already ongoing in this chat.\n"
                "Use /endmatch to finish the current match before starting a new one."
            )
            return

        MATCHES[chat.id] = {
            "host_id": user.id,
            "team_A": [],
            "team_B": [],
            "captain_A": None,
            "captain_B": None,
            "overs": None,
            "state": "setup",
            "batting_team": None,
            "bowling_team": None,
            "score": {"A": 0, "B": 0},
            "wickets": {"A": 0, "B": 0},
            "balls": 0,
            "striker": None,
            "non_striker": None,
            "current_bowler": None,
            "last_bowler": None,
            "innings": 1,
            "players_out": {"A": [], "B": []},
            "toss": {"state": None, "choice": None, "winner": None, "batbowl": None}
        }

        await update.message.reply_text(
            "🎮 *New Match Created!*\n"
            "1️⃣ Host: Add players with /add_A <username|user_id> or /add_B <username|user_id>\n"
            "2️⃣ Remove with /remove_A <num> or /remove_B <num>\n"
            "3️⃣ Assign captains with /cap_A <num> and /cap_B <num>\n"
            "4️⃣ Set overs with /setovers <num> (1-20)\n"
            "5️⃣ Start match with /startmatch\n"
            "6️⃣ Use /help for instructions.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in /cclgroup: {e}", exc_info=True)

async def add_A_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user
        args = context.args
        if chat.id not in MATCHES:
            await update.message.reply_text("No ongoing match in this chat. Use /cclgroup to create one.")
            return
        match = MATCHES[chat.id]
        if user.id != match["host_id"]:
            await update.message.reply_text("Only the host can add players.")
            return
        if not args:
            await update.message.reply_text("Usage: /add_A <username|user_id>")
            return
        player = find_player(args[0])
        if not player:
            await update.message.reply_text("Player not found or not registered.")
            return
        if player in match["team_A"] or player in match["team_B"]:
            await update.message.reply_text(f"{player['name']} (@{player.get('username','')}) is already in a team.")
            return
        match["team_A"].append(player)
        await update.message.reply_text(
            f"✅ Added {player['name']} (@{player.get('username','')}) to Team A.\n"
            f"Team A now has {len(match['team_A'])} players."
        )
    except Exception as e:
        logger.error(f"Error in /add_A: {e}", exc_info=True)

async def add_B_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user
        args = context.args
        if chat.id not in MATCHES:
            await update.message.reply_text("No ongoing match in this chat. Use /cclgroup to create one.")
            return
        match = MATCHES[chat.id]
        if user.id != match["host_id"]:
            await update.message.reply_text("Only the host can add players.")
            return
        if not args:
            await update.message.reply_text("Usage: /add_B <username|user_id>")
            return
        player = find_player(args[0])
        if not player:
            await update.message.reply_text("Player not found or not registered.")
            return
        if player in match["team_A"] or player in match["team_B"]:
            await update.message.reply_text(f"{player['name']} (@{player.get('username','')}) is already in a team.")
            return
        match["team_B"].append(player)
        await update.message.reply_text(
            f"✅ Added {player['name']} (@{player.get('username','')}) to Team B.\n"
            f"Team B now has {len(match['team_B'])} players."
        )
    except Exception as e:
        logger.error(f"Error in /add_B: {e}", exc_info=True)

async def remove_A_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user
        args = context.args
        if chat.id not in MATCHES:
            await update.message.reply_text("No ongoing match in this chat.")
            return
        match = MATCHES[chat.id]
        if user.id != match["host_id"]:
            await update.message.reply_text("Only the host can remove players.")
            return
        if not args or not args[0].isdigit():
            await update.message.reply_text("Usage: /remove_A <player_number>")
            return
        player_num = int(args[0])
        if player_num < 1 or player_num > len(match["team_A"]):
            await update.message.reply_text("Invalid player number for Team A.")
            return
        removed = match["team_A"].pop(player_num - 1)
        # Remove as striker/non-striker if needed
        if match.get("striker") and match["striker"]["user_id"] == removed["user_id"]:
            match["striker"] = None
        if match.get("non_striker") and match["non_striker"]["user_id"] == removed["user_id"]:
            match["non_striker"] = None
        await update.message.reply_text(
            f"❌ Removed {removed['name']} (@{removed.get('username','')}) from Team A."
        )
    except Exception as e:
        logger.error(f"Error in /remove_A: {e}", exc_info=True)

async def remove_B_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user
        args = context.args
        if chat.id not in MATCHES:
            await update.message.reply_text("No ongoing match in this chat.")
            return
        match = MATCHES[chat.id]
        if user.id != match["host_id"]:
            await update.message.reply_text("Only the host can remove players.")
            return
        if not args or not args[0].isdigit():
            await update.message.reply_text("Usage: /remove_B <player_number>")
            return
        player_num = int(args[0])
        if player_num < 1 or player_num > len(match["team_B"]):
            await update.message.reply_text("Invalid player number for Team B.")
            return
        removed = match["team_B"].pop(player_num - 1)
        if match.get("striker") and match["striker"]["user_id"] == removed["user_id"]:
            match["striker"] = None
        if match.get("non_striker") and match["non_striker"]["user_id"] == removed["user_id"]:
            match["non_striker"] = None
        await update.message.reply_text(
            f"❌ Removed {removed['name']} (@{removed.get('username','')}) from Team B."
        )
    except Exception as e:
        logger.error(f"Error in /remove_B: {e}", exc_info=True)
async def teams_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        if chat.id not in MATCHES:
            await update.message.reply_text("No ongoing match in this chat.")
            return
        match = MATCHES[chat.id]
        text = "*Team A:*\n"
        if match["team_A"]:
            for i, p in enumerate(match["team_A"], 1):
                text += f"{i}. {p['name']} (@{p.get('username','')})\n"
        else:
            text += "No players added.\n"
        text += "\n*Team B:*\n"
        if match["team_B"]:
            for i, p in enumerate(match["team_B"], 1):
                text += f"{i}. {p['name']} (@{p.get('username','')})\n"
        else:
            text += "No players added.\n"
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error in /teams: {e}", exc_info=True)

async def cap_A_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user
        args = context.args
        if chat.id not in MATCHES:
            await update.message.reply_text("No ongoing match in this chat.")
            return
        match = MATCHES[chat.id]
        if user.id != match["host_id"]:
            await update.message.reply_text("Only the host can assign captains.")
            return
        if not args or not args[0].isdigit():
            await update.message.reply_text("Usage: /cap_A <player_number>")
            return
        player_num = int(args[0])
        if player_num < 1 or player_num > len(match["team_A"]):
            await update.message.reply_text("Invalid player number for Team A.")
            return
        match["captain_A"] = match["team_A"][player_num - 1]
        await update.message.reply_text(
            f"🅰️ Captain for Team A: {match['captain_A']['name']} (@{match['captain_A'].get('username','')})"
        )
    except Exception as e:
        logger.error(f"Error in /cap_A: {e}", exc_info=True)

async def cap_B_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user
        args = context.args
        if chat.id not in MATCHES:
            await update.message.reply_text("No ongoing match in this chat.")
            return
        match = MATCHES[chat.id]
        if user.id != match["host_id"]:
            await update.message.reply_text("Only the host can assign captains.")
            return
        if not args or not args[0].isdigit():
            await update.message.reply_text("Usage: /cap_B <player_number>")
            return
        player_num = int(args[0])
        if player_num < 1 or player_num > len(match["team_B"]):
            await update.message.reply_text("Invalid player number for Team B.")
            return
        match["captain_B"] = match["team_B"][player_num - 1]
        await update.message.reply_text(
            f"🅱️ Captain for Team B: {match['captain_B']['name']} (@{match['captain_B'].get('username','')})"
        )
    except Exception as e:
        logger.error(f"Error in /cap_B: {e}", exc_info=True)

async def setovers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user
        args = context.args
        if chat.id not in MATCHES:
            await update.message.reply_text("No ongoing match in this chat.")
            return
        match = MATCHES[chat.id]
        if user.id != match["host_id"]:
            await update.message.reply_text("Only the host can set overs.")
            return
        if not args or not args[0].isdigit():
            await update.message.reply_text("Usage: /setovers <number_of_overs>")
            return
        overs = int(args[0])
        if overs < 1 or overs > 20:
            await update.message.reply_text("Overs must be between 1 and 20.")
            return
        match["overs"] = overs
        await update.message.reply_text(
            f"⏳ Overs set to {overs}. Host: When ready, start the match with /startmatch."
        )
    except Exception as e:
        logger.error(f"Error in /setovers: {e}", exc_info=True)

async def startmatch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user
        if chat.id not in MATCHES:
            await update.message.reply_text("No ongoing match in this chat.")
            return
        match = MATCHES[chat.id]
        if user.id != match["host_id"]:
            await update.message.reply_text("Only the host can start the match.")
            return
        if len(match["team_A"]) < 1 or len(match["team_B"]) < 1:
            await update.message.reply_text("Both teams must have at least 1 player.")
            return
        if match["captain_A"] is None or match["captain_B"] is None:
            await update.message.reply_text("Captains must be assigned for both teams.")
            return
        if match["overs"] is None:
            await update.message.reply_text("Overs must be set before starting the match.")
            return
        match["state"] = "toss"
        await update.message.reply_text(
            "✅ Match setup complete!\nHost: Use /toss to start the toss."
        )
    except Exception as e:
        logger.error(f"Error in /startmatch: {e}", exc_info=True)

async def toss_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user
        if chat.id not in MATCHES:
            await update.message.reply_text("No ongoing match.")
            return
        match = MATCHES[chat.id]
        if user.id != match["host_id"]:
            await update.message.reply_text("Only the host can start the toss.")
            return
        if not match["captain_A"] or not match["captain_B"]:
            await update.message.reply_text("Assign both captains before toss.")
            return
        match["toss"]["state"] = "waiting_heads_tails"
        capA = match["captain_A"]
        keyboard = [
            [
                InlineKeyboardButton("Heads", callback_data="toss_heads"),
                InlineKeyboardButton("Tails", callback_data="toss_tails"),
            ]
        ]
        await update.message.reply_text(
            f"🪙 Toss time!\n{mention_player(capA)} (Team A captain), choose Heads or Tails:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in /toss: {e}", exc_info=True)
import time

async def toss_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        chat_id = query.message.chat.id
        user_id = query.from_user.id
        if chat_id not in MATCHES:
            await query.answer("No ongoing match.")
            return
        match = MATCHES[chat_id]
        if match["toss"]["state"] != "waiting_heads_tails":
            await query.answer("Toss is not active.")
            return
        capA = match["captain_A"]
        capB = match["captain_B"]
        if user_id != capA["user_id"]:
            await query.answer("Only Team A captain can pick heads or tails.")
            return
        choice = "Heads" if query.data == "toss_heads" else "Tails"
        match["toss"]["choice"] = choice
        match["toss"]["state"] = "toss_result"
        toss_result = random.choice(["Heads", "Tails"])
        winner = capA if toss_result == choice else capB
        match["toss"]["winner"] = winner
        match["toss"]["toss_result"] = toss_result
        await query.edit_message_text(
            f"🪙 Toss result: *{toss_result}*!\n\n"
            f"{mention_player(winner)} won the toss.",
            parse_mode="Markdown"
        )
        keyboard = [
            [
                InlineKeyboardButton("Bat", callback_data="toss_bat"),
                InlineKeyboardButton("Bowl", callback_data="toss_bowl"),
            ]
        ]
        match["toss"]["state"] = "waiting_batbowl"
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"{mention_player(winner)}, choose Bat or Bowl:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in toss callback: {e}", exc_info=True)

async def toss_batbowl_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        chat_id = query.message.chat.id
        user_id = query.from_user.id
        if chat_id not in MATCHES:
            await query.answer("No ongoing match.")
            return
        match = MATCHES[chat_id]
        if match["toss"]["state"] != "waiting_batbowl":
            await query.answer("Not time to pick bat/bowl.")
            return
        winner = match["toss"]["winner"]
        if user_id != winner["user_id"]:
            await query.answer("Only toss winner can pick Bat/Bowl.")
            return
        pick = "bat" if query.data == "toss_bat" else "bowl"
        match["toss"]["batbowl"] = pick
        if pick == "bat":
            match["batting_team"] = "A" if winner == match["captain_A"] else "B"
            match["bowling_team"] = "B" if winner == match["captain_A"] else "A"
        else:
            match["bowling_team"] = "A" if winner == match["captain_A"] else "B"
            match["batting_team"] = "B" if winner == match["captain_A"] else "A"
        match["toss"]["state"] = None
        await query.edit_message_text(
            f"{mention_player(winner)} chose to *{pick.upper()}* first!\n\n"
            f"Batting: Team {match['batting_team']}\nBowling: Team {match['bowling_team']}\n\n"
            f"Host: Assign batsmen with /bat <striker_num> <non_striker_num> and bowler with /bowl <bowler_num>.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in toss bat/bowl callback: {e}", exc_info=True)

def run_commentary(runs):
    if runs == 0:
        return random.choice([
            "Dot ball! 🦾 The pressure is building.",
            "No run. Tight bowling! 🧤",
            "Beaten! No run. 😮",
            "Defended solidly. No run. 🏏"
        ])
    elif runs == 1:
        return random.choice([
            "Just a single. Good running. 🚀",
            "Quick single taken! 🏃‍♂️",
            "Easy run, keeps the strike ticking. 🔄"
        ])
    elif runs == 2:
        return random.choice([
            "They come back for two! 🏃‍♂️🏃‍♂️",
            "Great running between the wickets! 👏",
            "Two runs, nicely placed. 👌"
        ])
    elif runs == 3:
        return random.choice([
            "Three runs! That's some hustle. 💨",
            "Excellent running! They get three. 🏃‍♂️🏃‍♂️🏃‍♂️",
            "Good placement, three runs. 🎯"
        ])
    elif runs == 4:
        return random.choice([
            "FOUR! Cracking shot to the boundary. 🔥",
            "That's a boundary! Beautifully played. 🏏",
            "Four runs, the crowd loves it! 👏"
        ])
    elif runs == 6:
        return random.choice([
            "SIX! That's out of the park! 💥",
            "What a hit! That's a maximum. 💣",
            "Huge six! The bowler under pressure. 😱"
        ])
    else:
        return ""

async def bat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (same as before, assign striker/non-striker, send confirmation in group) ...
    # Not repeated for brevity, see previous part.

async def bowl_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (same as before, assign bowler, send confirmation in group) ...
    # Not repeated for brevity, see previous part.

async def process_ball(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        chat_id = update.effective_chat.id
        text = update.message.text.strip().lower()
        match = None
        role = None
        for cid, m in MATCHES.items():
            if m.get("striker") and m["striker"]["user_id"] == user.id:
                match = m
                role = "batsman"
                break
            if m.get("current_bowler") and m["current_bowler"]["user_id"] == user.id:
                match = m
                role = "bowler"
                break
        if not match:
            return
        group_chat_id = chat_id if chat_id < 0 else None
        if role == "batsman":
            if not text.isdigit() or int(text) not in ALLOWED_BATSMAN_RUNS:
                await update.message.reply_text("Invalid runs. Please send one of: 0, 1, 2, 3, 4, 6")
                return
            match["pending_batsman_run"] = int(text)
            if group_chat_id:
                await context.bot.send_message(group_chat_id, f"✅ {mention_player(match['striker'])} sent their runs!", parse_mode="Markdown")
            await update.message.reply_text("✅ Your run was received. Waiting for bowler.")
        else:
            if text not in ALLOWED_BOWLER_VARIATIONS:
                await update.message.reply_text("Invalid bowling variation. Send one of: rs, bouncer, yorker, short, slower, knuckle")
                return
            match["pending_bowler_variation"] = BOWLER_VARIATIONS_MAP[text]
            if group_chat_id:
                await context.bot.send_message(group_chat_id, f"✅ {mention_player(match['current_bowler'])} sent their variation!", parse_mode="Markdown")
            await update.message.reply_text("✅ Your variation was received. Waiting for batsman.")
        if "pending_batsman_run" in match and "pending_bowler_variation" in match:
            await handle_ball_result(context, match, group_chat_id)
    except Exception as e:
        logger.error(f"Error in ball processing: {e}", exc_info=True)

async def handle_ball_result(context, match, group_chat_id):
    try:
        runs = match.pop("pending_batsman_run")
        variation = match.pop("pending_bowler_variation")
        striker = match["striker"]
        non_striker = match["non_striker"]
        bowler = match["current_bowler"]
        batting_team_key = match["batting_team"]
        match["balls"] += 1
        match["balls_in_over"] = match.get("balls_in_over", 0) + 1
        over_num = (match["balls"] - 1) // 6 + 1
        ball_num = (match["balls"] - 1) % 6 + 1

        # Announce ball in group chat with delays
        await context.bot.send_message(
            group_chat_id,
            f"🏏 Over {over_num}, Ball {ball_num}"
        )
        await asyncio.sleep(3)
        await context.bot.send_message(
            group_chat_id,
            f"{striker['name']} vs {bowler['name']}"
        )
        await asyncio.sleep(2)
        await context.bot.send_message(
            group_chat_id,
            f"{bowler['name']} bowls a {get_variation_name(variation)}!"
        )
        await asyncio.sleep(4)
        # Wicket check
        if runs == 0 and variation == 0:
            match["wickets"][batting_team_key] += 1
            match["players_out"][batting_team_key].append(striker)
            striker["balls_faced"] = striker.get("balls_faced", 0) + 1
            await context.bot.send_message(
                group_chat_id,
                f"💥 WICKET! {mention_player(striker)} is OUT! Bowled by {mention_player(bowler)} (RS Ball)",
                parse_mode="Markdown"
            )
            match["striker"] = None
            return
        match["score"][batting_team_key] += runs
        striker["runs_scored"] = striker.get("runs_scored", 0) + runs
        striker["balls_faced"] = striker.get("balls_faced", 0) + 1
        commentary = run_commentary(runs)
        msg = f"{striker['name']} {commentary}"
        gif_url = GIFS.get(runs)
        if gif_url:
            await context.bot.send_animation(group_chat_id, gif_url, caption=msg)
        else:
            await context.bot.send_message(group_chat_id, msg)
        # Swap strike if needed
        if runs % 2 == 1:
            match["striker"], match["non_striker"] = match["non_striker"], match["striker"]
        # Over end
        if match["balls_in_over"] == 6:
            if runs % 2 == 0:
                match["striker"], match["non_striker"] = match["non_striker"], match["striker"]
            match["last_bowler"] = bowler
            match["current_bowler"] = None
            match["balls_in_over"] = 0
            await context.bot.send_message(
                group_chat_id,
                f"🛑 Over completed. Host: Assign next bowler with /bowl <bowler_num>."
            )
        # Score update
        await context.bot.send_message(
            group_chat_id,
            f"Score: {match['score'][batting_team_key]}/{match['wickets'][batting_team_key]} in {match['balls']//6}.{match['balls']%6} overs."
        )
        # End of innings checks
        team_size = len(match["team_A"]) if batting_team_key == "A" else len(match["team_B"])
        if match["wickets"][batting_team_key] >= team_size:
            await context.bot.send_message(group_chat_id, "All out! Host: Use /inningswap to swap innings.")
        elif match["balls"] >= match["overs"] * 6:
            await context.bot.send_message(group_chat_id, "Overs completed! Host: Use /inningswap to swap innings.")
    except Exception as e:
        logger.error(f"Error in handle_ball_result: {e}", exc_info=True)

# Admin commands and result (bonus, penalty, inningswap, endmatch) are as in previous part, with group chat confirmations.
async def bonus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user
        args = context.args
        if chat.id not in MATCHES:
            await update.message.reply_text("No ongoing match in this chat.")
            return
        match = MATCHES[chat.id]
        if user.id != match["host_id"]:
            await update.message.reply_text("Only the host can add bonus runs.")
            return
        if len(args) != 2 or args[0].upper() not in ("A", "B") or not args[1].isdigit():
            await update.message.reply_text("Usage: /bonus <A|B> <runs>")
            return
        team = args[0].upper()
        runs = int(args[1])
        match["score"][team] += runs
        await update.message.reply_text(f"✅ Added {runs} bonus runs to Team {team}.")
    except Exception as e:
        logger.error(f"Error in /bonus: {e}", exc_info=True)

async def penalty_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user
        args = context.args
        if chat.id not in MATCHES:
            await update.message.reply_text("No ongoing match in this chat.")
            return
        match = MATCHES[chat.id]
        if user.id != match["host_id"]:
            await update.message.reply_text("Only the host can deduct penalty runs.")
            return
        if len(args) != 2 or args[0].upper() not in ("A", "B") or not args[1].isdigit():
            await update.message.reply_text("Usage: /penalty <A|B> <runs>")
            return
        team = args[0].upper()
        runs = int(args[1])
        match["score"][team] = max(0, match["score"][team] - runs)
        await update.message.reply_text(f"✅ Deducted {runs} penalty runs from Team {team}.")
    except Exception as e:
        logger.error(f"Error in /penalty: {e}", exc_info=True)

async def inningswap_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user
        if chat.id not in MATCHES:
            await update.message.reply_text("No ongoing match in this chat.")
            return
        match = MATCHES[chat.id]
        if user.id != match["host_id"]:
            await update.message.reply_text("Only the host can swap innings.")
            return
        keyboard = [
            [
                InlineKeyboardButton("Confirm", callback_data="inningswap_confirm"),
                InlineKeyboardButton("Cancel", callback_data="inningswap_cancel"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Are you sure you want to swap innings?", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error in /inningswap: {e}", exc_info=True)

async def inningswap_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        chat_id = query.message.chat.id
        if chat_id not in MATCHES:
            await query.edit_message_text("No ongoing match in this chat.")
            return
        match = MATCHES[chat_id]
        user_id = query.from_user.id
        if user_id != match["host_id"]:
            await query.edit_message_text("Only the host can confirm innings swap.")
            return
        if query.data == "inningswap_confirm":
            if match["innings"] == 1:
                match["innings"] = 2
                match["balls"] = 0
                match["balls_in_over"] = 0
                match["wickets"][match["bowling_team"]] = 0
                match["score"][match["bowling_team"]] = 0
                match["players_out"][match["bowling_team"]] = []
                match["batting_team"], match["bowling_team"] = match["bowling_team"], match["batting_team"]
                match["striker"] = None
                match["non_striker"] = None
                match["current_bowler"] = None
                match["last_bowler"] = None
                await query.edit_message_text("Innings swapped! Host, assign new batsmen with /bat and bowler with /bowl.")
            else:
                await query.edit_message_text("This is the second innings. Use /endmatch to finish the match.")
        else:
            await query.edit_message_text("Innings swap cancelled.")
    except Exception as e:
        logger.error(f"Error in inningswap callback: {e}", exc_info=True)

async def endmatch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user
        if chat.id not in MATCHES:
            await update.message.reply_text("No ongoing match in this chat.")
            return
        match = MATCHES[chat.id]
        if user.id != match["host_id"]:
            await update.message.reply_text("Only the host can end the match.")
            return
        score_A = match["score"]["A"]
        score_B = match["score"]["B"]
        wa = match['wickets']['A']
        wb = match['wickets']['B']
        if score_A > score_B:
            result = f"🏆 Team A won by {score_A - score_B} runs!"
        elif score_B > score_A:
            wickets_left = len(match["team_B"]) - wb
            result = f"🏆 Team B won by {wickets_left} wickets!"
        else:
            result = "🤝 The match is a tie!"
        await update.message.reply_text(
            f"🏁 Match ended!\n\n"
            f"Final Score:\nTeam A: {score_A}/{wa}\nTeam B: {score_B}/{wb}\n\nResult: {result}"
        )
        del MATCHES[chat.id]
    except Exception as e:
        logger.error(f"Error in /endmatch: {e}", exc_info=True)
        await update.message.reply_text("An error occurred while ending the match.")

def register_handlers(application):
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("register", register))
    application.add_handler(CommandHandler("profile", profile))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("cclgroup", cclgroup_command))
    application.add_handler(CommandHandler("add_A", add_A_command))
    application.add_handler(CommandHandler("add_B", add_B_command))
    application.add_handler(CommandHandler("remove_A", remove_A_command))
    application.add_handler(CommandHandler("remove_B", remove_B_command))
    application.add_handler(CommandHandler("teams", teams_command))
    application.add_handler(CommandHandler("cap_A", cap_A_command))
    application.add_handler(CommandHandler("cap_B", cap_B_command))
    application.add_handler(CommandHandler("setovers", setovers_command))
    application.add_handler(CommandHandler("startmatch", startmatch_command))
    application.add_handler(CommandHandler("toss", toss_command))
    application.add_handler(CommandHandler("bat", bat_command))
    application.add_handler(CommandHandler("bowl", bowl_command))
    application.add_handler(CommandHandler("score", score_command))
    application.add_handler(CommandHandler("bonus", bonus_command))
    application.add_handler(CommandHandler("penalty", penalty_command))
    application.add_handler(CommandHandler("inningswap", inningswap_command))
    application.add_handler(CommandHandler("endmatch", endmatch_command))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), process_ball))
    application.add_handler(CallbackQueryHandler(toss_callback, pattern="^toss_(heads|tails)$"))
    application.add_handler(CallbackQueryHandler(toss_batbowl_callback, pattern="^toss_(bat|bowl)$"))
    application.add_handler(CallbackQueryHandler(inningswap_callback, pattern="^inningswap_"))

async def on_startup(application):
    try:
        await load_users()
        logger.info("Bot started and users loaded.")
    except Exception as e:
        logger.error(f"Error during startup: {e}", exc_info=True)

async def main():
    application = ApplicationBuilder().token(TOKEN).build()
    register_handlers(application)
    application.post_init = on_startup
    logger.info("Starting bot...")
    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
                
