import logging
import asyncio
from datetime import datetime, timedelta
from pymongo import MongoClient
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes, filters
)

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# MongoDB setup
BOT_TOKEN = "8133604799:AAF2dE86UjRxfAdUcqyoz3O9RgaCeTwaoHM"
MONGO_URL = "mongodb://mongo:GhpHMiZizYnvJfKIQKxoDbRyzBCpqEyC@mainline.proxy.rlwy.net:54853"
client = MongoClient(MONGO_URL)
db = client["mafia_game"]
games = db["games"]

# Utility function to create buttons from player list
def create_player_buttons(players, prefix="target_", exclude_id=None):
    buttons = []
    row = []
    for player in players:
        if player["user_id"] != exclude_id:
            btn = InlineKeyboardButton(player["name"], callback_data=f"{prefix}{player['user_id']}")
            row.append(btn)
            if len(row) == 2:
                buttons.append(row)
                row = []
    if row:
        buttons.append(row)
    return buttons
# Command to start a new Mafia game in the group
async def startmafia_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    existing = games.find_one({"chat_id": chat_id, "status": "lobby"})
    if existing:
        await update.message.reply_text("A game is already starting in this group!")
        return

    games.insert_one({
        "chat_id": chat_id,
        "status": "lobby",
        "players": [],
        "created_at": datetime.utcnow(),
        "phase": None
    })
    join_button = InlineKeyboardMarkup([
        [InlineKeyboardButton("Join Mafia Game", url=f"https://t.me/{context.bot.username}?start=join_{chat_id}")]
    ])
    await update.message.reply_text("🕵️ Mafia game is starting! Press below to join.", reply_markup=join_button)

# Start command in DM
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.startswith("/start join_"):
        chat_id = int(update.message.text.split("_")[1])
        game = games.find_one({"chat_id": chat_id, "status": "lobby"})
        if not game:
            await update.message.reply_text("Game not found or already started.")
            return

        user_id = update.effective_user.id
        user_name = update.effective_user.full_name
        for player in game["players"]:
            if player["user_id"] == user_id:
                await update.message.reply_text("You've already joined the game.")
                return

        games.update_one(
            {"chat_id": chat_id},
            {"$push": {"players": {"user_id": user_id, "name": user_name, "role": None, "alive": True}}}
        )
        await update.message.reply_text(f"You joined the Mafia game in {chat_id}!")

        # Notify the group
        try:
            await context.bot.send_message(chat_id, f"{user_name} has joined the game!")
        except:
            pass
# Cancel command in group (with confirmation)
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = games.find_one({"chat_id": chat_id})
    if not game:
        await update.message.reply_text("No active game found.")
        return

    if not update.effective_user or not update.effective_chat.get_member(update.effective_user.id).status in ["administrator", "creator"]:
        await update.message.reply_text("Only group admins can cancel the game.")
        return

    confirm_markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_cancel_{chat_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_cancel")
        ]
    ])
    await update.message.reply_text("Are you sure you want to cancel the Mafia game?", reply_markup=confirm_markup)

# Handle cancel confirm buttons
async def handle_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("confirm_cancel_"):
        chat_id = int(query.data.split("_")[2])
        games.delete_one({"chat_id": chat_id})
        await query.edit_message_text("❌ Mafia game cancelled.")
        await context.bot.send_message(chat_id, "❌ The Mafia game has been cancelled by an admin.")
    elif query.data == "cancel_cancel":
        await query.edit_message_text("Cancellation aborted.")

