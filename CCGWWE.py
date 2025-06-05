import logging
import random
import uuid
import asyncio
from datetime import datetime, timedelta

import nest_asyncio
nest_asyncio.apply()

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

# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Configuration ---
TOKEN = "8133604799:AAF2dE86UjRxfAdUcqyoz3O9RgaCeTwaoHM"  # Replace with your bot token
ADMIN_IDS = {123456789}  # Replace with your Telegram user ID(s) for admin commands

MONGO_URL = "mongodb://mongo:GhpHMiZizYnvJfKIQKxoDbRyzBCpqEyC@mainline.proxy.rlwy.net:54853"  # Replace with your MongoDB connection string
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client.handcricket
users_collection = db.users

# --- Emojis ---
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

# --- Bowling variations mapping ---
BOWLING_TYPES = {
    "rs": 0,
    "bouncer": 1,
    "yorker": 2,
    "short": 3,
    "slower": 4,
    "knuckle": 6,
}

# --- GIF URLs ---
RUN_GIFS = {
    "0": "https://media0.giphy.com/media/QtipHdYxYopX3W6vMs/giphy.gif",
    "4": "https://media0.giphy.com/media/3o7btXfjIjTcU64YdG/giphy.gif",
    "6": "https://media4.giphy.com/media/pbhDFQQfXRX8CTmZ4O/giphy.gif",
    "out": "https://media3.giphy.com/media/Wq3WRGe9N5HkSqjITT/giphy.gif",
    "halfcentury": "https://media.giphy.com/media/3oEjI6SIIHBdRxXI40/giphy.gif",
    "century": "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif"
}

# --- Commentary ---
RUN_COMMENTARY_CCL = {
    0: ["Dot Ball!", "No run.", "Well bowled, no run."],
    1: ["Quick single.", "One run taken.", "They sneak a single."],
    2: ["Two runs!", "Good running between the wickets.", "They pick up a couple."],
    3: ["Three runs!", "Great running, three!", "Three runs taken."],
    4: ["He smashed a Four!", "Beautiful boundary!", "Cracking shot for four!"],
    6: ["He Smoked It For A Six!", "Maximum!", "What a massive six!"],
    "out": ["It's Out!", "Bowled him!", "What a wicket!", "Caught behind!"],
}

RUN_COMMENTARY_PM = {
    1: ["Quick single.", "One run taken.", "They sneak a single."],
    2: ["Two runs!", "Good running between the wickets.", "They pick up a couple."],
    3: ["Three runs!", "Great running, three!", "Three runs taken."],
    4: ["He smashed a Four!", "Beautiful boundary!", "Cracking shot for four!"],
    5: ["Five runs! (Rare!)"],
    6: ["He Smoked It For A Six!", "Maximum!", "What a massive six!"],
    "0": ["Dot Ball!", "No run.", "Well bowled, no run."],
    "out": ["It's Out!", "Bowled him!", "What a wicket!", "Caught behind!"],
}

# --- Global Data ---

USERS = {}  # user_id -> user dict

# PM mode matches: match_id -> match dict
PM_MATCHES = {}
USER_PM_MATCHES = {}  # user_id -> set of match_ids
GROUP_PM_MATCHES = {}  # group_chat_id -> set of match_ids

# CCL mode matches: match_id -> match dict
CCL_MATCHES = {}
USER_CCL_MATCH = {}  # user_id -> match_id
GROUP_CCL_MATCH = {}  # group_chat_id -> match_id

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
            USERS[user_id] = user
            USER_PM_MATCHES[user_id] = set()
            USER_CCL_MATCH[user_id] = None
        logger.info("Users loaded successfully.")
    except Exception as e:
        logger.error(f"Error loading users: {e}", exc_info=True)

def mention_player(player):
    return f"[{player['name']}](tg://user?id={player['user_id']})"

