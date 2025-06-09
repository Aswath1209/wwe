import logging
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    CallbackQueryHandler, MessageHandler, filters
)
from pymongo import MongoClient
import random
import asyncio
import os

# Set up logging
logging.basicConfig(level=logging.INFO)

# === MongoDB and Bot Token ===
MONGO_URL = "mongodb://mongo:GhpHMiZizYnvJfKIQKxoDbRyzBCpqEyC@mainline.proxy.rlwy.net:54853"
BOT_TOKEN = "8133604799:AAF2dE86UjRxfAdUcqyoz3O9RgaCeTwaoHM"

client = MongoClient(MONGO_URL)
db = client["ccl_group_db"]
match_col = db["match"]
users_col = db["users"]

# === START AND REGISTER ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏏 Welcome to CCL Group Cricket Bot!\nUse /register to join the game."
    )

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_data = {
        "user_id": user.id,
        "username": user.username or user.first_name
    }
    users_col.update_one({"user_id": user.id}, {"$set": user_data}, upsert=True)
    await update.message.reply_text("✅ You are registered for CCL matches!")

# === CCL GROUP INIT ===
async def cclgroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    match = {
        "chat_id": chat.id,
        "host_id": user.id,
        "host_name": user.username or user.first_name,
        "teamA": [],
        "teamB": [],
        "captainA": None,
        "captainB": None,
        "innings": 1,
        "current_batting": "A",
        "overs": None,
        "scoreboard": {"A": [], "B": []},
        "status": "setup"
    }
    match_col.update_one({"chat_id": chat.id}, {"$set": match}, upsert=True)

    await update.message.reply_text(
        f"🏏 CCL Group Match Initialized by {user.mention_html()}",
        parse_mode='HTML'
    )
