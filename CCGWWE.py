import logging
import random
import asyncio
from datetime import datetime, timedelta
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

import nest_asyncio
nest_asyncio.apply()

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, InputFile
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from motor.motor_asyncio import AsyncIOMotorClient

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# === CONFIG ===
TOKEN = "8156231369:AAHDFvjD9Aur9y5QjB5YWzvCQp7bUdLuuEc"
ADMIN_IDS = {123456789}  # Replace with your admin IDs
MONGO_URL = "mongodb://mongo:GhpHMiZizYnvJfKIQKxoDbRyzBCpqEyC@mainline.proxy.rlwy.net:54853"

# === DATABASE SETUP ===
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client.handcricket_unified
users_collection = db.users

# === GLOBAL DATA STRUCTURES ===
USERS = {}
CCL_GROUP_MATCHES = {}
COINS_EMOJI = "🪙"

# === USER MANAGEMENT ===
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

# === SCOREBOARD IMAGE TEMPLATE ===
def create_scoreboard_template(width=800, height=400):
    img = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(img)

    # Header and footer
    draw.rectangle([(0, 0), (width, 60)], fill="#003366")
    draw.rectangle([(0, height - 40), (width, height)], fill="#003366")

    # Dividers
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

# === LMS (Last Man Standing) RULE ===
def is_lms_scenario(match):
    total_players = len(match["team_A"])
    if total_players != 8:
        return False
    batting_key = match["batting_team"]
    wickets = match["wickets"][batting_key]
    return wickets == 7  # 7 wickets down means last man bats alone

# === BASIC COMMANDS ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)
    await save_user(user.id)
    await update.message.reply_text(
        f"Welcome to Unified CCL HandCricket Bot, {USERS[user.id]['name']}! Use /register to get 4000 {COINS_EMOJI}.",
        parse_mode="Markdown",
    )

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)
    u = USERS[user.id]
    if u["registered"]:
        await update.message.reply_text("You have already registered.", parse_mode="Markdown")
        return
    u["coins"] += 4000
    u["registered"] = True
    await save_user(user.id)
    await update.message.reply_text(f"Registered! You received 4000 {COINS_EMOJI}.", parse_mode="Markdown")

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
    )
    await update.message.reply_text(text, parse_mode="Markdown")
# Helper function to format team display
def format_team(team_name, players, captain_index=None):
    text = f"**{team_name}**\n"
    if not players:
        text += "_No players added yet._\n"
        return text
    for i, player in enumerate(players, 1):
        cap_mark = " (c)" if captain_index == i else ""
        text += f"{i}) {player['name']}{cap_mark}\n"
    return text

# /cclgroup command - Host starts a new group match
async def cclgroup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("❌ This command can only be used in groups.")
        return

    if chat.id in CCL_GROUP_MATCHES:
        await update.message.reply_text("A CCL group match is already ongoing in this group.")
        return

    match_data = {
        "host_id": user.id,
        "team_A": [],
        "team_B": [],
        "team_A_name": "Team A",
        "team_B_name": "Team B",
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
        "innings": 1,
    }

    CCL_GROUP_MATCHES[chat.id] = match_data
    await update.message.reply_text(
        f"🏏 CCL Group match initiated by {USERS[user.id]['name']}.\n"
        "Host can add players with /add_A @username or /add_B @username.\n"
        "Use /teams to see current teams."
    )

# /add_A command - add player to Team A
async def add_A_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    args = context.args

    if chat.id not in CCL_GROUP_MATCHES:
        await update.message.reply_text("No ongoing CCL group match in this chat. Use /cclgroup to start.")
        return

    match = CCL_GROUP_MATCHES[chat.id]
    if user.id != match["host_id"]:
        await update.message.reply_text("Only the host can add players.")
        return

    if not args:
        await update.message.reply_text("Usage: /add_A @username")
        return

    username = args[0].lstrip("@").lower()

    player = None
    for u in USERS.values():
        if u["name"].lower() == username:
            player = u
            break

    if not player:
        await update.message.reply_text(f"User {args[0]} not found or not registered.")
        return

    if any(p["user_id"] == player["user_id"] for p in match["team_A"]):
        await update.message.reply_text(f"{player['name']} is already in Team A.")
        return
    if any(p["user_id"] == player["user_id"] for p in match["team_B"]):
        await update.message.reply_text(f"{player['name']} is already in Team B.")
        return

    match["team_A"].append(player)
    await update.message.reply_text(f"{player['name']} added to Team A.")