# --- Basic Commands ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)
    await save_user(user.id)
    await update.message.reply_text(
        f"Welcome to CCL HandCricket, {USERS[user.id]['name']}! Use /register to get 4000 {COINS_EMOJI}.",
        parse_mode="Markdown"
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
        f"Wins: {u['wins']}\n"
        f"Losses: {u['losses']}\n"
        f"Ties: {u['ties']}\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)
    now = datetime.utcnow()
    last = USERS[user.id].get("last_daily")
    if last and (now - last) < timedelta(hours=24):
        rem = timedelta(hours=24) - (now - last)
        h, m = divmod(rem.seconds // 60, 60)
        await update.message.reply_text(f"Daily already claimed. Try again in {h}h {m}m.", parse_mode="Markdown")
        return
    USERS[user.id]["coins"] += 2000
    USERS[user.id]["last_daily"] = now
    await save_user(user.id)
    await update.message.reply_text(f"You received 2000 {COINS_EMOJI} as daily reward!", parse_mode="Markdown")

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)
    sorted_users = sorted(USERS.values(), key=lambda u: u.get("coins", 0), reverse=True)
    page = 1
    if context.args and context.args[0].isdigit():
        page = int(context.args[0])
    text = ""
    if page == 1:
        text = "🏆 **Top 10 Richest Players by Coins:**\n\n"
        for i, u in enumerate(sorted_users[:10], 1):
            text += f"{i}. {u.get('name', 'Unknown')} - {u.get('coins', 0)} {COINS_EMOJI}\n"
    else:
        sorted_wins = sorted(USERS.values(), key=lambda u: u.get("wins", 0), reverse=True)
        text = "🏆 **Top 10 Players by Wins:**\n\n"
        for i, u in enumerate(sorted_wins[:10], 1):
            text += f"{i}. {u.get('name', 'Unknown')} - {u.get('wins', 0)} Wins\n"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬅️ Coins", callback_data=f"leaderboard_1"),
            InlineKeyboardButton("Wins ➡️", callback_data=f"leaderboard_2"),
        ]
    ])
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

async def leaderboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, page = query.data.split("_")
    page = int(page)
    sorted_users = sorted(USERS.values(), key=lambda u: u.get("coins", 0), reverse=True)
    text = ""
    if page == 1:
        text = "🏆 **Top 10 Richest Players by Coins:**\n\n"
        for i, u in enumerate(sorted_users[:10], 1):
            text += f"{i}. {u.get('name', 'Unknown')} - {u.get('coins', 0)} {COINS_EMOJI}\n"
    else:
        sorted_wins = sorted(USERS.values(), key=lambda u: u.get("wins", 0), reverse=True)
        text = "🏆 **Top 10 Players by Wins:**\n\n"
        for i, u in enumerate(sorted_wins[:10], 1):
            text += f"{i}. {u.get('name', 'Unknown')} - {u.get('wins', 0)} Wins\n"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬅️ Coins", callback_data=f"leaderboard_1"),
            InlineKeyboardButton("Wins ➡️", callback_data=f"leaderboard_2"),
        ]
    ])
    await query.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    await query.answer()
from telegram import InlineKeyboardMarkup, InlineKeyboardButton

# --- PM Mode Keyboards ---

def pm_join_cancel_keyboard(match_id):
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("Join ✅", callback_data=f"pm_join_{match_id}"),
            InlineKeyboardButton("Cancel ❌", callback_data=f"pm_cancel_{match_id}")
        ]]
    )

def pm_toss_keyboard(match_id):
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("Heads", callback_data=f"pm_toss_heads_{match_id}"),
            InlineKeyboardButton("Tails", callback_data=f"pm_toss_tails_{match_id}")
        ]]
    )

def pm_bat_bowl_keyboard(match_id):
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("Bat 🏏", callback_data=f"pm_bat_{match_id}"),
            InlineKeyboardButton("Bowl ⚾", callback_data=f"pm_bowl_{match_id}")
        ]]
    )

def pm_number_keyboard(prefix):
    buttons = [
        [InlineKeyboardButton(str(n), callback_data=f"{prefix}_{n}") for n in range(1, 4)],
        [InlineKeyboardButton(str(n), callback_data=f"{prefix}_{n}") for n in range(4, 7)],
    ]
    return InlineKeyboardMarkup(buttons)

# --- /pm Command Handler ---

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
        "toss_choice": None,
        "toss_winner": None,
        "bat_bowl_choice": None,
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
    }
    USER_PM_MATCHES.setdefault(user.id, set()).add(match_id)
    GROUP_PM_MATCHES.setdefault(chat.id, set()).add(match_id)

    await update.message.reply_text(
        f"🏏 PM Cricket game started by {USERS[user.id]['name']}! Bet: {bet}{COINS_EMOJI}\nPress Join below to play.",
        reply_markup=pm_join_cancel_keyboard(match_id),
    )

# --- PM Join Callback ---

