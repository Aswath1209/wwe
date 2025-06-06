# mafia_game_part1.py

import logging
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    CallbackContext, ContextTypes, CallbackQueryHandler
)
from pymongo import MongoClient
import random
import asyncio

# ====== CONFIG ======
BOT_TOKEN = "8133604799:AAF2dE86UjRxfAdUcqyoz3O9RgaCeTwaoHM"
MONGO_URI = "mongodb://mongo:GhpHMiZizYnvJfKIQKxoDbRyzBCpqEyC@mainline.proxy.rlwy.net:54853"
BOT_USERNAME = "YourBotUsername"  # without @

# ====== SETUP ======
client = MongoClient(MONGO_URI)
db = client["mafia_bot"]
games_col = db["games"]
users_col = db["users"]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ====== UTIL ======

def get_active_game(group_id: int):
    return games_col.find_one({"group_id": group_id, "status": {"$in": ["registration", "playing"]}})

def update_game(group_id: int, updates: dict):
    games_col.update_one({"group_id": group_id}, {"$set": updates})

def add_player_to_game(group_id: int, user_id: int, username: str):
    games_col.update_one(
        {"group_id": group_id},
        {"$addToSet": {"players": {"user_id": user_id, "username": username}}}
    )

def remove_game(group_id: int):
    games_col.delete_one({"group_id": group_id})

# ====== START AND REGISTER ======

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    args = context.args

    if chat.type == "private" and args and args[0].lower() == "join":
        active_game = games_col.find_one({"status": "registration"})
        if not active_game:
            await update.message.reply_text("🚫 No active Mafia game to join.")
            return

        group_id = active_game["group_id"]
        already = any(p['user_id'] == user.id for p in active_game.get("players", []))
        if already:
            await update.message.reply_text("✅ You already joined the game.")
        else:
            add_player_to_game(group_id, user.id, user.username or user.full_name)
            await update.message.reply_text(
                f"🎮 You joined the Mafia Game in the group!"
            )
            await update_registration_message(context.application, group_id)

    else:
        await update.message.reply_text("Welcome to Mafia Game Bot! Use /register in a group to start.")

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type != "group" and chat.type != "supergroup":
        await update.message.reply_text("❗ Use this command in a group.")
        return

    existing = get_active_game(chat.id)
    if existing:
        await update.message.reply_text("⚠️ A game is already in progress or open for registration.")
        return

    games_col.insert_one({
        "group_id": chat.id,
        "status": "registration",
        "players": [],
        "round": 0,
        "coins_given": False
    })
    await update_registration_message(context.application, chat.id)
    await update.message.reply_text("📢 Registration for Mafia Game has started!")
# part 2/6 - Update registration message with list & join button

from telegram.helpers import mention_html

async def update_registration_message(app, group_id: int):
    game = get_active_game(group_id)
    if not game:
        return

    players = game.get("players", [])
    player_count = len(players)

    text = "🕵️‍♂️ <b>Registration for Mafia Game is OPEN!</b>\n\n"
    if players:
        text += "<b>👥 Registered Players:</b>\n"
        for p in players:
            name = mention_html(p['user_id'], p.get("username", "Player"))
            text += f"• {name}\n"
    else:
        text += "No one has joined yet.\n"

    text += f"\n✅ <b>{player_count} players</b> joined so far.\n"
    text += "Click the button below to join the game in DM."

    button = InlineKeyboardMarkup.from_button(
        InlineKeyboardButton(
            text="🎮 Join Game",
            url=f"https://t.me/{BOT_USERNAME}?start=join"
        )
    )

    # try sending or editing pinned message
    try:
        if msg := game.get("message_id"):
            await app.bot.edit_message_text(
                chat_id=group_id,
                message_id=msg,
                text=text,
                reply_markup=button,
                parse_mode=ParseMode.HTML
            )
        else:
            sent = await app.bot.send_message(
                chat_id=group_id,
                text=text,
                reply_markup=button,
                parse_mode=ParseMode.HTML
            )
            games_col.update_one({"group_id": group_id}, {"$set": {"message_id": sent.message_id}})
    except Exception as e:
        logger.warning(f"Error updating registration message: {e}")
# part 3/6 - Role assignment and DM role message

