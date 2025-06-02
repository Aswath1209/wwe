import logging
import random
import asyncio
from io import BytesIO
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputFile,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

import nest_asyncio
nest_asyncio.apply()

from motor.motor_asyncio import AsyncIOMotorClient

# --- Config ---
TOKEN = "8156231369:AAHDFvjD9Aur9y5QjB5YWzvCQp7bUdLuuEc"
MONGO_URL = "mongodb://mongo:GhpHMiZizYnvJfKIQKxoDbRyzBCpqEyC@mainline.proxy.rlwy.net:54853"
ADMIN_IDS = {123456789}  # Replace with your Telegram ID(s)
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
USERS = {}  # user_id -> user dict
MATCHES = {}  # chat_id -> match dict

# --- Allowed inputs ---
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

# --- Commentary GIF placeholders ---
GIFS = {
    0: "https://media.giphy.com/media/3o6Zt481isNVuQI1l6/giphy.gif",  # dot ball
    4: "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif",  # four runs
    6: "https://media.giphy.com/media/26ufdipQqU2lhNA4g/giphy.gif",  # six runs
    "half_century": "https://media.giphy.com/media/3o6Zt6ML6BklcajjsA/giphy.gif",
    "century": "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif",
}

# --- Helpers ---
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

# --- Scoreboard Template ---
def create_scoreboard_template(width=800, height=400):
    img = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(img)

    # Header/Footer bars
    draw.rectangle([(0, 0), (width, 60)], fill="#003366")
    draw.rectangle([(0, height - 40), (width, height)], fill="#003366")

    # Dividing lines
    draw.line([(width//2, 60), (width//2, height - 40)], fill="black", width=2)
    draw.line([(0, 120), (width, 120)], fill="black", width=2)

    # Fonts
    try:
        font_header = ImageFont.truetype("arial.ttf", 30)
        font_subheader = ImageFont.truetype("arial.ttf", 20)
    except IOError:
        font_header = ImageFont.load_default()
        font_subheader = ImageFont.load_default()

    draw.text((20, 15), "CCL HandCricket Scoreboard", fill="white", font=font_header)
    draw.text((20, 70), "Team A", fill="black", font=font_subheader)
    draw.text((width//2 + 20, 70), "Team B", fill="black", font=font_subheader)
    draw.text((20, height - 35), "Innings: ", fill="white", font=font_subheader)

    return img, draw, font_subheader

# --- Basic Commands ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)
    await save_user(user.id)
    await update.message.reply_text(
        f"Welcome to Unified CCL HandCricket Bot, {USERS[user.id]['name']}!\n"
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
        f"**{u['name']}'s Profile**\n\n"
        f"Name: {u['name']}\n"
        f"ID: {user.id}\n"
        f"Purse: {u['coins']}{COINS_EMOJI}\n\n"
        f"Performance History:\n"
        f"Wins: {u['wins']}\n"
        f"Losses: {u['losses']}\n"
        f"Ties: {u['ties']}\n"
        f"Runs Scored: {u.get('runs_scored', 0)}\n"
        f"Balls Faced: {u.get('balls_faced', 0)}\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🏏 *CCL HandCricket Bot Commands*\n\n"
        "/start - Welcome message\n"
        "/register - Register and get starting coins\n"
        "/profile - View your profile\n"
        "/cclgroup - Host: Start a new group match\n"
        "/add_A @username - Host: Add player to Team A\n"
        "/add_B @username - Host: Add player to Team B\n"
        "/teams - Show current teams\n"
        "/cap_A <player_number> - Host: Assign captain for Team A\n"
        "/cap_B <player_number> - Host: Assign captain for Team B\n"
        "/setovers <number> - Host: Set overs (1-20)\n"
        "/startmatch - Host: Start the match after setup\n"
        "/bat <striker_num> <non_striker_num> - Host: Assign batsmen\n"
        "/bowl <bowler_num> - Host: Assign bowler for current over (no consecutive overs)\n"
        "/runs <runs> - Host: Add runs scored on ball (allowed: 0,1,2,3,4,6)\n"
        "/wicket - Host: Record wicket fallen\n"
        "/score - Show current score\n"
        "/bonus <A|B> <runs> - Host: Add bonus runs\n"
        "/penalty <A|B> <runs> - Host: Deduct penalty runs\n"
        "/inningswap - Host: Swap innings (confirmation required)\n"
        "/endmatch - Host: End the match and show result\n\n"
        "Instructions:\n"
        "- Host: Use /cclgroup to create match, add players with /add_A or /add_B anytime.\n"
        "- Assign captains with /cap_A and /cap_B.\n"
        "- Set overs with /setovers.\n"
        "- Start match with /startmatch.\n"
        "- Host chooses striker and non-striker at innings start and after wickets.\n"
        "- Batsman sends runs (0,1,2,3,4,6) in DM; bowler sends variation (rs, bouncer, yorker, short, slower, knuckle).\n"
        "- If batsman sends 0 and bowler sends rs(0), batsman is out.\n"
        "- Strike changes on odd runs except last ball of over (see rules).\n"
        "- Host assigns bowler each over (no consecutive overs by same bowler).\n"
        "- Commentary and GIFs sent for key events.\n"
        "- Host can add players anytime even mid-match.\n"
        "- If all batsmen out, host must swap innings.\n"
        "- Host can manually swap innings anytime with confirmation.\n"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

# --- Load users on startup ---
async def on_startup(application):
    await load_users()
    logger.info("Bot started and users loaded.")

# --- Main ---
async def main():
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("register", register))
    application.add_handler(CommandHandler("profile", profile))
    application.add_handler(CommandHandler("help", help_command))

    # Other handlers for match setup and play will be added in next parts

    application.post_init = on_startup

    logger.info("Starting bot...")
    await application.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
from telegram.constants import ParseMode

async def cclgroup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    ensure_user(user)

    if chat.id in MATCHES:
        await update.message.reply_text("A match is already ongoing in this chat. Use /endmatch to finish it first.")
        return

    MATCHES[chat.id] = {
        "host_id": user.id,
        "team_A": [],
        "team_B": [],
        "captain_A": None,
        "captain_B": None,
        "team_A_name": "Team A",
        "team_B_name": "Team B",
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
        f"Group match created by {user.first_name}.\n"
        "Host, add players with /add_A @username or /add_B @username.\n"
        "When teams are ready, assign captains with /cap_A <player_number> and /cap_B <player_number>.\n"
        "Set overs with /setovers <number> (1-20).\n"
        "Start match with /startmatch."
    )

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
        f"Host: Add more players or assign captain with /cap_A <player_number>."
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
        f"Host: Add more players or assign captain with /cap_B <player_number>."
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
    await update.message.reply_text(f"Captain for Team A set to {match['captain_A']['name']}.")

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
    await update.message.reply_text(f"Captain for Team B set to {match['captain_B']['name']}.")

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
    await update.message.reply_text(f"Overs set to {overs}.")

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

    # Validate teams and overs
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
    # Notify host and captains
    await update.message.reply_text(
        f"Match setup complete!\n"
        f"Host: Conduct the toss by messaging the captains privately.\n"
        f"Captains: Please prepare for the toss and team decisions.\n"
        f"Use /bat and /bowl commands after toss to assign players."
    )

# Register handlers for Part 2 commands
def register_part2_handlers(application):
    application.add_handler(CommandHandler("cclgroup", cclgroup_command))
    application.add_handler(CommandHandler("add_A", add_A_command))
    application.add_handler(CommandHandler("add_B", add_B_command))
    application.add_handler(CommandHandler("teams", teams_command))
    application.add_handler(CommandHandler("cap_A", cap_A_command))
    application.add_handler(CommandHandler("cap_B", cap_B_command))
    application.add_handler(CommandHandler("setovers", setovers_command))
    application.add_handler(CommandHandler("startmatch", startmatch_command))
import re
from telegram.constants import ParseMode

# Helper: get player display name with mention
def mention_player(player):
    return f"[{player['name']}](tg://user?id={player['user_id']})"

# Command: Assign batsmen (striker and non-striker)
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
        f"Non-Striker: {mention_player(match['non_striker'])}\n\n"
        f"Captains and players, please send runs and bowling variations accordingly."
        , parse_mode=ParseMode.MARKDOWN)

# Command: Assign bowler for current over (no consecutive overs)
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

    bowling_team_key = "B" if match["batting_team"] == "A" else "A"
    bowling_team = match["team_B"] if bowling_team_key == "B" else match["team_A"]

    bowler_num = int(args[0])
    if not (1 <= bowler_num <= len(bowling_team)):
        await update.message.reply_text("Bowler number out of range.")
        return

    bowler = bowling_team[bowler_num - 1]
    if match.get("last_bowler") and bowler["user_id"] == match["last_bowler"]["user_id"]:
        await update.message.reply_text("This bowler bowled the last over. Choose a different bowler.")
        return

    match["current_bowler"] = bowler
    await update.message.reply_text(f"Bowler for this over: {mention_player(bowler)}", parse_mode=ParseMode.MARKDOWN)

# Helper: Process ball input (runs and bowling variation)
async def process_ball(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip().lower()

    # Find match where user is striker or bowler
    match = None
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
        await update.message.reply_text("You are not currently assigned as striker or bowler in any match.")
        return

    if role == "batsman":
        # Validate batsman input
        if not text.isdigit() or int(text) not in ALLOWED_BATSMAN_RUNS:
            await update.message.reply_text(f"Invalid runs. Please send one of: {sorted(ALLOWED_BATSMAN_RUNS)}")
            return
        runs = int(text)
        match.setdefault("last_batsman_run", None)
        match["last_batsman_run"] = runs
        await update.message.reply_text(f"Runs received: {runs}. Waiting for bowler's variation.")
    else:
        # Validate bowler input
        if text not in ALLOWED_BOWLER_VARIATIONS:
            await update.message.reply_text(f"Invalid bowling variation. Send one of: {', '.join(ALLOWED_BOWLER_VARIATIONS)}")
            return
        variation_num = BOWLER_VARIATIONS_MAP[text]
        match.setdefault("last_bowler_variation", None)
        match["last_bowler_variation"] = variation_num
        await update.message.reply_text(f"Bowling variation received: {text}. Waiting for batsman's runs.")

    # If both inputs received, process ball
    if match.get("last_batsman_run") is not None and match.get("last_bowler_variation") is not None:
        await handle_ball_result(update, context, match)

async def handle_ball_result(update: Update, context: ContextTypes.DEFAULT_TYPE, match):
    runs = match.pop("last_batsman_run")
    variation = match.pop("last_bowler_variation")

    striker = match["striker"]
    non_striker = match["non_striker"]
    bowler = match["current_bowler"]
    batting_team_key = match["batting_team"]
    bowling_team_key = "B" if batting_team_key == "A" else "A"

    # Check for wicket: batsman runs=0 and bowler variation=0 (rs)
    if runs == 0 and variation == 0:
        # Wicket!
        match["wickets"][batting_team_key] += 1
        match["players_out"][batting_team_key].append(striker)
        striker["balls_faced"] = striker.get("balls_faced", 0) + 1
        await update.message.reply_text(
            f"WICKET! {mention_player(striker)} is out on ball {match['balls'] + 1}.\n"
            f"Bowled by {mention_player(bowler)}.\n"
            f"Host, please assign a new batsman using /bat <striker_num> <non_striker_num>."
            , parse_mode=ParseMode.MARKDOWN)
        match["striker"] = None  # Clear striker until host assigns
    else:
        # Runs scored
        match["score"][batting_team_key] += runs
        striker["runs_scored"] = striker.get("runs_scored", 0) + runs
        striker["balls_faced"] = striker.get("balls_faced", 0) + 1
        match["balls"] += 1

        # Commentary message
        commentary = f"{mention_player(striker)} scored {runs} run{'s' if runs != 1 else ''} off {mention_player(bowler)}'s {list(BOWLER_VARIATIONS_MAP.keys())[list(BOWLER_VARIATIONS_MAP.values()).index(variation)]} ball."

        # Send GIF if applicable
        gif_url = GIFS.get(runs)
        if gif_url:
            await update.message.reply_animation(gif_url, caption=commentary, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(commentary, parse_mode=ParseMode.MARKDOWN)

        # Strike rotation logic
        over_balls = match["balls"] % 6
        if runs % 2 == 1:
            # Odd runs: swap strike
            match["striker"], match["non_striker"] = match["non_striker"], match["striker"]

        # At end of over (6 balls)
        if over_balls == 0:
            # If last ball runs even, swap strike; if odd, retain strike
            if runs % 2 == 0:
                match["striker"], match["non_striker"] = match["non_striker"], match["striker"]
            # Update last bowler
            match["last_bowler"] = bowler
            match["current_bowler"] = None
            await update.message.reply_text(
                f"Over completed. Host, please assign next bowler using /bowl <bowler_num>.\n"
                f"Current striker: {mention_player(match['striker'])}"
                , parse_mode=ParseMode.MARKDOWN)

        # Check if innings over (all wickets or overs)
        if match["wickets"][batting_team_key] >= (len(match["team_A"]) if batting_team_key == "A" else len(match["team_B"])) - 1:
            await update.message.reply_text(
                f"All out! Host, please swap innings using /inningswap."
            )
        elif match["balls"] >= match["overs"] * 6:
            await update.message.reply_text(
                f"Overs completed! Host, please swap innings using /inningswap."
            )

# Register handlers for Part 3
def register_part3_handlers(application):
    application.add_handler(CommandHandler("bat", bat_command))
    application.add_handler(CommandHandler("bowl", bowl_command))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), process_ball))
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# --- Innings Swap Confirmation Handler ---

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
        # Swap innings
        if match["innings"] == 1:
            match["innings"] = 2
            # Swap batting and bowling teams
            if match["batting_team"] == "A":
                match["batting_team"] = "B"
                match["bowling_team"] = "A"
            else:
                match["batting_team"] = "A"
                match["bowling_team"] = "B"
            # Reset balls and wickets
            match["balls"] = 0
            match["wickets"][match["batting_team"]] = 0
            match["score"][match["batting_team"]] = 0
            match["striker"] = None
            match["non_striker"] = None
            match["current_bowler"] = None
            match["last_bowler"] = None
            await query.edit_message_text("Innings swapped! Host, please assign new batsmen and bowler.")
        else:
            await query.edit_message_text("This is the second innings. Match will end soon.")
    else:
        await query.edit_message_text("Innings swap cancelled.")

# --- Scoreboard Image Generation ---

async def send_scoreboard(chat_id, context: ContextTypes.DEFAULT_TYPE):
    if chat_id not in MATCHES:
        return

    match = MATCHES[chat_id]
    img, draw, font = create_scoreboard_template()

    # Draw team names and scores
    draw.text((20, 130), f"{match['team_A_name']} Score: {match['score']['A']} / {match['wickets']['A']}", fill="black", font=font)
    draw.text((410, 130), f"{match['team_B_name']} Score: {match['score']['B']} / {match['wickets']['B']}", fill="black", font=font)

    # Draw overs and balls
    overs_completed = match["balls"] // 6
    balls_in_over = match["balls"] % 6
    innings = match["innings"]
    draw.text((20, 350), f"Innings: {innings}", fill="white", font=font)
    draw.text((20, 370), f"Overs: {overs_completed}.{balls_in_over} / {match['overs']}", fill="white", font=font)

    # Save to bytes
    bio = BytesIO()
    bio.name = "scoreboard.png"
    img.save(bio, "PNG")
    bio.seek(0)

    await context.bot.send_photo(chat_id=chat_id, photo=InputFile(bio), caption="Current Scoreboard")

# --- Score Command ---

async def score_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.id not in MATCHES:
        await update.message.reply_text("No ongoing match in this chat.")
        return
    await send_scoreboard(chat.id, context)

# --- Bonus and Penalty Commands ---

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

# --- End Match Command ---

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

    if score_A > score_B:
        result = f"Team A ({match['team_A_name']}) won by {score_A - score_B} runs!"
    elif score_B > score_A:
        result = f"Team B ({match['team_B_name']}) won by {len(match['team_B']) - match['wickets']['B']} wickets!"
    else:
        result = "The match is a tie!"

    await update.message.reply_text(f"Match ended!\nFinal Score:\nTeam A: {score_A}\nTeam B: {score_B}\n\nResult: {result}")

    # Cleanup
    del MATCHES[chat.id]

# --- Register Part 4 Handlers ---

def register_part4_handlers(application):
    application.add_handler(CommandHandler("inningswap", inningswap_command))
    application.add_handler(CallbackQueryHandler(inningswap_callback, pattern="^inningswap_"))
    application.add_handler(CommandHandler("score", score_command))
    application.add_handler(CommandHandler("bonus", bonus_command))
    application.add_handler(CommandHandler("penalty", penalty_command))
    application.add_handler(CommandHandler("endmatch", endmatch_command))
# --- Part 5: Helpers, Full Main, and Deployment Tips ---

import sys

# Helper: Check if user is host of a match in chat
def is_host(user_id, chat_id):
    match = MATCHES.get(chat_id)
    return match and match.get("host_id") == user_id

# Helper: Validate player number input
def valid_player_number(num_str, team):
    if not num_str.isdigit():
        return False
    num = int(num_str)
    return 1 <= num <= len(team)

# Helper: Swap striker and non-striker
def swap_strike(match):
    match["striker"], match["non_striker"] = match["non_striker"], match["striker"]

# --- Full main combining all parts ---

async def main():
    application = ApplicationBuilder().token(TOKEN).build()

    # Part 1 handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("register", register))
    application.add_handler(CommandHandler("profile", profile))
    application.add_handler(CommandHandler("help", help_command))

    # Part 2 handlers
    register_part2_handlers(application)

    # Part 3 handlers
    register_part3_handlers(application)

    # Part 4 handlers
    register_part4_handlers(application)

    application.post_init = on_startup

    logger.info("Starting bot...")
    await application.run_polling()

if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
        sys.exit()

# --- Deployment Tips ---

"""
1. Create a 'runtime.txt' file with your Python version, e.g.:
   python-3.10.9

2. Create 'requirements.txt' with dependencies:
   python-telegram-bot==20.3
   motor<3.6
   pymongo<4.9
   nest_asyncio==1.5.6
   pillow==9.5.0
   aiohttp==3.8.1

3. Ensure your MongoDB connection string is set in MONGO_URL.

4. Deploy on Railway or any cloud platform supporting Python.

5. Use polling mode as shown for easy deployment without webhook setup.

6. Test commands step-by-step starting with /start and /register.

7. Follow host instructions printed by the bot carefully.

8. For any issues, check logs and update dependencies accordingly.

"""