# Assign roles after lobby
def assign_roles(chat_id):
    game = games.find_one({"chat_id": chat_id})
    players = game["players"]
    total = len(players)
    roles = []

    # Basic role distribution (can customize more)
    mafia_count = max(1, total // 4)
    town_count = total - mafia_count - 1
    roles += ["mafia"] * mafia_count
    roles += ["don"]
    roles += ["townie"] * town_count

    import random
    random.shuffle(roles)

    updated_players = []
    for player, role in zip(players, roles):
        player["role"] = role
        player["alive"] = True
        updated_players.append(player)
        context.bot.send_message(
            chat_id=player["user_id"],
            text=f"Your role is: {role.capitalize()}",
        )

    games.update_one({"chat_id": chat_id}, {"$set": {"players": updated_players, "status": "started"}})

# Send message to Mafia team for internal DM chat
async def mafia_team_chat(context: ContextTypes.DEFAULT_TYPE, chat_id, sender_name, message):
    game = games.find_one({"chat_id": chat_id})
    for player in game["players"]:
        if player["role"] in ["mafia", "don", "framer"] and player["alive"]:
            await context.bot.send_message(
                chat_id=player["user_id"],
                text=f"{sender_name}: \n{message}"
            )

# Get alive players from game
def get_alive_players(chat_id):
    game = games.find_one({"chat_id": chat_id})
    return [p for p in game["players"] if p["alive"]]
# Begin night phase
async def start_night_phase(context: ContextTypes.DEFAULT_TYPE, chat_id):
    game = games.find_one({"chat_id": chat_id})
    games.update_one({"chat_id": chat_id}, {"$set": {"phase": "night", "night_actions": {}}})

    # Notify roles
    for player in game["players"]:
        if not player["alive"]:
            continue

        user_id = player["user_id"]
        role = player["role"]

        if role in ["mafia", "don"]:
            # Mafia vote buttons (players to kill)
            buttons = [[InlineKeyboardButton(p['name'], callback_data=f"mafiavote_{chat_id}_{p['user_id']}")] for p in game["players"] if p["alive"] and p["user_id"] != user_id]
            markup = InlineKeyboardMarkup(buttons)
            await context.bot.send_message(user_id, "🩸 Choose your target to eliminate tonight:", reply_markup=markup)

        elif role == "doctor":
            buttons = [[InlineKeyboardButton(p['name'], callback_data=f"doctor_{chat_id}_{p['user_id']}")] for p in game["players"] if p["alive"]]
            markup = InlineKeyboardMarkup(buttons)
            await context.bot.send_message(user_id, "🩺 Choose someone to heal tonight:", reply_markup=markup)

        elif role == "detective":
            buttons = [
                [
                    InlineKeyboardButton("🔍 Investigate", callback_data=f"detmode_{chat_id}_check"),
                    InlineKeyboardButton("🔪 Eliminate", callback_data=f"detmode_{chat_id}_kill")
                ]
            ]
            markup = InlineKeyboardMarkup(buttons)
            await context.bot.send_message(user_id, "🕵️ Choose your detective action:", reply_markup=markup)

    await context.bot.send_message(chat_id, "🌙 The night has fallen. Special roles are making their moves...")

    # Schedule resolution
    await asyncio.sleep(45)
    await resolve_night(context, chat_id)

# Handle detective first mode choice
async def handle_detective_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, chat_id, mode = query.data.split("_")
    chat_id = int(chat_id)

    game = games.find_one({"chat_id": chat_id})
    user_id = query.from_user.id
    buttons = [[InlineKeyboardButton(p['name'], callback_data=f"detective_{chat_id}_{mode}_{p['user_id']}")] for p in game["players"] if p["alive"] and p["user_id"] != user_id]
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data=f"detback_{chat_id}")])
    markup = InlineKeyboardMarkup(buttons)
    await query.edit_message_text(f"Detective: choose someone to {mode}:", reply_markup=markup)

# Handle mafia vote
async def handle_mafia_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, chat_id, target_id = query.data.split("_")
    chat_id = int(chat_id)
    target_id = int(target_id)
    voter_id = query.from_user.id

    game = games.find_one({"chat_id": chat_id})
    players = game["players"]
    voter_name = next((p['name'] for p in players if p['user_id'] == voter_id), "Someone")
    target_name = next((p['name'] for p in players if p['user_id'] == target_id), "Unknown")

    await context.bot.send_message(chat_id, f"🤵‍♂️ {voter_name} voted for {target_name}")
    games.update_one({"chat_id": chat_id}, {"$set": {f"night_actions.mafia": target_id}})