ROLE_SUMMARIES = {
    "Townie": "🧍‍♂️ You’re a simple villager. Stay alive and vote wisely to defeat the Mafia!",
    "Doctor": "💉 You can save 1 player each night from being killed. You can even save yourself.",
    "Detective": "🕵️‍♂️ You can inspect one player per night to learn their alignment.",
    "Mafia": "🔪 You’re part of the Mafia. Work with your team to eliminate the others.",
    "Don": "👑 The Don leads the Mafia. Your vote decides who dies if Mafia disagree.",
    "Framer": "🎭 You appear innocent but assist the Mafia. You can’t kill but help mislead.",
    "Watcher": "👁️ You can watch one player each night to see who visits them.",
    "Suicide": "☠️ Your goal is to get lynched during the day. Trick others into voting you!"
}

def generate_roles(n: int) -> list:
    """
    Given n players, return a shuffled list of roles.
    Don > Mafia > Framer > Suicide are Mafia side (max 4)
    Town side always includes Townie, Doctor, Detective
    """
    roles = []

    # Always include
    roles += ["Doctor", "Detective", "Don"]

    if n == 4:
        roles += ["Mafia"]
    elif n == 5:
        roles += ["Mafia", "Townie"]
    elif n == 6:
        roles += ["Mafia", "Townie", "Townie"]
    elif n == 7:
        roles += ["Mafia", "Townie", "Townie", "Framer"]
    elif n == 8:
        roles += ["Mafia", "Townie", "Townie", "Framer", "Watcher"]
    elif n == 9:
        roles += ["Mafia", "Townie", "Townie", "Framer", "Watcher", "Suicide"]
    elif n == 10:
        roles += ["Mafia", "Mafia", "Townie", "Townie", "Framer", "Watcher", "Suicide"]
    elif n == 11:
        roles += ["Mafia", "Mafia", "Townie", "Townie", "Framer", "Watcher", "Townie", "Suicide"]
    elif n == 12:
        roles += ["Mafia", "Mafia", "Framer", "Townie", "Townie", "Townie", "Watcher", "Suicide"]
    elif n == 13:
        roles += ["Mafia", "Mafia", "Framer", "Townie", "Townie", "Townie", "Watcher", "Suicide", "Townie"]
    elif n == 14:
        roles += ["Mafia", "Mafia", "Framer", "Townie", "Townie", "Watcher", "Townie", "Suicide", "Townie", "Mafia"]
    elif n == 15:
        roles += ["Mafia", "Mafia", "Framer", "Suicide", "Townie", "Townie", "Watcher", "Townie", "Townie", "Mafia"]

    while len(roles) < n:
        roles.append("Townie")

    random.shuffle(roles)
    return roles

async def assign_roles(app, group_id: int):
    game = get_active_game(group_id)
    if not game or len(game["players"]) < 4:
        return

    players = game["players"]
    roles = generate_roles(len(players))
    assigned = []

    for i, player in enumerate(players):
        role = roles[i]
        user_id = player["user_id"]
        assigned.append({**player, "role": role})
        try:
            await app.bot.send_message(
                chat_id=user_id,
                text=f"🕵️‍♂️ <b>Your Role:</b> <code>{role}</code>\n\n{ROLE_SUMMARIES[role]}",
                parse_mode=ParseMode.HTML
            )
        except:
            logger.warning(f"Couldn't DM {user_id}")

    update_game(group_id, {"players": assigned, "status": "playing", "round": 1})
# part 4/6 - Night phase handler and action collection

night_actions = {}  # {group_id: {user_id: action_data}}

async def start_night_phase(app, group_id: int):
    game = get_active_game(group_id)
    if not game or game["status"] != "playing":
        return

    round_no = game.get("round", 1)
    players = game["players"]

    alive = [p for p in players if not p.get("dead")]

    night_actions[group_id] = {}

    await app.bot.send_message(group_id, f"🌙 <b>Night {round_no}</b> begins...\nEveryone close your eyes 😴", parse_mode=ParseMode.HTML)

    for p in alive:
        uid = p["user_id"]
        role = p["role"]

        if role in ["Mafia", "Don"]:
            text = "🔪 Choose someone to kill tonight:"
            others = [x for x in alive if x["user_id"] != uid]
        elif role == "Doctor":
            text = "💉 Choose someone to heal:"
            others = alive
        elif role == "Detective":
            text = "🕵️‍♂️ Choose someone to investigate:"
            others = [x for x in alive if x["user_id"] != uid]
        elif role == "Watcher":
            text = "👁️ Choose someone to watch tonight:"
            others = [x for x in alive if x["user_id"] != uid]
        elif role == "Framer":
            text = "🎭 Choose someone to frame (they'll appear suspicious):"
            others = [x for x in alive if x["user_id"] != uid]
        else:
            continue  # No night action

        btns = [
            [InlineKeyboardButton(x["username"], callback_data=f"night_{group_id}_{uid}_{x['user_id']}")]
            for x in others
        ]
        try:
            await app.bot.send_message(
                uid,
                text=text,
                reply_markup=InlineKeyboardMarkup(btns),
            )
        except:
            logger.warning(f"Failed to send night action to {uid}")

