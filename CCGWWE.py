import random
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorClient
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, User, Message
)
from telegram.constants import ChatType
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    CallbackQueryHandler, MessageHandler, filters
)

# --- CONFIGURATION ---
BOT_TOKEN = "8133604799:AAF2dE86UjRxfAdUcqyoz3O9RgaCeTwaoHM"
MONGODB_URL = "mongodb://mongo:GhpHMiZizYnvJfKIQKxoDbRyzBCpqEyC@mainline.proxy.rlwy.net:54853"

# --- LOGGING ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- DATABASE ---
mongo_client = AsyncIOMotorClient(MONGODB_URL)
db = mongo_client["ccl_cricket"]
games: Dict[int, dict] = {}

# --- GIFs and COMMENTARY ---
GIFS = {
    0: [
        "https://media.giphy.com/media/xT0BKqhdlKCxCNsVTq/giphy.gif",
        "https://media.giphy.com/media/3o7btPCcdNniyf0ArS/giphy.gif"
    ],
    4: [
        "https://media.giphy.com/media/3o6Zt62PeJeFUDwBKo/giphy.gif",
        "https://media.giphy.com/media/3oKIPnAiaMCws8nOsE/giphy.gif"
    ],
    6: [
        "https://media.giphy.com/media/3o6gE5aYp7h1E7e5MI/giphy.gif",
        "https://media.giphy.com/media/26gsqQxPQXHBiBEUU/giphy.gif"
    ],
    'OUT': [
        "https://media.giphy.com/media/3o6Zt8zb1A6Y2T1y5C/giphy.gif",
        "https://media.giphy.com/media/l4FGnCqEwC7p1nUrm/giphy.gif"
    ],
    'FIFTY': [
        "https://media.giphy.com/media/3o6ZtrnM7gJtjuo1Co/giphy.gif"
    ],
    'HUNDRED': [
        "https://media.giphy.com/media/3o6ZsW0nsi2E4pYv5y/giphy.gif"
    ]
}
COMMENTARY = {
    0: [
        "Dot ball! Batsman couldn't get it past.",
        "No run, pressure on the batsman.",
        "Good delivery, defended."
    ],
    1: [
        "Quick single, good running!",
        "One run taken.",
        "Placed nicely for a single."
    ],
    2: [
        "They come back for two!",
        "Two runs, solid running.",
        "Excellent placement for a couple."
    ],
    3: [
        "Three runs! Great running.",
        "Good shot, three on the board.",
        "They push hard and get three."
    ],
    4: [
        "FOUR! Crunched to the boundary.",
        "That's a lovely shot for four.",
        "Ball races away! Four runs."
    ],
    6: [
        "SIX! That's massive!",
        "Into the stands! Six runs.",
        "What a hit! Maximum."
    ],
    'OUT': [
        "He's OUT! Perfect ball.",
        "Clean bowled!",
        "Caught! He's gone.",
        "That's a wicket!"
    ],
    'FIFTY': [
        "Fifty up! Well played.",
        "Half century! Classy batting.",
        "50 runs! Raises the bat."
    ],
    'HUNDRED': [
        "Century! Outstanding knock.",
        "100 runs! Take a bow.",
        "A brilliant hundred."
    ]
}
BALL_VARIATION_MAP = {
    'Rs': 0,
    'Bouncer': 1,
    'Yorker': 2,
    'Short': 3,
    'Slower': 4,
    'Knuckle': 6
}

def get_gif(run):
    return random.choice(GIFS[run]) if run in GIFS else None

def get_commentary(event):
    return random.choice(COMMENTARY[event]) if event in COMMENTARY else "Exciting cricket!"

def user_mention(user):
    return f"[{user['name']}](tg://user?id={user['user_id']})"

async def save_game(group_id):
    await db.games.update_one(
        {"group_id": group_id},
        {"$set": games[group_id]},
        upsert=True
    )

async def load_game(group_id):
    doc = await db.games.find_one({"group_id": group_id})
    if doc:
        games[group_id] = doc

def init_score_state():
    return {"runs": 0, "balls": 0, "bat_stats": {}, "bowl_stats": {}, "bat_order": [], "bowl_order": [], "wickets": 0}

def get_opposite_team(team): return 'B' if team == 'A' else 'A'