async def pm_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    _, _, match_id = query.data.split("_", 2)

    current_match = PM_MATCHES.get(match_id)
    if not current_match or current_match["state"] != "waiting_join":
        await query.answer("Match not available to join.", show_alert=True)
        return

    if user.id == current_match["initiator"]:
        await query.answer("You cannot join your own match.", show_alert=True)
        return

    if current_match["opponent"]:
        await query.answer("Match already has an opponent.", show_alert=True)
        return

    ensure_user(user)

    if current_match["bet"] > 0 and USERS[user.id]["coins"] < current_match["bet"]:
        await query.answer("You don't have enough coins to join this bet match.", show_alert=True)
        return

    current_match["opponent"] = user.id
    current_match["state"] = "toss"

    USER_PM_MATCHES.setdefault(user.id, set()).add(match_id)

    await query.message.edit_text(
        f"Match started between {USERS[current_match['initiator']]['name']} and {USERS[user.id]['name']}!\n"
        f"{USERS[current_match['initiator']]['name']}, choose Heads or Tails for the toss.",
        reply_markup=pm_toss_keyboard(match_id),
    )
    await query.answer()

# --- PM Cancel Callback ---

async def pm_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    _, _, match_id = query.data.split("_", 2)

    current_match = PM_MATCHES.get(match_id)
    if not current_match:
        await query.answer("Match not found or already ended.", show_alert=True)
        return

    if user.id != current_match["initiator"]:
        await query.answer("Only the match initiator can cancel.", show_alert=True)
        return

    chat_id = current_match["group_chat_id"]

    # Refund bets if any
    if current_match["bet"] > 0:
        USERS[current_match["initiator"]]["coins"] += current_match["bet"]
        if current_match["opponent"]:
            USERS[current_match["opponent"]]["coins"] += current_match["bet"]

    del PM_MATCHES[match_id]
    USER_PM_MATCHES[current_match["initiator"]].discard(match_id)
    if current_match.get("opponent"):
        USER_PM_MATCHES[current_match["opponent"]].discard(match_id)
    GROUP_PM_MATCHES[chat_id].discard(match_id)

    await query.message.edit_text("The PM match has been cancelled by the initiator.")
    await query.answer()

# --- PM Toss Choice Callback ---

async def pm_toss_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    _, _, toss_choice, match_id = query.data.split("_", 3)

    current_match = PM_MATCHES.get(match_id)
    if not current_match or current_match["state"] != "toss":
        await query.answer("Invalid toss state.", show_alert=True)
        return

    if user.id != current_match["initiator"]:
        await query.answer("Only the initiator chooses toss.", show_alert=True)
        return

    coin_result = random.choice(["heads", "tails"])
    current_match["toss_choice"] = toss_choice
    toss_winner = current_match["initiator"] if toss_choice == coin_result else current_match["opponent"]
    toss_loser = current_match["opponent"] if toss_winner == current_match["initiator"] else current_match["initiator"]

    current_match["toss_winner"] = toss_winner
    current_match["toss_loser"] = toss_loser
    current_match["state"] = "bat_bowl_choice"

    await query.message.edit_text(
        f"The coin landed on {coin_result.capitalize()}!\n"
        f"{USERS[toss_winner]['name']} won the toss! Choose to Bat or Bowl first.",
        reply_markup=pm_bat_bowl_keyboard(match_id),
    )
    await query.answer()

# --- PM Bat/Bowl Choice Callback ---

