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
    MessageHandler,
    filters,
    ContextTypes,
)

from motor.motor_asyncio import AsyncIOMotorClient

# --- Config ---
TOKEN = "YOUR_BOT_TOKEN_HERE"
ADMIN_IDS = {123456789}  # Replace with your Telegram user ID(s)

MONGO_URL = "YOUR_MONGODB_CONNECTION_STRING"  # <--- PUT YOUR MONGO URL HERE
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client.handcricket
users_collection = db.users

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# --- Global Data ---
USERS = {}  # user_id -> user dict

PM_MATCHES = {}          # match_id -> match dict
USER_PM_MATCHES = {}     # user_id -> set of match_ids
GROUP_PM_MATCHES = {}    # group_chat_id -> set of match_ids

CCL_MATCHES = {}         # match_id -> match dict
USER_CCL_MATCH = {}      # user_id -> match_id
GROUP_CCL_MATCH = {}     # group_chat_id -> match_id

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
        USER_PM_MATCHES[user.id] = set()
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
            user_id = user.get("user_id") or user.get("_id")
            if not user_id:
                logger.warning(f"Skipping user without user_id: {user}")
                continue
            if "user_id" not in user:
                user["user_id"] = user_id
            USERS[user_id] = user
            USER_PM_MATCHES[user_id] = set()
            USER_CCL_MATCH[user_id] = None
        logger.info("Users loaded successfully.")
    except Exception as e:
        logger.error(f"Error loading users: {e}", exc_info=True)

def mention_player(player):
    user_id = player.get('user_id') or player.get('id')
    name = player.get('name', 'Player')
    if user_id is None:
        return name
    return f"[{name}](tg://user?id={user_id})"

# --- Commands ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)
    await save_user(user.id)
    await update.message.reply_text(
        f"Welcome to CCL HandCricket, {USERS[user.id]['name']}! Use /register to get 4000 💰 coins."
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
    await update.message.reply_text("Registered! You received 4000 💰 coins.")

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)
    u = USERS[user.id]
    text = (
        f"👤 Profile\n"
        f"• Name: {u['name']}\n"
        f"• ID: {user.id}\n"
        f"• Purse: 💰 {u.get('coins', 0)} coins\n\n"
        f"📊 Performance History\n"
        f"• Wins: 🏆 {u.get('wins', 0)}\n"
        f"• Losses: ❌ {u.get('losses', 0)}"
    )
    await update.message.reply_text(text)

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)
    now = datetime.utcnow()
    last = USERS[user.id].get("last_daily")
    if last and (now - last) < timedelta(hours=24):
        rem = timedelta(hours=24) - (now - last)
        h, m = divmod(rem.seconds // 60, 60)
        await update.message.reply_text(f"Daily already claimed. Try again in {h}h {m}m.")
        return
    USERS[user.id]["coins"] += 2000
    USERS[user.id]["last_daily"] = now
    await save_user(user.id)
    await update.message.reply_text("You received 2000 💰 coins as daily reward!")

async def send_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)
    if not update.message.reply_to_message:
        await update.message.reply_text("Please reply to the user you want to send coins to.")
        return
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /send <amount> (reply to user message)")
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

async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def endmatch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("❌ This command can only be used in groups.")
        return
    ccl_match_id = GROUP_CCL_MATCH.get(chat.id)
    if ccl_match_id:
        match = CCL_MATCHES.get(ccl_match_id)
        if match:
            USER_CCL_MATCH[match["initiator"]] = None
            if match.get("opponent"):
                USER_CCL_MATCH[match["opponent"]] = None
            GROUP_CCL_MATCH.pop(chat.id, None)
            CCL_MATCHES.pop(ccl_match_id, None)
            await update.message.reply_text("✅ The ongoing CCL match in this group has been ended by an admin.")
            return
    await update.message.reply_text("ℹ️ No ongoing CCL match found in this group.")

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

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "**CCL HandCricket Commands:**\n\n"
        "/start - Start the bot\n"
        "/register - Register and get 4000 💰 coins\n"
        "/pm [bet] - Start a PM match optionally with bet\n"
        "/ccl [bet] - Start a CCL match optionally with bet\n"
        "/profile - Show your profile\n"
        "/daily - Claim daily 2000 💰 coins\n"
        "/leaderboard - Show leaderboard\n"
        "/send - Send coins (reply to user and use /send <amount>)\n"
        "/add - Add coins (admin only)\n"
        "/endmatch - End ongoing CCL match in group (admin only)\n"
        "/help - Show this help message"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")
