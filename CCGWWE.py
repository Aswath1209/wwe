import logging
import random
import uuid
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from motor.motor_asyncio import AsyncIOMotorClient

# --- Configuration ---
BOT_TOKEN = "8133604799:AAF2dE86UjRxfAdUcqyoz3O9RgaCeTwaoHM"
MONGO_URL = "mongodb://mongo:GhpHMiZizYnvJfKIQKxoDbRyzBCpqEyC@mainline.proxy.rlwy.net:54853"
ADMIN_IDS = {123456789}  # Replace with your Telegram user ID(s)

# --- MongoDB Setup ---
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client.handcricket
users_collection = db.users

# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# --- Global Data Stores ---
USERS = {}  # user_id -> user data dict

CCL_MATCHES = {}         # match_id -> match dict
USER_CCL_MATCH = {}      # user_id -> match_id (one match per user)
GROUP_CCL_MATCH = {}     # group_chat_id -> match_id (one match per group)

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

# --- Command Handlers ---

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

# --- Leaderboard with page switching ---
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

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📜 Available Commands:\n"
        "/start - Start the bot\n"
        "/register - Get free coins\n"
        "/profile - View your profile\n"
        "/send - Send coins (reply to user)\n"
        "/add - Admin: add coins\n"
        "/leaderboard - View top players\n"
        "/ccl - Start a CCL match in group\n"
        "/endmatch - Admin: end ongoing CCL match in group\n"
        "/help - Show this help message"
    )
    await update.message.reply_text(help_text)

# --- CCL command will be in Part 2 ---
import asyncio

# --- Constants for CCL ---

BOWLER_MAP = {
    "0": "RS",
    "1": "Bouncer",
    "2": "Yorker",
    "3": "Short",
    "4": "Slower",
    "6": "Knuckle"
}

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

# --- Helper keyboards for toss and bat/bowl choice ---

def toss_keyboard(match_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Heads", callback_data=f"ccl_toss_{match_id}_heads"),
            InlineKeyboardButton("Tails", callback_data=f"ccl_toss_{match_id}_tails"),
        ]
    ])

def batbowl_keyboard(match_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Bat 🏏", callback_data=f"ccl_batbowl_{match_id}_bat"),
            InlineKeyboardButton("Bowl ⚾", callback_data=f"ccl_batbowl_{match_id}_bowl"),
        ]
    ])

def join_cancel_keyboard(match_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Join ✅", callback_data=f"ccl_join_{match_id}")],
        [InlineKeyboardButton("Cancel ❌", callback_data=f"ccl_cancel_{match_id}")]
    ])

# --- Utility to send random GIF and commentary ---

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

# --- /ccl Command Handler ---

async def ccl_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    ensure_user(user)

    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("CCL matches can only be started in groups.")
        return

    if GROUP_CCL_MATCH.get(chat.id):
        await update.message.reply_text("There is already an ongoing CCL match in this group.")
        return

    if USER_CCL_MATCH.get(user.id):
        await update.message.reply_text("You are already participating in a CCL match.")
        return

    match_id = str(uuid.uuid4())
    match = {
        "match_id": match_id,
        "group_id": chat.id,
        "initiator": user.id,
        "opponent": None,
        "state": "waiting_for_opponent",
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
        reply_markup=join_cancel_keyboard(match_id)
    )
    match["message_id"] = sent_msg.message_id

# --- Callback Handlers ---

async def ccl_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    _, _, match_id = query.data.split("_", 2)
    match = CCL_MATCHES.get(match_id)
    if not match or match["state"] != "waiting_for_opponent":
        await query.answer("Match not available to join.", show_alert=True)
        return
    if user.id == match["initiator"]:
        await query.answer("You cannot join your own match.", show_alert=True)
        return
    if match["opponent"]:
        await query.answer("Match already has an opponent.", show_alert=True)
        return
    ensure_user(user)
    if USER_CCL_MATCH.get(user.id):
        await query.answer("You are already in a CCL match.", show_alert=True)
        return
    match["opponent"] = user.id
    match["state"] = "toss"
    USER_CCL_MATCH[user.id] = match_id
    chat_id = match["group_id"]
    message_id = match["message_id"]
    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=(
            f"Match between {USERS[match['initiator']]['name']} and {USERS[user.id]['name']}!\n"
            f"{USERS[match['initiator']]['name']}, choose Heads or Tails for the toss."
        ),
        reply_markup=toss_keyboard(match_id)
    )
    await query.answer()

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
    USER_CCL_MATCH[match["initiator"]] = None
    if match.get("opponent"):
        USER_CCL_MATCH[match["opponent"]] = None
    GROUP_CCL_MATCH.pop(chat_id, None)
    CCL_MATCHES.pop(match_id, None)
    if message_id:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text="The CCL match has been cancelled by the initiator."
        )
    await query.answer()

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
        reply_markup=batbowl_keyboard(match_id)
    )
    await query.answer()

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
    # Initialize innings data
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

    # Send DM to batsman and bowler asking for text input
    try:
        await context.bot.send_message(
            chat_id=match["batting_user"],
            text=(
                "🏏 You're batting! Send your shot number as text:\n"
                "Allowed numbers: 0,1,2,3,4,6"
            )
        )
        await context.bot.send_message(
            chat_id=match["bowling_user"],
            text=(
                "⚾ You're bowling! Send your delivery number as text:\n"
                "RS=0, Bouncer=1, Yorker=2, Short=3, Slower=4, Knuckle=6"
            )
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
            f"Both players have been sent instructions via DM."
        ),
        reply_markup=None
    )
    await query.answer()