async def pm_bat_bowl_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    _, choice, match_id = query.data.split("_", 2)

    current_match = PM_MATCHES.get(match_id)
    if not current_match or current_match["state"] != "bat_bowl_choice":
        await query.answer("Invalid state for Bat/Bowl choice.", show_alert=True)
        return

    if user.id != current_match["toss_winner"]:
        await query.answer("Only toss winner can choose.", show_alert=True)
        return

    current_match["bat_bowl_choice"] = choice
    if choice == "bat":
        current_match["batting_user"] = current_match["toss_winner"]
        current_match["bowling_user"] = current_match["toss_loser"]
    else:
        current_match["batting_user"] = current_match["toss_loser"]
        current_match["bowling_user"] = current_match["toss_winner"]

    current_match.update({
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

    await query.message.edit_text(
        f"Match started!\n\n"
        f"🏏 Batter: {USERS[current_match['batting_user']]['name']}\n"
        f"⚾ Bowler: {USERS[current_match['bowling_user']]['name']}\n\n"
        f"{USERS[current_match['batting_user']]['name']}, choose your batting number:",
        reply_markup=pm_number_keyboard("pm_batnum"),
    )
    await query.answer()

# --- PM Batting Number Callback ---

async def pm_batnum_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    _, num_str = query.data.split("_", 2)
    num = int(num_str)

    current_match = None
    for m in PM_MATCHES.values():
        if m["state"] == "batting" and m["batting_user"] == user.id and m["batsman_choice"] is None:
            current_match = m
            break

    if not current_match:
        await query.answer("No active batting turn found or already chosen.", show_alert=True)
        return

    current_match["batsman_choice"] = num
    await query.answer(f"You chose {num} for batting.")

    await context.bot.send_message(
        chat_id=current_match["group_chat_id"],
        text=f"{USERS[current_match['bowling_user']]['name']}, choose your bowling number:",
        reply_markup=pm_number_keyboard("pm_bowlnum"),
    )

# --- PM Bowling Number Callback ---

async def pm_bowlnum_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    _, num_str = query.data.split("_", 2)
    num = int(num_str)

    current_match = None
    for m in PM_MATCHES.values():
        if m["state"] == "batting" and m["bowling_user"] == user.id and m["bowler_choice"] is None:
            current_match = m
            break

    if not current_match:
        await query.answer("No active bowling turn found or already chosen.", show_alert=True)
        return

    current_match["bowler_choice"] = num
    await query.answer(f"You chose {num} for bowling.")

    # Process the ball result
    await process_pm_ball(context, current_match)

# --- Process Ball Result in PM Mode ---

async def process_pm_ball(context: ContextTypes.DEFAULT_TYPE, current_match):
    chat_id = current_match["group_chat_id"]

    batsman_choice = current_match["batsman_choice"]
    bowler_choice = current_match["bowler_choice"]

    current_match["balls"] += 1
    over_num = (current_match["balls"] - 1) // 6
    ball_num = (current_match["balls"] - 1) % 6 + 1

    is_out = batsman_choice == bowler_choice

    text_lines = [
        f"🏏 Over: {over_num}.{ball_num}",
        f"🏃 Batsman chose: {batsman_choice}",
        f"⚾ Bowler chose: {bowler_choice}",
    ]

    milestone_gif = None
    milestone_text = None

    if is_out:
        current_match["wickets"] += 1
        text_lines.append("\n" + random.choice(RUN_COMMENTARY_PM["out"]))
        gif_url = RUN_GIFS["out"]
    else:
        current_match["score"] += batsman_choice
        run_comment_list = RUN_COMMENTARY_PM.get(batsman_choice, ["Runs scored!"])
        text_lines.append(f"\nTotal Score : {current_match['score']} Runs")
        text_lines.append(random.choice(run_comment_list))
        gif_url = RUN_GIFS.get(str(batsman_choice), None)

        if not current_match.get("milestone_50") and current_match["score"] >= 50:
            milestone_gif = RUN_GIFS["halfcentury"]
            milestone_text = "🏏 Half-century! 50 runs!"
            current_match["milestone_50"] = True
        if not current_match.get("milestone_100") and current_match["score"] >= 100:
            milestone_gif = RUN_GIFS["century"]
            milestone_text = "💯 Century! 100 runs!"
            current_match["milestone_100"] = True

    # First Innings: ends on wicket
    if current_match["innings"] == 1:
        if current_match["wickets"] >= 1:
            current_match["target"] = current_match["score"]
            current_match["innings"] = 2
            current_match["score"] = 0
            current_match["balls"] = 0
            current_match["wickets"] = 0
            current_match["batsman_choice"] = None
            current_match["bowler_choice"] = None
            current_match["milestone_50"] = False
            current_match["milestone_100"] = False
            text_lines.append(f"\nInnings over! Target for second innings: {current_match['target'] + 1}")
            await context.bot.send_message(chat_id=chat_id, text="\n".join(text_lines))
            if milestone_gif:
                await context.bot.send_animation(chat_id=chat_id, animation=milestone_gif, caption=milestone_text)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"{USERS[current_match['opponent']]['name']}, choose your batting number:",
                reply_markup=pm_number_keyboard("pm_batnum"),
            )
            return
    else:
        # Second innings: check for win or tie
        target = current_match["target"]
        innings_ended = current_match["wickets"] >= 1 or current_match["score"] >= target

        if innings_ended:
            if current_match["score"] > target:
                winner_id = current_match["opponent"]
                loser_id = current_match["initiator"]
                result_text = f"🏆 {USERS[winner_id]['name']} won the match by chasing the target!"
            elif current_match["score"] == target and current_match["wickets"] >= 1:
                winner_id = None
                loser_id = None
                result_text = "🤝 The match is a tie!"
            else:
                winner_id = current_match["initiator"]
                loser_id = current_match["opponent"]
                result_text = f"🏆 {USERS[winner_id]['name']} won the match!"

            text_lines.append(f"\n{result_text}")
            await context.bot.send_message(chat_id=chat_id, text="\n".join(text_lines))
            if milestone_gif:
                await context.bot.send_animation(chat_id=chat_id, animation=milestone_gif, caption=milestone_text)

            bet = current_match.get("bet", 0)
            if bet > 0 and winner_id:
                USERS[winner_id]["coins"] += bet * 2
                USERS[loser_id]["coins"] = max(0, USERS[loser_id]["coins"] - bet)

            if winner_id:
                USERS[winner_id]["wins"] += 1
                USERS[loser_id]["losses"] += 1
            else:
                USERS[current_match["initiator"]]["ties"] += 1
                USERS[current_match["opponent"]]["ties"] += 1

            if winner_id:
                await save_user(winner_id)
                await save_user(loser_id)
            else:
                await save_user(current_match["initiator"])
                await save_user(current_match["opponent"])

            del PM_MATCHES[current_match["match_id"]]
            USER_PM_MATCHES[current_match["initiator"]].discard(current_match["match_id"])
            USER_PM_MATCHES[current_match["opponent"]].discard(current_match["match_id"])
            GROUP_PM_MATCHES[chat_id].discard(current_match["match_id"])
            return

    # Reset choices for next ball
    current_match["batsman_choice"] = None
    current_match["bowler_choice"] = None

    await context.bot.send_message(chat_id=chat_id, text="\n".join(text_lines))
    if gif_url:
        await context.bot.send_animation(chat_id=chat_id, animation=gif_url)
    if milestone_gif:
        await context.bot.send_animation(chat_id=chat_id, animation=milestone_gif, caption=milestone_text)

    # Prompt next batsman choice
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"{USERS[current_match['batting_user']]['name']}, choose your batting number:",
        reply_markup=pm_number_keyboard("pm_batnum"),
        )
