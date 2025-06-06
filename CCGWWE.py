import logging
import random
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    CallbackQueryHandler, MessageHandler, filters
)
from pymongo import MongoClient

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# === CONFIG ===
BOT_TOKEN = '8133604799:AAF2dE86UjRxfAdUcqyoz3O9RgaCeTwaoHM'
MONGO_URL = 'mongodb://mongo:GhpHMiZizYnvJfKIQKxoDbRyzBCpqEyC@mainline.proxy.rlwy.net:54853'

# === MONGO DB SETUP ===
client = MongoClient(MONGO_URL)
db = client.mafia_game_bot
players_col = db.players       # stores players info
state_col = db.state           # stores game state, registrations, etc.

# === INITIALIZE GAME STATE ===
if not state_col.find_one({"_id": "main"}):
    state_col.insert_one({"_id": "main", "group_id": None, "registered": []})

# === HELPER FUNCTIONS ===

def get_registered():
    state = state_col.find_one({"_id": "main"})
    return state.get("registered", [])

def add_player(user_id, name):
    registered = get_registered()
    if user_id not in registered:
        registered.append(user_id)
        state_col.update_one({"_id": "main"}, {"$set": {"registered": registered}})
        players_col.update_one(
            {"_id": user_id},
            {"$set": {"name": name, "coins": 0, "alive": True}},
            upsert=True
        )
        return True
    return False

def clear_all():
    players_col.delete_many({})
    state_col.update_one({"_id": "main"}, {"$set": {"registered": []}})

# === COMMANDS ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to Mafia Game Bot!\n\n"
        "Register in the group to join games."
    )

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    added = add_player(user.id, user.full_name)
    if added:
        await update.message.reply_text(f"✅ You have registered for the Mafia game, {user.full_name}!")
    else:
        await update.message.reply_text("ℹ️ You are already registered.")

