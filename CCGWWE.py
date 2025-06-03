import logging
import random
import asyncio
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ParseMode,
)
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

# --- Configuration ---
TOKEN = "8156231369:AAHDFvjD9Aur9y5QjB5YWzvCQp7bUdLuuEc"
MONGO_URL = "mongodb://mongo:GhpHMiZizYnvJfKIQKxoDbRyzBCpqEyC@mainline.proxy.rlwy.net:54853"
COINS_EMOJI = "🪙"
TROPHY_EMOJI = "🏆"
WICKET_EMOJI = "💥"
BALL_EMOJI = "⚾"
BAT_EMOJI = "🏏"
RUN_EMOJI = "🏃‍♂️"
CHECK_MARK = "✅"
CROSS_MARK = "❌"
WARNING = "⚠️"
CLOCK_EMOJI = "⏳"
CRICKET_BALL = "🏏"

# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# --- Database Setup ---
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

# --- Helper Functions ---
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

# --- Core Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        ensure_user(user)
        await save_user(user.id)
        await update.message.reply_text(
            f"{CRICKET_BALL} *Welcome to CCL HandCricket Bot!*\n\n"
            f"1️⃣ Use /register to get 4000 {COINS_EMOJI} and start playing\n"
            f"2️⃣ Use /help for full instructions\n"
            f"3️⃣ Hosts: Create matches with /cclgroup",
            parse_mode=ParseMode.MARKDOWN
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
            await update.message.reply_text(f"{CHECK_MARK} You have already registered.")
            return
        u["coins"] += 4000
        u["registered"] = True
        await save_user(user.id)
        await update.message.reply_text(f"{CHECK_MARK} Registered! You received 4000 {COINS_EMOJI}.")
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
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error in /profile: {e}", exc_info=True)
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text(
            f"{CRICKET_BALL} *HandCricket Commands*\n"
            "• /register - Register and get coins\n"
            "• /profile - View your stats\n"
            "• /cclgroup - Host: Start a new match\n"
            "• /add_A <username|user_id> - Add to Team A\n"
            "• /add_B <username|user_id> - Add to Team B\n"
            "• /remove_A <num> - Remove player from Team A\n"
            "• /remove_B <num> - Remove player from Team B\n"
            "• /teams - Show teams\n"
            "• /cap_A <num> - Assign Team A captain (with confirmation)\n"
            "• /cap_B <num> - Assign Team B captain (with confirmation)\n"
            "• /setovers <num> - Set overs (1-20)\n"
            "• /startmatch - Start match\n"
            "• /toss - Start toss\n"
            "• /bat <striker> <non_striker> - Assign batsmen\n"
            "• /bowl <bowler> - Assign bowler\n"
            "• /score - Show score\n"
            "• /bonus <A|B> <runs> - Add bonus\n"
            "• /penalty <A|B> <runs> - Deduct runs\n"
            "• /inningswap - Swap innings (with confirmation)\n"
            "• /endmatch - End match (with confirmation)\n"
            "• Players get DM prompts for batting/bowling\n"
            "• All ball results and confirmations appear in group chat\n"
            "• Host can remove players anytime\n",
            parse_mode=ParseMode.MARKDOWN
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
                f"{WARNING} A match is already ongoing in this chat.\n"
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
            f"{TROPHY_EMOJI} *New Match Created!*\n"
            "1️⃣ Host: Add players with /add_A <username|user_id> or /add_B <username|user_id>\n"
            "2️⃣ Remove with /remove_A <num> or /remove_B <num>\n"
            "3️⃣ Assign captains with /cap_A <num> and /cap_B <num> (confirmation required)\n"
            "4️⃣ Set overs with /setovers <num> (1-20)\n"
            "5️⃣ Start match with /startmatch\n"
            "6️⃣ Use /help for instructions.",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Error in /cclgroup: {e}", exc_info=True)

async def add_A_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user
        args = context.args

        if chat.id not in MATCHES:
            await update.message.reply_text(f"{WARNING} No ongoing match in this chat. Use /cclgroup to create one.")
            return

        match = MATCHES[chat.id]
        if user.id != match["host_id"]:
            await update.message.reply_text(f"{CROSS_MARK} Only the host can add players.")
            return

        if not args:
            await update.message.reply_text("Usage: /add_A <username|user_id>")
            return

        player = find_player(args[0])
        if not player:
            await update.message.reply_text(f"{CROSS_MARK} Player not found or not registered.")
            return

        if player in match["team_A"] or player in match["team_B"]:
            await update.message.reply_text(f"{CROSS_MARK} {player['name']} (@{player.get('username','')}) is already in a team.")
            return

        match["team_A"].append(player)
        await update.message.reply_text(
            f"{CHECK_MARK} Added {player['name']} (@{player.get('username','')}) to Team A.\n"
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
            await update.message.reply_text(f"{WARNING} No ongoing match in this chat. Use /cclgroup to create one.")
            return

        match = MATCHES[chat.id]
        if user.id != match["host_id"]:
            await update.message.reply_text(f"{CROSS_MARK} Only the host can add players.")
            return

        if not args:
            await update.message.reply_text("Usage: /add_B <username|user_id>")
            return

        player = find_player(args[0])
        if not player:
            await update.message.reply_text(f"{CROSS_MARK} Player not found or not registered.")
            return

        if player in match["team_A"] or player in match["team_B"]:
            await update.message.reply_text(f"{CROSS_MARK} {player['name']} (@{player.get('username','')}) is already in a team.")
            return

        match["team_B"].append(player)
        await update.message.reply_text(
            f"{CHECK_MARK} Added {player['name']} (@{player.get('username','')}) to Team B.\n"
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
            await update.message.reply_text(f"{WARNING} No ongoing match in this chat.")
            return

        match = MATCHES[chat.id]
        if user.id != match["host_id"]:
            await update.message.reply_text(f"{CROSS_MARK} Only the host can remove players.")
            return

        if not args or not args[0].isdigit():
            await update.message.reply_text("Usage: /remove_A <player_number>")
            return

        player_num = int(args[0])
        if player_num < 1 or player_num > len(match["team_A"]):
            await update.message.reply_text("Invalid player number for Team A.")
            return

        removed = match["team_A"].pop(player_num - 1)
        if match.get("striker") and match["striker"]["user_id"] == removed["user_id"]:
            match["striker"] = None
        if match.get("non_striker") and match["non_striker"]["user_id"] == removed["user_id"]:
            match["non_striker"] = None

        await update.message.reply_text(
            f"{CROSS_MARK} Removed {removed['name']} (@{removed.get('username','')}) from Team A."
        )
    except Exception as e:
        logger.error(f"Error in /remove_A: {e}", exc_info=True)

async def remove_B_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user
        args = context.args

        if chat.id not in MATCHES:
            await update.message.reply_text(f"{WARNING} No ongoing match in this chat.")
            return

        match = MATCHES[chat.id]
        if user.id != match["host_id"]:
            await update.message.reply_text(f"{CROSS_MARK} Only the host can remove players.")
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
            f"{CROSS_MARK} Removed {removed['name']} (@{removed.get('username','')}) from Team B."
        )
    except Exception as e:
        logger.error(f"Error in /remove_B: {e}", exc_info=True)

# --- Captain Assignment with Confirmation ---

async def cap_A_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user
        args = context.args

        if chat.id not in MATCHES:
            await update.message.reply_text(f"{WARNING} No ongoing match in this chat.")
            return

        match = MATCHES[chat.id]

        if user.id != match["host_id"]:
            await update.message.reply_text(f"{CROSS_MARK} Only the host can assign captains.")
            return

        if not args or not args[0].isdigit():
            await update.message.reply_text("Usage: /cap_A <player_number>")
            return

        player_num = int(args[0])
        if player_num < 1 or player_num > len(match["team_A"]):
            await update.message.reply_text("Invalid player number for Team A.")
            return

        player = match["team_A"][player_num - 1]

        keyboard = [
            [
                InlineKeyboardButton(f"{CHECK_MARK} Confirm", callback_data=f"confirm_cap_A_{player_num}"),
                InlineKeyboardButton(f"{CROSS_MARK} Cancel", callback_data="cancel_cap"),
            ]
        ]
        await update.message.reply_text(
            f"⚠️ Are you sure you want to assign captain for Team A to {mention_player(player)}?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Error in /cap_A: {e}", exc_info=True)

async def cap_B_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user
        args = context.args

        if chat.id not in MATCHES:
            await update.message.reply_text(f"{WARNING} No ongoing match in this chat.")
            return

        match = MATCHES[chat.id]

        if user.id != match["host_id"]:
            await update.message.reply_text(f"{CROSS_MARK} Only the host can assign captains.")
            return

        if not args or not args[0].isdigit():
            await update.message.reply_text("Usage: /cap_B <player_number>")
            return

        player_num = int(args[0])
        if player_num < 1 or player_num > len(match["team_B"]):
            await update.message.reply_text("Invalid player number for Team B.")
            return

        player = match["team_B"][player_num - 1]

        keyboard = [
            [
                InlineKeyboardButton(f"{CHECK_MARK} Confirm", callback_data=f"confirm_cap_B_{player_num}"),
                InlineKeyboardButton(f"{CROSS_MARK} Cancel", callback_data="cancel_cap"),
            ]
        ]
        await update.message.reply_text(
            f"⚠️ Are you sure you want to assign captain for Team B to {mention_player(player)}?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Error in /cap_B: {e}", exc_info=True)

# --- Callback Query Handler for Captain Confirmation ---

async def captain_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        chat_id = query.message.chat.id
        user_id = query.from_user.id

        if chat_id not in MATCHES:
            await query.answer("No ongoing match.")
            return

        match = MATCHES[chat_id]

        if user_id != match["host_id"]:
            await query.answer("Only the host can confirm this action.")
            return

        data = query.data

        if data == "cancel_cap":
            await query.edit_message_text("❌ Captain assignment cancelled.")
            return

        if data.startswith("confirm_cap_A_"):
            player_num = int(data.split("_")[-1])
            if player_num < 1 or player_num > len(match["team_A"]):
                await query.edit_message_text("Invalid player number.")
                return
            match["captain_A"] = match["team_A"][player_num - 1]
            await query.edit_message_text(
                f"🅰️ Captain for Team A assigned to {mention_player(match['captain_A'])}."
            )
            return

        if data.startswith("confirm_cap_B_"):
            player_num = int(data.split("_")[-1])
            if player_num < 1 or player_num > len(match["team_B"]):
                await query.edit_message_text("Invalid player number.")
                return
            match["captain_B"] = match["team_B"][player_num - 1]
            await query.edit_message_text(
                f"🅱️ Captain for Team B assigned to {mention_player(match['captain_B'])}."
            )
            return

        await query.answer()
    except Exception as e:
        logger.error(f"Error in captain confirmation callback: {e}", exc_info=True)
# --- Innings Swap Command with Confirmation ---

async def inningswap_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user

        if chat.id not in MATCHES:
            await update.message.reply_text(f"{WARNING} No ongoing match in this chat.")
            return

        match = MATCHES[chat.id]

        if user.id != match["host_id"]:
            await update.message.reply_text(f"{CROSS_MARK} Only the host can swap innings.")
            return

        keyboard = [
            [
                InlineKeyboardButton(f"{CHECK_MARK} Confirm Innings Swap", callback_data="confirm_inningswap"),
                InlineKeyboardButton(f"{CROSS_MARK} Cancel", callback_data="cancel_inningswap"),
            ]
        ]

        await update.message.reply_text(
            f"⚠️ Are you sure you want to swap innings now?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Error in /inningswap: {e}", exc_info=True)

# --- End Match Command with Confirmation ---

async def endmatch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user

        if chat.id not in MATCHES:
            await update.message.reply_text(f"{WARNING} No ongoing match in this chat.")
            return

        match = MATCHES[chat.id]

        if user.id != match["host_id"]:
            await update.message.reply_text(f"{CROSS_MARK} Only the host can end the match.")
            return

        keyboard = [
            [
                InlineKeyboardButton(f"{CHECK_MARK} Confirm End Match", callback_data="confirm_endmatch"),
                InlineKeyboardButton(f"{CROSS_MARK} Cancel", callback_data="cancel_endmatch"),
            ]
        ]

        await update.message.reply_text(
            f"⚠️ Are you sure you want to end the match now?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Error in /endmatch: {e}", exc_info=True)

# --- Callback Query Handler for Innings Swap and End Match Confirmation ---

async def match_control_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        chat_id = query.message.chat.id
        user_id = query.from_user.id

        if chat_id not in MATCHES:
            await query.answer("No ongoing match.")
            return

        match = MATCHES[chat_id]

        if user_id != match["host_id"]:
            await query.answer("Only the host can confirm this action.")
            return

        data = query.data

        if data == "cancel_inningswap":
            await query.edit_message_text("❌ Innings swap cancelled.")
            return

        if data == "confirm_inningswap":
            # Swap innings logic
            if match["innings"] == 1:
                match["innings"] = 2
                match["batting_team"], match["bowling_team"] = match["bowling_team"], match["batting_team"]
                match["balls"] = 0
                match["wickets"][match["batting_team"]] = 0
                match["striker"] = None
                match["non_striker"] = None
                match["current_bowler"] = None
                match["last_bowler"] = None
                match["players_out"][match["batting_team"]] = []
                match["state"] = "innings2"
                await query.edit_message_text(f"🔄 Innings swapped! Now Team {match['batting_team']} is batting.")
            else:
                await query.edit_message_text("⚠️ Innings already swapped once. Use /endmatch to finish the match.")
            return

        if data == "cancel_endmatch":
            await query.edit_message_text("❌ End match cancelled.")
            return

        if data == "confirm_endmatch":
            # End match logic
            score_A = match["score"]["A"]
            wickets_A = match["wickets"]["A"]
            score_B = match["score"]["B"]
            wickets_B = match["wickets"]["B"]

            if score_A > score_B:
                result = f"🎉 Team A won by {score_A - score_B} runs! {TROPHY_EMOJI}"
            elif score_B > score_A:
                result = f"🎉 Team B won by {len(match['team_B']) - wickets_B} wickets! {TROPHY_EMOJI}"
            else:
                result = "🤝 Match tied!"

            scoreboard_text = format_scoreboard(match, final=True)

            await query.edit_message_text(f"🏁 *Match Ended!*\n\n{scoreboard_text}\n\n{result}", parse_mode=ParseMode.MARKDOWN)

            # Clean up match data
            del MATCHES[chat_id]
            return

        await query.answer()
    except Exception as e:
        logger.error(f"Error in match control callback: {e}", exc_info=True)

# --- Enhanced Scoreboard Formatter ---

def format_scoreboard(match, final=False):
    # Extract data
    score_A = match["score"]["A"]
    wickets_A = match["wickets"]["A"]
    score_B = match["score"]["B"]
    wickets_B = match["wickets"]["B"]
    overs = match.get("overs") or 0
    balls = match.get("balls") or 0
    batting_team = match.get("batting_team", "A")
    innings = match.get("innings", 1)

    overs_bowled = balls // 6
    balls_bowled = balls % 6

    # Batsmen info
    striker = match.get("striker")
    non_striker = match.get("non_striker")

    def player_stats(player):
        if not player:
            return "N/A"
        runs = player.get("runs_scored", 0)
        balls_faced = player.get("balls_faced", 0)
        return f"{mention_player(player)}: *{runs}* runs ({balls_faced} balls)"

    striker_info = player_stats(striker)
    non_striker_info = player_stats(non_striker)

    # Format scoreboard
    lines = [
        "┌───────────────🏏 *CCL HandCricket Scoreboard* 🏏───────────────┐",
        f"│ Team A: *{score_A}* / *{wickets_A}*",
        f"│ Team B: *{score_B}* / *{wickets_B}*",
        f"│ Overs: *{overs_bowled}.{balls_bowled}* / *{overs}*",
        f"│ Currently Batting: *Team {batting_team}* (Innings {innings})",
        "│",
        f"│ 🏏 Striker: {striker_info}",
        f"│ 🏏 Non-Striker: {non_striker_info}",
        "└──────────────────────────────────────────────────────────────┘",
    ]

    if final:
        lines.append(f"\n{TROPHY_EMOJI} *Match Completed!*")

    return "\n".join(lines)
# --- Toss Callbacks ---

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
            parse_mode=ParseMode.MARKDOWN
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
            parse_mode=ParseMode.MARKDOWN
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
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Error in toss bat/bowl callback: {e}", exc_info=True)

# --- Bat Command ---

async def bat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user
        args = context.args

        if chat.id not in MATCHES:
            await update.message.reply_text(f"{WARNING} No ongoing match in this chat.")
            return

        match = MATCHES[chat.id]

        if user.id != match["host_id"]:
            await update.message.reply_text(f"{CROSS_MARK} Only the host can assign batsmen.")
            return

        if len(args) != 2 or not all(arg.isdigit() for arg in args):
            await update.message.reply_text("Usage: /bat <striker_num> <non_striker_num>")
            return

        if not match.get("batting_team"):
            await update.message.reply_text(f"{WARNING} Complete the toss first!")
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

        # DM batsmen to send runs
        try:
            await context.bot.send_message(
                chat_id=match["striker"]["user_id"],
                text=f"{BAT_EMOJI} You are the *Striker*. Send your run (0,1,2,3,4,6).",
                parse_mode=ParseMode.MARKDOWN
            )
            await context.bot.send_message(
                chat_id=match["non_striker"]["user_id"],
                text=f"{BAT_EMOJI} You are the *Non-Striker*. Wait for your turn.",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            # Ignore if DM fails
            pass

        await update.message.reply_text(
            f"Batsmen assigned:\n"
            f"Striker: {mention_player(match['striker'])}\n"
            f"Non-Striker: {mention_player(match['non_striker'])}\n"
            f"Host: Assign bowler with /bowl <bowler_num>.",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Error in /bat: {e}", exc_info=True)

# --- Bowl Command ---

async def bowl_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user
        args = context.args

        if chat.id not in MATCHES:
            await update.message.reply_text(f"{WARNING} No ongoing match in this chat.")
            return

        match = MATCHES[chat.id]

        if user.id != match["host_id"]:
            await update.message.reply_text(f"{CROSS_MARK} Only the host can assign the bowler.")
            return

        if len(args) != 1 or not args[0].isdigit():
            await update.message.reply_text("Usage: /bowl <bowler_num>")
            return

        if not match.get("bowling_team"):
            await update.message.reply_text(f"{WARNING} Complete the toss first!")
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

        # DM bowler to send variation
        try:
            await context.bot.send_message(
                chat_id=bowler["user_id"],
                text=f"{BALL_EMOJI} You are the *Bowler*. Send your variation (rs, bouncer, yorker, short, slower, knuckle).",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass

        await update.message.reply_text(
            f"Bowler for this over: {mention_player(bowler)}\n"
            f"Striker: {mention_player(match['striker'])}\n"
            f"Non-Striker: {mention_player(match['non_striker'])}\n"
            f"Batsman and Bowler, please send your inputs in DM.",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Error in /bowl: {e}", exc_info=True)

# --- Ball Processing ---

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

        group_chat_id = None
        for chat_id, m in MATCHES.items():
            if m == match:
                group_chat_id = chat_id
                break

        if role == "batsman":
            if not text.isdigit() or int(text) not in ALLOWED_BATSMAN_RUNS:
                await update.message.reply_text(f"{CROSS_MARK} Invalid runs. Please send one of: 0, 1, 2, 3, 4, 6")
                return
            match["pending_batsman_run"] = int(text)
            await update.message.reply_text(f"{CHECK_MARK} Your run was received. Waiting for bowler.")
            if group_chat_id:
                await context.bot.send_message(group_chat_id, f"{CHECK_MARK} {mention_player(match['striker'])} sent their runs!", parse_mode=ParseMode.MARKDOWN)
        else:
            if text not in ALLOWED_BOWLER_VARIATIONS:
                await update.message.reply_text(f"{CROSS_MARK} Invalid bowling variation. Send one of: rs, bouncer, yorker, short, slower, knuckle")
                return
            match["pending_bowler_variation"] = BOWLER_VARIATIONS_MAP[text]
            await update.message.reply_text(f"{CHECK_MARK} Your variation was received. Waiting for batsman.")
            if group_chat_id:
                await context.bot.send_message(group_chat_id, f"{CHECK_MARK} {mention_player(match['current_bowler'])} sent their variation!", parse_mode=ParseMode.MARKDOWN)

        if "pending_batsman_run" in match and "pending_bowler_variation" in match:
            await handle_ball_result(context, match, group_chat_id)
    except Exception as e:
        logger.error(f"Error in ball processing: {e}", exc_info=True)

# --- Handler Registration ---

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
    application.add_handler(CallbackQueryHandler(captain_confirm_callback, pattern="^(confirm_cap_A_|confirm_cap_B_|cancel_cap)$"))
    application.add_handler(CallbackQueryHandler(toss_callback, pattern="^toss_(heads|tails)$"))
    application.add_handler(CallbackQueryHandler(toss_batbowl_callback, pattern="^toss_(bat|bowl)$"))
    application.add_handler(CallbackQueryHandler(match_control_callback, pattern="^(confirm_inningswap|cancel_inningswap|confirm_endmatch|cancel_endmatch)$"))

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
    import asyncio
    asyncio.run(main())
# --- Commentary Helper ---

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

# --- Handle Ball Result ---

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

        # Announce ball with delays
        await context.bot.send_message(group_chat_id, f"{CRICKET_BALL} Over {over_num}, Ball {ball_num}")
        await asyncio.sleep(3)
        await context.bot.send_message(group_chat_id, f"{bowler['name']} bowls a {get_variation_name(variation)}!")
        await asyncio.sleep(4)

        # Wicket check (RS ball + 0 runs)
        if runs == 0 and variation == 0:
            match["wickets"][batting_team_key] += 1
            match["players_out"][batting_team_key].append(striker)
            striker["balls_faced"] = striker.get("balls_faced", 0) + 1
            await context.bot.send_message(
                group_chat_id,
                f"{WICKET_EMOJI} WICKET! {mention_player(striker)} is OUT! Bowled by {mention_player(bowler)} (RS Ball)",
                parse_mode=ParseMode.MARKDOWN
            )
            match["striker"] = None
            return

        # Update runs and balls
        match["score"][batting_team_key] += runs
        striker["runs_scored"] = striker.get("runs_scored", 0) + runs
        striker["balls_faced"] = striker.get("balls_faced", 0) + 1

        commentary = run_commentary(runs)
        msg = f"{mention_player(striker)} {commentary}"
        gif_url = GIFS.get(runs)
        if gif_url:
            await context.bot.send_animation(group_chat_id, gif_url, caption=msg, parse_mode=ParseMode.MARKDOWN)
        else:
            await context.bot.send_message(group_chat_id, msg, parse_mode=ParseMode.MARKDOWN)

        # Swap strike if runs odd
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
            f"📊 Score: {match['score'][batting_team_key]}/{match['wickets'][batting_team_key]} "
            f"in {match['balls']//6}.{match['balls']%6} overs."
        )

        # End of innings checks
        team_size = len(match["team_A"]) if batting_team_key == "A" else len(match["team_B"])
        if match["wickets"][batting_team_key] >= team_size:
            await context.bot.send_message(group_chat_id, f"{WICKET_EMOJI} All out! Host: Use /inningswap to swap innings.")
        elif match["balls"] >= match["overs"] * 6:
            await context.bot.send_message(group_chat_id, f"{CLOCK_EMOJI} Overs completed! Host: Use /inningswap to swap innings.")
    except Exception as e:
        logger.error(f"Error in handle_ball_result: {e}", exc_info=True)

# --- Bonus and Penalty Commands ---

async def bonus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user
        args = context.args

        if chat.id not in MATCHES:
            await update.message.reply_text(f"{WARNING} No ongoing match in this chat.")
            return

        match = MATCHES[chat.id]

        if user.id != match["host_id"]:
            await update.message.reply_text(f"{CROSS_MARK} Only the host can add bonus runs.")
            return

        if len(args) != 2 or args[0] not in ("A", "B") or not args[1].isdigit():
            await update.message.reply_text("Usage: /bonus <A|B> <runs>")
            return

        team = args[0]
        runs = int(args[1])
        match["score"][team] += runs

        await update.message.reply_text(f"{CHECK_MARK} Added {runs} bonus runs to Team {team}.")
    except Exception as e:
        logger.error(f"Error in /bonus: {e}", exc_info=True)

async def penalty_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        user = update.effective_user
        args = context.args

        if chat.id not in MATCHES:
            await update.message.reply_text(f"{WARNING} No ongoing match in this chat.")
            return

        match = MATCHES[chat.id]

        if user.id != match["host_id"]:
            await update.message.reply_text(f"{CROSS_MARK} Only the host can deduct penalty runs.")
            return

        if len(args) != 2 or args[0] not in ("A", "B") or not args[1].isdigit():
            await update.message.reply_text("Usage: /penalty <A|B> <runs>")
            return

        team = args[0]
        runs = int(args[1])
        match["score"][team] = max(0, match["score"][team] - runs)

        await update.message.reply_text(f"{CHECK_MARK} Deducted {runs} penalty runs from Team {team}.")
    except Exception as e:
        logger.error(f"Error in /penalty: {e}", exc_info=True)
    