import asyncio

# --- CCL Mode Inline Keyboards ---

def ccl_join_cancel_keyboard(match_id):
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("Join ✅", callback_data=f"ccl_join_{match_id}"),
            InlineKeyboardButton("Cancel ❌", callback_data=f"ccl_cancel_{match_id}")
        ]]
    )

def ccl_toss_keyboard(match_id):
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("Heads", callback_data=f"ccl_toss_heads_{match_id}"),
            InlineKeyboardButton("Tails", callback_data=f"ccl_toss_tails_{match_id}")
        ]]
    )

def ccl_bat_bowl_keyboard(match_id):
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("Bat 🏏", callback_data=f"ccl_bat_{match_id}"),
            InlineKeyboardButton("Bowl ⚾", callback_data=f"ccl_bowl_{match_id}")
        ]]
    )

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
    }
    USER_CCL_MATCH[user.id] = match_id
    GROUP_CCL_MATCH[chat.id] = match_id

    await update.message.reply_text(
        f"🏏 CCL Cricket game started by {USERS[user.id]['name']}! Bet: {bet}{COINS_EMOJI}\nPress Join below to play.",
        reply_markup=ccl_join_cancel_keyboard(match_id),
    )

# --- CCL Join Callback ---

async def ccl_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    _, _, match_id = query.data.split("_", 2)

    current_match = CCL_MATCHES.get(match_id)
    if not current_match or current_match["state"] != "waiting_join":
        await query.answer("Match not available to join.", show_alert=True)
        return

    if user.id == current_match["initiator"]:
        await query.answer("You cannot join your own match.", show_alert=True)
        return

    if current_match["opponent"]:
        await query.answer("Match already has an opponent.", show_alert=True)
        return

    ensure_user(user)

    bet = current_match.get("bet", 0)
    if bet > 0 and USERS[user.id]["coins"] < bet:
        await query.answer("You don't have enough coins to join this bet match.", show_alert=True)
        return

    current_match["opponent"] = user.id
    current_match["state"] = "toss"

    USER_CCL_MATCH[user.id] = match_id

    await query.message.edit_text(
        f"Match started between {USERS[current_match['initiator']]['name']} and {USERS[user.id]['name']}!\n"
        f"{USERS[current_match['initiator']]['name']}, choose Heads or Tails for the toss.",
        reply_markup=ccl_toss_keyboard(match_id),
    )
    await query.answer()

