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
    0: "https://media.giphy.com/media/3o6Zt481isNVuQI1l6/giphy.gif",  # dot ball
    4: "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif",  # four runs
    6: "https://media.giphy.com/media/26ufdipQqU2lhNA4g/giphy.gif",  # six runs
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

# Core commands

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        ensure_user(user)
        await save_user(user.id)
        await update.message.reply_text(
            "🏏 *Welcome to CCL HandCricket Bot!*\n\n"
            "1️⃣ Use /register to get 4000 🪙 and start playing.\n\n"
            "2️⃣ Use /help for step-by-step instructions.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in /start: {e}", exc_info=True)

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        ensure_user(user)
        u = USERS[user.id]
        u["username"] = user.username  # Always update username on register
        if u["registered"]:
            await save_user(user.id)
            await update.message.reply_text("You have already registered.")
            return
        u["coins"] += 4000
        u["registered"] = True
        await save_user(user.id)
        await update.message.reply_text(f"Registered! You received 4000 {COINS_EMOJI}.")
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
            "🏏 *How to Play CCL HandCricket*\n\n"
            "1️⃣ /register - Register and get starting coins.\n"
            "2️⃣ /profile - View your stats and coins.\n"
            "3️⃣ /cclgroup - Host: start a new match.\n"
            "4️⃣ /add_A <username|user_id> - Add player to Team A.\n"
            "5️⃣ /add_B <username|user_id> - Add player to Team B.\n"
            "6️⃣ /teams - Show teams and player numbers.\n"
            "7️⃣ /cap_A <num> - Assign Team A captain.\n"
            "8️⃣ /cap_B <num> - Assign Team B captain.\n"
            "9️⃣ /setovers <num> - Set overs (1-20).\n"
            "🔟 /startmatch - Start the match.\n"
            "1️⃣1️⃣ /toss - Start the toss.\n"
            "1️⃣2️⃣ /bat <striker_num> <non_striker_num> - Assign batsmen.\n"
            "1️⃣3️⃣ /bowl <bowler_num> - Assign bowler.\n"
            "1️⃣4️⃣ Send runs (0,1,2,3,4,6) as batsman.\n"
            "1️⃣5️⃣ Send variation (rs, bouncer, yorker, short, slower, knuckle) as bowler.\n"
            "1️⃣6️⃣ /score - Show current score.\n"
            "1️⃣7️⃣ /bonus <A|B> <runs> - Add bonus runs.\n"
            "1️⃣8️⃣ /penalty <A|B> <runs> - Deduct penalty runs.\n"
            "1️⃣9️⃣ /inningswap - Swap innings.\n"
            "2️⃣0️⃣ /endmatch - End match and show result.\n",
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
                "A match is already ongoing in this chat.\n"
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
            "🎮 *New Match Created!*\n\n"
            "1️⃣ Host: Add players with /add_A <username|user_id> or /add_B <username|user_id>\n"
            "2️⃣ Assign captains with /cap_A <num> and /cap_B <num>\n"
            "3️⃣ Set overs with /setovers <num> (1-20)\n"
            "4️⃣ Start match with /startmatch\n"
            "5️⃣ Use /help for instructions.",
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
            f"Added {player['name']} (@{player.get('username','')}) to Team A.\n"
            f"Team A now has {len(match['team_A'])} players.\n"
            "Assign captain with /cap_A <player_number> or continue adding."
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
            f"Added {player['name']} (@{player.get('username','')}) to Team B.\n"
            f"Team B now has {len(match['team_B'])} players.\n"
            "Assign captain with /cap_B <player_number> or continue adding."
        )
    except Exception as e:
        logger.error(f"Error in /add_B: {e}", exc_info=True)

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
            f"Captain for Team A set to {match['captain_A']['name']} (@{match['captain_A'].get('username','')}).\n"
            "Assign Team B captain with /cap_B <player_number>."
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
            f"Captain for Team B set to {match['captain_B']['name']} (@{match['captain_B'].get('username','')}).\n"
            "Set overs with /setovers <number>."
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
            f"Overs set to {overs}.\nHost: When ready, start the match with /startmatch."
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
            "✅ Match setup complete!\n\nHost: Use /toss to start the toss."
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
            f"Toss time!\n\n{mention_player(capA)} (Team A captain), choose Heads or Tails:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in /toss: {e}", exc_info=True)

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
            f"Toss result: *{toss_result}*!\n\n"
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
async def bat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user
        args = context.args

        if chat.id not in MATCHES:
            await update.message.reply_text("No ongoing match in this chat.")
            return
        match = MATCHES[chat.id]
        if user.id != match["host_id"]:
            await update.message.reply_text("Only the host can assign batsmen.")
            return

        if len(args) != 2 or not all(arg.isdigit() for arg in args):
            await update.message.reply_text("Usage: /bat <striker_num> <non_striker_num>")
            return

        if not match.get("batting_team"):
            await update.message.reply_text("Host: Complete the toss first!")
            return

        striker_num, non_striker_num = map(int, args)
        batting_team_key = match["batting_team"]
        team = match["team_A"] if batting_team_key == "A" else match["team_B"]

        if not (1 <= striker_num <= len(team)) or not (1 <= non_striker_num <= len(team)):
            await update.message.reply_text("Player numbers out of range.")
            return

        if striker_num == non_striker_num:
            await update.message.reply_text("Striker and non-striker cannot be the same player.")
            return

        if team[striker_num - 1] in match["players_out"][batting_team_key]:
            await update.message.reply_text(f"{team[striker_num - 1]['name']} is out. Choose another striker.")
            return
        if team[non_striker_num - 1] in match["players_out"][batting_team_key]:
            await update.message.reply_text(f"{team[non_striker_num - 1]['name']} is out. Choose another non-striker.")
            return

        match["striker"] = team[striker_num - 1]
        match["non_striker"] = team[non_striker_num - 1]

        await update.message.reply_text(
            f"Batsmen assigned:\n"
            f"Striker: {mention_player(match['striker'])}\n"
            f"Non-Striker: {mention_player(match['non_striker'])}\n"
            f"Host: Assign bowler with /bowl <bowler_num>.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in /bat: {e}", exc_info=True)