# --- PM Mode Inline Keyboards ---

def pm_join_cancel_keyboard(match_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Join ✅", callback_data=f"pm_join_{match_id}"),
            InlineKeyboardButton("Cancel ❌", callback_data=f"pm_cancel_{match_id}")
        ]
    ])

def pm_toss_keyboard(match_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Heads", callback_data=f"pm_toss_heads_{match_id}"),
            InlineKeyboardButton("Tails", callback_data=f"pm_toss_tails_{match_id}")
        ]
    ])

def pm_bat_bowl_keyboard(match_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Bat 🏏", callback_data=f"pm_bat_{match_id}"),
            InlineKeyboardButton("Bowl ⚾", callback_data=f"pm_bowl_{match_id}")
        ]
    ])

def pm_number_keyboard(match_id, player_type):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(str(n), callback_data=f"pm_{player_type}num_{match_id}_{n}") for n in [1,2,3]],
        [InlineKeyboardButton(str(n), callback_data=f"pm_{player_type}num_{match_id}_{n}") for n in [4,5,6]],
    ])

def build_pm_match_message(match):
    over = match["balls"] // 6
    ball_in_over = match["balls"] % 6 + 1
    batter = USERS[match["batting_user"]]["name"]
    bowler = USERS[match["bowling_user"]]["name"]

    lines = [
        f"**Over : {over}.{ball_in_over}**",
        "",
        f"🏏 **Batter : {batter}**",
        f"⚾ **Bowler : {bowler}**",
        ""
    ]

    # Awaiting batsman
    if match["batsman_choice"] is None and match["bowler_choice"] is None:
        lines.append(f"**{batter}, choose your Bat number!**")
        return "\n".join(lines)

    # Awaiting bowler
    if match["batsman_choice"] is not None and match["bowler_choice"] is None:
        lines.append(f"**{batter} has selected a number, {bowler} it's your turn to bowl.**")
        return "\n".join(lines)

    # Both have chosen, show both numbers and total score
    if match["batsman_choice"] is not None and match["bowler_choice"] is not None:
        lines.append(f"**{batter} Bat {match['batsman_choice']}**")
        lines.append(f"**{bowler} Bowl {match['bowler_choice']}**\n")
        lines.append("**Total Score :**")
        lines.append(f"**{batter} scored total of {match['score']} runs**\n")
        if match.get("is_out", False):
            if match["innings"] == 1:
                lines.append(f"**{batter} sets a target of {match['score'] + 1}**\n")
                lines.append(f"**{bowler} will now Bat and {batter} will now Bowl!**")
            else:
                lines.append("")  # Winner message handled separately
        else:
            lines.append("**Next Move :**")
            lines.append(f"**{batter} continue your Bat!**")
        return "\n".join(lines)

    return "\n".join(lines)

# --- PM Command Handler ---

async def pm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    args = context.args

    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("❌ PM matches can only be started in groups.")
        return

    ensure_user(user)

    bet = 0
    if args:
        try:
            bet = int(args[0])
            if bet < 0:
                await update.message.reply_text("Bet amount must be positive.")
                return
        except ValueError:
            await update.message.reply_text("Invalid bet amount.")
            return

    if bet > 0 and USERS[user.id]["coins"] < bet:
        await update.message.reply_text("You don't have enough coins for that bet.")
        return

    match_id = str(uuid.uuid4())
    PM_MATCHES[match_id] = {
        "match_id": match_id,
        "group_chat_id": chat.id,
        "initiator": user.id,
        "opponent": None,
        "bet": bet,
        "state": "waiting_join",
        "toss_winner": None,
        "batting_user": None,
        "bowling_user": None,
        "score": 0,
        "balls": 0,
        "innings": 1,
        "target": None,
        "batsman_choice": None,
        "bowler_choice": None,
        "message_id": None,
    }
    USER_PM_MATCHES.setdefault(user.id, set()).add(match_id)
    GROUP_PM_MATCHES.setdefault(chat.id, set()).add(match_id)

    sent_msg = await update.message.reply_text(
        f"🏏 PM Cricket game started by {USERS[user.id]['name']}! Bet: {bet}💰\nPress Join below to play.",
        reply_markup=pm_join_cancel_keyboard(match_id),
    )
    PM_MATCHES[match_id]["message_id"] = sent_msg.message_id

