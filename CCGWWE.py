import logging
import random
import uuid
from datetime import datetime, timedelta

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from motor.motor_asyncio import AsyncIOMotorClient

# --- Config ---
BOT_TOKEN = "8133604799:AAF2dE86UjRxfAdUcqyoz3O9RgaCeTwaoHM"
MONGO_URL = "mongodb://mongo:GhpHMiZizYnvJfKIQKxoDbRyzBCpqEyC@mainline.proxy.rlwy.net:54853"

ADMIN_IDS = {123456789}  # Replace with your Telegram user ID(s)

# --- MongoDB Setup ---
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client.handcrickett
users_collection = db.users

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# --- Global Data ---
USERS = {}  # user_id -> user dict

CCL_MATCHES = {}         # match_id -> match dict
USER_CCL_MATCH = {}      # user_id -> match_id (single per user)
GROUP_CCL_MATCH = {}     # group_chat_id -> match_id (single per group)

# --- Helper Functions ---

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
        USER_CCL_MATCH[user.id] = None

async def save_user(user_id):
    try:
        user = USERS[user_id]
        await users_collection.update_one(
            {"user_id": user_id},
            {"$set": user},
            upsert=True,
        )
        logger.info(f"Saved user {user_id} to database.")
    except Exception as e:
        logger.error(f"Error saving user {user_id}: {e}", exc_info=True)

async def load_users():
    try:
        cursor = users_collection.find({})
        async for user in cursor:
            user_id = user.get("user_id")
            USERS[user_id] = user
            USER_CCL_MATCH[user_id] = None
        logger.info("Users loaded successfully.")
    except Exception as e:
        logger.error(f"Error loading users: {e}", exc_info=True)

# --- Commands ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)
    await update.message.reply_text(
        f"Welcome to HandCricket, {USERS[user.id]['name']}!\n"
        "Use /register to get 4000💰 coins."
    )

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)
    if USERS[user.id]["registered"]:
        await update.message.reply_text("You're already registered!")
        return
    USERS[user.id]["coins"] += 4000
    USERS[user.id]["registered"] = True
    await save_user(user.id)
    await update.message.reply_text("Registered! 4000💰 added to your account.")

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)
    profile_text = (
        f"👤 {USERS[user.id]['name']}\n"
        f"🆔 {user.id}\n"
        f"💰 {USERS[user.id]['coins']}\n"
        f"🏆 Wins: {USERS[user.id]['wins']}\n"
        f"💔 Losses: {USERS[user.id]['losses']}\n"
        f"🤝 Ties: {USERS[user.id]['ties']}"
    )
    await update.message.reply_text(profile_text)

async def send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user's message to send coins.")
        return
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /send <amount> (reply to user)")
        return
    amount = int(args[0])
    if amount <= 0:
        await update.message.reply_text("Please enter a positive amount.")
        return
    sender = USERS[user.id]
    if sender["coins"] < amount:
        await update.message.reply_text(f"You don't have enough coins to send {amount}💰.")
        return
    receiver_user = update.message.reply_to_message.from_user
    ensure_user(receiver_user)
    receiver = USERS[receiver_user.id]
    sender["coins"] -= amount
    receiver["coins"] += amount
    await save_user(user.id)
    await save_user(receiver_user.id)
    await update.message.reply_text(
        f"✅ {user.first_name} sent {amount}💰 to {receiver['name']}."
    )

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /add <user_id> <amount>")
        return
    try:
        target_user_id = int(args[0])
        amount = int(args[1])
        if amount <= 0:
            await update.message.reply_text("Amount must be positive.")
            return
    except ValueError:
        await update.message.reply_text("Invalid user ID or amount.")
        return
    ensure_user(type("User", (), {"id": target_user_id})())
    USERS[target_user_id]["coins"] += amount
    await save_user(target_user_id)
    await update.message.reply_text(f"✅ Added {amount}💰 to user {USERS[target_user_id]['name']}.")

# --- Leaderboard with Switch Button ---
def leaderboard_markup(current="coins"):
    if current == "coins":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("Show Wins 🏆", callback_data="leaderboard_wins")]
        ])
    else:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("Show Coins 💰", callback_data="leaderboard_coins")]
        ])

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user)
    sorted_users = sorted(USERS.values(), key=lambda u: u.get("coins", 0), reverse=True)
    text = "🏆 Top 10 Players by Coins:\n\n"
    for i, u in enumerate(sorted_users[:10], 1):
        text += f"{i}. {u.get('name', 'Unknown')} - {u.get('coins', 0)} 💰\n"
    await update.message.reply_text(text, reply_markup=leaderboard_markup("coins"))