def admin_or_host(game, user_id, admins):
    if game['host_id'] == user_id: return True
    for admin in admins:
        if admin.user.id == user_id: return True
    return False

async def get_admins(context, chat_id):
    try:
        return await context.bot.get_chat_administrators(chat_id)
    except Exception:
        return []

def get_player_by_index(game, team, idx):
    if idx < 0 or idx >= len(game['teams'][team]):
        return None
    return game['teams'][team][idx]

def get_player_index(game, team, user_id):
    for i, player in enumerate(game['teams'][team]):
        if player['user_id'] == user_id:
            return i
    return None

def get_team_name(letter):
    return "Team A" if letter == "A" else "Team B"

def get_live_score(game):
    a = game['score']['A']
    b = game['score']['B']
    cur = game['current']
    msg = (
        f"🏏 *Current Score*\n"
        f"Team A: {a['runs']} / {a['wickets']} ({a['balls']//6}.{a['balls']%6} overs)\n"
        f"Team B: {b['runs']} / {b['wickets']} ({b['balls']//6}.{b['balls']%6} overs)\n"
    )
    if cur['striker'] and cur['non_striker']:
        msg += (
            f"\nBatting: {get_team_name(cur['bat_team'])}\n"
            f"Striker: {cur['striker']['name']}\n"
            f"Non-striker: {cur['non_striker']['name']}\n"
        )
    if cur['bowler']:
        msg += f"Bowler: {cur['bowler']['name']}\n"
    msg += (
        f"\nBonus: A +{game['bonus']['A']}, B +{game['bonus']['B']}\n"
        f"Penalty: A -{game['penalty']['A']}, B -{game['penalty']['B']}"
    )
    return msg

def get_final_scoreboard(game):
    a = game['score']['A']
    b = game['score']['B']
    msg = (
        f"🏆 *Final Scoreboard*\n"
        f"Team A: {a['runs']} / {a['wickets']} ({a['balls']//6}.{a['balls']%6} overs)\n"
        f"Team B: {b['runs']} / {b['wickets']} ({b['balls']//6}.{b['balls']%6} overs)\n"
        f"\nTop Batsmen (A):\n"
    )
    topA = sorted(a['bat_stats'].items(), key=lambda x: x[1]['runs'], reverse=True)[:3]
    for i, (uid, stats) in enumerate(topA):
        msg += f"{i+1}. {stats['name']} - {stats['runs']} ({stats['balls']} balls)\n"
    msg += "\nTop Bowlers (A):\n"
    topBA = sorted(a['bowl_stats'].items(), key=lambda x: x[1]['wickets'], reverse=True)[:3]
    for i, (uid, stats) in enumerate(topBA):
        msg += f"{i+1}. {stats['name']} - {stats['wickets']} wkts\n"
    msg += "\nTop Batsmen (B):\n"
    topB = sorted(b['bat_stats'].items(), key=lambda x: x[1]['runs'], reverse=True)[:3]
    for i, (uid, stats) in enumerate(topB):
        msg += f"{i+1}. {stats['name']} - {stats['runs']} ({stats['balls']} balls)\n"
    msg += "\nTop Bowlers (B):\n"
    topBB = sorted(b['bowl_stats'].items(), key=lambda x: x[1]['wickets'], reverse=True)[:3]
    for i, (uid, stats) in enumerate(topBB):
        msg += f"{i+1}. {stats['name']} - {stats['wickets']} wkts\n"
    # Victory summary
    if a['runs'] > b['runs']:
        msg += f"\n🎉 Team A won by {a['runs']-b['runs']} runs"
    elif b['runs'] > a['runs']:
        wickets_left = len(game['teams']['B']) - b['wickets']
        msg += f"\n🎉 Team B won by {wickets_left} wickets"
    else:
        msg += "\n🤝 Match Drawn!"
    return msg

# --- (continues with ALL commands & full game logic in next reply, as platform limits reached) ---
# === COMMANDS CONTINUED ===

# --- MATCH SETUP AND MANAGEMENT COMMANDS ---