# --- Text Handlers for batsman and bowler choices ---

async def batsman_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()
    match_id = USER_CCL_MATCH.get(user.id)
    if not match_id:
        return
    match = CCL_MATCHES.get(match_id)
    if not match or match["state"] != "awaiting_inputs":
        return
    if user.id != match["batting_user"]:
        return
    if text not in BATSMAN_OPTIONS:
        await update.message.reply_text("❌ Invalid shot! Please send one of: 0,1,2,3,4,6")
        return
    if match["bat_choice"] is not None:
        await update.message.reply_text("⚠️ You already sent your shot for this ball.")
        return
    match["bat_choice"] = text
    await update.message.reply_text(f"✅ You chose: {text}")
    await check_both_choices_and_process(context, match)

async def bowler_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()
    match_id = USER_CCL_MATCH.get(user.id)
    if not match_id:
        return
    match = CCL_MATCHES.get(match_id)
    if not match or match["state"] != "awaiting_inputs":
        return
    if user.id != match["bowling_user"]:
        return
    if text not in BOWLER_MAP.keys():
        await update.message.reply_text(
            "❌ Invalid delivery! Please send one of:\n"
            "RS=0, Bouncer=1, Yorker=2, Short=3, Slower=4, Knuckle=6"
        )
        return
    if match["bowl_choice"] is not None:
        await update.message.reply_text("⚠️ You already sent your delivery for this ball.")
        return
    match["bowl_choice"] = text
    await update.message.reply_text(f"✅ You chose: {text} ({BOWLER_MAP[text]})")
    await check_both_choices_and_process(context, match)

# --- Check both choices and process ball ---

async def check_both_choices_and_process(context: ContextTypes.DEFAULT_TYPE, match):
    if match["bat_choice"] is not None and match["bowl_choice"] is not None:
        await process_ball(context, match)

# --- Process ball logic ---

async def process_ball(context: ContextTypes.DEFAULT_TYPE, match):
    chat_id = match["group_id"]
    bat_num = match["bat_choice"]
    bowl_num = match["bowl_choice"]

    # Clear choices for next ball
    match["bat_choice"] = None
    match["bowl_choice"] = None

    match["balls"] += 1
    over = (match["balls"] - 1) // 6
    ball_in_over = (match["balls"] - 1) % 6 + 1

    # Out condition: bowler chooses Yorker (2) and batsman chooses 2 OR both choose same number
    is_out = (bowl_num == "2" and bat_num == "2") or (bowl_num == bat_num)

    await context.bot.send_message(chat_id=chat_id, text=f"Over {over + 1}\nBall {ball_in_over}")
    await asyncio.sleep(2)
    await context.bot.send_message(chat_id=chat_id, text=f"{USERS[match['bowling_user']]['name']} bowls {BOWLER_MAP[bowl_num]}")

    await asyncio.sleep(3)

    if is_out:
        await send_random_event_update(context, chat_id, "out")
        if match["innings"] == 1:
            # First innings over
            match["target"] = match["score"] + 1
            match["innings"] = 2
            match["balls"] = 0
            match["score"] = 0
            match["batting_user"], match["bowling_user"] = match["bowling_user"], match["batting_user"]
            match["half_century_announced"] = False
            match["century_announced"] = False
            await context.bot.send_message(chat_id=chat_id, text=f"Innings break! Target for second innings: {match['target']}")
        else:
            # Second innings out => match ends, bowler wins
            await finish_match(context, match, winner=match["bowling_user"])
            return
    else:
        runs = int(bat_num)
        match["score"] += runs
        await send_random_event_update(context, chat_id, bat_num)

        # Milestone announcements
        if match["score"] >= 50 and not match["half_century_announced"]:
            match["half_century_announced"] = True
            await send_random_event_update(context, chat_id, "50")
            await context.bot.send_message(chat_id=chat_id, text="🎉 Half-century! Keep it up!")
        if match["score"] >= 100 and not match["century_announced"]:
            match["century_announced"] = True
            await send_random_event_update(context, chat_id, "100")
            await context.bot.send_message(chat_id=chat_id, text="🏆 Century! Amazing innings!")

        # Check second innings target chase
        if match["innings"] == 2 and match["score"] >= match["target"]:
            # Batting player wins immediately
            await finish_match(context, match, winner=match["batting_user"])
            return

    # Send current score separately
    await context.bot.send_message(chat_id=chat_id, text=f"Current Score: {match['score']}")

    # Prompt next inputs by DM
    try:
        await context.bot.send_message(
            chat_id=match["batting_user"],
            text="🏏 Send your shot number (0,1,2,3,4,6):"
        )
        await context.bot.send_message(
            chat_id=match["bowling_user"],
            text="⚾ Send your delivery number (RS=0, Bouncer=1, Yorker=2, Short=3, Slower=4, Knuckle=6):"
        )
    except Exception as e:
        logger.error(f"Error sending DM prompts: {e}")