# Handle doctor save
async def handle_doctor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, chat_id, target_id = query.data.split("_")
    chat_id = int(chat_id)
    target_id = int(target_id)

    games.update_one({"chat_id": chat_id}, {"$set": {f"night_actions.doctor": target_id}})
    await query.edit_message_text("You have chosen to heal someone tonight.")
async def handle_detective_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    choice = query.data

    game = get_game_by_user(user_id)
    if not game or not game["night_phase"]:
        return

    if choice == "check" or choice == "kill":
        context.user_data["detective_action_type"] = choice
        buttons = []
        for pid in game["players"]:
            if pid != user_id and game["players"][pid]["alive"]:
                buttons.append([InlineKeyboardButton(game["players"][pid]["name"], callback_data=f"det_target:{pid}")])
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="det_back")])
        await query.edit_message_text("Who will you {}?".format("check" if choice == "check" else "kill"), reply_markup=InlineKeyboardMarkup(buttons))
    elif choice.startswith("det_target:"):
        target_id = int(choice.split(":")[1])
        action = context.user_data.get("detective_action_type")
        game["night_actions"]["detective"] = {"type": action, "target": target_id, "by": user_id}
        update_game(game["_id"], game)
        await query.edit_message_text(f"You've voted to {action} {game['players'][target_id]['name']}")
    elif choice == "det_back":
        buttons = [
            [InlineKeyboardButton("🔍 Check", callback_data="check")],
            [InlineKeyboardButton("🔫 Kill", callback_data="kill")]
        ]
        await query.edit_message_text("Detective, choose your action:", reply_markup=InlineKeyboardMarkup(buttons))


async def handle_doctor_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    game = get_game_by_user(user_id)
    if not game or not game["night_phase"]:
        return

    choice = query.data
    if choice.startswith("doc_save:"):
        target_id = int(choice.split(":")[1])
        if target_id == user_id and game["players"][user_id].get("self_saved", False):
            await query.edit_message_text("You can only save yourself once!")
            return
        game["night_actions"]["doctor"] = target_id
        if target_id == user_id:
            game["players"][user_id]["self_saved"] = True
        update_game(game["_id"], game)
        await query.edit_message_text(f"You've voted to save {game['players'][target_id]['name']}")


async def handle_framer_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    game = get_game_by_user(user_id)
    if not game or not game["night_phase"]:
        return

    choice = query.data
    if choice.startswith("frame:"):
        target_id = int(choice.split(":")[1])
        game["night_actions"]["framer"] = target_id
        update_game(game["_id"], game)
        await query.edit_message_text(f"You've voted to frame {game['players'][target_id]['name']}")
async def handle_mafia_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    game = get_game_by_user(user_id)
    if not game or not game["night_phase"]:
        return

    choice = query.data
    if choice.startswith("mafia_vote:"):
        target_id = int(choice.split(":")[1])
        game["night_actions"]["mafia_votes"][user_id] = target_id
        update_game(game["_id"], game)
        name = game['players'][target_id]["name"]
        await send_to_group(game["group_id"], f"{get_role_emoji(game['players'][user_id]['role'])} {mention_html(user_id, game['players'][user_id]['name'])} voted for {name}", parse_mode=ParseMode.HTML)

        # Send message to all mafia members
        for pid in game["players"]:
            if game["players"][pid]["role"] in ['mafia', 'don', 'framer'] and game["players"][pid]["alive"]:
                if pid != user_id:
                    try:
                        await context.bot.send_message(pid, f"{game['players'][user_id]['name']}: Voted for {name}")
                    except:
                        pass

        await query.edit_message_text(f"You voted for {name}.")


def all_night_actions_collected(game):
    needed = []
    for pid, p in game["players"].items():
        if not p["alive"]:
            continue
        role = p["role"]
        if role == "doctor" and "doctor" not in game["night_actions"]:
            needed.append("doctor")
        if role == "framer" and "framer" not in game["night_actions"]:
            needed.append("framer")
        if role == "detective" and "detective" not in game["night_actions"]:
            needed.append("detective")
        if role in ["mafia", "don"] and pid not in game["night_actions"]["mafia_votes"]:
            needed.append(f"mafia:{pid}")
    return len(needed) == 0