async def leaderboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    if data == "leaderboard_coins":
        sorted_users = sorted(USERS.values(), key=lambda u: u.get("coins", 0), reverse=True)
        text = "🏆 Top 10 Players by Coins:\n\n"
        for i, u in enumerate(sorted_users[:10], 1):
            text += f"{i}. {u.get('name', 'Unknown')} - {u.get('coins', 0)} 💰\n"
        markup = leaderboard_markup("coins")
    elif data == "leaderboard_wins":
        sorted_users = sorted(USERS.values(), key=lambda u: u.get("wins", 0), reverse=True)
        text = "🏆 Top 10 Players by Wins:\n\n"
        for i, u in enumerate(sorted_users[:10], 1):
            text += f"{i}. {u.get('name', 'Unknown')} - {u.get('wins', 0)} 🏆\n"
        markup = leaderboard_markup("wins")
    else:
        await query.answer()
        return
    await query.message.edit_text(text, reply_markup=markup)
    await query.answer()

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📜 Available Commands:\n"
        "/start - Start the bot\n"
        "/register - Get free coins\n"
        "/profile - View profile\n"
        "/send - Send coins\n"
        "/add - Admin: add coins\n"
        "/leaderboard - Top players\n"
        "/ccl - Start or manage CCL match\n"
        "/endmatch - Admin: end ongoing match\n"
        "/help - Show this help"
    )
    await update.message.reply_text(help_text)
import asyncio

# --- Constants for CCL ---

BOWLER_OPTIONS = ["RS", "BOUNCER", "YORKER", "SHORT", "SLOWER", "KNUCKLE"]
BATSMAN_OPTIONS = ["0", "1", "2", "3", "4", "6"]

# Multiple GIFs per event
CCL_GIFS = {
    "0": [
        "https://media.giphy.com/media/3o7aD2saalBwwftBIY/giphy.gif",
        "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif"
    ],
    "4": [
        "https://media.giphy.com/media/l0MYB8Ory7Hqefo9a/giphy.gif",
        "https://media.giphy.com/media/3o7aD2saalBwwftBIY/giphy.gif"
    ],
    "6": [
        "https://media.giphy.com/media/3oEjI5VtIhHvK37WYo/giphy.gif",
        "https://media.giphy.com/media/26ufdipQqU2lhNA4g/giphy.gif"
    ],
    "out": [
        "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif",
        "https://media.giphy.com/media/3o7aD2saalBwwftBIY/giphy.gif"
    ],
    "50": [
        "https://media.giphy.com/media/3o7TKyQ6mQ2x2l7f7i/giphy.gif",
        "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif"
    ],
    "100": [
        "https://media.giphy.com/media/3oEjI5VtIhHvK37WYo/giphy.gif",
        "https://media.giphy.com/media/26ufdipQqU2lhNA4g/giphy.gif"
    ],
}

# Multiple commentary lines with emojis
COMMENTARY = {
    "0": [
        "😶 Dot ball! Pressure builds...",
        "🎯 Tight delivery, no run.",
        "🛑 No run, good fielding!"
    ],
    "4": [
        "🔥 Cracking four! What a shot!",
        "💥 The ball races to the boundary!",
        "🏏 Beautiful timing for four runs!"
    ],
    "6": [
        "🚀 Massive six! Into the stands!",
        "🎉 What a smash! Six runs!",
        "🔥 Smoked it for a sixer! 🔥"
    ],
    "out": [
        "💥 Bowled him! What a delivery!",
        "😢 Caught out! End of the innings!",
        "🚫 Out! The crowd goes silent..."
    ],
    "50": [
        "🎉 Half-century! What a milestone!",
        "🏆 50 runs scored! Keep it up!",
        "🔥 Fifty up! Player is on fire!"
    ],
    "100": [
        "🏅 CENTURY! What a magnificent innings!",
        "🎊 100 runs! A true champion!",
        "🔥 Century scored! The crowd erupts!"
    ],
}

# --- Helper keyboards for DM input ---

def ccl_batsman_keyboard(match_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(n, callback_data=f"ccl_bat_{match_id}_{n}") for n in BATSMAN_OPTIONS[:3]],
        [InlineKeyboardButton(n, callback_data=f"ccl_bat_{match_id}_{n}") for n in BATSMAN_OPTIONS[3:]],
    ])

