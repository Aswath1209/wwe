import logging
import asyncio
from datetime import datetime, timedelta
from collections import Counter

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatPermissions,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

from pymongo import MongoClient

# === CONFIG ===
BOT_TOKEN = "8133604799:AAF2dE86UjRxfAdUcqyoz3O9RgaCeTwaoHM"
MONGO_URL = "mongodb://mongo:GhpHMiZizYnvJfKIQKxoDbRyzBCpqEyC@mainline.proxy.rlwy.net:54853"

# === GLOBALS ===
active_games = {}  # group_id: game_data

# === MongoDB Setup ===
mongo_client = MongoClient(MONGO_URL)
db = mongo_client["mafia_bot"]
users_collection = db["users"]
games_collection = db["games"]

# === Logging ===
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# === Helper functions ===

def get_player_name(game, user_id):
    for p in game["players"]:
        if p["user_id"] == user_id:
            return p["name"]
    return "Unknown"

def create_inline_keyboard(buttons, row_width=2):
    keyboard = []
    for i in range(0, len(buttons), row_width):
        keyboard.append(buttons[i:i + row_width])
    return InlineKeyboardMarkup(keyboard)

def build_confirmation_buttons():
    buttons = [
        InlineKeyboardButton("✅ Confirm", callback_data="cancel_confirm"),
        InlineKeyboardButton("❌ Cancel", callback_data="cancel_cancel"),
    ]
    return create_inline_keyboard(buttons, row_width=2)

# === Command Handlers ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to Mafia Bot!\n"
        "Use /startmafia in a group to begin a new Mafia game."
    )

async def startmafia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.type != "group" and chat.type != "supergroup":
        await update.message.reply_text("You can only start a game in groups.")
        return

    if chat.id in active_games:
        await update.message.reply_text("A game is already active in this group.")
        return

    # Initialize a new game state for the group
    active_games[chat.id] = {
        "group_id": chat.id,
        "players": [],
        "registered_user_ids": set(),
        "state": "registration",
        "night": 0,
        "votes": {},
        "night_actions": {},
        "start_time": datetime.utcnow(),
    }

    await update.message.reply_text(
        "Mafia game started!\n"
        "Players can now register by sending /joinmafia."
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    if chat.type != "group" and chat.type != "supergroup":
        await update.message.reply_text("You can only cancel a game in groups.")
        return

    if chat.id not in active_games:
        await update.message.reply_text("There is no active game to cancel.")
        return

    # Ask for confirmation with inline buttons
    await update.message.reply_text(
        "Are you sure you want to cancel the ongoing Mafia game?",
        reply_markup=build_confirmation_buttons()
    )

async def cancel_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id

    if query.data == "cancel_confirm":
        if chat_id in active_games:
            del active_games[chat_id]
        await query.edit_message_text("The Mafia game has been cancelled.")
    else:
        await query.edit_message_text("Game cancellation aborted.")

# === Entry point ===
async def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("startmafia", startmafia))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CallbackQueryHandler(cancel_confirmation, pattern="^cancel_"))

    # Add other handlers later...

    await application.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
# === Part 2/7 ===

from telegram import ChatAction

# Command: /joinmafia - Players join the current game registration
async def join_mafia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.type != "group" and chat.type != "supergroup":
        await update.message.reply_text("You can only join Mafia games in groups.")
        return

    if chat.id not in active_games:
        await update.message.reply_text("No active Mafia game in this group. Wait for /startmafia.")
        return

    game = active_games[chat.id]

    if game["state"] != "registration":
        await update.message.reply_text("Registration is closed.")
        return

    if user.id in game["registered_user_ids"]:
        await update.message.reply_text(f"{user.first_name}, you have already joined the game.")
        return

    # Add player
    game["players"].append({
        "user_id": user.id,
        "name": user.full_name,
        "role": None,
        "alive": True,
        "protected": False,
        "checked": False,
        "votes_received": 0,
    })
    game["registered_user_ids"].add(user.id)

    await update.message.reply_text(f"{user.full_name} has joined the Mafia game!")