# --- PM Join Callback ---

async def pm_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    _, _, match_id = query.data.split("_", 2)

    match = PM_MATCHES.get(match_id)
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

    if match["bet"] > 0 and USERS[user.id]["coins"] < match["bet"]:
        await query.answer("You don't have enough coins to join this bet match.", show_alert=True)
        return

    match["opponent"] = user.id
    match["state"] = "toss"
    USER_PM_MATCHES.setdefault(user.id, set()).add(match_id)

    chat_id = match["group_chat_id"]
    message_id = match["message_id"]

    text = (
        f"Match started between {USERS[match['initiator']]['name']} and {USERS[user.id]['name']}!\n"
        f"{USERS[match['initiator']]['name']}, choose Heads or Tails for the toss."
    )
    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=text,
        reply_markup=pm_toss_keyboard(match_id),
    )
    await query.answer()

# --- PM Cancel Callback ---

async def pm_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    _, _, match_id = query.data.split("_", 2)

    match = PM_MATCHES.get(match_id)
    if not match:
        await query.answer("Match not found or already ended.", show_alert=True)
        return

    if user.id != match["initiator"]:
        await query.answer("Only the match initiator can cancel.", show_alert=True)
        return

    chat_id = match["group_chat_id"]
    message_id = match.get("message_id")

    USER_PM_MATCHES[match["initiator"]].discard(match_id)
    if match.get("opponent"):
        USER_PM_MATCHES[match["opponent"]].discard(match_id)
    GROUP_PM_MATCHES[chat_id].discard(match_id)
    PM_MATCHES.pop(match_id, None)

    if message_id:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text="The PM match has been cancelled by the initiator.",
        )
    await query.answer()

# --- PM Toss Choice Callback ---

async def pm_toss_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    _, _, toss_choice, match_id = query.data.split("_", 3)

    match = PM_MATCHES.get(match_id)
    if not match or match["state"] != "toss":
        await query.answer("Invalid toss state.", show_alert=True)
        return

    if user.id != match["initiator"]:
        await query.answer("Only the initiator chooses toss.", show_alert=True)
        return

    coin_result = random.choice(["heads", "tails"])
    toss_winner = match["initiator"] if toss_choice == coin_result else match["opponent"]
    toss_loser = match["opponent"] if toss_winner == match["initiator"] else match["initiator"]

    match["toss_winner"] = toss_winner
    match["toss_loser"] = toss_loser
    match["state"] = "bat_bowl_choice"

    chat_id = match["group_chat_id"]
    message_id = match["message_id"]

    text = (
        f"The coin landed on {coin_result.capitalize()}!\n"
        f"{USERS[toss_winner]['name']} won the toss! Choose to Bat or Bowl first."
    )
    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=text,
        reply_markup=pm_bat_bowl_keyboard(match_id),
    )
    await query.answer()

# --- PM Bat/Bowl Choice Callback ---

async def pm_bat_bowl_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    _, choice, match_id = query.data.split("_", 2)

    match = PM_MATCHES.get(match_id)
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
        "state": "init",
        "score": 0,
        "balls": 0,
        "innings": 1,
        "target": None,
        "batsman_choice": None,
        "bowler_choice": None,
    })

    chat_id = match["group_chat_id"]
    message_id = match["message_id"]

    text = build_pm_match_message(match)
    keyboard = pm_number_keyboard(match_id, "bat")

    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=text,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await query.answer()

# --- PM Bat Number Callback ---

async def pm_batnum_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    _, _, match_id, num_str = query.data.split("_", 3)
    num = int(num_str)

    match = PM_MATCHES.get(match_id)
    if not match or match["state"] not in ["init", "batting"]:
        await query.answer("Match not in batting state.", show_alert=True)
        return

    if user.id != match["batting_user"]:
        await query.answer("It's not your turn to bat.", show_alert=True)
        return

    if match["batsman_choice"] is not None:
        await query.answer("You already chose your batting number.", show_alert=True)
        return

    match["batsman_choice"] = num
    match["state"] = "batting"

    chat_id = match["group_chat_id"]
    message_id = match["message_id"]

    text = build_pm_match_message(match)
    keyboard = pm_number_keyboard(match_id, "bowl")
    await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=keyboard, parse_mode="Markdown")
    await query.answer()

# --- PM Bowl Number Callback ---