async def handle_night_choice(uid: int, target_id: int, group_id: int, app):
    if group_id not in night_actions:
        night_actions[group_id] = {}
    night_actions[group_id][uid] = target_id

    # Acknowledge instantly
    try:
        await app.bot.send_message(uid, f"✅ You selected <code>{target_id}</code> for tonight.", parse_mode=ParseMode.HTML)
    except:
        pass

    # Check if all actions are in
    game = get_active_game(group_id)
    alive = [p for p in game["players"] if not p.get("dead")]
    roles_with_actions = [p for p in alive if p["role"] in ["Mafia", "Don", "Doctor", "Detective", "Framer", "Watcher"]]

    if len(night_actions[group_id]) >= len(roles_with_actions):
        await resolve_night_phase(app, group_id)

async def resolve_night_phase(app, group_id: int):
    actions = night_actions[group_id]
    game = get_active_game(group_id)
    if not game:
        return

    players = game["players"]
    id_to_player = {p["user_id"]: p for p in players if not p.get("dead")}
    
    # Extract roles
    kills = []
    save = None
    investigate_result = ""
    frame_targets = set()
    watch_reports = []

    for uid, target_id in actions.items():
        role = id_to_player[uid]["role"]
        if role in ["Don", "Mafia"]:
            kills.append(target_id)
        elif role == "Doctor":
            save = target_id
        elif role == "Detective":
            target_role = id_to_player.get(target_id, {}).get("role", "")
            result = "🟩 Innocent" if target_role in ["Townie", "Doctor", "Watcher", "Detective"] else "🟥 Suspicious"
            investigate_result = f"🕵️ You investigated {id_to_player[target_id]['username']} — {result}"
        elif role == "Framer":
            frame_targets.add(target_id)
        elif role == "Watcher":
            for k, v in actions.items():
                if v == target_id and k != uid:
                    watch_reports.append((uid, id_to_player[k]["username"], id_to_player[v]["username"]))

    # Finalize kill (Don overrides)
    kill_target = None
    dons = [p for p in id_to_player.values() if p["role"] == "Don" and p["user_id"] in actions]
    if dons:
        kill_target = actions[dons[0]["user_id"]]
    elif kills:
        kill_target = random.choice(kills)

    if kill_target and kill_target != save:
        for p in players:
            if p["user_id"] == kill_target:
                p["dead"] = True
                break
        await app.bot.send_message(group_id, f"💀 Someone was found dead this morning...")

    else:
        await app.bot.send_message(group_id, f"🌤️ Everyone survived the night!")

    # Send individual role messages
    for uid in actions:
        role = id_to_player[uid]["role"]
        if role == "Detective" and investigate_result:
            await app.bot.send_message(uid, investigate_result)
        elif role == "Watcher":
            reports = [f"👁️ {u} visited {t}" for x, u, t in watch_reports if x == uid]
            if reports:
                await app.bot.send_message(uid, "\n".join(reports))
            else:
                await app.bot.send_message(uid, "👁️ No one visited your target.")

    # Clean up
    update_game(group_id, {"players": players, "round": game["round"] + 1})
    night_actions.pop(group_id, None)

    # Now begin day phase (to be continued in next part)
    await start_day_voting(app, group_id)
# part 5/6 - Day phase, voting, and win condition checks

vote_data = {}  # {group_id: {voter_id: target_id}}

async def start_day_voting(app, group_id: int):
    game = get_active_game(group_id)
    if not game or game["status"] != "playing":
        return

    players = game["players"]
    alive = [p for p in players if not p.get("dead")]
    vote_data[group_id] = {}

    await app.bot.send_message(group_id, "🌞 <b>Day Time!</b>\nDiscuss and vote to lynch someone!", parse_mode="HTML")

    # Send vote buttons to alive users
    for voter in alive:
        voter_id = voter["user_id"]
        buttons = [
            [InlineKeyboardButton(p["username"], callback_data=f"vote_{group_id}_{voter_id}_{p['user_id']}")]
            for p in alive if p["user_id"] != voter_id
        ]
        try:
            await app.bot.send_message(
                voter_id,
                "⚖️ <b>Vote someone to lynch:</b>",
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode="HTML"
            )
        except:
            continue