# === ADD PLAYERS TO TEAM A/B ===
async def addA(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await add_player(update, context, "A")

async def addB(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await add_player(update, context, "B")

async def add_player(update: Update, context: ContextTypes.DEFAULT_TYPE, team: str):
    chat_id = update.effective_chat.id
    match = match_col.find_one({"chat_id": chat_id})
    if not match: return

    if len(context.args) != 1:
        await update.message.reply_text("⚠️ Usage: /addA @username or user_id")
        return

    user_input = context.args[0]
    if user_input.startswith("@"):
        user_input = user_input[1:]

    player = users_col.find_one({
        "$or": [{"username": user_input}, {"user_id": int(user_input) if user_input.isdigit() else -1}]
    })

    if not player:
        await update.message.reply_text("❌ Player not registered.")
        return

    player_entry = {"user_id": player["user_id"], "username": player["username"]}
    team_key = "teamA" if team == "A" else "teamB"

    if player_entry in match[team_key]:
        await update.message.reply_text("⚠️ Player already in team.")
        return

    match[team_key].append(player_entry)
    match_col.update_one({"chat_id": chat_id}, {"$set": {team_key: match[team_key]}})
    await update.message.reply_text(f"✅ Added {player['username']} to Team {team}")

# === SET CAPTAIN ===
async def capA(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await set_captain(update, context, "A")

async def capB(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await set_captain(update, context, "B")

async def set_captain(update: Update, context: ContextTypes.DEFAULT_TYPE, team: str):
    chat_id = update.effective_chat.id
    match = match_col.find_one({"chat_id": chat_id})
    if not match: return

    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("⚠️ Usage: /CapA 1")
        return

    index = int(context.args[0]) - 1
    team_key = "teamA" if team == "A" else "teamB"
    if index < 0 or index >= len(match[team_key]):
        await update.message.reply_text("❌ Invalid player index.")
        return

    player = match[team_key][index]
    cap_key = "captainA" if team == "A" else "captainB"
    match_col.update_one({"chat_id": chat_id}, {"$set": {cap_key: player}})
    await update.message.reply_text(f"🧢 {player['username']} is now Captain of Team {team}")

# === VIEW TEAM ===
async def team(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    match = match_col.find_one({"chat_id": chat_id})
    if not match: return

    def format_team(team, name):
        lines = [f"🏏 {name}"]
        for i, p in enumerate(team, 1):
            lines.append(f"{i}) {p['username']}")
        return "\n".join(lines)

    msg = f"{format_team(match['teamA'], 'Team A')}\n\n{format_team(match['teamB'], 'Team B')}"
    await update.message.reply_text(msg)
# === TOSS HANDLER ===
async def toss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    match = match_col.find_one({"chat_id": chat_id})
    if not match or not match.get("captainA") or not match.get("captainB"):
        await update.message.reply_text("⚠️ Both teams and captains must be set first.")
        return

    keyboard = [
        [
            InlineKeyboardButton("Heads", callback_data="toss_heads"),
            InlineKeyboardButton("Tails", callback_data="toss_tails")
        ]
    ]
    capA_id = match['captainA']['user_id']
    msg = await update.message.reply_text(
        f"🪙 {match['captainA']['username']}, choose Heads or Tails:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    match_col.update_one({"chat_id": chat_id}, {"$set": {"toss_msg_id": msg.message_id}})

# === TOSS CALLBACK ===
async def toss_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    match = match_col.find_one({"chat_id": chat_id})

    if not match or match["status"] != "setup":
        return

    user_id = query.from_user.id
    if user_id != match["captainA"]["user_id"]:
        await query.answer("Only Team A captain can choose toss.", show_alert=True)
        return

    user_choice = query.data.split("_")[1]
    actual = random.choice(["heads", "tails"])
    winner = "A" if user_choice == actual else "B"
    match_col.update_one({"chat_id": chat_id}, {"$set": {"toss_winner": winner}})

    toss_winner_cap = match["captainA"] if winner == "A" else match["captainB"]
    keyboard = [
        [
            InlineKeyboardButton("Bat", callback_data="choose_bat"),
            InlineKeyboardButton("Bowl", callback_data="choose_bowl")
        ]
    ]
    await query.edit_message_text(
        f"🪙 It's {actual.title()}!\n🏆 Team {winner} won the toss.\n"
        f"{toss_winner_cap['username']}, choose to Bat or Bowl:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# === BAT/BOWL CALLBACK ===
async def batbowl_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    match = match_col.find_one({"chat_id": chat_id})
    if not match: return

    user_id = query.from_user.id
    toss_winner = match.get("toss_winner")
    cap_id = match["captainA"]["user_id"] if toss_winner == "A" else match["captainB"]["user_id"]
    if user_id != cap_id:
        await query.answer("Only toss winner captain can choose.", show_alert=True)
        return

    choice = query.data.split("_")[1]
    match_col.update_one({"chat_id": chat_id}, {"$set": {"choice": choice}})
    await query.edit_message_text(f"🔧 Team {toss_winner} chose to {choice.title()} first!")

# === COMMENTARY/GIF ENGINE ===
commentary_pool = {
    0: ["Dot ball! Tight bowling.", "No run, well bowled!", "He defends it."],
    1: ["Quick single taken.", "They steal a run!", "Just a tap for one."],
    2: ["Good running between wickets!", "Double taken!", "Two runs with ease."],
    3: ["Excellent running! 3 runs.", "Triple taken, rare!", "A fumble allows three."],
    4: ["That's a boundary!", "Crisp four!", "Smashed to the ropes!"],
    6: ["What a six!", "Massive hit!", "Out of the park!"],
    "out": ["Clean bowled!", "Caught out!", "Gone! Big wicket!"]
}

gif_pool = {
    0: ["https://tenor.com/view/dotball1.gif", "https://tenor.com/view/dotball2.gif"],
    4: ["https://tenor.com/view/four1.gif", "https://tenor.com/view/four2.gif"],
    6: ["https://tenor.com/view/six1.gif", "https://tenor.com/view/six2.gif"],
    "out": ["https://tenor.com/view/out1.gif", "https://tenor.com/view/out2.gif"]
}

def get_random_commentary(event):
    return random.choice(commentary_pool.get(event, [""]))

def get_random_gif(event):
    return random.choice(gif_pool.get(event, []))
# === PLAYER INPUT HANDLING ===
valid_runs = ['0', '1', '2', '3', '4', '6']
valid_balls = {
    "Rs": 0,
    "Bouncer": 1,
    "Yorker": 2,
    "Short": 3,
    "Slower": 4,
    "Knuckle": 6
}

player_inputs = {}

async def dm_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    chat_id = update.effective_chat.id

    for match in match_col.find():
        if match.get("current_striker", {}).get("user_id") == user_id:
            if text in valid_runs:
                player_inputs[user_id] = int(text)
                await update.message.reply_text(f"✅ You chose {text}")
            else:
                await update.message.reply_text("❌ Invalid input. Choose from 0,1,2,3,4,6")
            return

        elif match.get("current_bowler", {}).get("user_id") == user_id:
            if text in valid_balls:
                player_inputs[user_id] = valid_balls[text]
                await update.message.reply_text(f"✅ You chose {text} ball")
            else:
                await update.message.reply_text("❌ Invalid input. Choose from Rs, Bouncer, Yorker, Short, Slower, Knuckle")
            return

# === BALL PROCESSING ENGINE ===
async def process_ball(context: ContextTypes.DEFAULT_TYPE, match):
    chat_id = match["chat_id"]
    striker = match["current_striker"]
    bowler = match["current_bowler"]
    striker_id = striker["user_id"]
    bowler_id = bowler["user_id"]

    if striker_id not in player_inputs or bowler_id not in player_inputs:
        return  # Wait for both

    run = player_inputs.pop(striker_id)
    ball = player_inputs.pop(bowler_id)

    event_msg = [f"Over {match['current_over']}.{match['ball_in_over'] + 1}"]
    await context.bot.send_message(chat_id, f"🏏 {event_msg[0]}")
    await asyncio.sleep(2)

    await context.bot.send_message(chat_id, f"🎯 {bowler['username']} bowls a {get_key_from_value(valid_balls, ball)}")
    await asyncio.sleep(2)

    if run == ball:
        # OUT
        match['wickets'] += 1
        msg = f"❌ {striker['username']} is OUT!"
        comment = get_random_commentary("out")
        gif = get_random_gif("out")
        match['current_batting_team']['score'] += 0
        match['ball_in_over'] += 1
    else:
        match['current_batting_team']['score'] += run
        msg = f"{striker['username']} scores {run} run(s)"
        comment = get_random_commentary(run)
        gif = get_random_gif(run) if run in [0, 4, 6] else None
        match['ball_in_over'] += 1
        if run % 2 == 1:
            # strike rotation
            match['current_striker'], match['current_non_striker'] = match['current_non_striker'], match['current_striker']

    await context.bot.send_message(chat_id, f"{comment}\n{msg}")
    if gif:
        await context.bot.send_animation(chat_id, gif)

    # Check over end
    if match['ball_in_over'] >= 6:
        match['current_over'] += 1
        match['ball_in_over'] = 0
        # swap striker for even runs at over end
        if run % 2 == 0:
            match['current_striker'], match['current_non_striker'] = match['current_non_striker'], match['current_striker']

    # Save updated match
    match_col.update_one({"chat_id": chat_id}, {"$set": match})

def get_key_from_value(d, val):
    for k, v in d.items():
        if v == val:
            return k
    return None
# === ADMIN/HOST UTILITY COMMANDS ===

@bot_cmd("retiredhurt")
async def retired_hurt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    match = match_col.find_one({"chat_id": chat_id})
    if not match: return

    args = context.args
    if not args or args[0].lower() not in ["strike", "non", "bowler"]:
        return await update.message.reply_text("Usage: /retiredhurt strike|non|bowler")

    key = args[0].lower()
    text = ""
    if key == "strike":
        match["retired_hurt"].append(match["current_striker"])
        text = f"{match['current_striker']['username']} has been retired hurt!"
        match["current_striker"] = {}
    elif key == "non":
        match["retired_hurt"].append(match["current_non_striker"])
        text = f"{match['current_non_striker']['username']} has been retired hurt!"
        match["current_non_striker"] = {}
    elif key == "bowler":
        match["retired_hurt_bowlers"].append(match["current_bowler"])
        text = f"{match['current_bowler']['username']} has been retired hurt after partial over!"
        match["current_bowler"] = {}

    match_col.update_one({"chat_id": chat_id}, {"$set": match})
    await update.message.reply_text(text)

@bot_cmd("retiredout")
async def retired_out(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    match = match_col.find_one({"chat_id": chat_id})
    if not match: return
    args = context.args
    if not args or args[0].lower() not in ["strike", "non"]:
        return await update.message.reply_text("Usage: /retiredout strike|non")

    if args[0].lower() == "strike":
        name = match["current_striker"]["username"]
        match["wickets"] += 1
        match["current_striker"] = {}
    else:
        name = match["current_non_striker"]["username"]
        match["wickets"] += 1
        match["current_non_striker"] = {}

    match_col.update_one({"chat_id": chat_id}, {"$set": match})
    await update.message.reply_text(f"❌ {name} retired out.")

@bot_cmd("bonus")
async def bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args or args[0] not in ["A", "B"]:
        return await update.message.reply_text("Usage: /bonus A/B runs")
    team_key = "team_a" if args[0] == "A" else "team_b"
    try:
        runs = int(args[1])
    except:
        return await update.message.reply_text("Invalid run amount.")
    match = match_col.find_one({"chat_id": update.effective_chat.id})
    match[team_key]["score"] += runs
    match_col.update_one({"chat_id": update.effective_chat.id}, {"$set": match})
    await update.message.reply_text(f"✅ {args[0]} team got +{runs} bonus runs")

@bot_cmd("penalty")
async def penalty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args or args[0] not in ["A", "B"]:
        return await update.message.reply_text("Usage: /penalty A/B runs")
    team_key = "team_a" if args[0] == "A" else "team_b"
    try:
        runs = int(args[1])
    except:
        return await update.message.reply_text("Invalid run amount.")
    match = match_col.find_one({"chat_id": update.effective_chat.id})
    match[team_key]["score"] -= runs
    match_col.update_one({"chat_id": update.effective_chat.id}, {"$set": match})
    await update.message.reply_text(f"⚠️ {args[0]} team got -{runs} penalty runs")

@bot_cmd("inningswap")
async def innings_swap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    match = match_col.find_one({"chat_id": chat_id})
    if not match: return
    match["innings"] = 2
    match["ball_in_over"] = 0
    match["current_over"] = 0
    match["wickets"] = 0
    match["current_striker"] = {}
    match["current_non_striker"] = {}
    match["current_bowler"] = {}
    match["retired_hurt"] = []
    match["retired_hurt_bowlers"] = []
    match["target"] = match["team_a"]["score"] + 1
    match["current_batting_team"] = match["team_b"]
    match_col.update_one({"chat_id": chat_id}, {"$set": match})
    await update.message.reply_text("🚨 Innings changed. Team B will now chase!")

@bot_cmd("hostchange")
async def host_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return
    member = await chat.get_member(user.id)
    if not member.status in ["administrator", "creator"]:
        return await update.message.reply_text("Only admins can become host during a match.")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm", callback_data=f"hostconfirm|{user.id}"),
         InlineKeyboardButton("❌ Cancel", callback_data="hostcancel")]
    ])
    await update.message.reply_text(f"{user.first_name}, do you want to become the new host?", reply_markup=kb)

@callback_handler
async def host_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("hostconfirm"):
        user_id = int(data.split("|")[1])
        user = await context.bot.get_chat_member(query.message.chat.id, user_id)
        match_col.update_one({"chat_id": query.message.chat.id}, {"$set": {"host": user.user.id}})
        await query.edit_message_text(f"✅ {user.user.first_name} is now the new host!")
    elif data == "hostcancel":
        await query.edit_message_text("❌ Host change cancelled.")

@bot_cmd("finish")
async def finish_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm", callback_data="finish_yes"),
         InlineKeyboardButton("❌ Cancel", callback_data="finish_no")]
    ])
    await update.message.reply_text("Are you sure you want to end the match?", reply_markup=kb)

@callback_handler
async def finish_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "finish_yes":
        chat_id = query.message.chat.id
        match = match_col.find_one({"chat_id": chat_id})
        if not match: return
        summary = f"🏁 Match Ended!\n\n"
        summary += f"Team A: {match['team_a']['score']} runs\n"
        summary += f"Team B: {match['team_b']['score']} runs\n"
        if match["team_b"]["score"] >= match["target"]:
            summary += f"🎉 Team B won by {10 - match['wickets']} wickets!"
        else:
            margin = match["target"] - 1 - match["team_b"]["score"]
            summary += f"🏆 Team A won by {margin} runs!"
        await query.edit_message_text(summary)
        match_col.delete_one({"chat_id": chat_id})
    elif data == "finish_no":
        await query.edit_message_text("❌ Match finish cancelled.")
# === GUIDE / HELP COMMAND ===

@bot_cmd("guide")
async def guide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📘 *CCL Group Match Bot Guide*\n\n"
        "*Setup Commands:*\n"
        "/cclgroup - Start group match setup\n"
        "/addA @user - Add player to Team A\n"
        "/addB @user - Add player to Team B\n"
        "/removeA 1 - Remove Team A's 1st player\n"
        "/removeB 2 - Remove Team B's 2nd player\n"
        "/CapA 1 - Make Team A player 1 the captain\n"
        "/CapB 2 - Make Team B player 2 the captain\n"
        "/setovers 5 - Set number of overs\n"
        "/team - Show team list\n"
        "/toss - Start toss (auto toss choice prompts)\n\n"
        "*Match Control:*\n"
        "/bat 1 - Set striker/non-striker (by index)\n"
        "/bowl 2 - Set bowler (by index)\n"
        "/inningswap - Start 2nd innings\n"
        "/retiredhurt strike/non/bowler - Replace without losing wicket\n"
        "/retiredout strike/non - Remove batsman with wicket\n"
        "/bonus A 4 - Add 4 runs to Team A\n"
        "/penalty B 2 - Deduct 2 runs from Team B\n"
        "/hostchange - GC admins can take over as host\n"
        "/endmatch - End match with confirmation\n"
        "/finish - Use at end of second innings (if chase fails)\n\n"
        "*During Match:*\n"
        "/score - View full scoreboard\n"
        "/bat LMS - Allow only one player to bat\n"
        "/guide - Show this guide"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# === REGISTER HANDLER ===

@bot_cmd("register")
async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_data = users_col.find_one({"user_id": user.id})
    if user_data:
        return await update.message.reply_text("You're already registered!")
    users_col.insert_one({
        "user_id": user.id,
        "username": user.username or user.first_name,
        "coins": 0,
        "games_played": 0,
        "wins": 0
    })
    await update.message.reply_text("✅ Registered successfully!")

# === START COMMAND ===

@bot_cmd("start")
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome to CCL Group Match Bot! Use /guide to view all commands.")

# === RUN BOT ===

if __name__ == "__main__":
    app.run_polling()