async def pm_bowlnum_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    _, _, match_id, num_str = query.data.split("_", 3)
    num = int(num_str)

    match = PM_MATCHES.get(match_id)
    if not match or match["state"] != "batting":
        await query.answer("Match not in batting state.", show_alert=True)
        return

    if user.id != match["bowling_user"]:
        await query.answer("It's not your turn to bowl.", show_alert=True)
        return

    if match["bowler_choice"] is not None:
        await query.answer("You already chose your bowling number.", show_alert=True)
        return

    match["bowler_choice"] = num

    await process_pm_ball(context, match)
    await query.answer()

# --- Process Ball Result in PM Mode ---

async def process_pm_ball(context: ContextTypes.DEFAULT_TYPE, match):
    batsman_choice = match["batsman_choice"]
    bowler_choice = match["bowler_choice"]
    chat_id = match["group_chat_id"]
    message_id = match["message_id"]

    if batsman_choice is None or bowler_choice is None:
        return

    match["balls"] += 1
    is_out = batsman_choice == bowler_choice
    match["is_out"] = is_out  # Track for message

    if not is_out:
        match["score"] += batsman_choice

    text = build_pm_match_message(match)

    # Out in first innings: swap
    if is_out and match["innings"] == 1:
        match["target"] = match["score"] + 1
        match["innings"] = 2
        match["batting_user"], match["bowling_user"] = match["bowling_user"], match["batting_user"]
        match["score"] = 0
        match["balls"] = 0
        match["batsman_choice"] = None
        match["bowler_choice"] = None
        match["state"] = "init"
        match["is_out"] = False
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=pm_number_keyboard(match["match_id"], "bat"),
            parse_mode="Markdown"
        )
        return

    # Out or target reached in second innings: finish match
    if is_out or (match["innings"] == 2 and match["score"] >= match["target"]):
        player1 = USERS[match["batting_user"]]["name"]
        player2 = USERS[match["bowling_user"]]["name"]
        score1 = match["score"] if match["innings"] == 2 else match["target"] - 1
        score2 = match["score"] if match["innings"] == 2 else 0
        if match["innings"] == 2:
            winner = player1 if match["score"] >= match["target"] else player2
            win_by = abs(match["score"] - (match["target"] - 1))
            result_text = (
                f"Results of the match between {player1} and {player2}\n\n"
                f"Score :\n\n"
                f"{player1} : {match['score']} Runs\n"
                f"{player2} : {match['target'] - 1} Runs\n\n"
                f"{winner} won by {win_by} Runs"
            )
        else:
            result_text = text
        await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=result_text, reply_markup=None, parse_mode="Markdown")

        # Update stats and coins
        bet = match["bet"]
        if bet > 0:
            winner_id = match["batting_user"] if match["score"] >= match["target"] else match["bowling_user"]
            loser_id = match["bowling_user"] if winner_id == match["batting_user"] else match["batting_user"]
            USERS[winner_id]["coins"] += bet * 2
            USERS[loser_id]["coins"] = max(0, USERS[loser_id]["coins"] - bet)
            USERS[winner_id]["wins"] += 1
            USERS[loser_id]["losses"] += 1
            await save_user(winner_id)
            await save_user(loser_id)

        match["state"] = "finished"
        USER_PM_MATCHES[match["initiator"]].discard(match["match_id"])
        if match.get("opponent"):
            USER_PM_MATCHES[match["opponent"]].discard(match["match_id"])
        GROUP_PM_MATCHES[chat_id].discard(match["match_id"])
        PM_MATCHES.pop(match["match_id"], None)
        return

    # Continue next ball
    match["batsman_choice"] = None
    match["bowler_choice"] = None
    match["state"] = "batting"
    match["is_out"] = False
    text = build_pm_match_message(match)
    keyboard = pm_number_keyboard(match["match_id"], "bat")
    await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=keyboard, parse_mode="Markdown")
import asyncio

# --- CCL Inline Keyboards ---

def ccl_join_cancel_keyboard(match_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Join ✅", callback_data=f"ccl_join_{match_id}"),
            InlineKeyboardButton("Cancel ❌", callback_data=f"ccl_cancel_{match_id}")
        ]
    ])

def ccl_toss_keyboard(match_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Heads", callback_data=f"ccl_toss_heads_{match_id}"),
            InlineKeyboardButton("Tails", callback_data=f"ccl_toss_tails_{match_id}")
        ]
    ])