def ccl_bowler_keyboard(match_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(opt, callback_data=f"ccl_bowl_{match_id}_{opt}") for opt in BOWLER_OPTIONS[:3]],
        [InlineKeyboardButton(opt, callback_data=f"ccl_bowl_{match_id}_{opt}") for opt in BOWLER_OPTIONS[3:]],
    ])

# --- CCL Command Handler ---

async def ccl_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    ensure_user(user)

    if GROUP_CCL_MATCH.get(chat.id):
        await update.message.reply_text("❌ Only one CCL match allowed per group at a time.")
        return
    if USER_CCL_MATCH.get(user.id):
        await update.message.reply_text("❌ You are already in a CCL match.")
        return

    match_id = str(uuid.uuid4())
    match = {
        "match_id": match_id,
        "group_id": chat.id,
        "initiator": user.id,
        "opponent": None,
        "state": "waiting_join",
        "toss_winner": None,
        "batting_user": None,
        "bowling_user": None,
        "balls": 0,
        "score": 0,
        "innings": 1,
        "target": None,
        "bat_choice": None,
        "bowl_choice": None,
        "half_century_announced": False,
        "century_announced": False,
        "message_id": None,
    }
    CCL_MATCHES[match_id] = match
    USER_CCL_MATCH[user.id] = match_id
    GROUP_CCL_MATCH[chat.id] = match_id

    sent_msg = await update.message.reply_text(
        f"🏏 CCL Match started by {USERS[user.id]['name']}!\nWaiting for an opponent to join.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Join ✅", callback_data=f"ccl_join_{match_id}")],
            [InlineKeyboardButton("Cancel ❌", callback_data=f"ccl_cancel_{match_id}")]
        ])
    )
    match["message_id"] = sent_msg.message_id

# --- Join, Cancel, Toss, Bat/Bowl, DM inputs, and ball processing handlers ---
# Implement handlers for:
# - ccl_join_<match_id>
# - ccl_cancel_<match_id>
# - ccl_toss_<match_id>_<choice>
# - ccl_bat_<match_id>_<number>
# - ccl_bowl_<match_id>_<variation>

# These handlers should:
# - Manage state transitions
# - Send DMs to batting and bowling players with keyboards
# - Validate inputs and send confirmations or error messages
# - After receiving both inputs, update the group message with timed delays
# - Send GIFs and commentary randomly chosen from the lists above
# - Announce milestones (50, 100) with congratulatory messages and GIFs
# - Detect match end conditions: tie, win, loss
# - Update user stats and coins accordingly
# - Clean up match data after completion or cancellation

# Due to the complexity and length, full handler implementations will be provided in subsequent parts.

# --- Utility functions to send GIFs and commentary ---

async def send_random_event_update(context, chat_id, event_key):
    gif_list = CCL_GIFS.get(event_key, [])
    commentary_list = COMMENTARY.get(event_key, [])
    gif_url = random.choice(gif_list) if gif_list else None
    commentary = random.choice(commentary_list) if commentary_list else ""
    if gif_url:
        await context.bot.send_animation(
            chat_id=chat_id,
            animation=gif_url,
            caption=commentary
        )
    else:
        await context.bot.send_message(chat_id=chat_id, text=commentary)

# --- Registration of handlers will be in part 3 ---
import asyncio

# --- CCL Join Handler ---
async def ccl_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    _, _, match_id = query.data.split("_", 2)
    match = CCL_MATCHES.get(match_id)
    if not match or match["state"] != "waiting_join":
        await query.answer("Match not available to join.", show_alert=True)
        return
    if user.id == match["initiator"]:
        await query.answer("You cannot join your own match.", show_alert=True)
        return
    if match["opponent"]:
        await query.answer("Match already has an opponent.", show_alert=True)
        return
    ensure_user(user)
    match["opponent"] = user.id
    match["state"] = "toss"
    chat_id = match["group_id"]
    message_id = match["message_id"]
    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=(
            f"Match between {USERS[match['initiator']]['name']} and {USERS[user.id]['name']}!\n"
            f"{USERS[match['initiator']]['name']}, choose Heads or Tails for the toss."
        ),
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Heads", callback_data=f"ccl_toss_{match_id}_heads"),
                InlineKeyboardButton("Tails", callback_data=f"ccl_toss_{match_id}_tails"),
            ]
        ])
    )
    await query.answer()