# --- CCL Cancel Callback ---

async def ccl_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    _, _, match_id = query.data.split("_", 2)

    current_match = CCL_MATCHES.get(match_id)
    if not current_match:
        await query.answer("Match not found or already ended.", show_alert=True)
        return

    if user.id != current_match["initiator"]:
        await query.answer("Only the initiator can cancel.", show_alert=True)
        return

    chat_id = current_match["group_chat_id"]

    del CCL_MATCHES[match_id]
    USER_CCL_MATCH[current_match["initiator"]] = None
    if current_match.get("opponent"):
        USER_CCL_MATCH[current_match["opponent"]] = None
    GROUP_CCL_MATCH.pop(chat_id, None)

    await query.message.edit_text("The CCL match has been cancelled by the initiator.")
    await query.answer()

# --- CCL Toss Choice Callback ---

async def ccl_toss_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    _, _, choice, match_id = query.data.split("_", 3)

    current_match = CCL_MATCHES.get(match_id)
    if not current_match or current_match["state"] != "toss":
        await query.answer("Invalid toss state.", show_alert=True)
        return

    if user.id != current_match["initiator"]:
        await query.answer("Only the initiator chooses toss.", show_alert=True)
        return

    coin_result = random.choice(["heads", "tails"])
    toss_winner = current_match["initiator"] if choice == coin_result else current_match["opponent"]
    toss_loser = current_match["opponent"] if toss_winner == current_match["initiator"] else current_match["initiator"]

    current_match["toss_winner"] = toss_winner
    current_match["toss_loser"] = toss_loser
    current_match["state"] = "bat_bowl_choice"

    await query.message.edit_text(
        f"The coin landed on {coin_result.capitalize()}!\n"
        f"{USERS[toss_winner]['name']} won the toss! Choose to Bat or Bowl first.",
        reply_markup=ccl_bat_bowl_keyboard(match_id),
    )
    await query.answer()

# --- CCL Bat/Bowl Choice Callback ---