def ccl_bat_bowl_keyboard(match_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Bat 🏏", callback_data=f"ccl_bat_{match_id}"),
            InlineKeyboardButton("Bowl ⚾", callback_data=f"ccl_bowl_{match_id}")
        ]
    ])

CCL_BATTING_NUMBERS = {"0", "1", "2", "3", "4", "6"}
CCL_BOWLING_TYPES = {"rs", "bouncer", "yorker", "short", "slower", "knuckle"}

# --- Commentary and GIFs (multiple GIFs per type) ---

CCL_COMMENTARY = {
    "0": [
        "Dot ball! The batsman couldn't score.",
        "No run, well bowled!",
        "That's a dot. Bowler on top.",
        "No runs off this ball.",
        "Defended solidly, no run!"
    ],
    "1": [
        "Just a single taken.",
        "Quick run for one!",
        "Keeps the scoreboard ticking with a single.",
        "Easy one run.",
        "Good running between the wickets!"
    ],
    "2": [
        "They come back for two!",
        "Double run, nice placement.",
        "Good running, that's two.",
        "A couple taken.",
        "They sneak two runs!"
    ],
    "3": [
        "Excellent running, that's three!",
        "Three runs, great effort!",
        "A triple! Not often you see that.",
        "They run three, fantastic.",
        "That's a quick three!"
    ],
    "4": [
        "FOUR! Beautiful shot to the boundary.",
        "That's a cracking FOUR!",
        "Driven for FOUR runs!",
        "What a shot, FOUR runs!",
        "Boundary! That's FOUR."
    ],
    "6": [
        "SIX! Out of the park!",
        "That's huge! SIX runs!",
        "Massive hit for SIX!",
        "He smokes it for a SIX!",
        "That's a monster SIX!"
    ],
    "wicket": [
        "Bowled! The batsman is OUT!",
        "Caught! That's a wicket.",
        "LBW! The umpire raises his finger.",
        "Clean bowled! What a delivery.",
        "That's OUT! The bowler celebrates."
    ],
    "tie": [
        "It's a tie! Both teams scored the same.",
        "Match tied! What a game.",
        "It's all square, the match ends in a tie.",
        "No winner today, it's a tie.",
        "Both teams finish level, tie game!"
    ]
}

CCL_GIFS = {
    "0": [
        "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif"
    ],
    "4": [
        "https://media.giphy.com/media/3o6Zt6ML6BklcajjsA/giphy.gif"
    ],
    "6": [
        "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif"
    ],
    "wicket": [
        "https://media.giphy.com/media/3o6Zt6ML6BklcajjsA/giphy.gif",
        "https://media.giphy.com/media/26ufdipQqU2lhNA4g/giphy.gif"
    ],
    "50": [
        "https://media.giphy.com/media/3o6Zt6ML6BklcajjsA/giphy.gif"
    ],
    "100": [
        "https://media.giphy.com/media/3o6Zt6ML6BklcajjsA/giphy.gif"
    ],
}

def random_gif(gif_list):
    return random.choice(gif_list) if gif_list else None

# --- /ccl Command Handler ---

async def ccl_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    args = context.args

    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("❌ CCL matches can only be started in groups.")
        return

    ensure_user(user)

    if GROUP_CCL_MATCH.get(chat.id):
        await update.message.reply_text("❌ There is already an ongoing CCL match in this group. Please wait for it to finish.")
        return

    bet = 0
    if args:
        try:
            bet = int(args[0])
            if bet < 0:
                await update.message.reply_text("Bet amount must be positive.")
                return
        except ValueError:
            await update.message.reply_text("Invalid bet amount.")
            return

    if bet > 0 and USERS[user.id]["coins"] < bet:
        await update.message.reply_text("You don't have enough coins for that bet.")
        return

    match_id = str(uuid.uuid4())
    CCL_MATCHES[match_id] = {
        "match_id": match_id,
        "group_chat_id": chat.id,
        "initiator": user.id,
        "opponent": None,
        "bet": bet,
        "state": "waiting_join",
        "toss_winner": None,
        "toss_loser": None,
        "batting_user": None,
        "bowling_user": None,
        "score": 0,
        "balls": 0,
        "wickets": 0,
        "innings": 1,
        "target": None,
        "batsman_choice": None,
        "bowler_choice": None,
        "milestone_50": False,
        "milestone_100": False,
        "score_first": 0,
        "score_second": 0,
    }
    USER_CCL_MATCH[user.id] = match_id
    GROUP_CCL_MATCH[chat.id] = match_id

    await update.message.reply_text(
        f"🏏 CCL Cricket game started by {USERS[user.id]['name']}! Bet: {bet}💰\nPress Join below to play.",
        reply_markup=ccl_join_cancel_keyboard(match_id),
    )