# Command: /players - Show list of players registered
async def show_players(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    if chat.type != "group" and chat.type != "supergroup":
        await update.message.reply_text("This command works only in group chats.")
        return

    if chat.id not in active_games:
        await update.message.reply_text("No active Mafia game in this group.")
        return

    game = active_games[chat.id]
    players = game["players"]

    if not players:
        await update.message.reply_text("No players have joined yet.")
        return

    text = "Players registered:\n"
    for p in players:
        status = "Alive" if p["alive"] else "Dead"
        text += f" - {p['name']} ({status})\n"

    await update.message.reply_text(text)

# Register these handlers to the application
def register_player_handlers(app):
    app.add_handler(CommandHandler("joinmafia", join_mafia))
    app.add_handler(CommandHandler("players", show_players))
# === Part 3/7 ===

import random

# Roles list by player count
ROLE_SETUPS = {
    4: ['Don', 'Mafia', 'Townie', 'Suicide'],
    5: ['Don', 'Mafia', 'Mafia', 'Townie', 'Suicide'],
    6: ['Don', 'Mafia', 'Mafia', 'Framer', 'Townie', 'Townie'],
    7: ['Don', 'Mafia', 'Mafia', 'Framer', 'Townie', 'Townie', 'Townie'],
    8: ['Don', 'Mafia', 'Mafia', 'Framer', 'Watcher', 'Townie', 'Townie', 'Townie'],
    9: ['Don', 'Mafia', 'Mafia', 'Framer', 'Watcher', 'Townie', 'Townie', 'Townie', 'Townie'],
    10: ['Don', 'Mafia', 'Mafia', 'Framer', 'Watcher', 'Townie', 'Townie', 'Townie', 'Townie', 'Townie'],
    # Continue similarly for up to 15 players
}

# Role descriptions for DM
ROLE_DESCRIPTIONS = {
    "Don": "You are the Don, leader of the Mafia. Coordinate with your team and eliminate the Town.",
    "Mafia": "You are Mafia. Work with Don and Framer to kill the Town.",
    "Framer": "You are the Framer. Help Mafia by framing Town members to confuse the Detective.",
    "Watcher": "You are the Watcher. Each night, you watch one player to gather clues.",
    "Townie": "You are a Townie. Find and lynch the Mafia to protect your town.",
    "Suicide": "You are the Suicide. Your goal is to get yourself lynched.",
}

# Assign roles randomly from ROLE_SETUPS according to player count
def assign_roles(game):
    players = game["players"]
    num_players = len(players)

    # Find closest setup available <= num_players
    valid_counts = sorted([k for k in ROLE_SETUPS.keys() if k <= num_players], reverse=True)
    chosen_count = valid_counts[0]

    roles = ROLE_SETUPS[chosen_count].copy()
    random.shuffle(roles)

    for i, player in enumerate(players):
        if i < chosen_count:
            player["role"] = roles[i]
        else:
            # Extra players beyond setup get Townie role
            player["role"] = "Townie"

        player["alive"] = True
        player["protected"] = False
        player["checked"] = False
        player["votes_received"] = 0

# Send role message to each player in private chat with button to open bot
async def send_roles_private(application, game):
    for player in game["players"]:
        try:
            chat_id = player["user_id"]
            role = player["role"]
            desc = ROLE_DESCRIPTIONS.get(role, "No description available.")

            text = f"Your role is: {role}\n\n{desc}"

            # If Mafia/Don/Framer, list team members
            if role in ["Don", "Mafia", "Framer"]:
                team = [p["name"] for p in game["players"] if p["role"] in ["Don", "Mafia", "Framer"] and p["user_id"] != player["user_id"]]
                if team:
                    text += "\n\nRemember your team members:\n" + "\n".join(f"  - {t}" for t in team)

            # Button to open bot chat
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Open Bot Chat", url=f"tg://user?id={chat_id}")]
            ])

            await application.bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
        except Exception as e:
            print(f"Failed to send role to {player['name']}: {e}")