async def process_night_phase(context: ContextTypes.DEFAULT_TYPE, game_id):
    game = get_game_by_id(game_id)
    if not game or not game["night_phase"]:
        return

    if not all_night_actions_collected(game):
        await asyncio.sleep(5)
        return await process_night_phase(context, game_id)

    # Tally Mafia Votes
    mafia_votes = {}
    for voter, target in game["night_actions"]["mafia_votes"].items():
        mafia_votes[target] = mafia_votes.get(target, 0) + 1

    victim = max(mafia_votes.items(), key=lambda x: x[1])[0] if mafia_votes else None

    # Doctor save
    save_id = game["night_actions"].get("doctor")
    if save_id == victim:
        victim = None

    # Detective
    det = game["night_actions"].get("detective")
    if det:
        action = det["type"]
        target = det["target"]
        by = det["by"]
        if action == "check":
            role = game["players"][target]["role"]
            try:
                await context.bot.send_message(by, f"{game['players'][target]['name']}'s role is {get_role_emoji(role)} {role.capitalize()}")
            except:
                pass
        elif action == "kill":
            victim = target

    if victim:
        game["players"][victim]["alive"] = False
        await send_to_group(game["group_id"], f"{game['players'][victim]['name']} was killed last night.")

    game["night_phase"] = False
    update_game(game_id, game)

    # Start voting phase
    await announce_voting(game, context)
async def announce_voting(game, context: ContextTypes.DEFAULT_TYPE):
    group_id = game["group_id"]
    game["votes"] = {}
    update_game(game["_id"], game)

    buttons = []
    for uid, player in game["players"].items():
        if player["alive"]:
            buttons.append([InlineKeyboardButton(player["name"], callback_data=f"vote:{uid}")])

    markup = InlineKeyboardMarkup(buttons)

    for uid, player in game["players"].items():
        if player["alive"]:
            try:
                await context.bot.send_message(uid, "Choose someone to lynch:", reply_markup=markup)
            except:
                pass

    await send_to_group(group_id, "It's voting time! Check your DMs to vote.")
    await asyncio.sleep(45)
    await tally_votes(game["_id"], context)


async def handle_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    game = get_game_by_user(user_id)
    if not game or game["night_phase"]:
        return

    target_id = int(query.data.split(":")[1])
    game["votes"][user_id] = target_id
    update_game(game["_id"], game)
    voter = game['players'][user_id]["name"]
    voted = game['players'][target_id]["name"]
    await send_to_group(game["group_id"], f"{mention_html(user_id, voter)} voted for {voted}", parse_mode=ParseMode.HTML)
    await query.edit_message_text(f"You voted for {voted}.")


async def tally_votes(game_id, context: ContextTypes.DEFAULT_TYPE):
    game = get_game_by_id(game_id)
    if not game:
        return

    vote_count = {}
    for voter, voted in game["votes"].items():
        vote_count[voted] = vote_count.get(voted, 0) + 1

    if not vote_count:
        await send_to_group(game["group_id"], "Nobody voted. No one will be lynched today.")
        return

    top = sorted(vote_count.items(), key=lambda x: (-x[1], x[0]))
    top_voted, count = top[0]
    confirm_message = await context.bot.send_message(
        game["group_id"],
        f"Are you sure about lynching {game['players'][top_voted]['name']}?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👍 0", callback_data=f"confirmlynch:{top_voted}:yes"),
             InlineKeyboardButton("👎 0", callback_data=f"confirmlynch:{top_voted}:no")]
        ])
    )

    game["lynch_vote"] = {
        "target": top_voted,
        "message_id": confirm_message.message_id,
        "yes": [],
        "no": []
    }
    update_game(game["_id"], game)
    await asyncio.sleep(30)
    await finalize_lynch_vote(game["_id"], context)
