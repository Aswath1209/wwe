import logging
import random
import asyncio
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

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

COMMENTARY_PHRASES = {
    0: ["Dot ball!", "Good defense.", "No run this ball."],
    1: ["Quick single taken.", "Good running between the wickets."],
    2: ["Two runs scored.", "Excellent placement for two."],
    3: ["Three runs! Great running!"],
    4: ["That's a boundary!", "Four runs! What a shot!"],
    6: ["SIX! What a massive hit!", "That's out of the park!"],
}
GIFS = {
    0: "https://media.giphy.com/media/3o6Zt481isNVuQI1l6/giphy.gif",  # dot ball
    4: "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif",  # four runs
    6: "https://media.giphy.com/media/26ufdipQqU2lhNA4g/giphy.gif",  # six runs
    "half_century": "https://media.giphy.com/media/3o6Zt6ML6BklcajjsA/giphy.gif",
    "century": "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif",
}

def get_username(user):
    return user.first_name or user.username or "Player"

def ensure_user(user):
    if user.id not in USERS:
        USERS[user.id] = {
            "user_id": user.id,
            "name": get_username(user),
            "coins": 0,
            "wins": 0,
            "losses": 0,
            "ties": 0,
            "registered": False,
            "last_daily": None,
            "runs_scored": 0,
            "balls_faced": 0,
        }

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

# --- Core Commands ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)
    await save_user(user.id)
    await update.message.reply_text(
        f"Welcome to CCL HandCricket Bot, {USERS[user.id]['name']}!\n"
        f"Use /register to get 4000 {COINS_EMOJI} and start playing.\n"
        f"Use /help for command list."
    )

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)
    u = USERS[user.id]
    if u["registered"]:
        await update.message.reply_text("You have already registered.")
        return
    u["coins"] += 4000
    u["registered"] = True
    await save_user(user.id)
    await update.message.reply_text(f"Registered! You received 4000 {COINS_EMOJI}.")

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)
    u = USERS[user.id]
    text = (
        f"{u['name']}'s Profile\n"
        f"ID: {user.id}\n"
        f"Purse: {u['coins']}{COINS_EMOJI}\n"
        f"Wins: {u['wins']}  Losses: {u['losses']}  Ties: {u['ties']}\n"
        f"Runs Scored: {u.get('runs_scored', 0)}  Balls Faced: {u.get('balls_faced', 0)}"
    )
    await update.message.reply_text(text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏏 *CCL HandCricket Bot Help*\n"
        "\n"
        "1. /register - Register and get coins\n"
        "2. /profile - View your stats\n"
        "3. /cclgroup - Host: Start a new match in group\n"
        "4. /add_A @username or /add_B @username - Add players to teams\n"
        "5. /teams - Show teams\n"
        "6. /cap_A <num> or /cap_B <num> - Assign captains\n"
        "7. /setovers <num> - Set overs (1-20)\n"
        "8. /startmatch - Start match after setup\n"
        "9. /bat <striker_num> <non_striker_num> - Assign batsmen\n"
        "10. /bowl <bowler_num> - Assign bowler (no consecutive overs)\n"
        "11. Batsman: Send 0,1,2,3,4,6 | Bowler: Send rs,bouncer,yorker,short,slower,knuckle\n"
        "12. /score - Show current score\n"
        "13. /bonus <A|B> <runs> or /penalty <A|B> <runs>\n"
        "14. /inningswap - Swap innings (with confirm)\n"
        "15. /endmatch - End match and show result\n"
        "\n"
        "*Rules:*\n"
        "- If batsman sends 0 and bowler sends rs(0), it's OUT.\n"
        "- Strike rotates on odd runs except last ball of over.\n"
        "- Host can add players anytime.\n"
        "- All communication is text-based.\n",
        parse_mode="Markdown"
    )

async def cclgroup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    }

    await update.message.reply_text(
        f"Match created by {user.first_name}!\n\n"
        "Host: Add players with /add_A @username or /add_B @username (max 8 per team).\n"
        "Then assign captains with /cap_A <num> and /cap_B <num>.\n"
        "Set overs with /setovers <num> (1-20).\n"
        "Start match with /startmatch.\n"
        "Use /help for full instructions."
    )