# === Part 4/7 ===

from telegram.ext import CallbackQueryHandler

# Helper: get alive players excluding self
def alive_others(game, user_id):
    return [p for p in game["players"] if p["alive"] and p["user_id"] != user_id]

# Create buttons for alive players for actions
def create_player_buttons(game, user_id, prefix):
    players = alive_others(game, user_id)
    buttons = []
    for p in players:
        buttons.append(InlineKeyboardButton(p["name"], callback_data=f"{prefix}:{p['user_id']}"))
    # Arrange buttons in rows of 2
    keyboard = []
    row = []
    for i, btn in enumerate(buttons):
        row.append(btn)
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)

# Send Detective action choice (Check or Kill)
async def send_detective_action(application, game, detective_id):
    chat_id = detective_id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Check", callback_data="detective:check")],
        [InlineKeyboardButton("Kill", callback_data="detective:kill")]
    ])
    await application.bot.send_message(chat_id, "Detective, choose an action:", reply_markup=keyboard)

# Callback for Detective action type selection
async def detective_action_choice(update, context):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data  # e.g. "detective:check" or "detective:kill"
    action = data.split(":")[1]

    # Save action type in user context (or game state)
    context.user_data["detective_action"] = action

    # Send player selection buttons
    game = get_game_by_user(user_id)  # Implement accordingly
    reply_markup = create_player_buttons(game, user_id, f"detective_{action}")
    await query.edit_message_text(f"Who do you want to {action}?", reply_markup=reply_markup)

# Callback for Detective choosing target player
async def detective_target_chosen(update, context):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data  # e.g. "detective_check:123456789"

    action, target_id_str = data.split(":")
    target_id = int(target_id_str)

    # Save detective's choice in game state
    game = get_game_by_user(user_id)
    if action.startswith("detective_check"):
        game["night_actions"]["detective_check"] = target_id
        # Notify group
        await application.bot.send_message(game["group_id"], "🕵️‍ Detective is looking for the criminals...")
    elif action.startswith("detective_kill"):
        game["night_actions"]["detective_kill"] = target_id
        await application.bot.send_message(game["group_id"], "🕵️‍ Detective has his weapons lock'n'loaded...")

    await query.edit_message_text(f"You've voted for {get_player_name(game, target_id)}")

# Similarly for Doctor Save
async def send_doctor_action(application, game, doctor_id):
    keyboard = create_player_buttons(game, doctor_id, "doctor_save")
    await application.bot.send_message(doctor_id, "Doctor, who do you want to save tonight? (You can only save yourself once)", reply_markup=keyboard)

async def doctor_save_chosen(update, context):
    query = update.callback_query
    user_id = query.from_user.id
    target_id = int(query.data.split(":")[1])
    game = get_game_by_user(user_id)

    # Check if doctor has saved self before
    player = get_player(game, user_id)
    if target_id == user_id and player.get("doctor_self_save_used", False):
        await query.answer("You have already saved yourself once, choose someone else.", show_alert=True)
        return
    if target_id == user_id:
        player["doctor_self_save_used"] = True

    game["night_actions"]["doctor_save"] = target_id
    await query.edit_message_text(f"You've chosen to save {get_player_name(game, target_id)}")

# Mafia kill action
async def send_mafia_action(application, game, mafia_id):
    keyboard = create_player_buttons(game, mafia_id, "mafia_kill")
    await application.bot.send_message(mafia_id, "Mafia, who do you want to kill tonight?", reply_markup=keyboard)

async def mafia_kill_chosen(update, context):
    query = update.callback_query
    user_id = query.from_user.id
    target_id = int(query.data.split(":")[1])
    game = get_game_by_user(user_id)

    # Save mafia kill vote (handle multiple mafia voting logic here)
    game["night_actions"]["mafia_kill"] = target_id

    # Announce vote in mafia chat or DM
    mafia_name = get_player_name(game, user_id)
    target_name = get_player_name(game, target_id)
    mafia_chat_id = game["mafia_chat_id"]
    await application.bot.send_message(mafia_chat_id, f"🤵🏼 Mafia {mafia_name} voted for {target_name}")

    await query.edit_message_text(f"You've voted to kill {target_name}")