# /add_B command - add player to Team B
async def add_B_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    args = context.args

    if chat.id not in CCL_GROUP_MATCHES:
        await update.message.reply_text("No ongoing CCL group match in this chat. Use /cclgroup to start.")
        return

    match = CCL_GROUP_MATCHES[chat.id]
    if user.id != match["host_id"]:
        await update.message.reply_text("Only the host can add players.")
        return

    if not args:
        await update.message.reply_text("Usage: /add_B @username")
        return

    username = args[0].lstrip("@").lower()

    player = None
    for u in USERS.values():
        if u["name"].lower() == username:
            player = u
            break

    if not player:
        await update.message.reply_text(f"User {args[0]} not found or not registered.")
        return

    if any(p["user_id"] == player["user_id"] for p in match["team_B"]):
        await update.message.reply_text(f"{player['name']} is already in Team B.")
        return
    if any(p["user_id"] == player["user_id"] for p in match["team_A"]):
        await update.message.reply_text(f"{player['name']} is already in Team A.")
        return

    match["team_B"].append(player)
    await update.message.reply_text(f"{player['name']} added to Team B.")

# /teams command - show current teams
async def teams_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    if chat.id not in CCL_GROUP_MATCHES:
        await update.message.reply_text("No ongoing CCL group match in this chat.")
        return

    match = CCL_GROUP_MATCHES[chat.id]

    text = ""
    text += format_team(match["team_A_name"], match["team_A"], match.get("captain_A"))
    text += "\n"
    text += format_team(match["team_B_name"], match["team_B"], match.get("captain_B"))

    await update.message.reply_text(text, parse_mode="Markdown")

# /cap_A command - assign captain for Team A
async def cap_A_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    args = context.args

    if chat.id not in CCL_GROUP_MATCHES:
        await update.message.reply_text("No ongoing CCL group match in this chat.")
        return

    match = CCL_GROUP_MATCHES[chat.id]
    if user.id != match["host_id"]:
        await update.message.reply_text("Only the host can assign captains.")
        return

    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /cap_A <player_number>")
        return

    num = int(args[0])
    if num < 1 or num > len(match["team_A"]):
        await update.message.reply_text("Invalid player number for Team A.")
        return

    match["captain_A"] = num
    player = match["team_A"][num - 1]
    await update.message.reply_text(f"{player['name']} is now captain of Team A.")

# /cap_B command - assign captain for Team B
async def cap_B_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    args = context.args

    if chat.id not in CCL_GROUP_MATCHES:
        await update.message.reply_text("No ongoing CCL group match in this chat.")
        return

    match = CCL_GROUP_MATCHES[chat.id]
    if user.id != match["host_id"]:
        await update.message.reply_text("Only the host can assign captains.")
        return

    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /cap_B <player_number>")
        return

    num = int(args[0])
    if num < 1 or num > len(match["team_B"]):
        await update.message.reply_text("Invalid player number for Team B.")
        return

    match["captain_B"] = num
    player = match["team_B"][num - 1]
    await update.message.reply_text(f"{player['name']} is now captain of Team B.")

# /setovers command - host sets overs with inline buttons (1-20)
async def set_overs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.id not in CCL_GROUP_MATCHES:
        await update.message.reply_text("No ongoing CCL group match in this chat.")
        return

    match = CCL_GROUP_MATCHES[chat.id]
    if user.id != match["host_id"]:
        await update.message.reply_text("Only the host can set overs.")
        return

    buttons = []
    for i in range(1, 21):
        buttons.append(InlineKeyboardButton(str(i), callback_data=f"setovers_{i}"))

    keyboard = [buttons[i:i+4] for i in range(0, 20, 4)]
    await update.message.reply_text("Select number of overs:", reply_markup=InlineKeyboardMarkup(keyboard))