# --- Team Management and Match Setup Commands ---

async def add_A_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await update.message.reply_text("Usage: /add_A @username")
        return

    username = args[0].lstrip("@")
    player = None
    for u in USERS.values():
        if u["name"].lower() == username.lower():
            player = u
            break

    if not player:
        await update.message.reply_text(f"User @{username} not found or not registered.")
        return

    if player in match["team_A"] or player in match["team_B"]:
        await update.message.reply_text(f"{player['name']} is already in a team.")
        return

    if len(match["team_A"]) >= 8:
        await update.message.reply_text("Team A already has 8 players.")
        return

    match["team_A"].append(player)
    await update.message.reply_text(
        f"Added {player['name']} to Team A.\n"
        f"Team A now has {len(match['team_A'])} players.\n"
        "Host: Continue adding or assign captain with /cap_A <player_number>.\n"
        "Use /teams to view both teams."
    )

async def add_B_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await update.message.reply_text("Usage: /add_B @username")
        return

    username = args[0].lstrip("@")
    player = None
    for u in USERS.values():
        if u["name"].lower() == username.lower():
            player = u
            break

    if not player:
        await update.message.reply_text(f"User @{username} not found or not registered.")
        return

    if player in match["team_A"] or player in match["team_B"]:
        await update.message.reply_text(f"{player['name']} is already in a team.")
        return

    if len(match["team_B"]) >= 8:
        await update.message.reply_text("Team B already has 8 players.")
        return

    match["team_B"].append(player)
    await update.message.reply_text(
        f"Added {player['name']} to Team B.\n"
        f"Team B now has {len(match['team_B'])} players.\n"
        "Host: Continue adding or assign captain with /cap_B <player_number>.\n"
        "Use /teams to view both teams."
    )

async def teams_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.id not in MATCHES:
        await update.message.reply_text("No ongoing match in this chat.")
        return

    match = MATCHES[chat.id]
    text = f"Teams for current match:\n\n*Team A*:\n"
    if match["team_A"]:
        for i, p in enumerate(match["team_A"], start=1):
            text += f"{i}. {p['name']}\n"
    else:
        text += "No players added yet.\n"

    text += f"\n*Team B*:\n"
    if match["team_B"]:
        for i, p in enumerate(match["team_B"], start=1):
            text += f"{i}. {p['name']}\n"
    else:
        text += "No players added yet.\n"

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def cap_A_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    await update.message.reply_text(f"Captain for Team A set to {match['captain_A']['name']}.\nAssign Team B captain with /cap_B <player_number>.")

async def cap_B_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    await update.message.reply_text(f"Captain for Team B set to {match['captain_B']['name']}.\nSet overs with /setovers <number>.")

async def setovers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        f"Overs set to {overs}.\n"
        "Host: When ready, start the match with /startmatch."
    )

async def startmatch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        f"Match setup complete!\n"
        f"Host: Conduct the toss and set which team bats first by setting 'batting_team' and 'bowling_team' in the code (or add a toss command if you wish).\n"
        f"Then assign batsmen with /bat <striker_num> <non_striker_num> and bowler with /bowl <bowler_num>."
        )
# --- Batting, Bowling, and Ball-by-Ball Play ---

async def bat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await update.message.reply_text("Host: Please set 'batting_team' and 'bowling_team' in the code or via a toss command before assigning batsmen.")
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

    # Check if players are out
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

async def bowl_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await update.message.reply_text("Host: Please set 'batting_team' and 'bowling_team' in the code or via a toss command before assigning bowler.")
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