# --- Join/Cancel/Toss/BatBowl handlers (same as PM, just use ccl_ prefix) ---

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
    if match["bet"] > 0 and USERS[user.id]["coins"] < match["bet"]:
        await query.answer("You don't have enough coins to join this bet match.", show_alert=True)
        return
    match["opponent"] = user.id
    match["state"] = "toss"
    USER_CCL_MATCH[user.id] = match_id
    await query.message.edit_text(
        f"Match started between {USERS[match['initiator']]['name']} and {USERS[user.id]['name']}!\n"
        f"{USERS[match['initiator']]['name']}, choose Heads or Tails for the toss.",
        reply_markup=ccl_toss_keyboard(match_id),
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
        await query.answer("Only the initiator can cancel.", show_alert=True)
        return
    chat_id = match["group_chat_id"]
    del CCL_MATCHES[match_id]
    USER_CCL_MATCH[match["initiator"]] = None
    if match.get("opponent"):
        USER_CCL_MATCH[match["opponent"]] = None
    GROUP_CCL_MATCH.pop(chat_id, None)
    await query.message.edit_text("The CCL match has been cancelled by the initiator.")
    await query.answer()

async def ccl_toss_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    _, _, choice, match_id = query.data.split("_", 3)
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
    await query.message.edit_text(
        f"The coin landed on {coin_result.capitalize()}!\n"
        f"{USERS[toss_winner]['name']} won the toss! Choose to Bat or Bowl first.",
        reply_markup=ccl_bat_bowl_keyboard(match_id),
    )
    await query.answer()

async def ccl_bat_bowl_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    _, choice, match_id = query.data.split("_", 2)
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
        "state": "batting",
        "score": 0,
        "balls": 0,
        "wickets": 0,
        "innings": 1,
        "target": None,
        "batsman_choice": None,
        "bowler_choice": None,
        "milestone_50": False,
        "milestone_100": False,
    })
    batting_mention = mention_player(USERS[match['batting_user']])
    bowling_mention = mention_player(USERS[match['bowling_user']])
    await query.message.edit_text(
        f"Match started!\n\n"
        f"🏏 Batter: {batting_mention}\n"
        f"⚾ Bowler: {bowling_mention}\n\n"
        f"{batting_mention} and {bowling_mention}, please send your choices in DM to me.",
        parse_mode="Markdown",
    )
    await send_ccl_dm_prompts(context, match)
    await query.answer()

async def send_ccl_dm_prompts(context: ContextTypes.DEFAULT_TYPE, match):
    try:
        await context.bot.send_message(
            chat_id=match["batting_user"],
            text="Please send your batting number (0,1,2,3,4,6):",
        )
    except Exception:
        group_chat_id = match["group_chat_id"]
        await context.bot.send_message(
            chat_id=group_chat_id,
            text=f"Cannot send DM to {mention_player(USERS[match['batting_user']])}. Please start a chat with me first.",
        )
    try:
        await context.bot.send_message(
            chat_id=match["bowling_user"],
            text="Please send your bowling type (rs, bouncer, yorker, short, slower, knuckle):",
        )
    except Exception:
        group_chat_id = match["group_chat_id"]
        await context.bot.send_message(
            chat_id=group_chat_id,
            text=f"Cannot send DM to {mention_player(USERS[match['bowling_user']])}. Please start a chat with me first.",
        )

async def ccl_dm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip().lower()
    match_id = USER_CCL_MATCH.get(user.id)
    if not match_id:
        await update.message.reply_text("You are not currently in a CCL match.")
        return
    match = CCL_MATCHES.get(match_id)
    if not match or match["state"] != "batting":
        await update.message.reply_text("Match is not in batting state.")
        return
    if user.id == match["batting_user"]:
        if text not in CCL_BATTING_NUMBERS:
            await update.message.reply_text("Please choose between 0, 1, 2, 3, 4, 6.")
            return
        if match["batsman_choice"] is not None:
            await update.message.reply_text("You have already sent your batting number for this ball.")
            return
        match["batsman_choice"] = int(text)
        await update.message.reply_text(f"You chose {text}.")
    elif user.id == match["bowling_user"]:
        if text not in CCL_BOWLING_TYPES:
            await update.message.reply_text("Please choose between rs, bouncer, yorker, short, slower, knuckle.")
            return
        if match["bowler_choice"] is not None:
            await update.message.reply_text("You have already sent your bowling type for this ball.")
            return
        match["bowler_choice"] = text
        await update.message.reply_text(f"You chose {text}.")
    else:
        await update.message.reply_text("You are not a player in this match.")
        return
    if match["batsman_choice"] is not None and match["bowler_choice"] is not None:
        await process_ccl_ball(context, match)

