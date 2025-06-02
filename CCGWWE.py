import asyncio
import random
import os
from datetime import datetime
from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, ChatAction
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
)
from motor.motor_asyncio import AsyncIOMotorClient

# ─────────────────────
# CONFIGURATION
# ─────────────────────
BOT_TOKEN = "8156231369:AAHDFvjD9Aur9y5QjB5YWzvCQp7bUdLuuEc"
MONGO_URI = "mongodb://mongo:GhpHMiZizYnvJfKIQKxoDbRyzBCpqEyC@mainline.proxy.rlwy.net:54853"

client = AsyncIOMotorClient(MONGO_URI)
db = client.ccl_hand_cricket

# ─────────────────────
# UTILITIES
# ─────────────────────

def mention(user):
    return f"[{user.first_name}](tg://user?id={user.id})"

async def send_typing_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

# ─────────────────────
# COMMANDS: /start /register /profile
# ─────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_typing_action(update, context)
    await update.message.reply_text(
        "🏏 *Welcome to CCL Hand Cricket Bot!*\n"
        "Use /register to get started with 4000 coins.\n"
        "Use /profile anytime to check your progress.",
        parse_mode="Markdown"
    )

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    username = user.username or user.first_name

    existing = await db.users.find_one({"_id": uid})
    if existing:
        await update.message.reply_text("✅ You are already registered.")
        return

    await db.users.insert_one({
        "_id": uid,
        "username": username,
        "coins": 4000,
        "matches_played": 0,
        "matches_won": 0
    })

    await update.message.reply_text(
        f"🎉 Registered successfully, {username}!\n"
        f"You've been credited with 💰 *4000 coins*!",
        parse_mode="Markdown"
    )

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id

    user_data = await db.users.find_one({"_id": uid})
    if not user_data:
        await update.message.reply_text("❌ You're not registered. Use /register first.")
        return

    await update.message.reply_text(
        f"📋 *Profile of {user_data['username']}*\n"
        f"💰 Coins: {user_data['coins']}\n"
        f"🏏 Matches Played: {user_data['matches_played']}\n"
        f"🏆 Matches Won: {user_data['matches_won']}",
        parse_mode="Markdown"
    )