async def toss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    game = games.get(group_id)
    if not game:
        await update.message.reply_text("No active match. Use /cclgroup first.")
        return
    admins = await get_admins(context, group_id)
    if not admin_or_host(game, update.effective_user.id, admins):
        await update.message.reply_text("Only host/admin can start the toss.")
        return
    if not game['captains']['A'] or not game['captains']['B']:
        await update.message.reply_text("Both captains must be set with /CapA and /CapB before the toss.")
        return
    capA_id = game['captains']['A']
    keyboard = [
        [InlineKeyboardButton("Heads", callback_data="toss_heads"),
         InlineKeyboardButton("Tails", callback_data="toss_tails")]
    ]
    await context.bot.send_message(
        chat_id=capA_id,
        text="🪙 Toss time! Choose Heads or Tails.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    await update.message.reply_text(
        "Toss started! Team A captain will receive a DM to pick Heads or Tails.\n"
        "After toss, toss winner will choose Bat/Bowl in DM."
    )

async def toss_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    group_id = None
    for gid, game in games.items():
        if game['captains']['A'] == user.id:
            group_id = gid
            break
    if not group_id:
        await query.edit_message_text("You are not the captain for any current match.")
        return
    game = games[group_id]
    toss_choice = query.data.split("_")[1]
    toss_result = random.choice(["heads", "tails"])
    toss_winner = 'A' if toss_choice.lower() == toss_result else 'B'
    game['toss'] = {"winner": toss_winner, "side": toss_result}
    await save_game(group_id)
    winner_id = game['captains'][toss_winner]
    keyboard = [
        [InlineKeyboardButton("Bat", callback_data=f"toss_bat"),
         InlineKeyboardButton("Bowl", callback_data=f"toss_bowl")]
    ]
    await context.bot.send_message(
        chat_id=winner_id,
        text=f"🪙 Toss result: {toss_result.title()}! You won the toss. Choose Bat or Bowl.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    await query.edit_message_text(
        f"Toss result: {toss_result.title()}! Waiting for toss winner to choose Bat/Bowl."
    )

async def toss_bat_bowl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    bat_or_bowl = query.data.split("_")[1]
    group_id = None
    for gid, game in games.items():
        toss = game.get('toss')
        if toss and game['captains'][toss['winner']] == user.id:
            group_id = gid
            break
    if not group_id:
        await query.edit_message_text("You are not the toss winner for any current match.")
        return
    game = games[group_id]
    toss_winner = game['toss']['winner']
    bat_team = toss_winner if bat_or_bowl == "bat" else get_opposite_team(toss_winner)
    bowl_team = get_opposite_team(bat_team)
    game['current']['bat_team'] = bat_team
    game['current']['bowl_team'] = bowl_team
    game['status'] = "ready"
    await save_game(group_id)
    await query.edit_message_text(
        f"{get_team_name(bat_team)} will bat first.\n"
        "Host: Use /bat <index> to set striker, then /bat <index> for non-striker, and /bowl <index> to set the bowler!"
    )
    host_id = game['host_id']
    await context.bot.send_message(
        chat_id=host_id,
        text="Now set striker: /bat <index>\n(See player list with /team)"
    )

async def bat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    game = games.get(group_id)
    if not game:
        await update.message.reply_text("No active match.")
        return
    admins = await get_admins(context, group_id)
    if not admin_or_host(game, update.effective_user.id, admins):
        await update.message.reply_text("Only host/admin can set batsman.")
        return
    args = context.args
    if not args or (args[0].upper() != "LMS" and not args[0].isdigit()):
        await update.message.reply_text("Usage: /bat <index> OR /bat LMS")
        return
    bat_team = game['current']['bat_team']
    if args[0].upper() == "LMS":
        game['current']['lms'] = True
        await save_game(group_id)
        await update.message.reply_text("Last Man Standing mode activated! Only one batsman will play.")
        return
    idx = int(args[0])
    batsman = get_player_by_index(game, bat_team, idx)
    if batsman is None:
        await update.message.reply_text("Invalid index.")
        return
    if not game['current']['striker']:
        game['current']['striker'] = batsman
        await update.message.reply_text(
            f"Striker set: {batsman['name']}. Now set non-striker with /bat <index>."
        )
    elif not game['current']['non_striker']:
        if batsman['user_id'] == game['current']['striker']['user_id']:
            await update.message.reply_text("Striker and non-striker must be different players.")
            return
        game['current']['non_striker'] = batsman
        await update.message.reply_text(
            f"Non-striker set: {batsman['name']}."
        )
        host_id = game['host_id']
        await context.bot.send_message(
            chat_id=host_id,
            text="Now set bowler with /bowl <index> (See player list with /team)"
        )
    else:
        await update.message.reply_text("Both striker and non-striker already set. To change, use /bat again.")

    await save_game(group_id)