async def process_ccl_ball(context: ContextTypes.DEFAULT_TYPE, match):
    chat_id = match["group_chat_id"]
    batsman_choice = match["batsman_choice"]
    bowler_choice = match["bowler_choice"]
    match["balls"] += 1
    over_num = (match["balls"] - 1) // 6 + 1
    ball_num = (match["balls"] - 1) % 6 + 1
    bowler_number = {"rs": 0, "bouncer": 1, "yorker": 2, "short": 3, "slower": 4, "knuckle": 6}[bowler_choice]
    is_out = (batsman_choice == bowler_number)
    if not is_out:
        match["score"] += batsman_choice
    else:
        match["wickets"] = match.get("wickets", 0) + 1

    # 1. Over and ball
    await context.bot.send_message(chat_id=chat_id, text=f"**Over : {over_num}.{ball_num}**", parse_mode="Markdown")
    await asyncio.sleep(3)
    # 2. Bowling variation
    bowler_name = USERS[match["bowling_user"]]["name"]
    await context.bot.send_message(chat_id=chat_id, text=f"**{bowler_name} bowls a {bowler_choice.capitalize()}**", parse_mode="Markdown")
    await asyncio.sleep(4)

    # 3. Commentary and GIF
    text_lines = []
    gif_url = None
    if is_out:
        text_lines.append(f"**{random.choice(CCL_COMMENTARY['wicket'])}**")
        gif_url = random_gif(CCL_GIFS.get("wicket", []))
    else:
        run_str = str(batsman_choice)
        text_lines.append(f"**{random.choice(CCL_COMMENTARY[run_str])}**")
        if run_str in CCL_GIFS:
            gif_url = random_gif(CCL_GIFS[run_str])
        # Milestones
        if not match.get("milestone_50") and match["score"] >= 50:
            gif_url = random_gif(CCL_GIFS["50"])
            match["milestone_50"] = True
        if not match.get("milestone_100") and match["score"] >= 100:
            gif_url = random_gif(CCL_GIFS["100"])
            match["milestone_100"] = True

    if gif_url:
        await context.bot.send_animation(chat_id=chat_id, animation=gif_url)
    # 4. Current score and reveal
    batter = USERS[match["batting_user"]]["name"]
    bowler = USERS[match["bowling_user"]]["name"]
    text_lines.append("")
    text_lines.append(f"**{batter}! Bat {batsman_choice}**")
    text_lines.append(f"**{bowler}! Bowl {bowler_number}**\n")
    text_lines.append("**Total Score :**")
    text_lines.append(f"**{batter}! scored total of {match['score']} runs**")
    text_lines.append(f"**Current Score: {match['score']}/{match.get('wickets', 0)}**")
    await context.bot.send_message(chat_id=chat_id, text="\n".join(text_lines), parse_mode="Markdown")

    # 5. Innings and result logic
    if match["innings"] == 1:
        if is_out:
            match["target"] = match["score"] + 1
            match["score_first"] = match["score"]
            match["batting_user"], match["bowling_user"] = match["bowling_user"], match["batting_user"]
            match["score"] = 0
            match["balls"] = 0
            match["wickets"] = 0
            match["innings"] = 2
            match["batsman_choice"] = None
            match["bowler_choice"] = None
            await context.bot.send_message(chat_id=chat_id, text=f"**Innings over! Target for second innings: {match['target']}**", parse_mode="Markdown")
            await send_ccl_dm_prompts(context, match)
            return
    else:
        innings_ended = is_out or match["score"] >= match["target"]
        if innings_ended:
            match["score_second"] = match["score"]
            first = match["score_first"]
            second = match["score_second"]
            p1 = USERS[match["initiator"]]["name"]
            p2 = USERS[match["opponent"]]["name"]
            if second > first:
                winner = p2
                loser = p1
                win_by = second - first
                result_text = (
                    f"Results of the match between {p2} and {p1}\n\n"
                    f"Score :\n\n"
                    f"{p2} : {second} Runs\n"
                    f"{p1} : {first} Runs\n\n"
                    f"{p2} won by {win_by} Runs"
                )
                USERS[match["opponent"]]["wins"] += 1
                USERS[match["initiator"]]["losses"] += 1
            elif second < first:
                winner = p1
                loser = p2
                win_by = first - second
                result_text = (
                    f"Results of the match between {p1} and {p2}\n\n"
                    f"Score :\n\n"
                    f"{p1} : {first} Runs\n"
                    f"{p2} : {second} Runs\n\n"
                    f"{p1} won by {win_by} Runs"
                )
                USERS[match["initiator"]]["wins"] += 1
                USERS[match["opponent"]]["losses"] += 1
            else:
                result_text = (
                    f"Results of the match between {p1} and {p2}\n\n"
                    f"Score :\n\n"
                    f"{p1} : {first} Runs\n"
                    f"{p2} : {second} Runs\n\n"
                    f"{random.choice(CCL_COMMENTARY['tie'])}"
                )
                USERS[match["initiator"]]["ties"] = USERS[match["initiator"]].get("ties", 0) + 1
                USERS[match["opponent"]]["ties"] = USERS[match["opponent"]].get("ties", 0) + 1
            # Bet payout
            bet = match.get("bet", 0)
            if bet > 0 and second != first:
                winner_id = match["opponent"] if second > first else match["initiator"]
                loser_id = match["initiator"] if second > first else match["opponent"]
                USERS[winner_id]["coins"] += bet * 2
                USERS[loser_id]["coins"] = max(0, USERS[loser_id]["coins"] - bet)
            await context.bot.send_message(chat_id=chat_id, text=result_text)
            del CCL_MATCHES[match["match_id"]]
            USER_CCL_MATCH[match["batting_user"]] = None
            USER_CCL_MATCH[match["bowling_user"]] = None
            GROUP_CCL_MATCH[match["group_chat_id"]] = None
            return
    match["batsman_choice"] = None
    match["bowler_choice"] = None
    await send_ccl_dm_prompts(context, match)