async def handle_confirm_lynch_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data.split(":")
    game = get_game_by_id_from_group(query.message.chat_id)
    if not game or "lynch_vote" not in game:
        return

    lynch_vote = game["lynch_vote"]
    if user_id in lynch_vote["yes"] or user_id in lynch_vote["no"]:
        await query.answer("You already voted!", show_alert=True)
        return

    vote_for = data[2]  # 'yes' or 'no'
    if vote_for == "yes":
        lynch_vote["yes"].append(user_id)
    else:
        lynch_vote["no"].append(user_id)

    total_yes = len(lynch_vote["yes"])
    total_no = len(lynch_vote["no"])

    # Update buttons with current votes count
    buttons = [
        [
            InlineKeyboardButton(f"👍 {total_yes}", callback_data=f"confirmlynch:{lynch_vote['target']}:yes"),
            InlineKeyboardButton(f"👎 {total_no}", callback_data=f"confirmlynch:{lynch_vote['target']}:no")
        ]
    ]
    await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(buttons))
    update_game(game["_id"], game)


async def finalize_lynch_vote(game_id, context: ContextTypes.DEFAULT_TYPE):
    game = get_game_by_id(game_id)
    if not game or "lynch_vote" not in game:
        return

    lynch_vote = game["lynch_vote"]
    target_id = lynch_vote["target"]
    yes_votes = len(lynch_vote["yes"])
    no_votes = len(lynch_vote["no"])

    if yes_votes > no_votes:
        game["players"][target_id]["alive"] = False
        update_game(game["_id"], game)
        player_name = game["players"][target_id]["name"]
        role = game["players"][target_id]["role_emoji"] + " " + game["players"][target_id]["role"]
        await send_to_group(game["group_id"], f"{mention_html(target_id, player_name)} was lynched! They were a {role}.", parse_mode=ParseMode.HTML)
    else:
        await send_to_group(game["group_id"], f"The citizens couldn't come up with a decision ({yes_votes} 👍 | {no_votes} 👎)... They dispersed, lynching nobody today...")

    del game["lynch_vote"]
    update_game(game["_id"], game)
    await start_night_phase(game["_id"], context)
async def send_to_group(chat_id, text, parse_mode=None):
    try:
        await application.bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
    except Exception as e:
        logging.error(f"Failed to send message to group {chat_id}: {e}")


async def mention_html(user_id, name):
    return f'<a href="tg://user?id={user_id}">{name}</a>'


def get_game_by_id(game_id):
    return db.games.find_one({"_id": game_id})


def get_game_by_id_from_group(group_id):
    return db.games.find_one({"group_id": group_id, "status": "running"})


def update_game(game_id, game_data):
    db.games.update_one({"_id": game_id}, {"$set": game_data})


async def start_night_phase(game_id, context: ContextTypes.DEFAULT_TYPE):
    game = get_game_by_id(game_id)
    if not game:
        return
    # Reset night actions, send night role prompts, etc.
    # Notify group that night phase started
    await send_to_group(game["group_id"], "Night has fallen... All players with night actions, check your DMs.", parse_mode=ParseMode.HTML)
    # You would send DM prompts here for doctor, mafia, detective, etc.
    # Start a timer to collect actions then proceed to resolve night
    # After night resolution, call voting phase

# Main function and startup code

def main():
    global application
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("startmafia", startmafia_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(CallbackQueryHandler(handle_registration, pattern=r"^register:"))
    application.add_handler(CallbackQueryHandler(handle_role_choice, pattern=r"^rolechoice:"))
    application.add_handler(CallbackQueryHandler(handle_night_action, pattern=r"^nightaction:"))
    application.add_handler(CallbackQueryHandler(handle_vote, pattern=r"^vote:"))
    application.add_handler(CallbackQueryHandler(handle_confirm_lynch_vote, pattern=r"^confirmlynch:"))
    application.add_handler(CommandHandler("help", help_command))

    application.run_polling()


if __name__ == "__main__":
    main()