async def bowl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    game = games.get(group_id)
    if not game:
        await update.message.reply_text("No active match.")
        return
    admins = await get_admins(context, group_id)
    if not admin_or_host(game, update.effective_user.id, admins):
        await update.message.reply_text("Only host/admin can set bowler.")
        return
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /bowl <index>")
        return
    bowl_team = game['current']['bowl_team']
    idx = int(args[0])
    bowler = get_player_by_index(game, bowl_team, idx)
    if bowler is None:
        await update.message.reply_text("Invalid index.")
        return
    if game['current']['last_bowler'] and bowler['user_id'] == game['current']['last_bowler']:
        await update.message.reply_text("A bowler cannot bowl two consecutive overs.")
        return
    game['current']['bowler'] = bowler
    await save_game(group_id)
    await update.message.reply_text(
        f"Bowler set: {bowler['name']}."
    )
    host_id = game['host_id']
    await context.bot.send_message(
        chat_id=host_id,
        text="Now type /nextball to deliver the first ball of the over."
    )

async def nextball(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    game = games.get(group_id)
    if not game:
        await update.message.reply_text("No active match.")
        return
    cur = game['current']
    if not (cur['striker'] and cur['non_striker'] and cur['bowler']):
        await update.message.reply_text("Set striker, non-striker and bowler first.")
        return
    # DM prompt to batsman and bowler
    striker = cur['striker']
    bowler = cur['bowler']
    await context.bot.send_message(
        chat_id=striker['user_id'],
        text="🏏 Your turn to bat! Reply with a number: 0, 1, 2, 3, 4, or 6."
    )
    await context.bot.send_message(
        chat_id=bowler['user_id'],
        text="🎳 Your turn to bowl! Reply with: Rs, Bouncer, Yorker, Short, Slower, or Knuckle."
    )
    cur['inputs'] = {}
    await save_game(group_id)
    await update.message.reply_text("Ball in progress. Awaiting DM inputs from striker and bowler...")

async def handle_dm_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message.text.strip()
    for group_id, game in games.items():
        cur = game['current']
        if cur.get('striker') and cur['striker']['user_id'] == user.id and 'bat' not in cur['inputs']:
            if msg not in ['0','1','2','3','4','6']:
                await update.message.reply_text("Send: 0, 1, 2, 3, 4, or 6.")
                return
            cur['inputs']['bat'] = int(msg)
            await update.message.reply_text("Batting input received. Waiting for bowler...")
        elif cur.get('bowler') and cur['bowler']['user_id'] == user.id and 'bowl' not in cur['inputs']:
            if msg not in BALL_VARIATION_MAP:
                await update.message.reply_text("Send: Rs, Bouncer, Yorker, Short, Slower, or Knuckle.")
                return
            cur['inputs']['bowl'] = msg
            await update.message.reply_text("Bowling input received. Waiting for batsman...")
    for group_id, game in games.items():
        cur = game['current']
        if 'bat' in cur['inputs'] and 'bowl' in cur['inputs']:
            await process_ball(group_id, context)
            break

async def process_ball(group_id, context):
    game = games[group_id]
    cur = game['current']
    bat_team = cur['bat_team']
    bowl_team = cur['bowl_team']
    striker = cur['striker']
    non_striker = cur['non_striker']
    bowler = cur['bowler']
    ball = cur['ball']
    over = cur['over']

    # 1. Announce over/ball
    msg1 = f"Over {over} Ball {ball}"
    await context.bot.send_message(chat_id=group_id, text=msg1)
    await asyncio.sleep(2)
    # 2. Bowler commentary
    msg2 = f"{bowler['name']} bowled a {cur['inputs']['bowl']}!"
    await context.bot.send_message(chat_id=group_id, text=msg2)
    await asyncio.sleep(2)
    # 3. Bat commentary/result
    run = cur['inputs']['bat']
    var_num = BALL_VARIATION_MAP[cur['inputs']['bowl']]
    out = False
    if run == var_num:
        # OUT
        out = True
        commentary = get_commentary('OUT')
        gif = get_gif('OUT')
        await context.bot.send_message(chat_id=group_id, text=f"{striker['name']} is OUT! {commentary}")
        if gif:
            await context.bot.send_animation(chat_id=group_id, animation=gif)
        game['score'][bat_team]['wickets'] += 1
        # Replace striker with next batsman (prompt host)
        cur['striker'] = None
        await context.bot.send_message(
            chat_id=group_id,
            text="Host: Set new striker with /bat <index>\n(See /team for indexes.)"
        )
    else:
        commentary = get_commentary(run)
        gif = get_gif(run)
        await context.bot.send_message(chat_id=group_id, text=f"{striker['name']} scored {run}! {commentary}")
        if gif:
            await context.bot.send_animation(chat_id=group_id, animation=gif)
        game['score'][bat_team]['runs'] += run
        # Batting stats
        bst = game['score'][bat_team]['bat_stats'].setdefault(striker['user_id'], {"runs":0, "balls":0, "name":striker['name']})
        bst['runs'] += run
        bst['balls'] += 1
        # Bowling stats
        bowl_stats = game['score'][bowl_team]['bowl_stats'].setdefault(bowler['user_id'], {"balls":0, "wickets":0, "name":bowler['name']})
        bowl_stats['balls'] += 1
        if bst['runs'] >= 100 and not bst.get("hundred_announced"):
            msg = get_commentary('HUNDRED')
            gif = get_gif('HUNDRED')
            await context.bot.send_message(chat_id=group_id, text=msg)
            if gif: await context.bot.send_animation(chat_id=group_id, animation=gif)
            bst["hundred_announced"] = True
        elif bst['runs'] >= 50 and not bst.get("fifty_announced"):
            msg = get_commentary('FIFTY')
            gif = get_gif('FIFTY')
            await context.bot.send_message(chat_id=group_id, text=msg)
            if gif: await context.bot.send_animation(chat_id=group_id, animation=gif)
            bst["fifty_announced"] = True
        # Strike rotation
        if run % 2 == 1:
            cur['striker'], cur['non_striker'] = cur['non_striker'], cur['striker']
    # Ball/over increment
    cur['ball'] += 1
    game['score'][bat_team]['balls'] += 1
    if cur['ball'] > 6:
        cur['over'] += 1
        cur['ball'] = 1
        if not out and run % 2 == 0:
            cur['striker'], cur['non_striker'] = cur['non_striker'], cur['striker']
        cur['last_bowler'] = cur['bowler']['user_id']
        cur['bowler'] = None
        await context.bot.send_message(
            chat_id=group_id,
            text="Over completed! Host: Set bowler for next over with /bowl <index>."
        )
    # End of match or innings logic not shown (see finish/inningswap below)
    await save_game(group_id)
    cur['inputs'] = {}

async def retiredhurt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    game = games.get(group_id)
    if not game:
        await update.message.reply_text("No active match.")
        return
    admins = await get_admins(context, group_id)
    if not admin_or_host(game, update.effective_user.id, admins):
        await update.message.reply_text("Only host/admin can retire players.")
        return
    args = context.args
    if not args or args[0] not in ["strike", "non", "bowler"]:
        await update.message.reply_text("Usage: /retiredhurt strike/non/bowler")
        return
    who = args[0]
    if who == "strike":
        game['current']['striker'] = None
    elif who == "non":
        game['current']['non_striker'] = None
    elif who == "bowler":
        game['current']['bowler'] = None
    await save_game(group_id)
    await update.message.reply_text("Player retired hurt. Host: Replace with new player.")

async def retiredout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    game = games.get(group_id)
    if not game:
        await update.message.reply_text("No active match.")
        return
    admins = await get_admins(context, group_id)
    if not admin_or_host(game, update.effective_user.id, admins):
        await update.message.reply_text("Only host/admin can retire players.")
        return
    args = context.args
    if not args or args[0] not in ["strike", "non"]:
        await update.message.reply_text("Usage: /retiredout strike/non")
        return
    who = args[0]
    bat_team = game['current']['bat_team']
    game['score'][bat_team]['wickets'] += 1
    if who == "strike":
        game['current']['striker'] = None
    elif who == "non":
        game['current']['non_striker'] = None
    await save_game(group_id)
    await update.message.reply_text("Player retired out (counts as wicket). Host: Replace with new player.")

async def inningswap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    game = games.get(group_id)
    if not game:
        await update.message.reply_text("No active match.")
        return
    admins = await get_admins(context, group_id)
    if not admin_or_host(game, update.effective_user.id, admins):
        await update.message.reply_text("Only host/admin can swap innings.")
        return
    game['current']['bat_team'], game['current']['bowl_team'] = game['current']['bowl_team'], game['current']['bat_team']
    game['current']['striker'] = None
    game['current']['non_striker'] = None
    game['current']['bowler'] = None
    game['current']['last_bowler'] = None
    game['current']['over'] = 1
    game['current']['ball'] = 1
    game['current']['inputs'] = {}
    game['innings'] += 1
    await save_game(group_id)
    await update.message.reply_text("Innings swapped! Host: Set striker, non-striker, and bowler for the new innings.")

async def finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    game = games.get(group_id)
    if not game:
        await update.message.reply_text("No active match.")
        return
    admins = await get_admins(context, group_id)
    if not admin_or_host(game, update.effective_user.id, admins):
        await update.message.reply_text("Only host/admin can finish the match.")
        return
    game['finished'] = True
    await save_game(group_id)
    await update.message.reply_text("Match finished manually.")
    await context.bot.send_message(chat_id=group_id, text=get_final_scoreboard(game), parse_mode="Markdown")

async def endmatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    game = games.get(group_id)
    if not game:
        await update.message.reply_text("No active match.")
        return
    admins = await get_admins(context, group_id)
    if not admin_or_host(game, update.effective_user.id, admins):
        await update.message.reply_text("Only host/admin can end the match.")
        return
    game['finished'] = True
    await save_game(group_id)
    await update.message.reply_text("Match ended (early).")
    await context.bot.send_message(chat_id=group_id, text=get_final_scoreboard(game), parse_mode="Markdown")

async def hostchange(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    game = games.get(group_id)
    if not game:
        await update.message.reply_text("No active match.")
        return
    admins = await get_admins(context, group_id)
    if not any(admin.user.id == update.effective_user.id for admin in admins):
        await update.message.reply_text("Only a group admin can become host.")
        return
    game['host_id'] = update.effective_user.id
    await save_game(group_id)
    await update.message.reply_text(f"{update.effective_user.full_name} is now the host.")

async def bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    game = games.get(group_id)
    if not game:
        await update.message.reply_text("No active match.")
        return
    admins = await get_admins(context, group_id)
    if not admin_or_host(game, update.effective_user.id, admins):
        await update.message.reply_text("Only host/admin can give bonus.")
        return
    args = context.args
    if not args or len(args) != 2 or args[0] not in ("A","B") or not args[1].isdigit():
        await update.message.reply_text("Usage: /bonus A|B <runs>")
        return
    team, runs = args[0], int(args[1])
    game['bonus'][team] += runs
    game['score'][team]['runs'] += runs
    await save_game(group_id)
    await update.message.reply_text(f"Bonus: {runs} runs added to Team {team}.")

async def penalty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    game = games.get(group_id)
    if not game:
        await update.message.reply_text("No active match.")
        return
    admins = await get_admins(context, group_id)
    if not admin_or_host(game, update.effective_user.id, admins):
        await update.message.reply_text("Only host/admin can give penalty.")
        return
    args = context.args
    if not args or len(args) != 2 or args[0] not in ("A","B") or not args[1].isdigit():
        await update.message.reply_text("Usage: /penalty A|B <runs>")
        return
    team, runs = args[0], int(args[1])
    game['penalty'][team] += runs
    game['score'][team]['runs'] -= runs
    await save_game(group_id)
    await update.message.reply_text(f"Penalty: {runs} runs deducted from Team {team}.")

async def score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    game = games.get(group_id)
    if not game:
        await update.message.reply_text("No active match.")
        return
    await update.message.reply_text(get_live_score(game), parse_mode="Markdown")

async def guide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🏏 *CCL Telegram Cricket Bot - Full Guide*\n"
        "\n"
        "🟢 *Match Initialization:*\n"
        "/start — Start using the bot in DM\n"
        "/register — Register for a match (DM)\n"
        "/cclgroup — Start a new match in group (becomes Host)\n"
        "\n"
        "👥 *Player & Team Management:*\n"
        "/addA @username — Add player to Team A\n"
        "/addB @username — Add player to Team B\n"
        "/removeA <index> — Remove player from Team A\n"
        "/removeB <index> — Remove player from Team B\n"
        "/CapA <index> — Set captain for Team A\n"
        "/CapB <index> — Set captain for Team B\n"
        "/team — Show current teams\n"
        "\n"
        "⚙️ *Match Config:*\n"
        "/setovers <number> — Set number of overs\n"
        "/toss — Start toss\n"
        "\n"
        "🏏 *Player Selection:*\n"
        "/bat <index> — Set striker/non-striker\n"
        "/bowl <index> — Set bowler\n"
        "/bat LMS — Last Man Standing mode\n"
        "\n"
        "🔄 *During Match:*\n"
        "/nextball — Deliver next ball (after striker/bowler DM input)\n"
        "\n"
        "🚑 *Retire/Recovery:*\n"
        "/retiredhurt strike/non/bowler — Retire hurt\n"
        "/retiredout strike/non — Retire out (wicket)\n"
        "\n"
        "🔁 *Innings:*\n"
        "/inningswap — Swap innings\n"
        "\n"
        "➕/➖ *Bonus & Penalty:*\n"
        "/bonus A 5 — Add 5 runs to Team A\n"
        "/penalty B 6 — Deduct 6 runs from Team B\n"
        "\n"
        "📊 *Score & Result:*\n"
        "/score — Show scoreboard\n"
        "\n"
        "🛑 *Finish:*\n"
        "/finish — Finish match\n"
        "/endmatch — End match early\n"
        "\n"
        "👑 *Host Management:*\n"
        "/hostchange — GC admin can take host\n"
        "\n"
        "ℹ️ After every step, host will receive instructions for next action.\n"
        "\n"
        "🟡 *How to Play a Ball:*\n"
        "1. Host types /nextball in group.\n"
        "2. Striker gets a DM: Reply 0,1,2,3,4,6.\n"
        "3. Bowler gets a DM: Reply Rs, Bouncer, Yorker, Short, Slower, Knuckle.\n"
        "4. Bot posts commentary in group automatically.\n"
        "\n"
        "Strike changes if batsman hits an odd run. At over end, strike rotates only if last run is even.\n"
        "No fixed wicket limit—host decides when to finish or swap innings.\n"
        "For any confusion, ask /guide anytime!"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# === MAIN BOT STARTUP ===

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("register", register))
    app.add_handler(CommandHandler("cclgroup", cclgroup))
    app.add_handler(CommandHandler("addA", add_team))
    app.add_handler(CommandHandler("addB", add_team))
    app.add_handler(CommandHandler("removeA", remove_team))
    app.add_handler(CommandHandler("removeB", remove_team))
    app.add_handler(CommandHandler("CapA", set_captain))
    app.add_handler(CommandHandler("CapB", set_captain))
    app.add_handler(CommandHandler("team", team_command))
    app.add_handler(CommandHandler("setovers", set_overs))
    app.add_handler(CommandHandler("toss", toss))
    app.add_handler(CallbackQueryHandler(toss_choice, pattern="^toss_(heads|tails)$"))
    app.add_handler(CallbackQueryHandler(toss_bat_bowl, pattern="^toss_(bat|bowl)$"))
    app.add_handler(CommandHandler("bat", bat))
    app.add_handler(CommandHandler("bowl", bowl))
    app.add_handler(CommandHandler("nextball", nextball))
    app.add_handler(CommandHandler("retiredhurt", retiredhurt))
    app.add_handler(CommandHandler("retiredout", retiredout))
    app.add_handler(CommandHandler("inningswap", inningswap))
    app.add_handler(CommandHandler("finish", finish))
    app.add_handler(CommandHandler("endmatch", endmatch))
    app.add_handler(CommandHandler("hostchange", hostchange))
    app.add_handler(CommandHandler("bonus", bonus))
    app.add_handler(CommandHandler("penalty", penalty))
    app.add_handler(CommandHandler("score", score))
    app.add_handler(CommandHandler("guide", guide))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT, handle_dm_input))
    print("🏏 CCL Cricket Bot is running!")
    app.run_polling()

if __name__ == "__main__":
    main()