async def registration_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    registered = get_registered()
    if not registered:
        await update.message.reply_text("No players registered yet.")
        return

    text = "📝 *Registration Open*\n\n*Registered Players:*"
    for user_id in registered:
        player = players_col.find_one({"_id": user_id})
        name = player.get("name", "Unknown")
        text += f"\n- [{name}](tg://user?id={user_id})"
    keyboard = [[InlineKeyboardButton("Join (DM)", url=f"tg://resolve?domain={context.bot.username}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start - Welcome message\n"
        "/register - Register for the game\n"
        "/status - Show registered players\n"
        "/cancel - Admin only: cancel current game\n"
        "/assign_roles - Admin only: assign roles\n"
        "/coins - Show your coins\n"
    )

# === MAIN ===
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("register", register))
    app.add_handler(CommandHandler("status", registration_status))
    app.add_handler(CommandHandler("help", help_command))

    app.run_polling()

if __name__ == "__main__":
    main()
import asyncio

# === ROLES & ROLE SUMMARIES ===
ROLE_SUMMARIES = {
    "Citizen": "🧑 *Citizen*\nYou have no special powers. Survive and help lynch the mafia.",
    "Doctor": "💉 *Doctor*\nYou can protect one player each night from being killed.",
    "Detective": "🕵️ *Detective*\nYou can investigate one player each night to learn if they are Mafia or not.",
    "Mafia": "🕶️ *Mafia*\nYou collaborate with Mafia team to kill town members at night.",
    "Don": "👑 *Don*\nHead of Mafia. Your kill vote overrides other Mafia votes.",
    "Framer": "🎭 *Framer*\nYou confuse the Detective by framing a player as Mafia.",
    "Watcher": "👁️ *Watcher*\nYou watch one player at night to learn who visits them."
}

# === ROLE ASSIGNMENT FUNCTION ===
def assign_roles(num_players):
    """
    Returns a dict user_id->role
    Assign roles based on player count
    """

    registered = get_registered()
    random.shuffle(registered)

    roles = []

    # Assign roles based on player count
    if num_players == 4:
        roles = ["Don", "Mafia", "Doctor", "Citizen"]
    elif num_players == 5:
        roles = ["Don", "Mafia", "Doctor", "Detective", "Citizen"]
    elif num_players == 6:
        roles = ["Don", "Mafia", "Doctor", "Detective", "Framer", "Citizen"]
    elif num_players == 7:
        roles = ["Don", "Mafia", "Doctor", "Detective", "Framer", "Citizen", "Citizen"]
    elif num_players == 8:
        roles = ["Don", "Mafia", "Doctor", "Detective", "Framer", "Watcher", "Citizen", "Citizen"]
    elif num_players == 9:
        roles = ["Don", "Mafia", "Mafia", "Doctor", "Detective", "Framer", "Watcher", "Citizen", "Citizen"]
    else:
        # For 10 to 15 players: balanced distribution, max 4 mafia (Don + Mafia + Framer)
        mafia_count = min(4, num_players // 3)  # roughly 1/3 mafia max
        town_count = num_players - mafia_count - 2  # minus Don and Doctor
        roles = ["Don"] + ["Mafia"] * (mafia_count - 1) + ["Doctor", "Detective", "Framer", "Watcher"]
        roles += ["Citizen"] * (num_players - len(roles))

    # Trim roles to exactly num_players
    roles = roles[:num_players]

    role_map = {uid: role for uid, role in zip(registered, roles)}
    return role_map

# === SEND ROLE DM ===
async def send_role_dm(user_id: int, role: str, app):
    try:
        summary = ROLE_SUMMARIES.get(role, "No role info.")
        text = f"🎭 *Your Role:* {role}\n\n{summary}"
        await app.bot.send_message(chat_id=user_id, text=text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.warning(f"Failed to send role DM to {user_id}: {e}")

# === ADMIN COMMAND TO ASSIGN ROLES ===
async def assign_roles_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    # Only allow in groups and only admin can assign roles
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("❌ This command can only be used in groups.")
        return

    # Check admin
    member = await chat.get_member(user.id)
    if member.status not in ["administrator", "creator"]:
        await update.message.reply_text("❌ Only group admins can assign roles.")
        return

    registered = get_registered()
    num_players = len(registered)

    if num_players < 4:
        await update.message.reply_text("⚠️ At least 4 players needed to assign roles.")
        return

    role_map = assign_roles(num_players)

    # Save roles in DB
    state_col.update_one({"_id": "main"}, {"$set": {"roles": role_map, "game_started": True}})

    # Send role messages in DM concurrently
    await update.message.reply_text(f"✅ Assigned roles to {num_players} players. Sending roles in DM...")

    app = context.application

    for uid, role in role_map.items():
        await send_role_dm(uid, role, app)

    await update.message.reply_text("✅ Roles sent privately to all players.")
from collections import defaultdict

# === GAME STATE TRACKING ===

def get_game_state():
    state = state_col.find_one({"_id": "main"})
    if not state:
        return {}
    return state

def update_game_state(updates: dict):
    state_col.update_one({"_id": "main"}, {"$set": updates})

# === VOTING STRUCTURE ===

def reset_votes():
    update_game_state({"votes": {}, "night_votes": {}, "lynch_votes": {}})

def add_vote(voter_id, target_id, vote_type="lynch"):
    """
    vote_type: 'lynch' for daytime lynch votes,
               'night' for mafia kill votes
    """
    state = get_game_state()
    votes = state.get(f"{vote_type}_votes", {})
    votes[str(voter_id)] = target_id
    update_game_state({f"{vote_type}_votes": votes})

def count_votes(vote_type="lynch"):
    state = get_game_state()
    votes = state.get(f"{vote_type}_votes", {})
    tally = defaultdict(int)
    for target_id in votes.values():
        tally[target_id] += 1
    return tally

# === EXAMPLE: TALLY LYNCH VOTES ===
def lynch_winner():
    tally = count_votes("lynch")
    if not tally:
        return None
    max_votes = max(tally.values())
    winners = [uid for uid, count in tally.items() if count == max_votes]
    if len(winners) == 1:
        return winners[0]
    # Tie or no majority
    return None

# === KILL DECISION BY DON OVERRIDE ===
def night_kill_decision():
    state = get_game_state()
    night_votes = state.get("night_votes", {})
    roles = state.get("roles", {})
    don_vote = None
    mafia_votes = defaultdict(int)

    for voter_str, target in night_votes.items():
        voter = int(voter_str)
        role = roles.get(voter)
        if role == "Don":
            don_vote = target
        else:
            mafia_votes[target] += 1

    if don_vote is not None:
        # Don's choice overrides
        return don_vote
    if not mafia_votes:
        return None

    # Highest voted target by mafia members (excluding Don)
    max_votes = max(mafia_votes.values())
    top_targets = [target for target, count in mafia_votes.items() if count == max_votes]
    if len(top_targets) == 1:
        return top_targets[0]
    return None  # tie or no kill

# === ELIMINATE PLAYER ===
def eliminate_player(user_id):
    players_col.update_one({"_id": user_id}, {"$set": {"alive": False}})

# === CHECK ALIVE PLAYERS ===
def get_alive_players():
    alive = list(players_col.find({"alive": True}))
    return alive

# === ROUND MANAGEMENT ===
async def start_round(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Starts new round: resets votes, announces round, etc.
    """
    update_game_state({"votes": {}, "night_votes": {}, "lynch_votes": {}, "round": 1})
    await update.message.reply_text("🔔 New round started! Players, please cast your votes.")

async def end_round(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Tally votes and update game state accordingly.
    """
    lynched_id = lynch_winner()
    if lynched_id:
        eliminate_player(lynched_id)
        player = players_col.find_one({"_id": lynched_id})
        name = player.get("name", "Unknown")
        await update.message.reply_text(f"☠️ Player [{name}](tg://user?id={lynched_id}) was lynched today!", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("🤝 No player lynched this round.")

    kill_id = night_kill_decision()
    if kill_id:
        eliminate_player(kill_id)
        player = players_col.find_one({"_id": kill_id})
        name = player.get("name", "Unknown")
        await update.message.reply_text(f"🌙 Player [{name}](tg://user?id={kill_id}) was killed last night!", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("🌙 No player was killed last night.")

    # Increment round count
    state = get_game_state()
    current_round = state.get("round", 1) + 1
    update_game_state({"round": current_round})

    await update.message.reply_text(f"⏳ Round {current_round} begins! Cast your votes.")

# Add commands and handlers for voting, etc. in next parts.
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler

# === REGISTRATION ===
async def start_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Starts a new game registration in the group.
    """
    chat_id = update.effective_chat.id
    # Clear previous players and state
    players_col.delete_many({})
    update_game_state({"state": "registration", "round": 0, "votes": {}, "night_votes": {}, "lynch_votes": {}, "roles": {}})
    
    text = (
        "📝 *Registration for Trust Test has started!*\n\n"
        "Players can join by clicking the button below.\n\n"
        "*Registered Players:*\n_None yet_\n\n"
        "Press the button below to join."
    )
    join_button = InlineKeyboardButton("Join 📝", callback_data="join_game")
    keyboard = InlineKeyboardMarkup([[join_button]])
    await context.bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="Markdown")

# === HANDLE JOIN BUTTON ===
async def join_game_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat.id

    # Check registration state
    state = get_game_state()
    if state.get("state") != "registration":
        await query.answer("Registration is not open now.")
        return

    # Check if already joined
    existing = players_col.find_one({"_id": user.id})
    if existing:
        await query.answer("You have already joined!")
        return

    # Add player
    players_col.insert_one({"_id": user.id, "name": user.full_name, "alive": True, "points": 0})
    await query.answer("You joined the game! Check your DM.")

    # Update registration message with new player list
    players = list(players_col.find({}))
    player_names = "\n".join(f"- [{p['name']}](tg://user?id={p['_id']})" for p in players)
    text = (
        "📝 *Registration for Trust Test has started!*\n\n"
        "*Registered Players:*\n"
        f"{player_names}\n\n"
        "Press the button below to join."
    )
    join_button = InlineKeyboardButton("Join 📝", callback_data="join_game")
    keyboard = InlineKeyboardMarkup([[join_button]])
    try:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=query.message.message_id,
                                            text=text, reply_markup=keyboard, parse_mode="Markdown")
    except:
        pass  # message might be edited by another user simultaneously

    # Send DM welcome message
    try:
        await context.bot.send_message(user.id,
            "✅ You joined the Trust Test game! Wait for the registration to end.")
    except:
        pass  # user might have privacy settings

# === ASSIGN ROLES ===
def assign_roles():
    players = list(players_col.find({}))
    num_players = len(players)
    if num_players < 4:
        return False  # Not enough players
    
    # Define role distribution for Trust Test (example):
    # Townies: 50%
    # Mafia: 25%
    # Don: 1
    # Doctor: 1
    # Detective: 1
    # Framer: 1 (if players > 6)
    # Watcher: 1 (if players > 8)

    roles_list = []

    # Basic roles always present
    roles_list.append("Don")
    roles_list.append("Doctor")
    roles_list.append("Detective")

    # Mafia count
    mafia_count = max(1, num_players // 4)
    mafia_count = min(mafia_count, 4)  # max 4 mafia side

    roles_list += ["Mafia"] * (mafia_count -1)  # don included separately

    # Framer for 7+ players
    if num_players >= 7:
        roles_list.append("Framer")
    # Watcher for 9+ players
    if num_players >= 9:
        roles_list.append("Watcher")

    # Fill rest with Townies
    remaining = num_players - len(roles_list)
    roles_list += ["Townie"] * remaining

    # Shuffle roles randomly
    import random
    random.shuffle(roles_list)

    # Assign roles to players
    for i, player in enumerate(players):
        players_col.update_one({"_id": player["_id"]}, {"$set": {"role": roles_list[i], "alive": True, "points": 0}})

    # Save roles in game state for quick access
    roles_map = {p["_id"]: roles_list[i] for i, p in enumerate(players)}
    update_game_state({"roles": roles_map, "state": "in_game", "round": 1})
    return True

# === SEND ROLE DM ===
async def send_role_dm(context: ContextTypes.DEFAULT_TYPE):
    players = list(players_col.find({}))
    bot = context.bot

    role_summaries = {
        "Townie": "🧑 *Townie*\nJust a normal town member. Help find the mafia!",
        "Don": "🕵️‍♂️ *Don*\nHead of Mafia. Your vote decides who gets killed at night.",
        "Mafia": "🧛 *Mafia*\nWork with Don to kill a town member each night.",
        "Doctor": "💉 *Doctor*\nProtect one player each night from being killed.",
        "Detective": "🕵️ *Detective*\nInvestigate one player each night to find if they are Mafia.",
        "Framer": "🎭 *Framer*\nFrame a player to confuse the Detective.",
        "Watcher": "👁️ *Watcher*\nWatch a player to see who they visit at night.",
    }

    for player in players:
        uid = player["_id"]
        role = player.get("role", "Townie")
        summary = role_summaries.get(role, "Just a player.")
        try:
            await bot.send_message(uid, f"Your role is:\n\n{summary}")
        except:
            pass  # Could not send DM

# === COMMAND TO START GAME AFTER REGISTRATION ===
async def start_game_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = get_game_state()

    if state.get("state") != "registration":
        await update.message.reply_text("❌ Registration is not currently open.")
        return

    players = list(players_col.find({}))
    if len(players) < 4:
        await update.message.reply_text("❌ Not enough players to start the game (minimum 4).")
        return

    assigned = assign_roles()
    if not assigned:
        await update.message.reply_text("❌ Could not assign roles, something went wrong.")
        return

    await update.message.reply_text("✅ Roles assigned. Sending role messages...")
    await send_role_dm(context)

    await update.message.reply_text("🎲 Game started! Night phase begins...")

# === CANCEL GAME COMMAND (admin only) ===
async def cancel_game_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    member = await chat.get_member(user.id)
    if not member.status in ("administrator", "creator"):
        await update.message.reply_text("❌ Only admins can cancel the game.")
        return

    players_col.delete_many({})
    update_game_state({"state": "idle", "round": 0, "votes": {}, "night_votes": {}, "lynch_votes": {}, "roles": {}})

    await update.message.reply_text("🛑 Game cancelled by admin.")

# === REGISTER HANDLERS ===
def register_handlers(application):
    application.add_handler(CommandHandler("start_registration", start_registration))
    application.add_handler(CallbackQueryHandler(join_game_callback, pattern="^join_game$"))
    application.add_handler(CommandHandler("start_game", start_game_command))
    application.add_handler(CommandHandler("cancel", cancel_game_command))

# You can add more commands and callbacks in next parts.
import random
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, CallbackQueryHandler

# Helper functions
def get_alive_players():
    return list(players_col.find({"alive": True}))

def get_player_role(user_id):
    player = players_col.find_one({"_id": user_id})
    return player.get("role") if player else None

def update_player_alive(user_id, alive_status):
    players_col.update_one({"_id": user_id}, {"$set": {"alive": alive_status}})

def update_player_points(user_id, points):
    players_col.update_one({"_id": user_id}, {"$inc": {"points": points}})

# === NIGHT ACTIONS ===
async def night_phase(context: ContextTypes.DEFAULT_TYPE):
    """
    Night phase where Mafia/Don kill, Doctor protects, Detective investigates, Framer frames, Watcher watches.
    Collect votes and actions via DMs (you will need handlers for user replies/buttons).
    After all actions are collected, resolve the night.
    """
    state = get_game_state()
    round_num = state.get("round", 1)
    chat_id = state.get("chat_id")

    # Reset night votes
    update_game_state({"night_votes": {}, "lynch_votes": {}})

    alive_players = get_alive_players()

    # Send DM to Mafia + Don to choose kill target
    mafia_players = [p for p in alive_players if p.get("role") in ["Don", "Mafia"]]
    mafia_ids = [p["_id"] for p in mafia_players]

    # Collect kill votes - For simplicity, send a message with inline buttons for each alive player except mafia themselves
    # You will have to implement separate callbacks to handle their choice and store it in night_votes

    # Send DM to Doctor to choose protection target (can protect self)
    # Send DM to Detective to choose investigation target
    # Send DM to Framer to choose framing target
    # Send DM to Watcher to choose who to watch

    # This part requires interactive callbacks & is best done in next parts with actual handlers.

# === PROCESS NIGHT RESULTS ===
async def resolve_night(context: ContextTypes.DEFAULT_TYPE):
    """
    After all night actions collected, resolve kill, protection, investigations, framing, and watcher info.
    Send results as needed.
    """

    state = get_game_state()
    chat_id = state.get("chat_id")
    night_votes = state.get("night_votes", {})
    protection_target = night_votes.get("doctor_protect")
    kill_target = night_votes.get("mafia_kill")
    framed_target = night_votes.get("framer_frame")
    # detective_target = ...
    # watcher_target = ...

    # Don override kill vote if provided (implement logic based on collected votes)

    # Determine if kill is successful
    if kill_target and kill_target != protection_target:
        update_player_alive(kill_target, False)
        # Announce death in group chat
        killed_player = players_col.find_one({"_id": kill_target})
        if killed_player:
            text = f"💀 *{killed_player['name']}* was found dead in the morning..."
            await context.bot.send_message(chat_id, text, parse_mode="Markdown")
    else:
        await context.bot.send_message(chat_id, "😌 No one was killed last night.")

    # Send detective and watcher results to relevant players
    # Send framing info to mafia

    # Update round
    round_num = state.get("round", 1)
    round_num += 1
    update_game_state({"round": round_num})

    # Check win conditions (to be implemented)
    # If game not over, start next day or night phase

# === VOTING & LYNCHING ===
async def start_lynch_phase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Starts voting phase in the group chat to lynch a suspected player.
    Use inline buttons for alive players to vote.
    Collect votes and after time limit announce who is lynched.
    """

    state = get_game_state()
    chat_id = update.effective_chat.id

    alive_players = get_alive_players()
    keyboard = []
    for p in alive_players:
        button = InlineKeyboardButton(p["name"], callback_data=f"vote_{p['_id']}")
        keyboard.append([button])

    markup = InlineKeyboardMarkup(keyboard)
    text = "⚖️ Time to vote! Choose who to lynch:"
    await context.bot.send_message(chat_id, text, reply_markup=markup)

# Callback handler for lynch votes
async def lynch_vote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    voter_id = query.from_user.id
    vote_data = query.data
    chat_id = query.message.chat.id

    if not vote_data.startswith("vote_"):
        return

    vote_target = int(vote_data.split("_")[1])

    state = get_game_state()
    lynch_votes = state.get("lynch_votes", {})

    if voter_id not in [p["_id"] for p in get_alive_players()]:
        await query.answer("You are not alive to vote!")
        return

    lynch_votes[voter_id] = vote_target
    update_game_state({"lynch_votes": lynch_votes})

    await query.answer(f"You voted to lynch {players_col.find_one({'_id': vote_target})['name']}.")

    # Optionally update message to show current vote count

    # After all alive players voted or timeout, tally votes and lynch player with highest votes

# === WIN CONDITION CHECK ===
def check_win_conditions():
    alive_players = get_alive_players()
    mafia_alive = [p for p in alive_players if p.get("role") in ["Don", "Mafia", "Framer"]]
    town_alive = [p for p in alive_players if p.get("role") not in ["Don", "Mafia", "Framer"]]

    if len(mafia_alive) == 0:
        return "Town"
    if len(mafia_alive) >= len(town_alive):
        return "Mafia"
    return None

# === PROGRESS GAME ===
async def progress_game(context: ContextTypes.DEFAULT_TYPE):
    winner = check_win_conditions()
    chat_id = get_game_state().get("chat_id")
    if winner:
        await context.bot.send_message(chat_id, f"🎉 *{winner}* team has won the game! Congratulations!", parse_mode="Markdown")
        # Award coins here
        update_game_state({"state": "idle"})
        players_col.delete_many({})
    else:
        # Continue game, e.g. night phase or lynch phase
        pass

# === REGISTER NIGHT AND VOTE HANDLERS ===
def register_gameplay_handlers(application):
    application.add_handler(CallbackQueryHandler(lynch_vote_callback, pattern="^vote_"))
    # Add more handlers for night actions here in next parts
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackContext

# Send night action prompt to a player with possible targets
async def send_night_action_prompt(context: CallbackContext, user_id: int, role: str, alive_players):
    """
    Sends a DM to user_id asking for their night action target with inline buttons.
    alive_players: list of dicts with keys: _id, name
    """
    if role == "Don" or role == "Mafia":
        action_text = "Choose a player to kill tonight:"
    elif role == "Doctor":
        action_text = "Choose a player to protect tonight:"
    elif role == "Detective":
        action_text = "Choose a player to investigate tonight:"
    elif role == "Framer":
        action_text = "Choose a player to frame tonight:"
    elif role == "Watcher":
        action_text = "Choose a player to watch tonight:"
    else:
        return  # No action needed

    # Build buttons for alive players excluding self (except Doctor can protect self)
    buttons = []
    for p in alive_players:
        if p["_id"] == user_id and role != "Doctor":
            continue
        buttons.append([InlineKeyboardButton(p["name"], callback_data=f"night_{role}_{p['_id']}")])

    markup = InlineKeyboardMarkup(buttons)
    try:
        await context.bot.send_message(user_id, action_text, reply_markup=markup)
    except:
        # User may not have started the bot in private
        pass

# Callback handler for night action button press
async def night_action_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data  # format: night_ROLE_targetid

    parts = data.split("_")
    if len(parts) != 3:
        await query.answer("Invalid action.")
        return

    role, target_id_str = parts[1], parts[2]
    target_id = int(target_id_str)

    player_role = get_player_role(user_id)
    if player_role != role:
        await query.answer("You cannot perform this action.")
        return

    # Save the chosen target in game state under night_votes
    state = get_game_state()
    night_votes = state.get("night_votes", {})

    # Key depends on role
    if role == "Don" or role == "Mafia":
        night_votes["mafia_kill"] = target_id  # Don's kill will override later
    elif role == "Doctor":
        night_votes["doctor_protect"] = target_id
    elif role == "Detective":
        night_votes["detective_investigate"] = target_id
    elif role == "Framer":
        night_votes["framer_frame"] = target_id
    elif role == "Watcher":
        night_votes["watcher_watch"] = target_id
    else:
        await query.answer("Invalid role.")
        return

    update_game_state({"night_votes": night_votes})
    await query.answer(f"You chose to {role.lower()} {players_col.find_one({'_id': target_id})['name']} tonight.")
    await query.edit_message_reply_markup(reply_markup=None)  # remove buttons after choice

# Function to DM all players with night actions (call in night_phase)
async def prompt_night_actions(context):
    state = get_game_state()
    alive_players = get_alive_players()

    for player in alive_players:
        role = player.get("role")
        await send_night_action_prompt(context, player["_id"], role, alive_players)
from telegram import ParseMode

async def resolve_night_actions(context):
    state = get_game_state()
    night_votes = state.get("night_votes", {})

    alive_players = get_alive_players()
    alive_ids = [p["_id"] for p in alive_players]

    mafia_kill = night_votes.get("mafia_kill")
    doctor_protect = night_votes.get("doctor_protect")
    detective_investigate = night_votes.get("detective_investigate")
    framer_frame = night_votes.get("framer_frame")
    watcher_watch = night_votes.get("watcher_watch")

    killed_player = None
    framed_player = None
    detective_result = None
    watcher_result = None

    # Don's kill overrides Mafia vote, assumed mafia_kill is Don's final kill
    if mafia_kill and mafia_kill != doctor_protect and mafia_kill in alive_ids:
        # Kill the target
        killed_player = mafia_kill
        mark_player_dead(killed_player)

    # Framer framing (only if framed player alive)
    if framer_frame and framer_frame in alive_ids:
        framed_player = framer_frame

    # Detective investigate result
    if detective_investigate and detective_investigate in alive_ids:
        target_role = get_player_role(detective_investigate)
        # Detective sees if target is Mafia/Don or Townie
        if target_role in ["Don", "Mafia", "Framer"]:
            detective_result = f"❌ {get_player_name(detective_investigate)} is suspicious (Mafia side)."
        else:
            detective_result = f"✅ {get_player_name(detective_investigate)} seems innocent (Town)."

    # Watcher watches player role
    if watcher_watch and watcher_watch in alive_ids:
        watched_role = get_player_role(watcher_watch)
        watcher_result = f"👁️ You watched {get_player_name(watcher_watch)} who is a *{watched_role}*."

    # Build announcement message for morning
    message = "*🌞 Morning has come!*\n\n"
    if killed_player:
        message += f"💀 *{get_player_name(killed_player)}* was killed last night.\n"
    else:
        message += "😌 No one was killed last night.\n"

    if framed_player:
        message += f"🎭 *{get_player_name(framed_player)}* was framed and might appear suspicious.\n"

    if detective_result:
        # Send detective DM separately
        detective_id = get_player_id_by_role("Detective")
        if detective_id:
            await context.bot.send_message(detective_id, detective_result)

    if watcher_result:
        watcher_id = get_player_id_by_role("Watcher")
        if watcher_id:
            await context.bot.send_message(watcher_id, watcher_result)

    # Clear night votes for next night
    state["night_votes"] = {}
    update_game_state(state)

    # Send message in group chat
    group_chat_id = state.get("group_chat_id")
    if group_chat_id:
        await context.bot.send_message(group_chat_id, message, parse_mode=ParseMode.MARKDOWN)

    # Proceed to day phase
    await start_day_phase(context)

# Helper functions you should implement:
def mark_player_dead(player_id):
    # Update DB to mark player dead
    players_col.update_one({"_id": player_id}, {"$set": {"alive": False}})

def get_player_role(player_id):
    player = players_col.find_one({"_id": player_id})
    return player.get("role") if player else None

def get_player_name(player_id):
    player = players_col.find_one({"_id": player_id})
    return player.get("name") if player else "Unknown"

def get_player_id_by_role(role):
    player = players_col.find_one({"role": role, "alive": True})
    return player["_id"] if player else None

async def start_day_phase(context):
    # Implement day phase start logic:
    # send lynch vote message with inline buttons to group
    pass

def get_alive_players():
    return list(players_col.find({"alive": True}))
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# Start the day phase by sending lynch vote buttons to group
async def start_day_phase(context):
    state = get_game_state()
    group_chat_id = state.get("group_chat_id")
    alive_players = get_alive_players()

    buttons = []
    for p in alive_players:
        buttons.append([InlineKeyboardButton(p["name"], callback_data=f"lynch_{p['_id']}")])
    markup = InlineKeyboardMarkup(buttons)

    message_text = "🗳️ *Day Phase:* Choose a player to lynch. The player with most votes will be lynched."
    sent_msg = await context.bot.send_message(group_chat_id, message_text, reply_markup=markup, parse_mode="Markdown")

    # Save message id to track votes
    state["day_message_id"] = sent_msg.message_id
    state["lynch_votes"] = {}  # reset votes
    update_game_state(state)

# Callback handler for lynch vote buttons
async def lynch_vote_callback(update, context):
    query = update.callback_query
    voter_id = query.from_user.id
    data = query.data  # format: lynch_playerid

    parts = data.split("_")
    if len(parts) != 2:
        await query.answer("Invalid vote.")
        return
    target_id = int(parts[1])

    state = get_game_state()
    alive_players = get_alive_players()
    alive_ids = [p["_id"] for p in alive_players]

    # Check if target is alive
    if target_id not in alive_ids:
        await query.answer("Player already dead.")
        return

    lynch_votes = state.get("lynch_votes", {})

    # Record vote, only one vote per voter allowed, overwrite if already voted
    lynch_votes[str(voter_id)] = target_id
    state["lynch_votes"] = lynch_votes
    update_game_state(state)

    await query.answer(f"You voted to lynch {get_player_name(target_id)}.")

    # Optionally update vote counts message or just wait until all vote or timer

# Function to count votes and lynch player with most votes
async def tally_lynch_votes(context):
    state = get_game_state()
    lynch_votes = state.get("lynch_votes", {})
    alive_players = get_alive_players()
    alive_ids = [p["_id"] for p in alive_players]

    # Count votes per player
    vote_counts = {}
    for vote in lynch_votes.values():
        if vote in alive_ids:
            vote_counts[vote] = vote_counts.get(vote, 0) + 1

    if not vote_counts:
        # No votes, no lynch
        await context.bot.send_message(state["group_chat_id"], "No one was lynched today. Everyone survives.")
        await start_night_phase(context)
        return

    # Find max votes
    max_votes = max(vote_counts.values())
    lynch_candidates = [pid for pid, count in vote_counts.items() if count == max_votes]

    if len(lynch_candidates) > 1:
        # Tie - no lynch or random lynch, your choice
        await context.bot.send_message(state["group_chat_id"], "Tie in votes, no one was lynched today.")
        await start_night_phase(context)
        return

    lynched_player = lynch_candidates[0]
    mark_player_dead(lynched_player)

    await context.bot.send_message(state["group_chat_id"],
                                   f"⚰️ *{get_player_name(lynched_player)}* was lynched by the town.",
                                   parse_mode="Markdown")

    # Clear lynch votes
    state["lynch_votes"] = {}
    update_game_state(state)

    # Check win conditions after lynch
    if check_win_conditions(context):
        await end_game(context)
    else:
        # Proceed to night phase
        await start_night_phase(context)

def check_win_conditions(context) -> bool:
    alive_players = get_alive_players()
    alive_roles = [p["role"] for p in alive_players]

    mafia_count = sum(r in ["Don", "Mafia", "Framer"] for r in alive_roles)
    town_count = sum(r in ["Citizen", "Doctor", "Detective", "Watcher"] for r in alive_roles)

    # Mafia wins if mafia equal or outnumber town
    if mafia_count >= town_count and mafia_count > 0:
        return True  # Mafia win

    # Town wins if all mafia dead
    if mafia_count == 0:
        return True  # Town win

    return False

async def end_game(context):
    state = get_game_state()
    group_chat_id = state.get("group_chat_id")
    alive_players = get_alive_players()

    mafia_alive = [p for p in alive_players if p["role"] in ["Don", "Mafia", "Framer"]]
    if mafia_alive:
        winner = "Mafia"
    else:
        winner = "Town"

    await context.bot.send_message(group_chat_id, f"🏆 *Game Over!* {winner} wins! 🎉", parse_mode="Markdown")

    # Award coins or handle post-game cleanup
    # Reset game state or prepare for next game

    reset_game_state()