async def bowl_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user
        args = context.args

        if chat.id not in MATCHES:
            await update.message.reply_text("No ongoing match in this chat.")
            return
        match = MATCHES[chat.id]
        if user.id != match["host_id"]:
            await update.message.reply_text("Only the host can assign the bowler.")
            return

        if len(args) != 1 or not args[0].isdigit():
            await update.message.reply_text("Usage: /bowl <bowler_num>")
            return

        if not match.get("bowling_team"):
            await update.message.reply_text("Host: Complete the toss first!")
            return

        bowling_team_key = match["bowling_team"]
        bowling_team = match["team_A"] if bowling_team_key == "A" else match["team_B"]

        bowler_num = int(args[0])
        if not (1 <= bowler_num <= len(bowling_team)):
            await update.message.reply_text("Bowler number out of range.")
            return

        bowler = bowling_team[bowler_num - 1]
        if match.get("last_bowler") and bowler["user_id"] == match["last_bowler"]["user_id"]:
            await update.message.reply_text("This bowler bowled the last over. Choose a different bowler.")
            return

        match["current_bowler"] = bowler
        match["balls_in_over"] = 0
        await update.message.reply_text(
            f"Bowler for this over: {mention_player(bowler)}\n"
            f"Striker: {mention_player(match['striker'])}\n"
            f"Non-Striker: {mention_player(match['non_striker'])}\n"
            f"Batsman, send your run (0,1,2,3,4,6). Bowler, send your variation (rs, bouncer, yorker, short, slower, knuckle).",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in /bowl: {e}", exc_info=True)

async def process_ball(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        text = update.message.text.strip().lower()

        match = None
        role = None
        for m in MATCHES.values():
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

        if role == "batsman":
            if not text.isdigit() or int(text) not in ALLOWED_BATSMAN_RUNS:
                await update.message.reply_text("Invalid runs. Please send one of: 0, 1, 2, 3, 4, 6")
                return
            match["pending_batsman_run"] = int(text)
            await update.message.reply_text(f"Runs received: {text}. Waiting for bowler's variation.")
        else:
            if text not in ALLOWED_BOWLER_VARIATIONS:
                await update.message.reply_text("Invalid bowling variation. Send one of: rs, bouncer, yorker, short, slower, knuckle")
                return
            match["pending_bowler_variation"] = BOWLER_VARIATIONS_MAP[text]
            await update.message.reply_text(f"Bowling variation received: {text}. Waiting for batsman's runs.")

        if "pending_batsman_run" in match and "pending_bowler_variation" in match:
            await handle_ball_result(update, context, match)
    except Exception as e:
        logger.error(f"Error in ball processing: {e}", exc_info=True)

async def handle_ball_result(update, context, match):
    try:
        runs = match.pop("pending_batsman_run")
        variation = match.pop("pending_bowler_variation")
        striker = match["striker"]
        non_striker = match["non_striker"]
        bowler = match["current_bowler"]
        batting_team_key = match["batting_team"]

        if runs == 0 and variation == 0:
            match["wickets"][batting_team_key] += 1
            match["players_out"][batting_team_key].append(striker)
            striker["balls_faced"] = striker.get("balls_faced", 0) + 1
            match["balls"] += 1
            match["balls_in_over"] = match.get("balls_in_over", 0) + 1
            await update.message.reply_text(
                f"WICKET! {mention_player(striker)} is OUT! {mention_player(bowler)} bowls a RS.\n"
                f"Host: Assign new batsman with /bat <striker_num> <non_striker_num>.",
                parse_mode="Markdown"
            )
            match["striker"] = None
            return

        match["score"][batting_team_key] += runs
        striker["runs_scored"] = striker.get("runs_scored", 0) + runs
        striker["balls_faced"] = striker.get("balls_faced", 0) + 1
        match["balls"] += 1
        match["balls_in_over"] = match.get("balls_in_over", 0) + 1

        variation_name = get_variation_name(variation)
        commentary = (
            f"{mention_player(bowler)} bowls a {variation_name}.\n"
            f"{mention_player(striker)} scores {runs} run{'s' if runs != 1 else ''}."
        )

        if striker["runs_scored"] == 50:
            commentary += " 🎉 That's a superb half-century! 🎉"
        if striker["runs_scored"] == 100:
            commentary += " 🎉🎉 Century for the batsman! 🎉🎉"

        gif_url = GIFS.get(runs)
        if gif_url:
            await update.message.reply_animation(gif_url, caption=commentary, parse_mode="Markdown")
        else:
            await update.message.reply_text(commentary, parse_mode="Markdown")

        over_balls = match["balls_in_over"]
        if runs % 2 == 1:
            match["striker"], match["non_striker"] = match["non_striker"], match["striker"]

        if over_balls == 6:
            if runs % 2 == 0:
                match["striker"], match["non_striker"] = match["non_striker"], match["striker"]
            match["last_bowler"] = bowler
            match["current_bowler"] = None
            match["balls_in_over"] = 0
            await update.message.reply_text(
                f"Over completed. Host: Assign next bowler with /bowl <bowler_num>.\n"
                f"Current striker: {mention_player(match['striker'])}",
                parse_mode="Markdown"
            )

        await update.message.reply_text(
            f"Score: {match['score'][batting_team_key]}/{match['wickets'][batting_team_key]} in {match['balls']//6}.{match['balls']%6} overs.",
            parse_mode="Markdown"
        )

        team_size = len(match["team_A"]) if batting_team_key == "A" else len(match["team_B"])
        if match["wickets"][batting_team_key] >= team_size:
            await update.message.reply_text("All out! Host: Use /inningswap to swap innings.")
        elif match["balls"] >= match["overs"] * 6:
            await update.message.reply_text("Overs completed! Host: Use /inningswap to swap innings.")
    except Exception as e:
        logger.error(f"Error in handle_ball_result: {e}", exc_info=True)

async def score_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        if chat.id not in MATCHES:
            await update.message.reply_text("No ongoing match in this chat.")
            return
        match = MATCHES[chat.id]
        a = match['score']['A']
        b = match['score']['B']
        wa = match['wickets']['A']
        wb = match['wickets']['B']
        balls = match['balls']
        overs = match['overs']
        batting = match.get("batting_team", "A")
        await update.message.reply_text(
            f"Team A: {a}/{wa}\nTeam B: {b}/{wb}\n"
            f"Overs: {balls//6}.{balls%6} / {overs}\n"
            f"Currently Batting: Team {batting}"
        )
    except Exception as e:
        logger.error(f"Error in /score: {e}", exc_info=True)

# Admin commands (bonus, penalty, inningswap, endmatch) would follow with similar structure and error handling.
def register_handlers(application):
    # Core commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("register", register))
    application.add_handler(CommandHandler("profile", profile))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("cclgroup", cclgroup_command))
    # Team management
    application.add_handler(CommandHandler("add_A", add_A_command))
    application.add_handler(CommandHandler("add_B", add_B_command))
    application.add_handler(CommandHandler("teams", teams_command))
    application.add_handler(CommandHandler("cap_A", cap_A_command))
    application.add_handler(CommandHandler("cap_B", cap_B_command))
    application.add_handler(CommandHandler("setovers", setovers_command))
    application.add_handler(CommandHandler("startmatch", startmatch_command))
    application.add_handler(CommandHandler("toss", toss_command))
    # Gameplay
    application.add_handler(CommandHandler("bat", bat_command))
    application.add_handler(CommandHandler("bowl", bowl_command))
    application.add_handler(CommandHandler("score", score_command))
    # Admin commands (bonus, penalty, inningswap, endmatch) to be added here similarly
    # Ball-by-ball play (text)
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), process_ball))
    # Callback handlers for toss and innings swap
    application.add_handler(CallbackQueryHandler(toss_callback, pattern="^toss_(heads|tails)$"))
    application.add_handler(CallbackQueryHandler(toss_batbowl_callback, pattern="^toss_(bat|bowl)$"))
    # Add inningswap callback handler here if implemented

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
    