async def handle_vote_choice(voter_id: int, target_id: int, group_id: int, app):
    if group_id not in vote_data:
        vote_data[group_id] = {}
    vote_data[group_id][voter_id] = target_id

    try:
        await app.bot.send_message(voter_id, f"✅ You voted for <code>{target_id}</code>", parse_mode="HTML")
    except:
        pass

    game = get_active_game(group_id)
    alive = [p for p in game["players"] if not p.get("dead")]

    if len(vote_data[group_id]) >= len(alive):
        await resolve_vote(app, group_id)

async def resolve_vote(app, group_id: int):
    game = get_active_game(group_id)
    votes = vote_data.get(group_id, {})
    tally = {}

    for target in votes.values():
        tally[target] = tally.get(target, 0) + 1

    # Max voted target
    if not tally:
        await app.bot.send_message(group_id, "🤷 No consensus. No one is lynched today.")
        await start_night_phase(app, group_id)
        return

    lynch_id = max(tally, key=tally.get)
    for p in game["players"]:
        if p["user_id"] == lynch_id:
            p["dead"] = True
            lynched_role = p["role"]
            lynched_user = p["username"]
            break

    await app.bot.send_message(group_id, f"⚰️ <b>{lynched_user}</b> was lynched by the town!\nTheir role was: <b>{lynched_role}</b>", parse_mode="HTML")

    update_game(group_id, {"players": game["players"]})
    vote_data.pop(group_id, None)

    if await check_victory(app, group_id):
        return
    await start_night_phase(app, group_id)

async def check_victory(app, group_id: int) -> bool:
    game = get_active_game(group_id)
    players = game["players"]

    mafia = [p for p in players if p["role"] in ["Mafia", "Don", "Framer"] and not p.get("dead")]
    town = [p for p in players if p["role"] not in ["Mafia", "Don", "Framer", "Suicide"] and not p.get("dead")]
    suicides = [p for p in players if p["role"] == "Suicide" and p.get("dead")]

    winner = None
    if not mafia:
        winner = "🟦 Town"
    elif not town:
        winner = "🟥 Mafia"
    elif any(suicides):
        winner = "💣 Suicide"

    if winner:
        await app.bot.send_message(group_id, f"🏆 <b>Game Over!</b>\n<b>{winner}</b> wins the game!", parse_mode="HTML")

        for p in players:
            if not p.get("dead"):
                try:
                    await app.bot.send_message(p["user_id"], "🎉 You survived and won!\n+10 🪙 Coins!")
                except:
                    pass

        games.pop(group_id, None)
        return True

    return False

@bot.on_message(filters.command("cancel") & filters.group)
async def cancel_game(_, message: Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    admins = await bot.get_chat_administrators(chat_id)
    if user_id not in [a.user.id for a in admins]:
        return await message.reply("❌ Only group admins can cancel the game.")

    if chat_id in games:
        games.pop(chat_id)
        await message.reply("🚫 Game cancelled.")
    else:
        await message.reply("❌ No game is running.")
# part 6/6 - MongoDB integration and utility functions

from pymongo import MongoClient

MONGO_URL = "mongodb://mongo:GhpHMiZizYnvJfKIQKxoDbRyzBCpqEyC@mainline.proxy.rlwy.net:54853"  # Replace with your MongoDB URI
BOT_TOKEN = "8133604799:AAF2dE86UjRxfAdUcqyoz3O9RgaCeTwaoHM"     # Replace with your bot token

client = MongoClient(MONGO_URL)
db = client["mafia_game"]
games_col = db["games"]

games = {}  # In-memory cache for fast access

def get_active_game(group_id: int):
    if group_id in games:
        return games[group_id]
    game = games_col.find_one({"group_id": group_id, "status": "playing"})
    if game:
        games[group_id] = game
    return game

def save_game(group_id: int, data: dict):
    games[group_id] = data
    games_col.update_one(
        {"group_id": group_id},
        {"$set": data},
        upsert=True
    )

def update_game(group_id: int, new_data: dict):
    current = get_active_game(group_id)
    if not current:
        return
    current.update(new_data)
    save_game(group_id, current)

def delete_game(group_id: int):
    if group_id in games:
        del games[group_id]
    games_col.delete_one({"group_id": group_id})