# Utility functions you need to implement:
# get_game_by_user(user_id) => returns current game dict user is in
# get_player(game, user_id) => returns player dict by user id
# get_player_name(game, user_id) => returns player name string
# === Part 5/7 ===

import asyncio

async def resolve_night_actions(application, game):
    actions = game.get("night_actions", {})

    group_id = game["group_id"]

    killed_players = []
    saved_player_id = actions.get("doctor_save")
    detective_checked_id = actions.get("detective_check")
    detective_killed_id = actions.get("detective_kill")
    mafia_kill_id = actions.get("mafia_kill")

    # Handle detective kill first if any
    if detective_killed_id:
        player = get_player(game, detective_killed_id)
        if player["alive"]:
            # Check if doctor saved them
            if saved_player_id == detective_killed_id:
                await application.bot.send_message(group_id, "Doctor patched up a victim tonight...")
            else:
                player["alive"] = False
                killed_players.append(player)
                await application.bot.send_message(group_id, f"🤵🏻 {player['name']} was brutally murdered tonight...")

    # Handle mafia kill
    if mafia_kill_id:
        player = get_player(game, mafia_kill_id)
        if player["alive"]:
            if saved_player_id == mafia_kill_id:
                await application.bot.send_message(group_id, "Doctor patched up a victim tonight...")
            else:
                player["alive"] = False
                killed_players.append(player)
                await application.bot.send_message(group_id, f"🤵🏻 {player['name']} was brutally murdered tonight...")

    # Detective checked someone message
    if detective_checked_id:
        checked_player = get_player(game, detective_checked_id)
        for p in game["players"]:
            if p["user_id"] == detective_checked_id:
                try:
                    await application.bot.send_message(p["user_id"], "Someone is very curious about your role...")
                except:
                    pass

    # Notify night summary delay
    await asyncio.sleep(20)

    # Start voting phase
    await application.bot.send_message(group_id, "It's mob justice time! Vote for the most suspicious player.\nVoting will last 45 seconds.", reply_markup=InlineKeyboardMarkup(
        [[InlineKeyboardButton("Vote 🔎", url=f"tg://resolve?domain=YourBotUsername")]]
    ))

    # Clear night actions
    game["night_actions"] = {}

# Call this function after all night actions collected and time ended
# === Part 6/7 ===

from collections import Counter

async def start_lynch_vote(application, game, voted_player_id):
    group_id = game["group_id"]
    voted_player = get_player(game, voted_player_id)

    # Send confirmation message with 👍👎 buttons
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👍", callback_data=f"lynch_confirm_{voted_player_id}"),
         InlineKeyboardButton("👎", callback_data=f"lynch_cancel_{voted_player_id}")]
    ])
    await application.bot.send_message(group_id, f"Are you sure about lynching {voted_player['name']}?", reply_markup=keyboard)

    # Store current lynch vote state
    game["lynch_vote"] = {
        "target_id": voted_player_id,
        "yes_votes": set(),
        "no_votes": set(),
    }

async def process_lynch_vote(application, game, user_id, vote_yes):
    if "lynch_vote" not in game:
        return

    lynch = game["lynch_vote"]
    if vote_yes:
        lynch["yes_votes"].add(user_id)
        lynch["no_votes"].discard(user_id)
    else:
        lynch["no_votes"].add(user_id)
        lynch["yes_votes"].discard(user_id)

    # Update message with count of votes (this requires message id - omitted for brevity)
    # You can update message text here to show vote counts

