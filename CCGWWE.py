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

GIFS = {
    0: "https://media.giphy.com/media/3o6Zt481isNVuQI1l6/giphy.gif",  # dot ball
    4: "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif",  # four runs
    6: "https://media.giphy.com/media/26ufdipQqU2lhNA4g/giphy.gif",  # six runs
    "half_century": "https://media.giphy.com/media/3o6Zt6ML6BklcajjsA/giphy.gif",
    "century": "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif",
}

def ensure_user(user):
    # Always update username on every command
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
        # Update username if changed or newly set
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
            # Always ensure username field exists
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
    """
    Find player by:
        - Telegram username (with or without @, case-insensitive)
        - Telegram user_id (as int or string)
    """
    identifier = identifier.strip()
    # Try by user_id
    try:
        identifier_num = int(identifier)
        for u in USERS.values():
            if int(u["user_id"]) == identifier_num:
                return u
    except Exception:
        pass
    # Try by username (case-insensitive, without @)
    username = identifier.lstrip("@").lower()
    for u in USERS.values():
        if u.get("username") and u["username"].lower() == username:
            return u
    return None

# --- Core Commands ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)
    await save_user(user.id)
    await update.message.reply_text(
        "🏏 *Welcome to CCL HandCricket Bot!*\n\n"
        "1️⃣ Use /register to get 4000 🪙 and start playing.\n\n"
        "2️⃣ Use /help for step-by-step instructions.",
        parse_mode="Markdown"
    )

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)
    u = USERS[user.id]
    # Always update username in DB and memory
    u["username"] = user.username
    if u["registered"]:
        await save_user(user.id)
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
        f"👤 *{u['name']}'s Profile*\n"
        f"ID: `{user.id}`\n"
        f"Username: @{u.get('username','')}\n"
        f"Purse: {u['coins']}{COINS_EMOJI}\n"
        f"Wins: {u['wins']}   Losses: {u['losses']}   Ties: {u['ties']}\n"
        f"Runs Scored: {u.get('runs_scored', 0)}   Balls Faced: {u.get('balls_faced', 0)}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏏 *How to Play CCL HandCricket*\n\n"
        "1️⃣ /register\n"
        "    Register and get your starting coins.\n\n"
        "2️⃣ /profile\n"
        "    See your stats and coin balance.\n\n"
        "3️⃣ /cclgroup\n"
        "    Host: Start a new match in the group.\n\n"
        "4️⃣ /add_A <username|user_id>\n"
        "    Add a player to Team A. Example: /add_A @john or /add_A 123456789\n\n"
        "5️⃣ /add_B <username|user_id>\n"
        "    Add a player to Team B. Example: /add_B @jane or /add_B 987654321\n\n"
        "6️⃣ /teams\n"
        "    Show both teams and player numbers.\n\n"
        "7️⃣ /cap_A <number>\n"
        "    Assign Team A captain by player number.\n\n"
        "8️⃣ /cap_B <number>\n"
        "    Assign Team B captain by player number.\n\n"
        "9️⃣ /setovers <number>\n"
        "    Set the number of overs (1-20).\n\n"
        "🔟 /startmatch\n"
        "    Start the match after setup.\n\n"
        "1️⃣1️⃣ /toss\n"
        "    Host: Start the toss. Team A captain picks heads/tails. Winner picks bat/bowl.\n\n"
        "1️⃣2️⃣ /bat <striker_num> <non_striker_num>\n"
        "    Assign striker and non-striker by player number.\n\n"
        "1️⃣3️⃣ /bowl <bowler_num>\n"
        "    Assign bowler by player number (no consecutive overs by same bowler).\n\n"
        "1️⃣4️⃣ Batsman: Send 0,1,2,3,4,6 as a message.\n"
        "1️⃣5️⃣ Bowler: Send rs, bouncer, yorker, short, slower, or knuckle as a message.\n\n"
        "1️⃣6️⃣ /score\n"
        "    Show current score.\n\n"
        "1️⃣7️⃣ /bonus <A|B> <runs>\n"
        "    Host: Add bonus runs to a team.\n\n"
        "1️⃣8️⃣ /penalty <A|B> <runs>\n"
        "    Host: Deduct runs from a team.\n\n"
        "1️⃣9️⃣ /inningswap\n"
        "    Swap innings (with confirmation).\n\n"
        "2️⃣0️⃣ /endmatch\n"
        "    End match and show result.\n\n"
        "*Rules:*\n"
        "• If batsman sends 0 and bowler sends rs(0), it's OUT.\n"
        "• Strike rotates on odd runs except last ball of over.\n"
        "• Host can add players anytime, even after match starts.\n"
        "• No limit on wickets: all players must be out for 'all out'.\n"
        "• All communication is text-based.\n",
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
        "toss": {"state": None, "choice": None, "winner": None, "batbowl": None}
    }

    await update.message.reply_text(
        "🎮 *New Match Created!*\n\n"
        "1️⃣ Host: Add players with /add_A <username|user_id> or /add_B <username|user_id>\n\n"
        "2️⃣ Assign captains with /cap_A <num> and /cap_B <num>\n\n"
        "3️⃣ Set overs with /setovers <num> (1-20)\n\n"
        "4️⃣ Start match with /startmatch\n\n"
        "5️⃣ Use /help for step-by-step instructions anytime.",
        parse_mode="Markdown"
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
        await update.message.reply_text("Usage: /add_A <username|user_id>  (example: /add_A @john or /add_A 123456789)")
        return

    identifier = args[0]
    player = find_player(identifier)
    if not player:
        await update.message.reply_text(
            f"No registered user found for '{identifier}'.\n"
            "Make sure they have used /register and have a Telegram username set in their Telegram settings."
        )
        return

    if player in match["team_A"] or player in match["team_B"]:
        await update.message.reply_text(f"{player['name']} (@{player.get('username','')}) is already in a team.")
        return

    match["team_A"].append(player)
    await update.message.reply_text(
        f"Added {player['name']} (@{player.get('username','')}) to Team A.\n"
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
        await update.message.reply_text("Usage: /add_B <username|user_id>  (example: /add_B @jane or /add_B 987654321)")
        return

    identifier = args[0]
    player = find_player(identifier)
    if not player:
        await update.message.reply_text(
            f"No registered user found for '{identifier}'.\n"
            "Make sure they have used /register and have a Telegram username set in their Telegram settings."
        )
        return

    if player in match["team_A"] or player in match["team_B"]:
        await update.message.reply_text(f"{player['name']} (@{player.get('username','')}) is already in a team.")
        return

    match["team_B"].append(player)
    await update.message.reply_text(
        f"Added {player['name']} (@{player.get('username','')}) to Team B.\n"
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
            text += f"{i}. {p['name']} (@{p.get('username','')})\n"
    else:
        text += "No players added yet.\n"

    text += f"\n*Team B*:\n"
    if match["team_B"]:
        for i, p in enumerate(match["team_B"], start=1):
            text += f"{i}. {p['name']} (@{p.get('username','')})\n"
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
    await update.message.reply_text(f"Captain for Team A set to {match['captain_A']['name']} (@{match['captain_A'].get('username','')}).\nAssign Team B captain with /cap_B <player_number>.")

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
    await update.message.reply_text(f"Captain for Team B set to {match['captain_B']['name']} (@{match['captain_B'].get('username','')}).\nSet overs with /setovers <number>.")

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
        "✅ Match setup complete!\n\n"
        "Host: Use /toss to start the toss."
    )
# --- Interactive Toss Flow ---

async def toss_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.id not in MATCHES:
        await update.message.reply_text("No ongoing match.")
        return
    match = MATCHES[chat.id]
    if user.id != match["host_id"]:
        await update.message.reply_text("Only the host can start the toss.")
        return
    if not match["captain_A"] or not match["captain_B"]:
        await update.message.reply_text("Assign both captains before toss.")
        return

    match["toss"]["state"] = "waiting_heads_tails"
    capA = match["captain_A"]
    keyboard = [
        [
            InlineKeyboardButton("Heads", callback_data="toss_heads"),
            InlineKeyboardButton("Tails", callback_data="toss_tails"),
        ]
    ]
    await update.message.reply_text(
        f"Toss time!\n\n{mention_player(capA)} (Team A captain), choose Heads or Tails:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def toss_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    # Save Team A's call
    choice = "Heads" if query.data == "toss_heads" else "Tails"
    match["toss"]["choice"] = choice
    match["toss"]["state"] = "toss_result"

    # Do the toss
    toss_result = random.choice(["Heads", "Tails"])
    winner = capA if toss_result == choice else capB
    match["toss"]["winner"] = winner
    match["toss"]["toss_result"] = toss_result

    await query.edit_message_text(
        f"Toss result: *{toss_result}*!\n\n"
        f"{mention_player(winner)} won the toss.",
        parse_mode="Markdown"
    )

    # Winner chooses bat or bowl
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
        parse_mode="Markdown"
    )

async def toss_batbowl_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        parse_mode="Markdown"
    )
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
    application.add_handler(CommandHandler("toss", toss_command))
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
    # Callback for toss and innings swap
    application.add_handler(CallbackQueryHandler(toss_callback, pattern="^toss_(heads|tails)$"))
    application.add_handler(CallbackQueryHandler(toss_batbowl_callback, pattern="^toss_(bat|bowl)$"))
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
    