# Callback handler for overs selection
async def set_overs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    chat = query.message.chat

    if chat.id not in CCL_GROUP_MATCHES:
        await query.answer("No ongoing match.")
        return

    match = CCL_GROUP_MATCHES[chat.id]
    if user.id != match["host_id"]:
        await query.answer("Only host can set overs.")
        return

    _, overs_str = query.data.split("_")
    overs = int(overs_str)
    match["overs"] = overs
    match["state"] = "overs_set"

    await query.message.edit_text(f"Overs set to {overs}. Use /startmatch to begin the match.")
    await query.answer()
# /startmatch command - starts the match after setup is complete
async def startmatch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.id not in CCL_GROUP_MATCHES:
        await update.message.reply_text("No ongoing CCL group match in this chat.")
        return

    match = CCL_GROUP_MATCHES[chat.id]

    if user.id != match["host_id"]:
        await update.message.reply_text("Only the host can start the match.")
        return

    if match["state"] != "overs_set":
        await update.message.reply_text("Please complete setup before starting the match (assign captains and set overs).")
        return

    if not match["captain_A"] or not match["captain_B"]:
        await update.message.reply_text("Both teams must have captains assigned before starting.")
        return

    # Send DM to captains to ask for team names
    captain_A = match["team_A"][match["captain_A"] - 1]
    captain_B = match["team_B"][match["captain_B"] - 1]

    try:
        await context.bot.send_message(
            chat_id=captain_A["user_id"],
            text="You are the captain of Team A. Please reply with your team name."
        )
        await context.bot.send_message(
            chat_id=captain_B["user_id"],
            text="You are the captain of Team B. Please reply with your team name."
        )
    except Exception:
        await update.message.reply_text("Failed to send DM to captains. Make sure they have started a chat with the bot.")
        return

    match["state"] = "awaiting_team_names"
    await update.message.reply_text("Match started! Waiting for captains to send their team names in DM.")

# Handler for captains sending team names in DM
async def dm_team_name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()

    found_match = None
    for match in CCL_GROUP_MATCHES.values():
        if match["state"] == "awaiting_team_names":
            captain_A = match["team_A"][match["captain_A"] - 1]
            captain_B = match["team_B"][match["captain_B"] - 1]
            if user.id == captain_A["user_id"]:
                match["team_A_name"] = text
                found_match = match
            elif user.id == captain_B["user_id"]:
                match["team_B_name"] = text
                found_match = match

    if not found_match:
        await update.message.reply_text("You are not currently expected to send a team name.")
        return

    if found_match["team_A_name"] and found_match["team_B_name"]:
        found_match["state"] = "toss"
        chat_id = None
        for c_id, m in CCL_GROUP_MATCHES.items():
            if m == found_match:
                chat_id = c_id
                break
        if chat_id:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"Team names set:\n"
                    f"Team A: {found_match['team_A_name']}\n"
                    f"Team B: {found_match['team_B_name']}\n\n"
                    f"{found_match['team_A_name']} captain, please choose Heads or Tails for the toss."
                ),
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("Heads", callback_data="toss_heads"),
                        InlineKeyboardButton("Tails", callback_data="toss_tails"),
                    ]
                ])
            )
        await update.message.reply_text("Team name received. Toss will begin shortly.")

# Toss callback handler
async def toss_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    chat = query.message.chat

    if chat.id not in CCL_GROUP_MATCHES:
        await query.answer("No ongoing match here.")
        return

    match = CCL_GROUP_MATCHES[chat.id]
    if match["state"] != "toss":
        await query.answer("Toss not in progress.")
        return

    captain_A = match["team_A"][match["captain_A"] - 1]
    if user.id != captain_A["user_id"]:
        await query.answer("Only Team A captain can choose toss.")
        return

    toss_choice = query.data.split("_")[1]  # heads or tails
    toss_result = random.choice(["heads", "tails"])

    if toss_choice == toss_result:
        match["toss_winner"] = "A"
        match["toss_loser"] = "B"
    else:
        match["toss_winner"] = "B"
        match["toss_loser"] = "A"

    match["state"] = "toss_winner_choice"

    await query.message.edit_text(
        f"The coin landed on {toss_result.capitalize()}!\n"
        f"{match['team_A_name'] if match['toss_winner']=='A' else match['team_B_name']} won the toss.\n"
        f"Captain, choose to Bat or Bowl first.",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Bat 🏏", callback_data="tosswin_bat"),
                InlineKeyboardButton("Bowl ⚾", callback_data="tosswin_bowl"),
            ]
        ])
    )
    await query.answer()