async def finalize_lynch(application, game):
    lynch = game.get("lynch_vote")
    group_id = game["group_id"]

    yes_count = len(lynch["yes_votes"])
    no_count = len(lynch["no_votes"])
    target_id = lynch["target_id"]
    target_player = get_player(game, target_id)

    if yes_count > no_count:
        # Lynch succeeds
        target_player["alive"] = False
        await application.bot.send_message(group_id, f"{target_player['name']} was lynched! They were a {target_player['role']}.")

        # Announce team death, check win conditions next
        check_game_end(application, game)

    else:
        await application.bot.send_message(group_id, f"The citizens couldn't come up with a decision ({yes_count} 👍 | {no_count} 👎)... They dispersed, lynching nobody today...")

    # Clear lynch vote
    game.pop("lynch_vote", None)

def check_game_end(application, game):
    # Count alive mafia and townies
    alive_mafia = [p for p in game["players"] if p["alive"] and p["team"] == "mafia"]
    alive_town = [p for p in game["players"] if p["alive"] and p["team"] == "town"]

    group_id = game["group_id"]

    if len(alive_mafia) == 0:
        # Town wins
        winners = [p for p in game["players"] if p["team"] == "town" and p["alive"]]
        losers = [p for p in game["players"] if p["team"] == "mafia" or not p["alive"]]

        asyncio.create_task(announce_game_over(application, game, winners, losers, "Town"))
        return True

    if len(alive_mafia) >= len(alive_town):
        # Mafia wins
        winners = [p for p in game["players"] if p["team"] == "mafia" and p["alive"]]
        losers = [p for p in game["players"] if p["team"] == "town" or not p["alive"]]

        asyncio.create_task(announce_game_over(application, game, winners, losers, "Mafia"))
        return True

    return False

async def announce_game_over(application, game, winners, losers, winning_team):
    group_id = game["group_id"]

    winners_text = "\n".join([f"{p['name']} - {p['role_emoji']} {p['role']}" for p in winners])
    losers_text = "\n".join([f"{p['name']} - {p['role_emoji']} {p['role']}" for p in losers])

    message = f"""The game is over!
The victorious team: {winning_team}

Winners:
{winners_text}

Other players:
{losers_text}

Thanks for playing!"""

    await application.bot.send_message(group_id, message)

    # Award coins to winners (you can implement coin logic here)

    # Cleanup game data for this group
    # ...
# === Part 7/7 ===

from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters

async def cancel_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user

    # Only admins can cancel
    member = await context.bot.get_chat_member(chat_id, user.id)
    if not member.status in ["administrator", "creator"]:
        await update.message.reply_text("Only group admins can cancel the game.")
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Confirm Cancel", callback_data="cancel_confirm"),
         InlineKeyboardButton("Abort", callback_data="cancel_abort")]
    ])
    await update.message.reply_text("Are you sure you want to cancel the ongoing game?", reply_markup=keyboard)

async def cancel_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    group_id = query.message.chat.id
    # Remove the game if exists
    if group_id in ongoing_games:
        del ongoing_games[group_id]
        await query.edit_message_text("Game cancelled by admin.")
    else:
        await query.edit_message_text("No active game to cancel.")

async def cancel_abort(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Cancellation aborted. The game continues.")

def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("startmafia", startmafia))
    application.add_handler(CommandHandler("cancel", cancel_game))

    # CallbackQueryHandlers for cancel confirmation buttons
    application.add_handler(CallbackQueryHandler(cancel_confirm, pattern="cancel_confirm"))
    application.add_handler(CallbackQueryHandler(cancel_abort, pattern="cancel_abort"))

    # Add other handlers: registration, night actions, voting, lynching, mafia chat, etc.
    # application.add_handler(CallbackQueryHandler(handle_registration, pattern="join_game"))
    # application.add_handler(CallbackQueryHandler(handle_night_action, pattern="check_.*|kill_.*|save_.*"))
    # application.add_handler(CallbackQueryHandler(handle_vote, pattern="vote_.*"))
    # application.add_handler(CallbackQueryHandler(handle_lynch_vote, pattern="lynch_.*"))
    # application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, handle_mafia_chat))

    application.run_polling()

if __name__ == "__main__":
    main()