# --- Handler Registration ---

def register_handlers(application):
    # General commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("register", register))
    application.add_handler(CommandHandler("profile", profile))
    application.add_handler(CommandHandler("daily", daily))
    application.add_handler(CommandHandler("leaderboard", leaderboard))
    application.add_handler(CallbackQueryHandler(leaderboard_callback, pattern="^leaderboard_"))
    application.add_handler(CommandHandler("send", send_command))
    application.add_handler(CommandHandler("add", add_command))
    application.add_handler(CommandHandler("endmatch", endmatch_command))
    application.add_handler(CommandHandler("help", help_command))

    # PM mode handlers
    application.add_handler(CommandHandler("pm", pm_command))
    application.add_handler(CallbackQueryHandler(pm_join_callback, pattern="^pm_join_"))
    application.add_handler(CallbackQueryHandler(pm_cancel_callback, pattern="^pm_cancel_"))
    application.add_handler(CallbackQueryHandler(pm_toss_choice_callback, pattern="^pm_toss_"))
    application.add_handler(CallbackQueryHandler(pm_bat_bowl_choice_callback, pattern="^pm_(bat|bowl)_"))
    application.add_handler(CallbackQueryHandler(pm_batnum_choice_callback, pattern="^pm_batnum_"))
    application.add_handler(CallbackQueryHandler(pm_bowlnum_choice_callback, pattern="^pm_bowlnum_"))

    # CCL mode handlers
    application.add_handler(CommandHandler("ccl", ccl_command))
    application.add_handler(CallbackQueryHandler(ccl_join_callback, pattern="^ccl_join_"))
    application.add_handler(CallbackQueryHandler(ccl_cancel_callback, pattern="^ccl_cancel_"))
    application.add_handler(CallbackQueryHandler(ccl_toss_choice_callback, pattern="^ccl_toss_"))
    application.add_handler(CallbackQueryHandler(ccl_bat_bowl_choice_callback, pattern="^ccl_(bat|bowl)_"))
    # CCL DM handler (for batsman/bowler input)
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, ccl_dm_handler))

# --- Startup and Main ---

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
    import nest_asyncio
    import asyncio
    nest_asyncio.apply()
    asyncio.get_event_loop().run_until_complete(main())
    