# Toss winner chooses Bat or Bowl
async def toss_winner_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat = query.message.chat

    if chat.id not in CCL_GROUP_MATCHES:
        await query.answer("No ongoing match here.")
        return

    match = CCL_GROUP_MATCHES[chat.id]
    if match["state"] != "toss_winner_choice":
        await query.answer("Not the right time to choose.")
        return

    choice = query.data.split("_")[1]  # bat or bowl

    if match["toss_winner"] == "A":
        if choice == "bat":
            match["batting_team"] = "A"
            match["bowling_team"] = "B"
        else:
            match["batting_team"] = "B"
            match["bowling_team"] = "A"
    else:
        if choice == "bat":
            match["batting_team"] = "B"
            match["bowling_team"] = "A"
        else:
            match["batting_team"] = "A"
            match["bowling_team"] = "B"

    match["state"] = "in_progress"
    match["innings"] = 1
    match["score"] = {"A": 0, "B": 0}
    match["wickets"] = {"A": 0, "B": 0}
    match["balls"] = 0
    match["striker"] = None
    match["non_striker"] = None
    match["current_bowler"] = None

    await query.message.edit_text(
        f"{match['team_A_name']} vs {match['team_B_name']} match has begun!\n"
        f"{match['team_A_name'] if match['batting_team']=='A' else match['team_B_name']} batting first."
    )
    await query.answer()
# Helper to rotate strike unless LMS scenario applies
def rotate_strike(match):
    if is_lms_scenario(match):
        # No strike rotation in LMS scenario
        return
    match["striker"], match["non_striker"] = match["non_striker"], match["striker"]

# /bat command - assign striker and non-striker by player numbers
async def bat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    args = context.args

    if chat.id not in CCL_GROUP_MATCHES:
        await update.message.reply_text("No ongoing CCL group match here.")
        return

    match = CCL_GROUP_MATCHES[chat.id]

    if user.id != match["host_id"]:
        await update.message.reply_text("Only the host can assign batsmen.")
        return

    if len(args) < 2 or not all(arg.isdigit() for arg in args[:2]):
        await update.message.reply_text("Usage: /bat <striker_number> <non_striker_number>")
        return

    striker_num, non_striker_num = map(int, args[:2])
    team_key = match["batting_team"]
    team = match["team_A"] if team_key == "A" else match["team_B"]

    if not (1 <= striker_num <= len(team)) or not (1 <= non_striker_num <= len(team)):
        await update.message.reply_text("Invalid player numbers.")
        return

    if striker_num == non_striker_num:
        await update.message.reply_text("Striker and non-striker cannot be the same player.")
        return

    match["striker"] = striker_num - 1
    match["non_striker"] = non_striker_num - 1

    await update.message.reply_text(
        f"Striker: {team[match['striker']]['name']}\n"
        f"Non-Striker: {team[match['non_striker']]['name']}"
    )

# /bowl command - assign current bowler by player number
async def bowl_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    args = context.args

    if chat.id not in CCL_GROUP_MATCHES:
        await update.message.reply_text("No ongoing CCL group match here.")
        return

    match = CCL_GROUP_MATCHES[chat.id]

    if user.id != match["host_id"]:
        await update.message.reply_text("Only the host can assign the bowler.")
        return

    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /bowl <player_number>")
        return

    bowler_num = int(args[0])
    team_key = match["bowling_team"]
    team = match["team_A"] if team_key == "A" else match["team_B"]

    if not (1 <= bowler_num <= len(team)):
        await update.message.reply_text("Invalid player number.")
        return

    match["current_bowler"] = bowler_num - 1
    await update.message.reply_text(f"Current bowler: {team[match['current_bowler']]['name']}")