# --- CCL Cancel Handler ---
async def ccl_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    _, _, match_id = query.data.split("_", 2)
    match = CCL_MATCHES.get(match_id)
    if not match:
        await query.answer("Match not found or already ended.", show_alert=True)
        return
    if user.id != match["initiator"]:
        await query.answer("Only the initiator can cancel the match.", show_alert=True)
        return
    chat_id = match["group_id"]
    message_id = match.get("message_id")
    CCL_MATCHES.pop(match_id, None)
    USER_CCL_MATCH[match["initiator"]] = None
    if match.get("opponent"):
        USER_CCL_MATCH[match["opponent"]] = None
    GROUP_CCL_MATCH.pop(chat_id, None)
    if message_id:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text="The CCL match has been cancelled by the initiator."
        )
    await query.answer()

# --- CCL Toss Handler ---
async def ccl_toss_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    _, _, match_id, choice = query.data.split("_", 3)
    match = CCL_MATCHES.get(match_id)
    if not match or match["state"] != "toss":
        await query.answer("Invalid toss state.", show_alert=True)
        return
    if user.id != match["initiator"]:
        await query.answer("Only the initiator chooses toss.", show_alert=True)
        return
    coin_result = random.choice(["heads", "tails"])
    toss_winner = match["initiator"] if choice == coin_result else match["opponent"]
    toss_loser = match["opponent"] if toss_winner == match["initiator"] else match["initiator"]
    match["toss_winner"] = toss_winner
    match["toss_loser"] = toss_loser
    match["state"] = "bat_bowl_choice"
    chat_id = match["group_id"]
    message_id = match["message_id"]
    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=(
            f"The coin landed on {coin_result.capitalize()}!\n"
            f"{USERS[toss_winner]['name']} won the toss! Choose to Bat or Bowl first."
        ),
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Bat 🏏", callback_data=f"ccl_batbowl_{match_id}_bat"),
                InlineKeyboardButton("Bowl ⚾", callback_data=f"ccl_batbowl_{match_id}_bowl"),
            ]
        ])
    )
    await query.answer()

# --- CCL Bat/Bowl Choice Handler ---
async def ccl_batbowl_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    _, _, match_id, choice = query.data.split("_", 3)
    match = CCL_MATCHES.get(match_id)
    if not match or match["state"] != "bat_bowl_choice":
        await query.answer("Invalid state for Bat/Bowl choice.", show_alert=True)
        return
    if user.id != match["toss_winner"]:
        await query.answer("Only toss winner can choose.", show_alert=True)
        return
    if choice == "bat":
        match["batting_user"] = match["toss_winner"]
        match["bowling_user"] = match["toss_loser"]
    else:
        match["batting_user"] = match["toss_loser"]
        match["bowling_user"] = match["toss_winner"]
    match.update({
        "state": "awaiting_inputs",
        "balls": 0,
        "score": 0,
        "innings": 1,
        "target": None,
        "bat_choice": None,
        "bowl_choice": None,
        "half_century_announced": False,
        "century_announced": False,
    })
    chat_id = match["group_id"]
    message_id = match["message_id"]

    # Send DM to batsman and bowler
    try:
        await context.bot.send_message(
            chat_id=match["batting_user"],
            text=f"🏏 You're batting! Choose your shot:",
            reply_markup=ccl_batsman_keyboard(match_id)
        )
        await context.bot.send_message(
            chat_id=match["bowling_user"],
            text=f"⚾ You're bowling! Choose your delivery:",
            reply_markup=ccl_bowler_keyboard(match_id)
        )
    except Exception as e:
        logger.error(f"Error sending DM: {e}")

    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=(
            f"Match started!\n"
            f"🏏 Batter: {USERS[match['batting_user']]['name']}\n"
            f"🧤 Bowler: {USERS[match['bowling_user']]['name']}\n\n"
            f"Both players have been tagged and sent their choices via DM."
        ),
        reply_markup=None
    )
    await query.answer()

# --- CCL Batsman Choice Handler ---
async def ccl_bat_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    _, _, match_id, choice = query.data.split("_", 3)
    match = CCL_MATCHES.get(match_id)
    if not match or match["state"] != "awaiting_inputs":
        await query.answer("Match not in correct state.", show_alert=True)
        return
    if user.id != match["batting_user"]:
        await query.answer("It's not your turn to bat.", show_alert=True)
        return
    if choice not in BATSMAN_OPTIONS:
        await query.answer("Invalid batting choice.", show_alert=True)
        return
    if match["bat_choice"] is not None:
        await query.answer("You already chose your batting number.", show_alert=True)
        return
    match["bat_choice"] = choice
    await query.answer(f"You chose {choice} to bat.")
    await check_both_choices_and_process(context, match)