# ─────────────────────
# MAIN FUNCTION
# ─────────────────────

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("register", register))
    app.add_handler(CommandHandler("profile", profile))

    print("✅ Bot is running...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
# ─────────────────────
# MATCH MANAGEMENT STRUCTURE
# ─────────────────────

# match_data stores active match info by chat_id
match_data = {}

# ─────────────────────
# /cclgroup - Start a new match in a group
# ─────────────────────

async def cclgroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if chat_id in match_data:
        await update.message.reply_text("⚠️ A match is already in progress in this group.")
        return

    match_data[chat_id] = {
        "host": user_id,
        "team_A": [],
        "team_B": [],
        "cap_A": None,
        "cap_B": None,
        "overs": None,
        "innings": 1,
        "batting_team": None,
        "bowling_team": None,
        "current_over": [],
        "batsmen": {},
        "bowler": None,
        "score": {
            "A": {"runs": 0, "wickets": 0, "balls": 0},
            "B": {"runs": 0, "wickets": 0, "balls": 0}
        },
        "current_striker": None,
        "non_striker": None,
        "last_bowler": None,
        "playing": False
    }

    await update.message.reply_text(
        "🆕 New CCL match created!\n"
        f"Host: {mention(update.effective_user)}\n\n"
        "Use /add_A @user or /add_B @user to add players.\n"
        "Then assign captains using /cap_A and /cap_B.\n"
        "Set overs using /setovers <number>.\n"
        "Start match with /startmatch.",
        parse_mode="Markdown"
    )

# ─────────────────────
# /add_A & /add_B - Add players to teams
# ─────────────────────

async def add_player(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    command = update.message.text.split()[0]

    if chat_id not in match_data:
        await update.message.reply_text("❌ No match exists in this group. Use /cclgroup first.")
        return

    match = match_data[chat_id]
    team_key = "team_A" if command == "/add_A" else "team_B"
    other_key = "team_B" if team_key == "team_A" else "team_A"

    if user_id != match["host"]:
        await update.message.reply_text("❌ Only the match host can add players.")
        return

    if len(context.args) != 1 or not context.args[0].startswith("@"):
        await update.message.reply_text("Usage: /add_A @username or /add_B @username")
        return

    username = context.args[0].lstrip("@")

    # Prevent adding duplicates
    for player in match["team_A"] + match["team_B"]:
        if player["username"] == username:
            await update.message.reply_text("⚠️ Player already in one of the teams.")
            return

    if len(match[team_key]) >= 8:
        await update.message.reply_text("⚠️ Maximum 8 players allowed per team.")
        return

    player_num = len(match[team_key]) + 1
    match[team_key].append({"username": username, "number": player_num})
    await update.message.reply_text(f"✅ Added @{username} to Team {'A' if team_key == 'team_A' else 'B'} as player #{player_num}.")

# ─────────────────────
# /teams - Show team composition
# ─────────────────────

async def show_teams(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if chat_id not in match_data:
        await update.message.reply_text("❌ No match in this group.")
        return

    match = match_data[chat_id]
    team_a = "\n".join([f"{p['number']}. @{p['username']}" for p in match['team_A']]) or "None"
    team_b = "\n".join([f"{p['number']}. @{p['username']}" for p in match['team_B']]) or "None"

    await update.message.reply_text(
        f"📢 *Current Teams:*\n\n"
        f"🏏 *Team A:*\n{team_a}\n\n"
        f"🏏 *Team B:*\n{team_b}",
        parse_mode="Markdown"
    )

# ─────────────────────
# /cap_A & /cap_B - Assign captains
# ─────────────────────

async def assign_captain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    command = update.message.text.split()[0]
    team_key = "team_A" if command == "/cap_A" else "team_B"

    if chat_id not in match_data:
        await update.message.reply_text("❌ No match exists here.")
        return

    match = match_data[chat_id]
    if user_id != match["host"]:
        await update.message.reply_text("❌ Only the host can assign captains.")
        return

    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /cap_A <number> or /cap_B <number>")
        return

    number = int(context.args[0])
    team = match[team_key]
    player = next((p for p in team if p["number"] == number), None)

    if not player:
        await update.message.reply_text("❌ Invalid player number.")
        return

    match["cap_A" if team_key == "team_A" else "cap_B"] = player["username"]
    await update.message.reply_text(f"🎖 Captain assigned: @{player['username']} for Team {'A' if team_key == 'team_A' else 'B'}.")

# ─────────────────────
# /setovers - Set overs
# ─────────────────────

async def set_overs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if chat_id not in match_data:
        await update.message.reply_text("❌ No match in this group.")
        return

    match = match_data[chat_id]
    if user_id != match["host"]:
        await update.message.reply_text("❌ Only host can set overs.")
        return

    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /setovers <1-20>")
        return

    overs = int(context.args[0])
    if not (1 <= overs <= 20):
        await update.message.reply_text("⚠️ Overs must be between 1 and 20.")
        return

    match["overs"] = overs
    await update.message.reply_text(f"✅ Match overs set to {overs}.")

# ─────────────────────
# Attach these handlers
# ─────────────────────

def attach_team_handlers(app):
    app.add_handler(CommandHandler("cclgroup", cclgroup))
    app.add_handler(CommandHandler("add_A", add_player))
    app.add_handler(CommandHandler("add_B", add_player))
    app.add_handler(CommandHandler("teams", show_teams))
    app.add_handler(CommandHandler("cap_A", assign_captain))
    app.add_handler(CommandHandler("cap_B", assign_captain))
    app.add_handler(CommandHandler("setovers", set_overs))
# ─────────────────────
# /startmatch - Validate and start the match
# ─────────────────────

async def startmatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if chat_id not in match_data:
        await update.message.reply_text("❌ No match found. Use /cclgroup first.")
        return

    match = match_data[chat_id]
    if user_id != match["host"]:
        await update.message.reply_text("❌ Only the host can start the match.")
        return

    # Validation
    if not match["team_A"] or not match["team_B"]:
        await update.message.reply_text("⚠️ Both teams must have at least one player.")
        return

    if not match["cap_A"] or not match["cap_B"]:
        await update.message.reply_text("⚠️ Assign captains for both teams using /cap_A and /cap_B.")
        return

    if not match["overs"]:
        await update.message.reply_text("⚠️ Set the number of overs using /setovers.")
        return

    # Manual toss instruction
    await update.message.reply_text(
        "🟡 Match is ready!\n\n"
        "Please now assign which team will bat and bowl.\n"
        "Use the following commands:\n"
        "`/batting_team A|B`\n"
        "`/bowling_team A|B`",
        parse_mode="Markdown"
    )

# ─────────────────────
# /batting_team & /bowling_team - Manually set batting order
# ─────────────────────

async def set_batting_team(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _set_team_role(update, context, role="batting")

async def set_bowling_team(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _set_team_role(update, context, role="bowling")

async def _set_team_role(update: Update, context: ContextTypes.DEFAULT_TYPE, role: str):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if chat_id not in match_data:
        await update.message.reply_text("❌ No match setup here.")
        return

    match = match_data[chat_id]
    if user_id != match["host"]:
        await update.message.reply_text("❌ Only host can assign team roles.")
        return

    if len(context.args) != 1 or context.args[0].upper() not in ("A", "B"):
        await update.message.reply_text(f"Usage: /{role}_team A or B")
        return

    team = context.args[0].upper()
    match[f"{role}_team"] = team

    await update.message.reply_text(f"✅ Team {team} set as the {role} team.")

    # Start game if both roles are set
    if match.get("batting_team") and match.get("bowling_team"):
        await update.message.reply_text(
            "🎉 Batting and bowling teams are set!\n"
            f"🏏 *Team {match['batting_team']} will bat first.*\n\n"
            "Host, now assign striker and non-striker with:\n"
            "`/bat <striker_num> <non_striker_num>`\n"
            "And assign bowler with:\n"
            "`/bowl <bowler_num>`",
            parse_mode="Markdown"
        )

# ─────────────────────
# /bat - Assign striker and non-striker
# ─────────────────────

async def assign_batsmen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if chat_id not in match_data:
        await update.message.reply_text("❌ No match.")
        return

    match = match_data[chat_id]
    if user_id != match["host"]:
        await update.message.reply_text("❌ Only host can assign batsmen.")
        return

    if len(context.args) != 2 or not all(arg.isdigit() for arg in context.args):
        await update.message.reply_text("Usage: /bat <striker_num> <non_striker_num>")
        return

    batting_team = match["batting_team"]
    team = match["team_A"] if batting_team == "A" else match["team_B"]

    striker = next((p for p in team if p["number"] == int(context.args[0])), None)
    non_striker = next((p for p in team if p["number"] == int(context.args[1])), None)

    if not striker or not non_striker:
        await update.message.reply_text("❌ Invalid player numbers.")
        return

    if striker["username"] == non_striker["username"]:
        await update.message.reply_text("❌ Striker and non-striker must be different.")
        return

    match["current_striker"] = striker
    match["non_striker"] = non_striker

    await update.message.reply_text(
        f"🏏 Striker: @{striker['username']}\n"
        f"👬 Non-Striker: @{non_striker['username']}"
    )

# ─────────────────────
# /bowl - Assign bowler
# ─────────────────────

async def assign_bowler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if chat_id not in match_data:
        await update.message.reply_text("❌ No match.")
        return

    match = match_data[chat_id]
    if user_id != match["host"]:
        await update.message.reply_text("❌ Only host can assign bowler.")
        return

    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /bowl <bowler_num>")
        return

    bowling_team = match["bowling_team"]
    team = match["team_A"] if bowling_team == "A" else match["team_B"]
    number = int(context.args[0])
    player = next((p for p in team if p["number"] == number), None)

    if not player:
        await update.message.reply_text("❌ Invalid bowler number.")
        return

    if match.get("last_bowler") == player["username"]:
        await update.message.reply_text("🚫 Bowler can't bowl two consecutive overs.")
        return

    match["bowler"] = player
    match["last_bowler"] = player["username"]
    match["playing"] = True

    await update.message.reply_text(
        f"🎯 Bowler for this over: @{player['username']}\n\n"
        "Now, striker and bowler will be tagged in DM for each ball."
    )

# ─────────────────────
# Attach these handlers
# ─────────────────────

def attach_start_handlers(app):
    app.add_handler(CommandHandler("startmatch", startmatch))
    app.add_handler(CommandHandler("batting_team", set_batting_team))
    app.add_handler(CommandHandler("bowling_team", set_bowling_team))
    app.add_handler(CommandHandler("bat", assign_batsmen))
    app.add_handler(CommandHandler("bowl", assign_bowler))
import random
import asyncio

# ────────────────────────────────
# Commentary phrases by runs
# ────────────────────────────────

commentary_zero = [
    "Clean bowled! What a delivery!",
    "Dot ball, good line and length.",
    "No run, nice bowling tight in line.",
    "Good defensive shot, dot ball."
]

commentary_one = [
    "Quick single taken!",
    "Smart running between the wickets.",
    "Pushed to the off side for a single.",
    "Quick feet and a single."
]

commentary_two = [
    "Nice placement for two runs.",
    "Good running, they get two.",
    "Guided to the leg side for a couple.",
    "Well timed, and they scamper two."
]

commentary_three = [
    "Three runs! That’s a rare one.",
    "Excellent running for three!",
    "Pushed to the deep, they get three.",
    "Great awareness, three runs taken."
]

commentary_four = [
    "What a shot! That’s a four! 🏏",
    "Beautiful boundary through the covers.",
    "Crushed it! Four runs.",
    "Lovely timing, four to the boundary."
]

commentary_six = [
    "Arun Smoked it For A Six 🔥🔥",
    "Massive hit! Six runs!",
    "Cleared the ropes with ease, SIX!",
    "What a slog! Six to the boundary!"
]

# ────────────────────────────────
# Half-century & century congratulation messages
# ────────────────────────────────

async def check_milestones(player, runs, chat_id, context):
    if runs == 50:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🎉 Congratulations @{player['username']} on your Half-Century! 🏆"
        )
    elif runs == 100:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🌟 AMAZING! @{player['username']} just scored a Century! 🎉🏏"
        )

# ────────────────────────────────
# GIF URLs for runs 0,4,6
# ────────────────────────────────

GIFS = {
    0: "https://media.giphy.com/media/l3q2IpFhH5y1Lgo2w/giphy.gif",    # dot ball gif
    4: "https://media.giphy.com/media/3oEjI6SIIHBdRxXI40/giphy.gif",  # four gif
    6: "https://media.giphy.com/media/5GoVLqeAOo6PK/giphy.gif"         # six gif
}

# ────────────────────────────────
# Tag striker and bowler in DM for each ball
# ────────────────────────────────

async def prompt_ball_choices(chat_id, context):
    match = match_data[chat_id]
    striker = match.get("current_striker")
    bowler = match.get("bowler")
    if not striker or not bowler:
        return

    bot = context.bot

    # DM striker for runs input
    try:
        await bot.send_message(
            chat_id=striker["user_id"],
            text="🏏 Your turn to bat! Send runs (0,1,2,3,4,6):"
        )
    except Exception:
        # User may not have started bot in private chat
        await bot.send_message(chat_id=chat_id, text=f"❗ @{striker['username']} please start a private chat with me to play.")

    # DM bowler for variation input
    try:
        await bot.send_message(
            chat_id=bowler["user_id"],
            text="🎯 Your turn to bowl! Send variation: rs, bouncer, yorker, short, slower, knuckle"
        )
    except Exception:
        await bot.send_message(chat_id=chat_id, text=f"❗ @{bowler['username']} please start a private chat with me to play.")

# ────────────────────────────────
# Helper to validate batsman input
# ────────────────────────────────

valid_batsman_inputs = {"0", "1", "2", "3", "4", "6"}
valid_bowler_variations = {
    "rs": 0,
    "bouncer": 1,
    "yorker": 2,
    "short": 3,
    "slower": 4,
    "knuckle": 6
}

# ────────────────────────────────
# Handle batsman DM message
# ────────────────────────────────

async def batsman_dm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # Find the match where this user is striker
    for chat_id, match in match_data.items():
        striker = match.get("current_striker")
        bowler = match.get("bowler")
        if striker and striker["user_id"] == user_id and match.get("playing") and not match.get("batsman_choice"):
            if text not in valid_batsman_inputs:
                await update.message.reply_text("❌ Invalid runs. Send 0,1,2,3,4 or 6.")
                return
            match["batsman_choice"] = int(text)
            # Check if bowler already sent choice for this ball
            if "bowler_choice" in match:
                await process_ball(chat_id, context)
            else:
                await update.message.reply_text("⏳ Waiting for bowler's delivery choice...")
            return

    await update.message.reply_text("⚠️ You are not the current striker or no active ball to play.")

# ────────────────────────────────
# Handle bowler DM message
# ────────────────────────────────

async def bowler_dm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip().lower()

    # Find the match where this user is bowler
    for chat_id, match in match_data.items():
        bowler = match.get("bowler")
        if bowler and bowler["user_id"] == user_id and match.get("playing") and not match.get("bowler_choice"):
            if text not in valid_bowler_variations:
                await update.message.reply_text("❌ Invalid variation. Send one of rs, bouncer, yorker, short, slower, knuckle.")
                return
            match["bowler_choice"] = valid_bowler_variations[text]
            # Check if batsman already sent choice for this ball
            if "batsman_choice" in match:
                await process_ball(chat_id, context)
            else:
                await update.message.reply_text("⏳ Waiting for batsman's run choice...")
            return

    await update.message.reply_text("⚠️ You are not the current bowler or no active ball to play.")

# ────────────────────────────────
# Process the completed ball with choices from batsman and bowler
# ────────────────────────────────

async def process_ball(chat_id, context):
    match = match_data[chat_id]
    striker = match["current_striker"]
    non_striker = match["non_striker"]
    bowler = match["bowler"]
    batsman_choice = match.pop("batsman_choice")
    bowler_choice = match.pop("bowler_choice")

    ball_number = match.get("ball_number", 1)
    over_number = match.get("over_number", 1)

    # Commentary messages
    bot = context.bot

    # Ball header
    await bot.send_message(chat_id=chat_id, text=f"⏳ Over {over_number}, Ball {ball_number}")

    await asyncio.sleep(2)

    # Bowler variation message
    variation_names = {
        0: "Regular ball",
        1: "Bouncer",
        2: "Yorker",
        3: "Short ball",
        4: "Slower ball",
        6: "Knuckle ball"
    }
    variation_text = variation_names.get(bowler_choice, "Delivery")
    await bot.send_message(chat_id=chat_id, text=f"{bowler['username'].title()} bowls a {variation_text}")

    await asyncio.sleep(4)

    # Determine outcome: if batsman_choice == 0 and bowler_choice == 0 => wicket
    is_wicket = (batsman_choice == 0 and bowler_choice == 0)

    # Compose ball result commentary
    if is_wicket:
        commentary = f"💥 WICKET! @{striker['username']} is out!"
    else:
        # Pick commentary based on runs scored
        if batsman_choice == 0:
            commentary = random.choice(commentary_zero)
        elif batsman_choice == 1:
            commentary = random.choice(commentary_one)
        elif batsman_choice == 2:
            commentary = random.choice(commentary_two)
        elif batsman_choice == 3:
            commentary = random.choice(commentary_three)
        elif batsman_choice == 4:
            commentary = random.choice(commentary_four)
        elif batsman_choice == 6:
            commentary = random.choice(commentary_six)
        else:
            commentary = "Good play."

    # Add player mentions
    commentary = f"🏏 @{striker['username']} to @{bowler['username']}\n" + commentary

    await bot.send_message(chat_id=chat_id, text=commentary)

    # Send GIF if run is 0,4,6
    if batsman_choice in GIFS and not is_wicket:
        await bot.send_animation(chat_id=chat_id, animation=GIFS[batsman_choice])

    # Update stats
    update_stats(match, striker, bowler, batsman_choice, is_wicket)

    # Check milestones
    total_runs = striker.get("runs", 0)
    await check_milestones(striker, total_runs, chat_id, context)

    # Ball & over count update
    ball_number += 1
    if ball_number > 6:
        ball_number = 1
        over_number += 1
        await bot.send_message(chat_id=chat_id, text=f"🟢 Over {over_number - 1} completed!")

        # Strike rotates at over end
        match["current_striker"], match["non_striker"] = match["non_striker"], match["current_striker"]

        # Inform host to assign new bowler
        host_mention = f"[Host](tg://user?id={match['host']})"
        await bot.send_message(chat_id=chat_id,
                               text=f"{host_mention}, please assign a new bowler with /bowl <number>",
                               parse_mode="Markdown")

    match["ball_number"] = ball_number
    match["over_number"] = over_number

    # Strike rotates on odd runs except last ball of over
    if ball_number != 1 and batsman_choice % 2 == 1:
        match["current_striker"], match["non_striker"] = match["non_striker"], match["current_striker"]

    # Clear playing flag if innings complete (simplified)
    if over_number > match["overs"]:
        await bot.send_message(chat_id=chat_id, text="🏁 Innings completed! Host can swap innings with /inningswap")
        match["playing"] = False
        return

    # Prompt next ball choices
    await prompt_ball_choices(chat_id, context)

# ────────────────────────────────
# Update player stats after each ball
# ────────────────────────────────

def update_stats(match, striker, bowler, runs, wicket):
    # Update striker runs
    striker["runs"] = striker.get("runs", 0) + runs
    striker["balls"] = striker.get("balls", 0) + 1
    # Update bowler balls and wickets
    bowler["balls"] = bowler.get("balls", 0) + 1
    if wicket:
        bowler["wickets"] = bowler.get("wickets", 0) + 1

    # Update team score and wickets
    batting_team = match["batting_team"]
    if batting_team == "A":
        match["score_A"] += runs
        if wicket:
            match["wickets_A"] += 1
    else:
        match["score_B"] += runs
        if wicket:
            match["wickets_B"] += 1
from PIL import Image, ImageDraw, ImageFont
import io

# ────────────────────────────────
# Innings swap command with confirm/cancel buttons
# ────────────────────────────────

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

async def innings_swap_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if chat_id not in match_data:
        await update.message.reply_text("No active match in this chat.")
        return

    match = match_data[chat_id]

    if user_id != match["host"]:
        await update.message.reply_text("Only the host can swap innings.")
        return

    if not match.get("playing", False):
        keyboard = [
            [
                InlineKeyboardButton("Confirm Innings Swap", callback_data="confirm_innings_swap"),
                InlineKeyboardButton("Cancel", callback_data="cancel_innings_swap")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Are you sure you want to swap innings? This will start the next innings.",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text("Match is currently playing. You can only swap innings after innings end.")

async def innings_swap_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id

    if chat_id not in match_data:
        await query.edit_message_text("No active match found.")
        return

    match = match_data[chat_id]

    if query.data == "confirm_innings_swap":
        # Swap teams
        match["batting_team"], match["bowling_team"] = match["bowling_team"], match["batting_team"]
        match["over_number"] = 1
        match["ball_number"] = 1
        match["playing"] = True
        match["wickets_A"] = 0
        match["wickets_B"] = 0
        # Reset player stats for second innings
        for player in match["team_A"]:
            player["runs"] = 0
            player["balls"] = 0
        for player in match["team_B"]:
            player["runs"] = 0
            player["balls"] = 0

        await query.edit_message_text("✅ Innings swapped. The second innings has started!")
        # Inform host to set striker, non-striker, and bowler again
        host_mention = f"[Host](tg://user?id={match['host']})"
        await context.bot.send_message(chat_id=chat_id,
                                       text=f"{host_mention}, please assign striker and non-striker with /bat <striker_num> <non_striker_num> and bowler with /bowl <bowler_num>",
                                       parse_mode="Markdown")

    else:
        await query.edit_message_text("❌ Innings swap cancelled.")

# ────────────────────────────────
# Bonus and Penalty commands
# ────────────────────────────────

async def bonus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if chat_id not in match_data:
        await update.message.reply_text("No active match in this chat.")
        return

    match = match_data[chat_id]
    if user_id != match["host"]:
        await update.message.reply_text("Only the host can add bonus runs.")
        return

    args = context.args
    if len(args) != 2 or args[0] not in ["A", "B"] or not args[1].isdigit():
        await update.message.reply_text("Usage: /bonus <A|B> <runs>")
        return

    team = args[0]
    runs = int(args[1])
    if runs <= 0:
        await update.message.reply_text("Bonus runs must be positive.")
        return

    if team == "A":
        match["score_A"] += runs
    else:
        match["score_B"] += runs

    await update.message.reply_text(f"✅ Added {runs} bonus runs to Team {team}.")

async def penalty_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if chat_id not in match_data:
        await update.message.reply_text("No active match in this chat.")
        return

    match = match_data[chat_id]
    if user_id != match["host"]:
        await update.message.reply_text("Only the host can deduct penalty runs.")
        return

    args = context.args
    if len(args) != 2 or args[0] not in ["A", "B"] or not args[1].isdigit():
        await update.message.reply_text("Usage: /penalty <A|B> <runs>")
        return

    team = args[0]
    runs = int(args[1])
    if runs <= 0:
        await update.message.reply_text("Penalty runs must be positive.")
        return

    if team == "A":
        match["score_A"] = max(0, match["score_A"] - runs)
    else:
        match["score_B"] = max(0, match["score_B"] - runs)

    await update.message.reply_text(f"✅ Deducted {runs} penalty runs from Team {team}.")

# ────────────────────────────────
# /score command: live score
# ────────────────────────────────

async def score_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if chat_id not in match_data:
        await update.message.reply_text("No active match in this chat.")
        return

    match = match_data[chat_id]

    text = (
        f"🏏 *Current Score*\n"
        f"Team A: {match['score_A']}/{match['wickets_A']} in {match['over_number']-1}.{match.get('ball_number', 0)-1} overs\n"
        f"Team B: {match['score_B']}/{match['wickets_B']} in {match.get('second_innings_overs', 0)} overs\n"
        f"Batting Team: Team {match['batting_team']}\n"
        f"Bowling Team: Team {match['bowling_team']}"
    )

    await update.message.reply_text(text, parse_mode="Markdown")

# ────────────────────────────────
# /endmatch command: ends match and sends scoreboard image
# ────────────────────────────────

async def endmatch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if chat_id not in match_data:
        await update.message.reply_text("No active match in this chat.")
        return

    match = match_data[chat_id]

    if user_id != match["host"]:
        await update.message.reply_text("Only the host can end the match.")
        return

    # Compose final result text
    score_a = match["score_A"]
    wickets_a = match["wickets_A"]
    score_b = match["score_B"]
    wickets_b = match["wickets_B"]

    if score_a > score_b:
        winner = "Team A"
    elif score_b > score_a:
        winner = "Team B"
    else:
        winner = "Match Drawn"

    final_text = (
        f"🏁 Match ended!\n"
        f"Team A: {score_a}/{wickets_a}\n"
        f"Team B: {score_b}/{wickets_b}\n"
        f"Result: {winner}"
    )

    await update.message.reply_text(final_text)

    # Generate scoreboard image
    image_bytes = generate_scoreboard_image(match)
    await context.bot.send_photo(chat_id=chat_id, photo=image_bytes)

    # Cleanup match data
    del match_data[chat_id]

# ────────────────────────────────
# Scoreboard image generation with Pillow
# ────────────────────────────────

def generate_scoreboard_image(match):
    width, height = 600, 400
    background_color = (30, 30, 30)
    text_color = (255, 255, 255)

    img = Image.new("RGB", (width, height), color=background_color)
    draw = ImageDraw.Draw(img)

    # Load a font (adjust path as needed)
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    try:
        font = ImageFont.truetype(font_path, 20)
        font_large = ImageFont.truetype(font_path, 30)
    except:
        font = ImageFont.load_default()
        font_large = ImageFont.load_default()

    # Title
    draw.text((width//2 - 100, 20), "CCL Hand Cricket Scoreboard", fill=text_color, font=font_large)

    # Team A details
    draw.text((50, 80), f"Team A:", fill=text_color, font=font)
    draw.text((50, 110), f"Score: {match['score_A']}/{match['wickets_A']}", fill=text_color, font=font)
    draw.text((50, 140), f"Overs: {match.get('over_number', 1)-1}.{match.get('ball_number', 1)-1}", fill=text_color, font=font)

    # Team B details
    draw.text((350, 80), f"Team B:", fill=text_color, font=font)
    draw.text((350, 110), f"Score: {match['score_B']}/{match['wickets_B']}", fill=text_color, font=font)
    draw.text((350, 140), f"Overs: {match.get('second_innings_overs', 0)}", fill=text_color, font=font)

    # Result
    if match["score_A"] > match["score_B"]:
        result_text = "Team A Won!"
    elif match["score_B"] > match["score_A"]:
        result_text = "Team B Won!"
    else:
        result_text = "Match Drawn"

    draw.text((width//2 - 80, 300), result_text, fill=(0, 255, 0), font=font_large)

    # Convert to bytes
    bio = io.BytesIO()
    bio.name = "scoreboard.png"
    img.save(bio, "PNG")
    bio.seek(0)
    return bio
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# ────────────────────────────────
# Add players mid-match (host only)
#/add_A and /add_B commands supporting mid-match additions
# ────────────────────────────────

async def add_player_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    message = update.message.text
    cmd = message.split()[0]
    team_letter = None
    if cmd == "/add_A":
        team_letter = "A"
    elif cmd == "/add_B":
        team_letter = "B"
    else:
        await update.message.reply_text("Invalid command.")
        return

    if chat_id not in match_data:
        await update.message.reply_text("No active match in this chat.")
        return

    match = match_data[chat_id]

    if user_id != match["host"]:
        await update.message.reply_text("Only the host can add players.")
        return

    if len(context.args) != 1:
        await update.message.reply_text(f"Usage: {cmd} @username")
        return

    username = context.args[0]
    if not username.startswith("@"):
        await update.message.reply_text("Please specify a valid username starting with @")
        return

    # Check if username already in either team
    all_players = [p["username"] for p in match["team_A"]] + [p["username"] for p in match["team_B"]]
    if username in all_players:
        await update.message.reply_text(f"{username} is already in a team.")
        return

    team_key = f"team_{team_letter}"
    if len(match[team_key]) >= 8:
        await update.message.reply_text(f"Team {team_letter} already has 8 players, cannot add more.")
        return

    # Add player with default stats
    match[team_key].append({
        "username": username,
        "runs": 0,
        "balls": 0,
        "out": False,
    })

    await update.message.reply_text(f"✅ Added {username} to Team {team_letter}.")

    # Inform host/player to assign if match ongoing
    if match.get("playing", False):
        await update.message.reply_text("Note: Please update batting order or bowler assignments if needed.")

# ────────────────────────────────
# Host change voting system
# /changehost initiates vote
# 50% of players must vote to remove current host
# Anyone not in players can become host after removal
# ────────────────────────────────

host_votes = defaultdict(set)  # chat_id: set of user_ids who voted to remove host

async def changehost_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if chat_id not in match_data:
        await update.message.reply_text("No active match in this chat.")
        return

    match = match_data[chat_id]
    if user_id == match["host"]:
        await update.message.reply_text("You are already the host.")
        return

    # Check if user is in players
    all_players = [p["username"].lstrip("@") for p in match["team_A"]] + [p["username"].lstrip("@") for p in match["team_B"]]
    user_username = update.effective_user.username
    if user_username is None:
        await update.message.reply_text("Please set a Telegram username in your profile to use this command.")
        return

    if user_username.lower() not in [x.lower() for x in all_players]:
        # User not player, can become host instantly if current host removed by vote
        if len(host_votes[chat_id]) >= (len(all_players) + 1) // 2:
            old_host_id = match["host"]
            match["host"] = user_id
            host_votes.pop(chat_id, None)
            await update.message.reply_text(f"{update.effective_user.mention_html()} is now the new host (previous host removed by vote).",
                                            parse_mode="HTML")
            return
        else:
            await update.message.reply_text("Current host has not been removed by vote yet. Players must vote first.")
            return

    # User is a player, cast vote
    if user_id in host_votes[chat_id]:
        await update.message.reply_text("You have already voted to remove the host.")
        return

    host_votes[chat_id].add(user_id)

    total_players = len(all_players)
    votes = len(host_votes[chat_id])
    needed_votes = (total_players + 1) // 2  # 50% rounded up

    await update.message.reply_text(f"Vote to remove host recorded ({votes}/{needed_votes} votes).")

    if votes >= needed_votes:
        old_host_id = match["host"]
        match["host"] = None  # Temporarily no host until a new one assigned
        host_votes.pop(chat_id, None)
        await update.message.reply_text("Host has been removed! Anyone not in players can now become host by sending /behost.")

async def behost_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if chat_id not in match_data:
        await update.message.reply_text("No active match in this chat.")
        return

    match = match_data[chat_id]

    if match.get("host") is not None:
        await update.message.reply_text("There is already a host assigned.")
        return

    # Check if user is NOT in players
    all_players = [p["username"].lstrip("@") for p in match["team_A"]] + [p["username"].lstrip("@") for p in match["team_B"]]
    user_username = update.effective_user.username
    if user_username is None:
        await update.message.reply_text("Please set a Telegram username in your profile to become host.")
        return

    if user_username.lower() in [x.lower() for x in all_players]:
        await update.message.reply_text("Players cannot become host right now. Wait for host to be assigned by vote.")
        return

    match["host"] = user_id
    await update.message.reply_text(f"{update.effective_user.mention_html()} is now the host of this match.", parse_mode="HTML")

# ────────────────────────────────
# Helper function: Mention player by number
# ────────────────────────────────

def mention_player_by_number(match, team_letter, player_num):
    team = match[f"team_{team_letter}"]
    if 1 <= player_num <= len(team):
        return team[player_num - 1]["username"]
    return None
import random
import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters

# ────────────────────────────────
# Commentary phrases & GIF URLs

commentary_zero = [
    "Clean bowled! What a delivery! 🎯",
    "That's a wicket! Bowler celebrates!",
    "Striker is out! Can't believe it!",
    "A sharp dismissal, well done!"
]

commentary_four = [
    "That's a classic boundary! Four runs! 🏏",
    "Excellent timing, races to the fence!",
    "Four runs! The crowd goes wild!",
    "Beautifully struck through the covers!"
]

commentary_six = [
    "SIX! Massive hit over the boundary! 🔥🔥",
    "What a monster hit! Six runs!",
    "The ball's gone into orbit! SIX!",
    "Arun Smoked it For A Six 🔥🔥"
]

# Half-century and century congratulatory messages
def get_milestone_message(runs):
    if runs == 50:
        return "🎉 Half-century! What a fantastic innings! 🎉"
    elif runs == 100:
        return "🏆 CENTURY! Outstanding batting performance! 🏆"
    return None

# GIF URLs for 0, 4, 6 runs
gif_urls = {
    0: "https://media.giphy.com/media/26tPplGWjN0xLybiU/giphy.gif",  # wicket gif
    4: "https://media.giphy.com/media/l3vR9O7xaNpP9pX9K/giphy.gif",  # four gif
    6: "https://media.giphy.com/media/3o6Zt8MgUuvSbkZYWc/giphy.gif",  # six gif
}

# ────────────────────────────────
# DM interaction: Batsman and Bowler inputs

async def prompt_batsman(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    # Find match and check if user is striker
    for mid, match in match_data.items():
        if match.get("playing") and user_id == match.get("striker_id"):
            await update.message.reply_text("Send your run choice: 0,1,2,3,4 or 6")
            context.user_data["awaiting_batsman_input"] = True
            return
    await update.message.reply_text("You are not the striker currently or no match active.")

async def prompt_bowler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    for mid, match in match_data.items():
        if match.get("playing") and user_id == match.get("bowler_id"):
            await update.message.reply_text("Send your ball variation: rs, bouncer, yorker, short, slower, knuckle")
            context.user_data["awaiting_bowler_input"] = True
            return
    await update.message.reply_text("You are not the current bowler or no match active.")

# ────────────────────────────────
# Process ball after receiving both batsman and bowler inputs

async def process_ball(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip().lower()

    # Find which match user is playing in
    for chat_id, match in match_data.items():
        if not match.get("playing"):
            continue
        striker_id = match.get("striker_id")
        bowler_id = match.get("bowler_id")
        if user_id == striker_id:
            # Expecting run input
            if text not in {"0","1","2","3","4","6"}:
                await update.message.reply_text("Invalid runs. Send only 0,1,2,3,4 or 6.")
                return
            match["last_batsman_input"] = int(text)
            if "last_bowler_input" in match:
                await complete_ball(chat_id, context)
            else:
                await update.message.reply_text("Waiting for bowler's input...")
            return
        elif user_id == bowler_id:
            # Expecting bowler variation
            if text not in {"rs","bouncer","yorker","short","slower","knuckle"}:
                await update.message.reply_text("Invalid ball type. Send one of rs,bouncer,yorker,short,slower,knuckle.")
                return
            match["last_bowler_input"] = text
            if "last_batsman_input" in match:
                await complete_ball(chat_id, context)
            else:
                await update.message.reply_text("Waiting for batsman's input...")
            return

# ────────────────────────────────
# Complete ball: update stats, commentary, rotation, over tracking

async def complete_ball(chat_id, context):
    match = match_data[chat_id]

    runs = match.pop("last_batsman_input")
    ball_type = match.pop("last_bowler_input")

    # Mapping bowler inputs to runs if needed
    ball_runs_map = {"rs":0, "bouncer":1, "yorker":2, "short":3, "slower":4, "knuckle":6}
    ball_runs = ball_runs_map[ball_type]

    striker_num = match["striker_num"]
    bowling_team = match["bowling_team"]
    batting_team = match["batting_team"]

    # Get striker & bowler info
    striker = match[f"team_{batting_team}"][striker_num -1]
    bowler_num = match["bowler_num"]
    bowler = match[f"team_{bowling_team}"][bowler_num -1]

    # Wicket condition: batsman 0 and bowler rs (0) => wicket
    wicket = False
    if runs == 0 and ball_type == "rs":
        wicket = True

    # Update stats
    if wicket:
        striker["out"] = True
        commentary_text = random.choice(commentary_zero)
    else:
        striker["runs"] += runs
        striker["balls"] += 1
        commentary_text = None
        if runs == 4:
            commentary_text = random.choice(commentary_four)
        elif runs == 6:
            commentary_text = random.choice(commentary_six)
        else:
            commentary_text = f"{striker['username']} scored {runs} run{'s' if runs>1 else ''}."

    # Check milestones
    milestone_msg = get_milestone_message(striker["runs"])

    # Update team total runs & balls
    if "runs" not in match:
        match["runs"] = 0
    if "balls" not in match:
        match["balls"] = 0
    if "wickets" not in match:
        match["wickets"] = 0

    if not wicket:
        match["runs"] += runs
        match["balls"] += 1
    else:
        match["wickets"] += 1
        match["balls"] += 1

    # Commentary message
    chat = await context.bot.get_chat(chat_id)

    # Simulate delays
    await context.bot.send_message(chat_id=chat_id, text=f"Over {match['current_over'] + 1}, Ball {match['balls'] % 6 if match['balls']%6 != 0 else 6}")
    await asyncio.sleep(2)

    # Bowler bowling text
    ball_type_texts = {
        "rs":"a regular delivery",
        "bouncer":"a bouncer",
        "yorker":"a yorker",
        "short":"a short ball",
        "slower":"a slower ball",
        "knuckle":"a knuckleball"
    }
    await context.bot.send_message(chat_id=chat_id, text=f"{bowler['username']} bowls {ball_type_texts[ball_type]}.")
    await asyncio.sleep(4)

    # Batsman commentary and GIF if needed
    await context.bot.send_message(chat_id=chat_id, text=commentary_text)
    if runs in gif_urls:
        await context.bot.send_animation(chat_id=chat_id, animation=gif_urls[runs])

    if milestone_msg:
        await context.bot.send_message(chat_id=chat_id, text=milestone_msg)

    # Strike rotation
    if not wicket:
        # Rotate strike on odd runs (except last ball of over)
        ball_in_over = match["balls"] % 6
        if ball_in_over == 0:  # last ball of over
            # Swap strike if runs even, else keep
            if runs % 2 == 0:
                match["striker_num"], match["non_striker_num"] = match["non_striker_num"], match["striker_num"]
        else:
            if runs % 2 == 1:
                match["striker_num"], match["non_striker_num"] = match["non_striker_num"], match["striker_num"]
    else:
        # Wicket - new striker needed
        await context.bot.send_message(chat_id=chat_id, text="Host, please assign new striker with /bat <striker_num> <non_striker_num>.")

    # Over completion check
    if match["balls"] % 6 == 0:
        match["current_over"] += 1
        await context.bot.send_message(chat_id=chat_id, text="Over completed! Host, assign new bowler with /bowl <bowler_num>.")
    else:
        await context.bot.send_message(chat_id=chat_id, text="Ball completed. Waiting for next ball.")

    # Check innings end
    if match["wickets"] >= len(match[f"team_{batting_team}"]) or match["current_over"] >= match["overs"]:
        await context.bot.send_message(chat_id=chat_id, text="Innings complete! Host use /inningswap to switch innings or /endmatch to finish.")

    # Save updated striker and non-striker IDs
    match["striker_id"] = await get_user_id_from_username(context, striker["username"])
    match["non_striker_id"] = await get_user_id_from_username(context, match[f"team_{batting_team}"][match["non_striker_num"] - 1]["username"])

    match["bowler_id"] = await get_user_id_from_username(context, bowler["username"])

    # Clear last inputs
    match.pop("last_batsman_input", None)
    match.pop("last_bowler_input", None)

# ────────────────────────────────
# Utility: get user_id from username
async def get_user_id_from_username(context: ContextTypes.DEFAULT_TYPE, username: str):
    if not username.startswith("@"):
        username = "@" + username
    try:
        user = await context.bot.get_chat(username)
        return user.id
    except Exception:
        return None

# ────────────────────────────────
# Register handlers (at the end, as requested)

def register_handlers(application):
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("register", register))
    application.add_handler(CommandHandler("profile", profile))
    application.add_handler(CommandHandler("cclgroup", cclgroup))
    application.add_handler(CommandHandler("add_A", add_player_command))
    application.add_handler(CommandHandler("add_B", add_player_command))
    application.add_handler(CommandHandler("teams", teams))
    application.add_handler(CommandHandler("cap_A", cap_A))
    application.add_handler(CommandHandler("cap_B", cap_B))
    application.add_handler(CommandHandler("setovers", setovers))
    application.add_handler(CommandHandler("startmatch", startmatch))
    application.add_handler(CommandHandler("bat", bat))
    application.add_handler(CommandHandler("bowl", bowl))
    application.add_handler(CommandHandler("inningswap", inningswap))
    application.add_handler(CommandHandler("score", score))
    application.add_handler(CommandHandler("bonus", bonus))
    application.add_handler(CommandHandler("penalty", penalty))
    application.add_handler(CommandHandler("endmatch", endmatch))
    application.add_handler(CommandHandler("changehost", changehost_command))
    application.add_handler(CommandHandler("behost", behost_command))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), process_ball))

# ────────────────────────────────
# Entry point (example)

if __name__ == "__main__":
    from telegram.ext import ApplicationBuilder

    # Set your TOKEN and MONGODB_URL here
    TOKEN = "8156231369:AAHDFvjD9Aur9y5QjB5YWzvCQp7bUdLuuEc"
    MONGODB_URL = "mongodb://mongo:GhpHMiZizYnvJfKIQKxoDbRyzBCpqEyC@mainline.proxy.rlwy.net:54853"

    application = ApplicationBuilder().token(TOKEN).build()
    register_handlers(application)

    print("Bot started...")
    application.run_polling()