# /runs command - add runs for the current ball and handle strike rotation and LMS rule
async def runs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    args = context.args

    if chat.id not in CCL_GROUP_MATCHES:
        await update.message.reply_text("No ongoing CCL group match here.")
        return

    match = CCL_GROUP_MATCHES[chat.id]

    if user.id != match["host_id"]:
        await update.message.reply_text("Only the host can add runs.")
        return

    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /runs <number_of_runs>")
        return

    runs = int(args[0])
    if runs < 0:
        await update.message.reply_text("Runs cannot be negative.")
        return

    batting_key = match["batting_team"]
    batting_team = match["team_A"] if batting_key == "A" else match["team_B"]

    if match["striker"] is None or match["non_striker"] is None:
        await update.message.reply_text("Please assign batsmen first using /bat command.")
        return

    # Update score
    match["score"][batting_key] += runs

    # Update balls
    match["balls"] += 1

    # Rotate strike if runs is odd and not LMS
    if runs % 2 == 1 and not is_lms_scenario(match):
        rotate_strike(match)

    # Rotate strike at end of over (6 balls) if not LMS
    if match["balls"] % 6 == 0 and not is_lms_scenario(match):
        rotate_strike(match)

    # Generate and send scoreboard image
    await send_scoreboard_image(update, context, match)

# /wicket command - record wicket and handle LMS scenario
async def wicket_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.id not in CCL_GROUP_MATCHES:
        await update.message.reply_text("No ongoing CCL group match here.")
        return

    match = CCL_GROUP_MATCHES[chat.id]

    if user.id != match["host_id"]:
        await update.message.reply_text("Only the host can record wickets.")
        return

    batting_key = match["batting_team"]
    match["wickets"][batting_key] += 1
    match["balls"] += 1

    # If LMS scenario reached, no strike rotation on wicket
    if is_lms_scenario(match):
        # LMS batsman continues alone, no strike change
        pass
    else:
        # Normal wicket: new batsman to be assigned with /bat command
        # Reset striker to None to force assignment
        match["striker"] = None

    await update.message.reply_text(
        f"Wicket fallen!\n"
        f"Score: {match['score'][batting_key]}/{match['wickets'][batting_key]}\n"
        f"Overs: {match['balls'] // 6}.{match['balls'] % 6}\n"
        "Assign new batsman using /bat command."
    )

    # Send updated scoreboard image
    await send_scoreboard_image(update, context, match)