# --- CCL Bowler Choice Handler ---
async def ccl_bowl_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    _, _, match_id, choice = query.data.split("_", 3)
    match = CCL_MATCHES.get(match_id)
    if not match or match["state"] != "awaiting_inputs":
        await query.answer("Match not in correct state.", show_alert=True)
        return
    if user.id != match["bowling_user"]:
        await query.answer("It's not your turn to bowl.", show_alert=True)
        return
    if choice not in BOWLER_OPTIONS:
        await query.answer("Invalid bowling choice.", show_alert=True)
        return
    if match["bowl_choice"] is not None:
        await query.answer("You already chose your bowling variation.", show_alert=True)
        return
    match["bowl_choice"] = choice
    await query.answer(f"You chose {choice} to bowl.")
    await check_both_choices_and_process(context, match)

# --- Check Both Choices and Process Ball ---
async def check_both_choices_and_process(context: ContextTypes.DEFAULT_TYPE, match):
    if match["bat_choice"] is not None and match["bowl_choice"] is not None:
        await process_ball(context, match)

# --- Process Ball ---
async def process_ball(context: ContextTypes.DEFAULT_TYPE, match):
    chat_id = match["group_id"]
    message_id = match["message_id"]
    bat_num = match["bat_choice"]
    bowl_var = match["bowl_choice"]

    # Clear choices for next ball
    match["bat_choice"] = None
    match["bowl_choice"] = None

    match["balls"] += 1
    over = (match["balls"] - 1) // 6
    ball_in_over = (match["balls"] - 1) % 6 + 1

    # Determine if out
    is_out = (bat_num == "0" and bowl_var == "YORKER") or (bat_num == bowl_var)  # Example condition
    # (You can customize your out condition here)

    # Compose messages with delays
    await context.bot.send_message(chat_id=chat_id, text=f"Over {over + 1}\nBall {ball_in_over}")
    await asyncio.sleep(3)
    await context.bot.send_message(chat_id=chat_id, text=f"{USERS[match['bowling_user']]['name']} Bowls a {bowl_var} Ball")
    await asyncio.sleep(4)

    if is_out:
        outcome_key = "out"
        await send_random_event_update(context, chat_id, outcome_key)
        # Handle wicket and innings logic here
        # Swap innings or end match as per your logic
    else:
        runs = int(bat_num)
        match["score"] += runs
        outcome_key = bat_num
        await send_random_event_update(context, chat_id, outcome_key)

        # Milestone announcements
        if match["score"] >= 50 and not match["half_century_announced"]:
            match["half_century_announced"] = True
            await send_random_event_update(context, chat_id, "50")
            await context.bot.send_message(chat_id=chat_id, text="🎉 Half-century! Keep it up!")
        if match["score"] >= 100 and not match["century_announced"]:
            match["century_announced"] = True
            await send_random_event_update(context, chat_id, "100")
            await context.bot.send_message(chat_id=chat_id, text="🏆 Century! Amazing innings!")

    # Prompt next inputs by DM
    try:
        await context.bot.send_message(
            chat_id=match["batting_user"],
            text=f"🏏 Choose your next shot:",
            reply_markup=ccl_batsman_keyboard(match["match_id"])
        )
        await context.bot.send_message(
            chat_id=match["bowling_user"],
            text=f"⚾ Choose your next delivery:",
            reply_markup=ccl_bowler_keyboard(match["match_id"])
        )
    except Exception as e:
        logger.error(f"Error sending DM prompts: {e}")

# --- Register all handlers ---
def register_handlers(application):
    application.add_handler(CommandHandler("ccl", ccl_command))
    application.add_handler(CallbackQueryHandler(ccl_join_callback, pattern=r"^ccl_join_"))
    application.add_handler(CallbackQueryHandler(ccl_cancel_callback, pattern=r"^ccl_cancel_"))
    application.add_handler(CallbackQueryHandler(ccl_toss_callback, pattern=r"^ccl_toss_"))
    application.add_handler(CallbackQueryHandler(ccl_batbowl_callback, pattern=r"^ccl_batbowl_"))
    application.add_handler(CallbackQueryHandler(ccl_bat_choice_callback, pattern=r"^ccl_bat_"))
    application.add_handler(CallbackQueryHandler(ccl_bowl_choice_callback, pattern=r"^ccl_bowl_"))

# --- You can call register_handlers(app) in your main bot setup ---