async def process_ball(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip().lower()

    # Find match where user is striker or bowler
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

    # Store input in match state
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

    # If both inputs received, process the ball
    if "pending_batsman_run" in match and "pending_bowler_variation" in match:
        await handle_ball_result(update, context, match)

async def handle_ball_result(update, context, match):
    runs = match.pop("pending_batsman_run")
    variation = match.pop("pending_bowler_variation")
    striker = match["striker"]
    non_striker = match["non_striker"]
    bowler = match["current_bowler"]
    batting_team_key = match["batting_team"]

    # Wicket check
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
        match["striker"] = None  # Host must assign new striker
        return

    # Normal runs
    match["score"][batting_team_key] += runs
    striker["runs_scored"] = striker.get("runs_scored", 0) + runs
    striker["balls_faced"] = striker.get("balls_faced", 0) + 1
    match["balls"] += 1
    match["balls_in_over"] = match.get("balls_in_over", 0) + 1

    # Commentary
    variation_name = get_variation_name(variation)
    commentary = (
        f"{mention_player(bowler)} bowls a {variation_name}.\n"
        f"{mention_player(striker)} scores {runs} run{'s' if runs != 1 else ''}."
    )

    # Milestone commentary
    if striker["runs_scored"] == 50:
        commentary += " 🎉 That's a superb half-century! 🎉"
    if striker["runs_scored"] == 100:
        commentary += " 🎉🎉 Century for the batsman! 🎉🎉"

    # Send GIF if applicable
    gif_url = GIFS.get(runs)
    if gif_url:
        await update.message.reply_animation(gif_url, caption=commentary, parse_mode="Markdown")
    else:
        await update.message.reply_text(commentary, parse_mode="Markdown")

    # Strike rotation
    over_balls = match["balls_in_over"]
    if runs % 2 == 1:
        match["striker"], match["non_striker"] = match["non_striker"], match["striker"]

    # End of over logic
    if over_balls == 6:
        # End of over: Strike change if last ball runs even, else retain
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

    # Show text score after each ball
    await update.message.reply_text(
        f"Score: {match['score'][batting_team_key]}/{match['wickets'][batting_team_key]} in {match['balls']//6}.{match['balls']%6} overs.",
        parse_mode="Markdown"
    )

    # Check for all out or overs completed
    team_size = len(match["team_A"]) if batting_team_key == "A" else len(match["team_B"])
    if match["wickets"][batting_team_key] >= team_size - 1:
        await update.message.reply_text("All out! Host: Use /inningswap to swap innings.")
    elif match["balls"] >= match["overs"] * 6:
        await update.message.reply_text("Overs completed! Host: Use /inningswap to swap innings.")

async def score_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
# --- Admin, Innings, and End Commands ---

async def bonus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    await update.message.reply_text(f"Added {runs} bonus runs to Team {team}.")

async def penalty_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    await update.message.reply_text(f"Deducted {runs} penalty runs from Team {team}.")

async def inningswap_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def inningswap_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
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
            # Swap batting and bowling teams
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

async def endmatch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        result = f"Team A won by {score_A - score_B} runs!"
    elif score_B > score_A:
        wickets_left = len(match["team_B"]) - wb
        result = f"Team B won by {wickets_left} wickets!"
    else:
        result = "The match is a tie!"

    await update.message.reply_text(
        f"🏁 Match ended!\n\nFinal Score:\nTeam A: {score_A}/{wa}\nTeam B: {score_B}/{wb}\n\nResult: {result}"
    )

    # Cleanup
    del MATCHES[chat.id]

# --- Handler Registration and Main Function ---

from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters

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
    # Gameplay
    application.add_handler(CommandHandler("bat", bat_command))
    application.add_handler(CommandHandler("bowl", bowl_command))
    application.add_handler(CommandHandler("score", score_command))
    application.add_handler(CommandHandler("bonus", bonus_command))
    application.add_handler(CommandHandler("penalty", penalty_command))
    application.add_handler(CommandHandler("inningswap", inningswap_command))
    application.add_handler(CommandHandler("endmatch", endmatch_command))
    # Ball-by-ball play (text)
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), process_ball))
    # Callback for innings swap
    application.add_handler(CallbackQueryHandler(inningswap_callback, pattern="^inningswap_"))

async def on_startup(application):
    await load_users()
    logger.info("Bot started and users loaded.")

async def main():
    application = ApplicationBuilder().token(TOKEN).build()
    register_handlers(application)
    application.post_init = on_startup
    logger.info("Starting bot...")
    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
    