async def ccl_bat_bowl_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    _, choice, match_id = query.data.split("_", 2)

    current_match = CCL_MATCHES.get(match_id)
    if not current_match or current_match["state"] != "bat_bowl_choice":
        await query.answer("Invalid state for Bat/Bowl choice.", show_alert=True)
        return

    if user.id != current_match["toss_winner"]:
        await query.answer("Only toss winner can choose.", show_alert=True)
        return

    if choice == "bat":
        current_match["batting_user"] = current_match["toss_winner"]
        current_match["bowling_user"] = current_match["toss_loser"]
    else:
        current_match["batting_user"] = current_match["toss_loser"]
        current_match["bowling_user"] = current_match["toss_winner"]

    current_match.update({
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

    batting_mention = mention_player(USERS[current_match['batting_user']])
    bowling_mention = mention_player(USERS[current_match['bowling_user']])

    await query.message.edit_text(
        f"Match started!\n\n"
        f"🏏 Batter: {batting_mention}\n"
        f"⚾ Bowler: {bowling_mention}\n\n"
        f"{batting_mention} and {bowling_mention}, please send your choices in DM to me.",
        parse_mode="Markdown",
    )

    try:
        await context.bot.send_message(
            chat_id=current_match["batting_user"],
            text="Please send your batting number (0,1,2,3,4,6):"
        )
    except:
        await query.message.reply_text(f"Cannot send DM to {batting_mention}. Please start a chat with me first.", parse_mode="Markdown")

    try:
        await context.bot.send_message(
            chat_id=current_match["bowling_user"],
            text="Please send your bowling type (rs, bouncer, yorker, short, slower, knuckle):"
        )
    except:
        await query.message.reply_text(f"Cannot send DM to {bowling_mention}. Please start a chat with me first.", parse_mode="Markdown")

    await query.answer()

# --- CCL DM Handler for Batting and Bowling Inputs ---

async def ccl_dm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip().lower()

    match_id = USER_CCL_MATCH.get(user.id)
    if not match_id:
        await update.message.reply_text("You are not currently in a CCL match.")
        return

    current_match = CCL_MATCHES.get(match_id)
    if not current_match or current_match["state"] != "batting":
        await update.message.reply_text("Match is not in batting state.")
        return

    if user.id == current_match["batting_user"]:
        if text not in {"0", "1", "2", "3", "4", "6"}:
            await update.message.reply_text("Invalid batting number. Please send one of 0,1,2,3,4,6.")
            return
        if current_match["batsman_choice"] is not None:
            await update.message.reply_text("You have already sent your batting number for this ball.")
            return
        current_match["batsman_choice"] = int(text)
        await update.message.reply_text(f"Batting number {text} received.")
    elif user.id == current_match["bowling_user"]:
        if text not in BOWLING_TYPES:
            await update.message.reply_text(f"Invalid bowling type. Please send one of {', '.join(BOWLING_TYPES.keys())}.")
            return
        if current_match["bowler_choice"] is not None:
            await update.message.reply_text("You have already sent your bowling type for this ball.")
            return
        current_match["bowler_choice"] = text
        await update.message.reply_text(f"Bowling type '{text}' received.")
    else:
        await update.message.reply_text("You are not a player in this match.")
        return

    if current_match["batsman_choice"] is not None and current_match["bowler_choice"] is not None:
        await process_ccl_ball(context, current_match)

# --- Process Ball Result in CCL Mode with Commentary and GIFs ---

async def process_ccl_ball(context: ContextTypes.DEFAULT_TYPE, current_match):
    chat_id = current_match["group_chat_id"]
    batsman_choice = current_match["batsman_choice"]
    bowler_choice = current_match["bowler_choice"]

    current_match["balls"] += 1
    over_num = (current_match["balls"] - 1) // 6 + 1
    ball_num = (current_match["balls"] - 1) % 6 + 1

    bowler_number = BOWLING_TYPES.get(bowler_choice, -1)
    is_out = (batsman_choice == bowler_number)

    await context.bot.send_message(chat_id=chat_id, text=f"🏏 Over {over_num} Ball {ball_num}")
    await asyncio.sleep(3)

    bowler_name = USERS[current_match["bowling_user"]]["name"]
    bowling_comment = f"{bowler_name} bowls a {bowler_choice.capitalize()} ball!"
    await context.bot.send_message(chat_id=chat_id, text=bowling_comment)
    await asyncio.sleep(4)

    text_lines = []
    milestone_gif = None
    milestone_text = None

    if is_out:
        current_match["wickets"] += 1
        text_lines.append(random.choice(RUN_COMMENTARY_CCL["out"]))
        gif_url = RUN_GIFS["out"]
    else:
        current_match["score"] += batsman_choice
        run_comment_list = RUN_COMMENTARY_CCL.get(batsman_choice, ["Runs scored!"])
        text_lines.append(random.choice(run_comment_list))
        gif_url = RUN_GIFS.get(str(batsman_choice), None)

        text_lines.append(f"Total Score: {current_match['score']} Runs")

        if not current_match.get("milestone_50") and current_match["score"] >= 50:
            milestone_gif = RUN_GIFS["halfcentury"]
            milestone_text = "🏏 Half-century! 50 runs!"
            current_match["milestone_50"] = True
        if not current_match.get("milestone_100") and current_match["score"] >= 100:
            milestone_gif = RUN_GIFS["century"]
            milestone_text = "💯 Century! 100 runs!"
            current_match["milestone_100"] = True

    await context.bot.send_message(chat_id=chat_id, text="\n".join(text_lines))
    if gif_url:
        await context.bot.send_animation(chat_id=chat_id, animation=gif_url)
    if milestone_gif:
        await context.bot.send_animation(chat_id=chat_id, animation=milestone_gif, caption=milestone_text)

    # Innings and result logic
    if current_match["innings"] == 1:
        if current_match["wickets"] >= 1:
            current_match["target"] = current_match["score"]
            current_match["batting_user"], current_match["bowling_user"] = current_match["bowling_user"], current_match["batting_user"]
            current_match["score"] = 0
            current_match["balls"] = 0
            current_match["wickets"] = 0
            current_match["innings"] = 2
            current_match["batsman_choice"] = None
            current_match["bowler_choice"] = None
            current_match["milestone_50"] = False
            current_match["milestone_100"] = False
            await context.bot.send_message(chat_id=chat_id, text=f"Innings over! Target for second innings: {current_match['target'] + 1}")
            await context.bot.send_message(chat_id=chat_id, text=f"{mention_player(USERS[current_match['batting_user']])}, please send your batting number (0,1,2,3,4,6) in DM.")
            await context.bot.send_message(chat_id=chat_id, text=f"{mention_player(USERS[current_match['bowling_user']])}, please send your bowling type in DM.")
            return
    else:
        innings_ended = current_match["wickets"] >= 1 or current_match["score"] > current_match["target"]

        if innings_ended:
            if current_match["score"] > current_match["target"]:
                winner_id = current_match["batting_user"]
                loser_id = current_match["bowling_user"]
                result_text = f"🏆 {USERS[winner_id]['name']} won the match by chasing the target!"
            elif current_match["score"] == current_match["target"]:
                winner_id = None
                loser_id = None
                result_text = "🤝 The match is a tie!"
            else:
                winner_id = current_match["bowling_user"]
                loser_id = current_match["batting_user"]
                result_text = f"🏆 {USERS[winner_id]['name']} won the match!"

            await context.bot.send_message(chat_id=chat_id, text=result_text)

            bet = current_match.get("bet", 0)
            if bet > 0 and winner_id:
                USERS[winner_id]["coins"] += bet * 2
                USERS[loser_id]["coins"] = max(0, USERS[loser_id]["coins"] - bet)

            if winner_id:
                USERS[winner_id]["wins"] += 1
                USERS[loser_id]["losses"] += 1
            else:
                USERS[current_match["batting_user"]]["ties"] += 1
                USERS[current_match["bowling_user"]]["ties"] += 1

            if winner_id:
                await save_user(winner_id)
                await save_user(loser_id)
            else:
                await save_user(current_match["batting_user"])
                await save_user(current_match["bowling_user"])

            del CCL_MATCHES[current_match["match_id"]]
            USER_CCL_MATCH[current_match["batting_user"]] = None
            USER_CCL_MATCH[current_match["bowling_user"]] = None
            GROUP_CCL_MATCH[current_match["group_chat_id"]] = None
            return

    # Reset choices for next ball
    current_match["batsman_choice"] = None
    current_match["bowler_choice"] = None

# --- /send Command: Transfer Coins ---

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
        await update.message.reply_text(f"You don't have enough coins to send {amount}{COINS_EMOJI}.")
        return

    receiver_user = update.message.reply_to_message.from_user
    ensure_user(receiver_user)
    receiver = USERS[receiver_user.id]

    sender["coins"] -= amount
    receiver["coins"] += amount

    await save_user(user.id)
    await save_user(receiver_user.id)

    await update.message.reply_text(
        f"✅ {user.first_name} sent {amount}{COINS_EMOJI} to {receiver['name']}."
                                        )
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters

# --- Handler Registration ---

def register_handlers(application):
    # Basic commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("register", register))
    application.add_handler(CommandHandler("profile", profile))
    application.add_handler(CommandHandler("daily", daily))
    application.add_handler(CommandHandler("leaderboard", leaderboard))
    application.add_handler(CallbackQueryHandler(leaderboard_callback, pattern="^leaderboard_"))

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
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, ccl_dm_handler))

    # Send coins command
    application.add_handler(CommandHandler("send", send_command))

    # Help command
    application.add_handler(CommandHandler("help", help_command))

# --- Help Command ---

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "**CCL HandCricket Commands:**\n\n"
        "/start - Start the bot\n"
        "/register - Register and get 4000 🪙 coins\n"
        "/pm [bet] - Start a PM match optionally with bet\n"
        "/ccl [bet] - Start a CCL match optionally with bet\n"
        "/profile - Show your profile\n"
        "/daily - Claim daily 2000 🪙 coins\n"
        "/leaderboard - Show leaderboard with coins and wins\n"
        "/send - Send coins to another player (reply to their message and use /send <amount>)\n"
        "/help - Show this help message\n"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

# --- Startup Function ---

async def on_startup(application):
    await load_users()
    logger.info("Bot started and users loaded.")

# --- Main Function ---

async def main():
    application = ApplicationBuilder().token(TOKEN).build()
    register_handlers(application)
    application.post_init = on_startup
    logger.info("Starting bot...")
    await application.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
    