# Function to generate and send scoreboard image
async def send_scoreboard_image(update: Update, context: ContextTypes.DEFAULT_TYPE, match):
    img, draw, font = create_scoreboard_template()
    width, height = img.size

    # Draw dynamic data
    # Team names
    draw.text((20, 90), match["team_A_name"], fill="black", font=font)
    draw.text((width//2 + 20, 90), match["team_B_name"], fill="black", font=font)

    # Scores and wickets
    draw.text((20, 140), f"Score: {match['score']['A']}/{match['wickets']['A']}", fill="black", font=font)
    draw.text((width//2 + 20, 140), f"Score: {match['score']['B']}/{match['wickets']['B']}", fill="black", font=font)

    # Overs
    overs_balls = match["balls"]
    overs = overs_balls // 6
    balls = overs_balls % 6
    draw.text((20, 180), f"Overs: {overs}.{balls}", fill="black", font=font)
    draw.text((width//2 + 20, 180), f"Overs: N/A", fill="black", font=font)  # Bowling team overs can be added

    # Innings
    draw.text((20, height - 35), f"Innings: {match['innings']}", fill="white", font=font)

    # Striker and non-striker
    batting_key = match["batting_team"]
    batting_team = match["team_A"] if batting_key == "A" else match["team_B"]

    striker_name = batting_team[match["striker"]]["name"] if match["striker"] is not None else "N/A"
    non_striker_name = batting_team[match["non_striker"]]["name"] if match["non_striker"] is not None else "N/A"

    draw.text((20, 220), f"Striker: {striker_name}", fill="black", font=font)
    draw.text((20, 260), f"Non-Striker: {non_striker_name}", fill="black", font=font)

    # Current bowler
    bowling_key = match["bowling_team"]
    bowling_team = match["team_A"] if bowling_key == "A" else match["team_B"]
    bowler_name = bowling_team[match["current_bowler"]]["name"] if match["current_bowler"] is not None else "N/A"
    draw.text((width//2 + 20, 220), f"Bowler: {bowler_name}", fill="black", font=font)

    # Save image to bytes
    bio = BytesIO()
    bio.name = "scoreboard.png"
    img.save(bio, "PNG")
    bio.seek(0)

    # Send photo
    await update.message.reply_photo(photo=InputFile(bio), caption="Current Scoreboard")

# /score command - show current score summary (text only)
async def score_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    if chat.id not in CCL_GROUP_MATCHES:
        await update.message.reply_text("No ongoing CCL group match here.")
        return

    match = CCL_GROUP_MATCHES[chat.id]

    def team_score_text(team_key):
        team = match["team_A"] if team_key == "A" else match["team_B"]
        score = match["score"][team_key]
        wickets = match["wickets"][team_key]
        balls = match["balls"] if match["batting_team"] == team_key else 0
        overs = balls // 6
        balls_left = balls % 6
        return f"{match['team_A_name'] if team_key == 'A' else match['team_B_name']} - {score}/{wickets} in {overs}.{balls_left} overs"

    text = (
        f"🏏 Current Score:\n"
        f"{team_score_text('A')}\n"
        f"{team_score_text('B')}\n"
        f"Innings: {match['innings']}\n"
    )
    await update.message.reply_text(text)
# /bonus command - host adds bonus runs to a team
async def bonus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    args = context.args

    if chat.id not in CCL_GROUP_MATCHES:
        await update.message.reply_text("No ongoing CCL group match here.")
        return

    match = CCL_GROUP_MATCHES[chat.id]
    if user.id != match["host_id"]:
        await update.message.reply_text("Only the host can add bonus runs.")
        return

    if len(args) < 2 or args[0].upper() not in ["A", "B"] or not args[1].isdigit():
        await update.message.reply_text("Usage: /bonus <A|B> <runs>")
        return

    team_key = args[0].upper()
    runs = int(args[1])

    match["score"][team_key] += runs
    await update.message.reply_text(f"Added {runs} bonus runs to Team {team_key}.")

# /penalty command - host subtracts runs from a team
async def penalty_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    args = context.args

    if chat.id not in CCL_GROUP_MATCHES:
        await update.message.reply_text("No ongoing CCL group match here.")
        return

    match = CCL_GROUP_MATCHES[chat.id]
    if user.id != match["host_id"]:
        await update.message.reply_text("Only the host can apply penalties.")
        return

    if len(args) < 2 or args[0].upper() not in ["A", "B"] or not args[1].isdigit():
        await update.message.reply_text("Usage: /penalty <A|B> <runs>")
        return

    team_key = args[0].upper()
    runs = int(args[1])

    match["score"][team_key] = max(0, match["score"][team_key] - runs)
    await update.message.reply_text(f"Subtracted {runs} penalty runs from Team {team_key}.")

# /endmatch command - host ends the match and declares result
async def endmatch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.id not in CCL_GROUP_MATCHES:
        await update.message.reply_text("No ongoing CCL group match here.")
        return

    match = CCL_GROUP_MATCHES[chat.id]
    if user.id != match["host_id"]:
        await update.message.reply_text("Only the host can end the match.")
        return

    score_A = match["score"]["A"]
    wickets_A = match["wickets"]["A"]
    score_B = match["score"]["B"]
    wickets_B = match["wickets"]["B"]

    if score_A > score_B:
        result = f"{match['team_A_name']} won by {score_A - score_B} runs 🏆"
    elif score_B > score_A:
        wickets_left = 10 - wickets_B
        result = f"{match['team_B_name']} won by {wickets_left} wicket{'s' if wickets_left != 1 else ''} 🏆"
    else:
        result = "Match tied 🤝"

    def team_score_text(team_key):
        team = match["team_A"] if team_key == "A" else match["team_B"]
        score = match["score"][team_key]
        wickets = match["wickets"][team_key]
        overs = match["overs"] if match["overs"] else 0
        return f"{match['team_A_name'] if team_key == 'A' else match['team_B_name']} - {score}/{wickets} in {overs} overs"

    scoreboard = (
        f"🏏 Match Ended!\n\n"
        f"{team_score_text('A')}\n"
        f"{team_score_text('B')}\n\n"
        f"Result: {result}"
    )

    await update.message.reply_text(scoreboard)
    del CCL_GROUP_MATCHES[chat.id]

# Host change voting mechanism
HOST_CHANGE_VOTES = {}

async def changehost_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.id not in CCL_GROUP_MATCHES:
        await update.message.reply_text("No ongoing CCL group match here.")
        return

    match = CCL_GROUP_MATCHES[chat.id]
    if user.id == match["host_id"]:
        await update.message.reply_text("You are already the host.")
        return

    voters = HOST_CHANGE_VOTES.setdefault(chat.id, set())
    if user.id in voters:
        await update.message.reply_text("You have already voted to change host.")
        return

    voters.add(user.id)
    total_players = len(match["team_A"]) + len(match["team_B"])
    votes_needed = total_players // 2 + 1

    if len(voters) >= votes_needed:
        HOST_CHANGE_VOTES.pop(chat.id, None)
        match["host_id"] = user.id
        await update.message.reply_text(f"Host changed to {USERS[user.id]['name']} by vote.")
    else:
        await update.message.reply_text(f"{len(voters)}/{votes_needed} votes to change host.")

async def behost_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    if chat.id not in CCL_GROUP_MATCHES:
        await update.message.reply_text("No ongoing CCL group match here.")
        return

    match = CCL_GROUP_MATCHES[chat.id]
    if user.id == match["host_id"]:
        await update.message.reply_text("You are already the host.")
        return

    await update.message.reply_text("You must first initiate a host change vote with /changehost.")

# Unknown command handler
async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Unknown command. Use /help to see available commands.")

# Error handler
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
async def main():
    await load_users()

    application = ApplicationBuilder().token(TOKEN).build()

    # Basic commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("register", register))
    application.add_handler(CommandHandler("profile", profile))

    # Group match setup commands
    application.add_handler(CommandHandler("cclgroup", cclgroup_command))
    application.add_handler(CommandHandler("add_A", add_A_command))
    application.add_handler(CommandHandler("add_B", add_B_command))
    application.add_handler(CommandHandler("teams", teams_command))
    application.add_handler(CommandHandler("cap_A", cap_A_command))
    application.add_handler(CommandHandler("cap_B", cap_B_command))
    application.add_handler(CommandHandler("setovers", set_overs_command))
    application.add_handler(CallbackQueryHandler(set_overs_callback, pattern=r"^setovers_\d+$"))

    # Match start and toss
    application.add_handler(CommandHandler("startmatch", startmatch_command))
    application.add_handler(CallbackQueryHandler(toss_callback, pattern=r"^toss_(heads|tails)$"))
    application.add_handler(CallbackQueryHandler(toss_winner_choice_callback, pattern=r"^tosswin_(bat|bowl)$"))

    # Matchplay commands
    application.add_handler(CommandHandler("bat", bat_command))
    application.add_handler(CommandHandler("bowl", bowl_command))
    application.add_handler(CommandHandler("runs", runs_command))
    application.add_handler(CommandHandler("wicket", wicket_command))
    application.add_handler(CommandHandler("score", score_command))

    # Bonus, penalty, and endmatch
    application.add_handler(CommandHandler("bonus", bonus_command))
    application.add_handler(CommandHandler("penalty", penalty_command))
    application.add_handler(CommandHandler("endmatch", endmatch_command))

    # Host management
    application.add_handler(CommandHandler("changehost", changehost_command))
    application.add_handler(CommandHandler("behost", behost_command))

    # DM handler for captains sending team names
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT, dm_team_name_handler))

    # Unknown command handler
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    # Error handler
    application.add_error_handler(error_handler)

    logger.info("Bot started.")
    await application.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
    