# --- Finish match and update stats ---

async def finish_match(context: ContextTypes.DEFAULT_TYPE, match, winner):
    chat_id = match["group_id"]
    initiator = match["initiator"]
    opponent = match["opponent"]
    loser = initiator if winner != initiator else opponent

    USERS[winner]["wins"] += 1
    USERS[loser]["losses"] += 1

    await save_user(winner)
    await save_user(loser)

    await context.bot.send_message(chat_id=chat_id, text=f"🏆 {USERS[winner]['name']} won the match! Congratulations! 🎉")

    USER_CCL_MATCH[initiator] = None
    USER_CCL_MATCH[opponent] = None
    GROUP_CCL_MATCH.pop(chat_id, None)
    CCL_MATCHES.pop(match["match_id"], None)

# --- /endmatch command for admins ---

async def endmatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("This command can only be used in groups.")
        return
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ You are not authorized to end matches.")
        return
    match_id = GROUP_CCL_MATCH.get(chat.id)
    if not match_id:
        await update.message.reply_text("No ongoing CCL match in this group.")
        return
    match = CCL_MATCHES.get(match_id)
    if not match:
        await update.message.reply_text("Match data not found.")
        return
    USER_CCL_MATCH[match["initiator"]] = None
    if match.get("opponent"):
        USER_CCL_MATCH[match["opponent"]] = None
    GROUP_CCL_MATCH.pop(chat.id, None)
    CCL_MATCHES.pop(match_id, None)
    await update.message.reply_text("The ongoing CCL match has been ended by an admin.")

# --- Register all handlers ---

def register_handlers(application):
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("register", register))
    application.add_handler(CommandHandler("profile", profile))
    application.add_handler(CommandHandler("send", send))
    application.add_handler(CommandHandler("add", add))
    application.add_handler(CommandHandler("leaderboard", leaderboard))
    application.add_handler(CallbackQueryHandler(leaderboard_callback, pattern=r"^leaderboard_"))
    application.add_handler(CommandHandler("help", help_command))

    application.add_handler(CommandHandler("ccl", ccl_command))
    application.add_handler(CallbackQueryHandler(ccl_join_callback, pattern=r"^ccl_join_"))
    application.add_handler(CallbackQueryHandler(ccl_cancel_callback, pattern=r"^ccl_cancel_"))
    application.add_handler(CallbackQueryHandler(ccl_toss_callback, pattern=r"^ccl_toss_"))
    application.add_handler(CallbackQueryHandler(ccl_batbowl_callback, pattern=r"^ccl_batbowl_"))

    application.add_handler(MessageHandler(filters.TEXT & filters.User(user_id=USER_CCL_MATCH.keys()), batsman_text_handler), group=1)
    application.add_handler(MessageHandler(filters.TEXT & filters.User(user_id=USER_CCL_MATCH.keys()), bowler_text_handler), group=2)

    application.add_handler(CommandHandler("endmatch", endmatch))
import asyncio
from telegram.ext import ApplicationBuilder

# --- Main Startup and Run ---

async def on_startup(app):
    await load_users()
    logger.info("Users loaded from database. Bot is ready.")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Register all command and callback handlers
    register_handlers(app)

    # Set startup hook
    app.post_init = on_startup

    logger.info("Starting bot polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
