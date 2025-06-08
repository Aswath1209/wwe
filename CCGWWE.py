import logging
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatAction
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    CallbackQueryHandler, MessageHandler, filters
)
from pymongo import MongoClient
import random
import asyncio

# ====== CONFIG ======
BOT_TOKEN = '8133604799:AAF2dE86UjRxfAdUcqyoz3O9RgaCeTwaoHM'
MONGO_URL = 'mongodb://mongo:GhpHMiZizYnvJfKIQKxoDbRyzBCpqEyC@mainline.proxy.rlwy.net:54853'

# ====== LOGGING ======
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ====== DB SETUP ======
client = MongoClient(MONGO_URL)
db = client.ccl_group_v_group

# Collections:
games_col = db.games
players_col = db.players

# ====== GAME DATA STRUCTURES ======

# We'll store games per chat_id:
# Each game dict structure:
# {
#   'host_id': int,
#   'host_username': str,
#   'teamA': [{'user_id': int, 'username': str, 'index': int}],
#   'teamB': [...],
#   'captainA': int (index in teamA),
#   'captainB': int (index in teamB),
#   'overs': int,
#   'current_innings': 1 or 2,
#   'batting_team': 'A' or 'B',
#   'bowling_team': 'A' or 'B',
#   'striker': user_id,
#   'non_striker': user_id or None,
#   'current_bowler': user_id,
#   'ball_in_over': int (1-6),
#   'over_number': int,
#   'scoreA': int,
#   'wicketsA': int,
#   'scoreB': int,
#   'wicketsB': int,
#   'players_data': {user_id: {... player stats like runs, balls, wickets ...}},
#   'state': str (like 'awaiting_toss_choice', 'in_progress', etc),
#   ...
# }

# You can expand the schema as needed.

# ====== BASIC COMMANDS ======

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to the CCL Group vs Group Bot!\n"
        "Use /register to register yourself.\n"
        "Host can start game with /cclgroup."
    )

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # Just a placeholder registration - you can expand as needed
    players_col.update_one(
        {'user_id': user.id},
        {'$set': {'username': user.username or user.full_name}},
        upsert=True
    )
    await update.message.reply_text(f"Registered {user.full_name} (@{user.username}) successfully!")

# ====== APP SETUP ======

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('register', register))

    # More handlers to be added in next parts...

    app.run_polling()

if __name__ == '__main__':
    main()
import random

# ====== COMMENTARY + GIFs ======

COMMENTARIES = {
    '0': [
        "Defended well, no run.",
        "Blocked it solidly.",
        "No run, dot ball."
    ],
    '1': [
        "Quick single taken.",
        "They scamper a single.",
        "Smart running for one."
    ],
    '2': [
        "Good placement, two runs.",
        "They pick up two easily.",
        "Well timed shot for two."
    ],
    '3': [
        "Three runs taken with a sharp turn.",
        "Excellent running between wickets for three.",
        "Pushed hard for three."
    ],
    '4': [
        "What a glorious boundary!",
        "Four runs! Racing to the fence.",
        "Cracking shot for four."
    ],
    '6': [
        "Smashed it for six!",
        "That’s out of the park!",
        "Huge six over the boundary."
    ],
    'out': [
        "Bowled him out!",
        "What a catch! Out.",
        "He’s walking back, that's out."
    ]
}

GIFS = {
    '0': [
        "https://example.com/dot1.gif",
        "https://example.com/dot2.gif"
    ],
    '4': [
        "https://example.com/four1.gif",
        "https://example.com/four2.gif"
    ],
    '6': [
        "https://example.com/six1.gif",
        "https://example.com/six2.gif"
    ],
    'out': [
        "https://example.com/out1.gif",
        "https://example.com/out2.gif"
    ]
}

# ====== GAME COMMANDS ======

async def cclgroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id

    # Only group chats
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("This command can only be used in group chats.")
        return

    # Check if game exists
    existing_game = games_col.find_one({'chat_id': chat_id})
    if existing_game:
        await update.message.reply_text("A game is already running in this group.")
        return

    # Create new game entry
    game_data = {
        'chat_id': chat_id,
        'host_id': user.id,
        'host_username': user.username or user.full_name,
        'teamA': [],
        'teamB': [],
        'captainA': None,
        'captainB': None,
        'overs': None,
        'current_innings': 1,
        'batting_team': None,
        'bowling_team': None,
        'state': 'waiting_for_players',
        'players_data': {},
        # Add other default fields as needed
    }

    games_col.insert_one(game_data)
    await update.message.reply_text(f"Game created by @{game_data['host_username']}! Use /addA and /addB to add players.")

async def addA(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user

    args = context.args
    if not args:
        await update.message.reply_text("Usage: /addA @username or user_id")
        return

    game = games_col.find_one({'chat_id': chat_id})
    if not game:
        await update.message.reply_text("No active game found. Use /cclgroup to start one.")
        return

    # Only host can add players
    if user.id != game['host_id']:
        await update.message.reply_text("Only the host can add players.")
        return

    player_id = None
    player_username = None

    # Parse user mention or user id
    arg = args[0]
    if arg.startswith('@'):
        player_username = arg[1:]
        # Try to find user in DB
        player_doc = players_col.find_one({'username': player_username})
        if player_doc:
            player_id = player_doc['user_id']
        else:
            await update.message.reply_text("Player not registered. Ask them to /register first.")
            return
    else:
        try:
            player_id = int(arg)
            player_doc = players_col.find_one({'user_id': player_id})
            if player_doc:
                player_username = player_doc.get('username', '')
            else:
                await update.message.reply_text("Player not registered. Ask them to /register first.")
                return
        except:
            await update.message.reply_text("Invalid user ID or username.")
            return

    # Check if player already in any team
    for p in game['teamA'] + game['teamB']:
        if p['user_id'] == player_id:
            await update.message.reply_text("Player already added in a team.")
            return

    # Add player to Team A
    teamA = game['teamA']
    new_index = len(teamA) + 1
    teamA.append({'user_id': player_id, 'username': player_username, 'index': new_index})

    games_col.update_one({'chat_id': chat_id}, {'$set': {'teamA': teamA}})

    await update.message.reply_text(f"Added @{player_username} to Team A as player {new_index}.")

async def addB(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Same as addA but for Team B
    chat_id = update.effective_chat.id
    user = update.effective_user
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /addB @username or user_id")
        return

    game = games_col.find_one({'chat_id': chat_id})
    if not game:
        await update.message.reply_text("No active game found. Use /cclgroup to start one.")
        return

    if user.id != game['host_id']:
        await update.message.reply_text("Only the host can add players.")
        return

    player_id = None
    player_username = None

    arg = args[0]
    if arg.startswith('@'):
        player_username = arg[1:]
        player_doc = players_col.find_one({'username': player_username})
        if player_doc:
            player_id = player_doc['user_id']
        else:
            await update.message.reply_text("Player not registered. Ask them to /register first.")
            return
    else:
        try:
            player_id = int(arg)
            player_doc = players_col.find_one({'user_id': player_id})
            if player_doc:
                player_username = player_doc.get('username', '')
            else:
                await update.message.reply_text("Player not registered. Ask them to /register first.")
                return
        except:
            await update.message.reply_text("Invalid user ID or username.")
            return

    for p in game['teamA'] + game['teamB']:
        if p['user_id'] == player_id:
            await update.message.reply_text("Player already added in a team.")
            return

    teamB = game['teamB']
    new_index = len(teamB) + 1
    teamB.append({'user_id': player_id, 'username': player_username, 'index': new_index})

    games_col.update_one({'chat_id': chat_id}, {'$set': {'teamB': teamB}})

    await update.message.reply_text(f"Added @{player_username} to Team B as player {new_index}.")

async def removeA(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /removeA <player_index>")
        return

    game = games_col.find_one({'chat_id': chat_id})
    if not game:
        await update.message.reply_text("No active game found.")
        return

    if user.id != game['host_id']:
        await update.message.reply_text("Only the host can remove players.")
        return

    idx = int(args[0])
    teamA = game['teamA']
    if idx < 1 or idx > len(teamA):
        await update.message.reply_text("Invalid player index.")
        return

    removed_player = teamA.pop(idx - 1)
    # Re-index team
    for i, p in enumerate(teamA, 1):
        p['index'] = i

    games_col.update_one({'chat_id': chat_id}, {'$set': {'teamA': teamA}})

    await update.message.reply_text(f"Removed @{removed_player['username']} from Team A.")

async def removeB(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /removeB <player_index>")
        return

    game = games_col.find_one({'chat_id': chat_id})
    if not game:
        await update.message.reply_text("No active game found.")
        return

    if user.id != game['host_id']:
        await update.message.reply_text("Only the host can remove players.")
        return

    idx = int(args[0])
    teamB = game['teamB']
    if idx < 1 or idx > len(teamB):
        await update.message.reply_text("Invalid player index.")
        return

    removed_player = teamB.pop(idx - 1)
    # Re-index team
    for i, p in enumerate(teamB, 1):
        p['index'] = i

    games_col.update_one({'chat_id': chat_id}, {'$set': {'teamB': teamB}})

    await update.message.reply_text(f"Removed @{removed_player['username']} from Team B.")

async def team(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = games_col.find_one({'chat_id': chat_id})
    if not game:
        await update.message.reply_text("No active game in this group.")
        return

    text = "*Team A*\n"
    if game['teamA']:
        for p in game['teamA']:
            text += f"{p['index']}) @{p['username']}\n"
    else:
        text += "No players yet.\n"

    text += "\n*Team B*\n"
    if game['teamB']:
        for p in game['teamB']:
            text += f"{p['index']}) @{p['username']}\n"
    else:
        text += "No players yet.\n"

    await update.message.reply_text(text, parse_mode='Markdown')

# Remember to add these handlers to your main app in the next part.
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

async def capA(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /capA <player_index>")
        return

    game = games_col.find_one({'chat_id': chat_id})
    if not game:
        await update.message.reply_text("No active game found.")
        return

    if user.id != game['host_id']:
        await update.message.reply_text("Only the host can assign captains.")
        return

    idx = int(args[0])
    teamA = game['teamA']
    if idx < 1 or idx > len(teamA):
        await update.message.reply_text("Invalid player index for Team A.")
        return

    captain = teamA[idx - 1]
    games_col.update_one({'chat_id': chat_id}, {'$set': {'captainA': captain}})

    await update.message.reply_text(f"@{captain['username']} is now captain of Team A.")

async def capB(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /capB <player_index>")
        return

    game = games_col.find_one({'chat_id': chat_id})
    if not game:
        await update.message.reply_text("No active game found.")
        return

    if user.id != game['host_id']:
        await update.message.reply_text("Only the host can assign captains.")
        return

    idx = int(args[0])
    teamB = game['teamB']
    if idx < 1 or idx > len(teamB):
        await update.message.reply_text("Invalid player index for Team B.")
        return

    captain = teamB[idx - 1]
    games_col.update_one({'chat_id': chat_id}, {'$set': {'captainB': captain}})

    await update.message.reply_text(f"@{captain['username']} is now captain of Team B.")

async def setovers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /setovers <number_of_overs>")
        return

    game = games_col.find_one({'chat_id': chat_id})
    if not game:
        await update.message.reply_text("No active game found.")
        return

    if user.id != game['host_id']:
        await update.message.reply_text("Only the host can set overs.")
        return

    overs = int(args[0])
    if overs < 1 or overs > 50:
        await update.message.reply_text("Please set overs between 1 and 50.")
        return

    games_col.update_one({'chat_id': chat_id}, {'$set': {'overs': overs}})
    await update.message.reply_text(f"Total overs set to {overs}.")

# ===== TOSS =====

async def toss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user

    game = games_col.find_one({'chat_id': chat_id})
    if not game:
        await update.message.reply_text("No active game found.")
        return

    if user.id != game['host_id']:
        await update.message.reply_text("Only the host can start the toss.")
        return

    if not game.get('captainA') or not game.get('captainB'):
        await update.message.reply_text("Both teams must have captains assigned before toss.")
        return

    if not game.get('overs'):
        await update.message.reply_text("Overs must be set before toss. Use /setovers.")
        return

    if game.get('state') != 'waiting_for_players':
        await update.message.reply_text("Toss has already started or match is in progress.")
        return

    # Change game state
    games_col.update_one({'chat_id': chat_id}, {'$set': {'state': 'toss_heads_tails'}})

    captainA = game['captainA']
    keyboard = [
        [InlineKeyboardButton("Heads", callback_data='toss_heads')],
        [InlineKeyboardButton("Tails", callback_data='toss_tails')]
    ]

    await update.message.reply_text(
        f"@{captainA['username']} (Captain Team A), choose Heads or Tails:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ===== CALLBACK HANDLER FOR TOSS =====

async def toss_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    data = query.data

    game = games_col.find_one({'chat_id': chat_id})
    if not game or game.get('state') not in ['toss_heads_tails', 'toss_bat_bowl_choice']:
        await query.edit_message_text("No active toss in progress.")
        return

    captainA = game['captainA']
    captainB = game['captainB']

    # Only Team A captain can choose heads/tails
    if query.from_user.id != captainA['user_id']:
        await query.answer("Only Team A captain can choose Heads or Tails.", show_alert=True)
        return

    # Store Team A captain's choice
    if data == 'toss_heads':
        choice = 'heads'
    else:
        choice = 'tails'

    # Random toss result
    toss_result = random.choice(['heads', 'tails'])
    winner = None

    if toss_result == choice:
        winner = 'A'
    else:
        winner = 'B'

    games_col.update_one({'chat_id': chat_id}, {
        '$set': {
            'toss_choice': choice,
            'toss_result': toss_result,
            'toss_winner': winner,
            'state': 'toss_bat_bowl_choice'
        }
    })

    if winner == 'A':
        keyboard = [
            [InlineKeyboardButton("Bat", callback_data='toss_choice_bat')],
            [InlineKeyboardButton("Bowl", callback_data='toss_choice_bowl')]
        ]
        await query.edit_message_text(
            f"Toss result: {toss_result.capitalize()}. Team A won the toss!\n"
            f"@{captainA['username']} choose to Bat or Bowl:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        keyboard = [
            [InlineKeyboardButton("Bat", callback_data='toss_choice_bat')],
            [InlineKeyboardButton("Bowl", callback_data='toss_choice_bowl')]
        ]
        await query.edit_message_text(
            f"Toss result: {toss_result.capitalize()}. Team B won the toss!\n"
            f"@{captainB['username']} choose to Bat or Bowl:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

# ===== CALLBACK HANDLER FOR BAT/BOWL CHOICE =====

async def toss_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    data = query.data

    game = games_col.find_one({'chat_id': chat_id})
    if not game or game.get('state') != 'toss_bat_bowl_choice':
        await query.edit_message_text("No active toss choice in progress.")
        return

    winner = game['toss_winner']
    captainA = game['captainA']
    captainB = game['captainB']

    user_id = query.from_user.id
    # Only toss winner captain can choose
    if winner == 'A' and user_id != captainA['user_id']:
        await query.answer("Only Team A captain can choose.", show_alert=True)
        return
    elif winner == 'B' and user_id != captainB['user_id']:
        await query.answer("Only Team B captain can choose.", show_alert=True)
        return

    # Determine batting and bowling teams
    if data == 'toss_choice_bat':
        batting_team = 'A' if winner == 'A' else 'B'
        bowling_team = 'B' if winner == 'A' else 'A'
    else:
        batting_team = 'B' if winner == 'A' else 'A'
        bowling_team = 'A' if winner == 'A' else 'B'

    games_col.update_one({'chat_id': chat_id}, {'$set': {
        'batting_team': batting_team,
        'bowling_team': bowling_team,
        'state': 'innings_setup'
    }})

    await query.edit_message_text(
        f"Match setup:\n"
        f"Batting Team: Team {batting_team}\n"
        f"Bowling Team: Team {bowling_team}\n"
        f"Host, now choose your opening batsmen and bowler."
    )

# Remember to add these callback query handlers to your dispatcher.
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# --- Batting and Bowling selection commands ---

async def cmd_bat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    args = context.args
    game = await get_game(chat_id)
    if not game:
        await update.message.reply_text("No active CCL group game.")
        return

    if user.id != game['host']:
        await update.message.reply_text("Only host can select batsmen.")
        return

    if len(args) != 1 or not args[0].isdigit():
        await update.message.reply_text("Usage: /bat <player_index>")
        return

    idx = int(args[0]) - 1
    # Determine batting team based on innings
    batting_team = game['batting_team']  # 'A' or 'B'
    team_players = game[f'team_{batting_team}']

    if idx < 0 or idx >= len(team_players):
        await update.message.reply_text(f"Invalid player index for Team {batting_team}.")
        return

    player_id = team_players[idx]
    # Assign striker and non-striker on first two /bat commands
    if 'striker' not in game or game['striker'] is None:
        game['striker'] = player_id
        await update.message.reply_text(f"Player {player_id} set as Striker.")
    elif 'non_striker' not in game or game['non_striker'] is None:
        if player_id == game['striker']:
            await update.message.reply_text("Striker and Non-striker cannot be the same player.")
            return
        game['non_striker'] = player_id
        await update.message.reply_text(f"Player {player_id} set as Non-striker.")
    else:
        await update.message.reply_text("Both striker and non-striker are already set.")

    await save_game(chat_id, game)

async def cmd_bowl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    args = context.args
    game = await get_game(chat_id)
    if not game:
        await update.message.reply_text("No active CCL group game.")
        return

    if user.id != game['host']:
        await update.message.reply_text("Only host can select bowlers.")
        return

    if len(args) != 1 or not args[0].isdigit():
        await update.message.reply_text("Usage: /bowl <player_index>")
        return

    idx = int(args[0]) - 1
    bowling_team = 'B' if game['batting_team'] == 'A' else 'A'
    team_players = game[f'team_{bowling_team}']

    if idx < 0 or idx >= len(team_players):
        await update.message.reply_text(f"Invalid player index for Team {bowling_team}.")
        return

    player_id = team_players[idx]
    # Ensure bowler isn't same as last over bowler and retired hurt
    last_bowler = game.get('last_bowler')
    retired_bowlers = game.get('retired_bowlers', [])
    if player_id == last_bowler:
        await update.message.reply_text("Cannot bowl consecutive overs.")
        return
    if player_id in retired_bowlers:
        await update.message.reply_text("This bowler is retired hurt and cannot bowl now.")
        return

    game['current_bowler'] = player_id
    await update.message.reply_text(f"Player {player_id} set as Bowler.")
    await save_game(chat_id, game)

# --- DM input validation for batsman and bowler ---

BAT_RUNS = ['0', '1', '2', '3', '4', '6']
BOWL_VARIATIONS = ['Rs', 'Bouncer', 'Yorker', 'Short', 'Slower', 'Knuckle']
VARIATION_MAP = {
    'Rs': 0,
    'Bouncer': 1,
    'Yorker': 2,
    'Short': 3,
    'Slower': 4,
    'Knuckle': 6,
}

async def handle_dm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()
    # Find which game this user is playing in
    game = await find_game_by_player(user.id)
    if not game:
        await update.message.reply_text("You're not part of any active match.")
        return

    chat_id = game['chat_id']
    # Check if user is striker or bowler expected to send input
    if user.id == game.get('striker'):
        # Validate batsman input
        if text not in BAT_RUNS:
            await update.message.reply_text(f"Invalid run. Send one of: {', '.join(BAT_RUNS)}")
            return
        game['last_batsman_input'] = int(text)
        await update.message.reply_text(f"You chose to run: {text}")
    elif user.id == game.get('current_bowler'):
        if text not in BOWL_VARIATIONS:
            await update.message.reply_text(f"Invalid bowling variation. Send one of: {', '.join(BOWL_VARIATIONS)}")
            return
        game['last_bowler_input'] = text
        await update.message.reply_text(f"You chose to bowl: {text}")
    else:
        await update.message.reply_text("It's not your turn to send input.")
        return

    # Check if both inputs received
    if 'last_batsman_input' in game and 'last_bowler_input' in game:
        # Evaluate ball
        batsman_run = game['last_batsman_input']
        bowler_variation = game['last_bowler_input']
        bowler_run = VARIATION_MAP[bowler_variation]

        is_out = (batsman_run == bowler_run)
        # Compose commentary and gif
        commentary, gif_url = get_commentary_and_gif(batsman_run, is_out)

        # Send message to group chat with delays as per your spec
        await context.bot.send_message(chat_id, f"Over {game.get('over', 1)} Ball {game.get('ball', 1)}")
        await asyncio.sleep(3)
        await context.bot.send_message(chat_id, f"Bowler {game['current_bowler']} bowls a {bowler_variation} ball")
        await asyncio.sleep(3)
        await context.bot.send_message(chat_id, commentary)
        await context.bot.send_animation(chat_id, gif_url)

        # Clear last inputs for next ball
        del game['last_batsman_input']
        del game['last_bowler_input']

        # Update game state: runs, wickets, ball count, strike change, etc.
        # (You will implement this part fully in next parts)

        await save_game(chat_id, game)

async def get_commentary_and_gif(runs, is_out):
    # Sample commentary lists
    six_commentaries = [
        "Smoked it for a Six!",
        "What a massive six!",
        "Over the boundary with ease!"
    ]
    four_commentaries = [
        "Crushed it for Four!",
        "That's a nice boundary!",
        "Four runs through the covers!"
    ]
    out_commentaries = [
        "Oh no! He's out!",
        "Clean bowled!",
        "Caught behind!"
    ]
    run_commentaries = [
        "Good running between the wickets.",
        "Quick single taken.",
        "Couple of runs added."
    ]

    six_gifs = [
        "https://media.giphy.com/media/3o6Zt6ML6BklcajjsA/giphy.gif",
        "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif",
    ]
    four_gifs = [
        "https://media.giphy.com/media/3o7aCTfyhYawdOXcFW/giphy.gif",
        "https://media.giphy.com/media/26Ff5bI1zFTZfmA7O/giphy.gif",
    ]
    out_gifs = [
        "https://media.giphy.com/media/3o6ZtaO9BZHcOjmErm/giphy.gif",
        "https://media.giphy.com/media/xT0xezQGU5xCDJuCPe/giphy.gif",
    ]

    if is_out:
        commentary = random.choice(out_commentaries)
        gif_url = random.choice(out_gifs)
    elif runs == 6:
        commentary = random.choice(six_commentaries)
        gif_url = random.choice(six_gifs)
    elif runs == 4:
        commentary = random.choice(four_commentaries)
        gif_url = random.choice(four_gifs)
    else:
        commentary = random.choice(run_commentaries)
        gif_url = None

    return commentary, gif_url

# --- Helper async functions to get and save game from DB ---

async def get_game(chat_id):
    # Fetch game document from MongoDB by chat_id
    pass

async def save_game(chat_id, game_data):
    # Save updated game document to MongoDB
    pass

async def find_game_by_player(user_id):
    # Find game where user is in team A or B and match is active
    pass
import asyncio

# --- Over & Ball management ---

async def next_ball(game):
    """
    Update ball count, over count, strike rotation and bowling restrictions.
    Called after each valid ball.
    """
    game['ball'] = game.get('ball', 1)
    game['over'] = game.get('over', 1)
    game['runs'] = game.get('runs', 0)
    game['wickets'] = game.get('wickets', 0)
    game['balls_in_over'] = game.get('balls_in_over', 0)
    game['retired_bowlers'] = game.get('retired_bowlers', [])
    game['retired_batsmen'] = game.get('retired_batsmen', [])

    game['balls_in_over'] += 1

    if game['balls_in_over'] > 6:
        # End of over
        game['over'] += 1
        game['balls_in_over'] = 1
        # Restrict last over's bowler from bowling next over
        last_bowler = game.get('current_bowler')
        if last_bowler and last_bowler not in game['retired_bowlers']:
            if 'bowlers_restriction' not in game:
                game['bowlers_restriction'] = []
            game['bowlers_restriction'].append(last_bowler)
        # Swap strike if last run even at over end
        last_run = game.get('last_batsman_run', 0)
        if last_run % 2 == 0:
            game['striker'], game['non_striker'] = game['non_striker'], game['striker']

    else:
        # Ball within over
        last_run = game.get('last_batsman_run', 0)
        # Strike rotates on odd runs
        if last_run % 2 == 1:
            game['striker'], game['non_striker'] = game['non_striker'], game['striker']

    await save_game(game['chat_id'], game)

# --- Retired Hurt / Retired Out commands ---

async def cmd_retiredhurt(update, context):
    chat_id = update.effective_chat.id
    user = update.effective_user
    args = context.args
    game = await get_game(chat_id)

    if user.id != game.get('host'):
        await update.message.reply_text("Only host can retire players.")
        return

    if len(args) != 2:
        await update.message.reply_text("Usage: /retiredhurt <striker/nonstriker/bowler> <player_index>")
        return

    role, idx_str = args
    if role.lower() not in ['striker', 'nonstriker', 'bowler']:
        await update.message.reply_text("Role must be striker, nonstriker or bowler.")
        return

    try:
        idx = int(idx_str) - 1
    except:
        await update.message.reply_text("Invalid player index.")
        return

    # Remove player from active or mark retired hurt
    # For batsman
    if role.lower() in ['striker', 'nonstriker']:
        batting_team = game['batting_team']
        team_players = game[f'team_{batting_team}']

        if idx < 0 or idx >= len(team_players):
            await update.message.reply_text("Invalid player index for batting team.")
            return

        player_id = team_players[idx]

        if role.lower() == 'striker' and game['striker'] != player_id:
            await update.message.reply_text("Player is not striker currently.")
            return
        if role.lower() == 'nonstriker' and game['non_striker'] != player_id:
            await update.message.reply_text("Player is not non-striker currently.")
            return

        # Mark retired hurt
        if 'retired_batsmen' not in game:
            game['retired_batsmen'] = []
        game['retired_batsmen'].append(player_id)

        # Replace striker or non striker
        if role.lower() == 'striker':
            game['striker'] = None
        else:
            game['non_striker'] = None

        await update.message.reply_text(f"Player {player_id} retired hurt.")

    # For bowler
    elif role.lower() == 'bowler':
        bowling_team = 'B' if game['batting_team'] == 'A' else 'A'
        team_players = game[f'team_{bowling_team}']

        if idx < 0 or idx >= len(team_players):
            await update.message.reply_text("Invalid player index for bowling team.")
            return

        player_id = team_players[idx]

        # Mark retired hurt
        if 'retired_bowlers' not in game:
            game['retired_bowlers'] = []
        game['retired_bowlers'].append(player_id)

        # If current bowler is retired hurt, reset bowler
        if game.get('current_bowler') == player_id:
            game['current_bowler'] = None

        await update.message.reply_text(f"Bowler {player_id} retired hurt.")

    await save_game(chat_id, game)

async def cmd_retiredout(update, context):
    chat_id = update.effective_chat.id
    user = update.effective_user
    args = context.args
    game = await get_game(chat_id)

    if user.id != game.get('host'):
        await update.message.reply_text("Only host can retire players.")
        return

    if len(args) != 2:
        await update.message.reply_text("Usage: /retiredout <striker/nonstriker> <player_index>")
        return

    role, idx_str = args
    if role.lower() not in ['striker', 'nonstriker']:
        await update.message.reply_text("Role must be striker or nonstriker.")
        return

    try:
        idx = int(idx_str) - 1
    except:
        await update.message.reply_text("Invalid player index.")
        return

    batting_team = game['batting_team']
    team_players = game[f'team_{batting_team}']

    if idx < 0 or idx >= len(team_players):
        await update.message.reply_text("Invalid player index for batting team.")
        return

    player_id = team_players[idx]

    if role.lower() == 'striker' and game['striker'] != player_id:
        await update.message.reply_text("Player is not striker currently.")
        return
    if role.lower() == 'nonstriker' and game['non_striker'] != player_id:
        await update.message.reply_text("Player is not non-striker currently.")
        return

    # Add wicket
    game['wickets'] = game.get('wickets', 0) + 1

    # Remove player from striker/non-striker
    if role.lower() == 'striker':
        game['striker'] = None
    else:
        game['non_striker'] = None

    await update.message.reply_text(f"Player {player_id} retired out. Wicket added.")

    await save_game(chat_id, game)

# --- Bonus and Penalty commands ---

async def cmd_bonus(update, context):
    chat_id = update.effective_chat.id
    user = update.effective_user
    args = context.args
    game = await get_game(chat_id)

    if user.id != game.get('host'):
        await update.message.reply_text("Only host can add bonus.")
        return

    if len(args) != 2:
        await update.message.reply_text("Usage: /bonus <A/B> <runs>")
        return

    team = args[0].upper()
    if team not in ['A', 'B']:
        await update.message.reply_text("Team must be A or B.")
        return

    try:
        runs = int(args[1])
    except:
        await update.message.reply_text("Runs must be a number.")
        return

    if 'bonus' not in game:
        game['bonus'] = {'A': 0, 'B': 0}
    game['bonus'][team] = game['bonus'].get(team, 0) + runs

    await update.message.reply_text(f"Added {runs} bonus runs to Team {team}.")
    await save_game(chat_id, game)

async def cmd_penalty(update, context):
    chat_id = update.effective_chat.id
    user = update.effective_user
    args = context.args
    game = await get_game(chat_id)

    if user.id != game.get('host'):
        await update.message.reply_text("Only host can add penalty.")
        return

    if len(args) != 2:
        await update.message.reply_text("Usage: /penalty <A/B> <runs>")
        return

    team = args[0].upper()
    if team not in ['A', 'B']:
        await update.message.reply_text("Team must be A or B.")
        return

    try:
        runs = int(args[1])
    except:
        await update.message.reply_text("Runs must be a number.")
        return

    if 'penalty' not in game:
        game['penalty'] = {'A': 0, 'B': 0}
    game['penalty'][team] = game['penalty'].get(team, 0) + runs

    await update.message.reply_text(f"Added {runs} penalty runs to Team {team}.")
    await save_game(chat_id, game)

# --- Scoreboard ---

def get_total_score(game, team):
    base_runs = game.get('runs_' + team.lower(), 0)
    bonus = game.get('bonus', {}).get(team, 0)
    penalty = game.get('penalty', {}).get(team, 0)
    wickets = game.get('wickets_' + team.lower(), 0)
    total = base_runs + bonus - penalty
    return total, wickets

async def cmd_score(update, context):
    chat_id = update.effective_chat.id
    game = await get_game(chat_id)
    if not game:
        await update.message.reply_text("No active match.")
        return

    msg = "📊 *Scoreboard*\n\n"
    for team in ['A', 'B']:
        runs, wickets = get_total_score(game, team)
        overs = game.get('over', 0) - 1 + game.get('balls_in_over', 0) / 6
        msg += f"*Team {team}*\nRuns: {runs}\nWickets: {wickets}\nOvers: {overs:.1f}\n\n"

    await update.message.reply_text(msg, parse_mode='Markdown')

# --- Save and load game functions to be implemented separately ---
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# --- Voting system for Host Change ---

async def cmd_hostchange(update, context):
    chat_id = update.effective_chat.id
    user = update.effective_user
    game = await get_game(chat_id)
    if not game:
        await update.message.reply_text("No active match.")
        return

    players = game['team_A'] + game['team_B']
    if user.id not in players:
        await update.message.reply_text("Only players in teams can call host change.")
        return

    if game.get('host_change_vote_started'):
        await update.message.reply_text("Host change voting already in progress.")
        return

    game['host_change_votes'] = set()
    game['host_change_vote_started'] = True
    game['host_change_initiator'] = user.id
    await save_game(chat_id, game)

    keyboard = [
        [InlineKeyboardButton("Confirm Host Change", callback_data="hostchange_confirm"),
         InlineKeyboardButton("Cancel", callback_data="hostchange_cancel")]
    ]
    await context.bot.send_message(chat_id, 
        f"{user.full_name} has requested to change the host. Current host: {game['host']}\n"
        "Players, please vote by pressing Confirm to approve host change.",
        reply_markup=InlineKeyboardMarkup(keyboard))

async def button_hostchange(update, context):
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat.id
    game = await get_game(chat_id)

    if not game or not game.get('host_change_vote_started'):
        await query.answer("No host change vote in progress.")
        return

    if query.data == "hostchange_confirm":
        if user.id in game.get('host_change_votes', set()):
            await query.answer("You have already voted.")
            return
        game['host_change_votes'].add(user.id)
        await save_game(chat_id, game)
        total_players = len(game['team_A']) + len(game['team_B'])
        votes_needed = min(5, total_players // 2)

        await query.answer(f"Vote counted. {len(game['host_change_votes'])}/{votes_needed} votes.")

        if len(game['host_change_votes']) >= votes_needed:
            old_host = game['host']
            game['host'] = game['host_change_initiator']
            game['host_change_vote_started'] = False
            game['host_change_votes'] = set()
            game['host_change_initiator'] = None
            await save_game(chat_id, game)
            await context.bot.send_message(chat_id, f"Host changed from {old_host} to {game['host']}")
    else:  # cancel
        if user.id != game['host_change_initiator']:
            await query.answer("Only the initiator can cancel the vote.")
            return
        game['host_change_vote_started'] = False
        game['host_change_votes'] = set()
        game['host_change_initiator'] = None
        await save_game(chat_id, game)
        await context.bot.send_message(chat_id, "Host change vote cancelled.")
        await query.answer("Vote cancelled.")

# --- End Match with Confirmation ---

async def cmd_endmatch(update, context):
    chat_id = update.effective_chat.id
    user = update.effective_user
    game = await get_game(chat_id)
    if not game:
        await update.message.reply_text("No active match.")
        return

    if user.id != game.get('host') and not await is_chat_admin(context.bot, chat_id, user.id):
        await update.message.reply_text("Only host or admin can end the match.")
        return

    keyboard = [
        [InlineKeyboardButton("Confirm End Match", callback_data="endmatch_confirm"),
         InlineKeyboardButton("Cancel", callback_data="endmatch_cancel")]
    ]
    await update.message.reply_text("Are you sure you want to end the match?", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_endmatch(update, context):
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat.id
    game = await get_game(chat_id)
    if not game:
        await query.answer("No active match.")
        return

    if query.data == "endmatch_confirm":
        if user.id != game.get('host') and not await is_chat_admin(context.bot, chat_id, user.id):
            await query.answer("Only host/admin can confirm.")
            return
        # End match logic
        await send_match_summary(context.bot, chat_id, game)
        await clear_game(chat_id)
        await query.message.reply_text("Match ended.")
        await query.answer()
    else:
        await query.message.reply_text("Match end cancelled.")
        await query.answer()

# --- Match summary with top performers ---

async def send_match_summary(bot, chat_id, game):
    # Example: gather top 3 batsmen and bowlers per team from game stats
    # Assuming game stores stats: runs, wickets, strike_rate etc per player

    msg = "🏏 *Match Summary*\n\n"

    for team in ['A', 'B']:
        msg += f"Team {team}:\n"
        batsmen_stats = game.get(f'batsmen_stats_{team}', {})
        bowlers_stats = game.get(f'bowlers_stats_{team}', {})

        top_batsmen = sorted(batsmen_stats.items(), key=lambda x: x[1]['runs'], reverse=True)[:3]
        top_bowlers = sorted(bowlers_stats.items(), key=lambda x: x[1]['wickets'], reverse=True)[:3]

        msg += "*Top Batsmen:*\n"
        for player_id, stats in top_batsmen:
            msg += f"Player {player_id}: {stats['runs']} runs\n"

        msg += "*Top Bowlers:*\n"
        for player_id, stats in top_bowlers:
            msg += f"Player {player_id}: {stats['wickets']} wickets\n"

        total_runs, total_wickets = get_total_score(game, team)
        msg += f"Total Score: {total_runs}/{total_wickets}\n\n"

    # Winner logic
    team_a_runs, _ = get_total_score(game, 'A')
    team_b_runs, _ = get_total_score(game, 'B')
    if team_a_runs > team_b_runs:
        margin = team_a_runs - team_b_runs
        msg += f"🏆 Team A won by {margin} runs!"
    elif team_b_runs > team_a_runs:
        msg += f"🏆 Team B won by chasing the target!"
    else:
        msg += "Match drawn."

    await bot.send_message(chat_id, msg, parse_mode='Markdown')

# --- /guide Command ---

async def cmd_guide(update, context):
    text = (
        "📜 *Game Commands Guide:*\n\n"
        "/start - Register yourself for the bot\n"
        "/cclgroup - Host starts a Group vs Group match\n"
        "/addA @user/id - Add player to Team A\n"
        "/addB @user/id - Add player to Team B\n"
        "/removeA <index> - Remove player from Team A\n"
        "/removeB <index> - Remove player from Team B\n"
        "/CapA <index> - Assign captain of Team A\n"
        "/CapB <index> - Assign captain of Team B\n"
        "/team - Show current teams\n"
        "/toss - Start toss (Captain chooses Heads/Tails)\n"
        "/bat <index> - Choose batsman by index\n"
        "/bowl <index> - Choose bowler by index\n"
        "/setovers <number> - Set number of overs before match\n"
        "/hostchange - Request host change vote\n"
        "/endmatch - End current match (host/admin only)\n"
        "/bonus <A/B> <runs> - Add bonus runs\n"
        "/penalty <A/B> <runs> - Add penalty runs\n"
        "/retiredhurt <role> <index> - Retire hurt player\n"
        "/retiredout <role> <index> - Retire out player\n"
        "/inningswap - End first innings, start second innings\n"
        "/score - Show current full scoreboard\n"
        "/guide - Show this guide\n"
    )
    await update.message.reply_text(text, parse_mode='Markdown')

# --- Helper function to check admin ---

async def is_chat_admin(bot, chat_id, user_id):
    member = await bot.get_chat_member(chat_id, user_id)
    return member.status in ('administrator', 'creator')

# --- Register handlers in your main bot ---

from telegram.ext import CommandHandler, CallbackQueryHandler, MessageHandler, filters

# Start & Register User
async def cmd_start(update, context):
    user = update.effective_user
    # Save user in DB if not exists
    await update.message.reply_text(
        f"Welcome {user.full_name}! Use /cclgroup to start a group vs group match."
    )

# Initialize Group Match (/cclgroup)
async def cmd_cclgroup(update, context):
    chat_id = update.effective_chat.id
    user = update.effective_user
    # Create new game document in DB with host=user.id and empty teams
    await update.message.reply_text(
        "Match initialized. Host is you.\nUse /addA and /addB to add players."
    )
    # Send Team Join Status message or buttons if needed

# Add Player to Team A or B
async def cmd_addA(update, context):
    chat_id = update.effective_chat.id
    user = update.effective_user
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /addA @username or user_id")
        return
    player_id = await extract_user_id(args[0], context)
    # Add player_id to Team A in DB
    await update.message.reply_text(f"Added player {player_id} to Team A.")

async def cmd_addB(update, context):
    chat_id = update.effective_chat.id
    user = update.effective_user
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /addB @username or user_id")
        return
    player_id = await extract_user_id(args[0], context)
    # Add player_id to Team B in DB
    await update.message.reply_text(f"Added player {player_id} to Team B.")

# Remove Player from Team A or B by index
async def cmd_removeA(update, context):
    chat_id = update.effective_chat.id
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /removeA <index>")
        return
    idx = int(args[0]) - 1
    # Remove player at idx from Team A in DB
    await update.message.reply_text(f"Removed player #{idx+1} from Team A.")

async def cmd_removeB(update, context):
    chat_id = update.effective_chat.id
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /removeB <index>")
        return
    idx = int(args[0]) - 1
    # Remove player at idx from Team B in DB
    await update.message.reply_text(f"Removed player #{idx+1} from Team B.")

# Assign Captains
async def cmd_CapA(update, context):
    chat_id = update.effective_chat.id
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /CapA <index>")
        return
    idx = int(args[0]) - 1
    # Set Team A captain index in DB
    await update.message.reply_text(f"Player #{idx+1} is now captain of Team A.")

async def cmd_CapB(update, context):
    chat_id = update.effective_chat.id
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /CapB <index>")
        return
    idx = int(args[0]) - 1
    # Set Team B captain index in DB
    await update.message.reply_text(f"Player #{idx+1} is now captain of Team B.")

# Show Teams (/team)
async def cmd_team(update, context):
    chat_id = update.effective_chat.id
    game = await get_game(chat_id)
    if not game:
        await update.message.reply_text("No active match.")
        return
    msg = "*Team A:*\n"
    for i, p in enumerate(game['team_A'], 1):
        msg += f"{i}) {p}\n"
    msg += "\n*Team B:*\n"
    for i, p in enumerate(game['team_B'], 1):
        msg += f"{i}) {p}\n"
    await update.message.reply_text(msg, parse_mode='Markdown')

# Toss command
async def cmd_toss(update, context):
    chat_id = update.effective_chat.id
    game = await get_game(chat_id)
    if not game:
        await update.message.reply_text("No active match.")
        return
    # Send toss message with buttons for Team A captain (Heads/Tails)
    keyboard = [
        [InlineKeyboardButton("Heads", callback_data="toss_heads"),
         InlineKeyboardButton("Tails", callback_data="toss_tails")]
    ]
    await update.message.reply_text(
        "Toss time! Team A captain, choose Heads or Tails.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_toss(update, context):
    query = update.callback_query
    # handle toss logic here (coin flip, winner, ask bat/bowl)
    await query.answer()

# Bat and Bowl selection
async def cmd_bat(update, context):
    chat_id = update.effective_chat.id
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /bat <player_index>")
        return
    # update striker/non-striker batsman
    await update.message.reply_text(f"Batsman selected: Player #{args[0]}")

async def cmd_bowl(update, context):
    chat_id = update.effective_chat.id
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /bowl <player_index>")
        return
    # update bowler
    await update.message.reply_text(f"Bowler selected: Player #{args[0]}")

# Set Overs
async def cmd_setovers(update, context):
    chat_id = update.effective_chat.id
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /setovers <number>")
        return
    overs = int(args[0])
    # Save overs in game data
    await update.message.reply_text(f"Overs set to {overs}.")

# Bonus & Penalty
async def cmd_bonus(update, context):
    chat_id = update.effective_chat.id
    args = context.args
    if len(args) < 2 or args[0] not in ['A','B'] or not args[1].isdigit():
        await update.message.reply_text("Usage: /bonus <A/B> <runs>")
        return
    team = args[0]
    runs = int(args[1])
    # Add bonus runs to team score
    await update.message.reply_text(f"Added {runs} bonus runs to Team {team}.")

async def cmd_penalty(update, context):
    chat_id = update.effective_chat.id
    args = context.args
    if len(args) < 2 or args[0] not in ['A','B'] or not args[1].isdigit():
        await update.message.reply_text("Usage: /penalty <A/B> <runs>")
        return
    team = args[0]
    runs = int(args[1])
    # Subtract penalty runs from team score
    await update.message.reply_text(f"Applied {runs} penalty runs to Team {team}.")

# Retired Hurt/Out
async def cmd_retiredhurt(update, context):
    chat_id = update.effective_chat.id
    args = context.args
    # Expect: role (batsman/nonstriker/bowler/lms), index
    if len(args) < 2 or args[1].isdigit() is False:
        await update.message.reply_text("Usage: /retiredhurt <role> <index>")
        return
    role = args[0].lower()
    idx = int(args[1]) - 1
    # Mark player retired hurt in DB, update game state
    await update.message.reply_text(f"{role.title()} #{idx+1} marked as Retired Hurt.")

async def cmd_retiredout(update, context):
    chat_id = update.effective_chat.id
    args = context.args
    if len(args) < 2 or args[1].isdigit() is False:
        await update.message.reply_text("Usage: /retiredout <role> <index>")
        return
    role = args[0].lower()
    idx = int(args[1]) - 1
    # Mark player retired out, add wicket
    await update.message.reply_text(f"{role.title()} #{idx+1} marked as Retired Out.")

# Innings swap
async def cmd_inningswap(update, context):
    chat_id = update.effective_chat.id
    # Swap innings logic, reset striker/non-striker/bowler as needed
    await update.message.reply_text("Innings swapped. Second innings started.")

# Scoreboard display (full)
async def cmd_score(update, context):
    chat_id = update.effective_chat.id
    game = await get_game(chat_id)
    if not game:
        await update.message.reply_text("No active match.")
        return
    # Build and send full scoreboard message
    scoreboard = build_scoreboard(game)
    await update.message.reply_text(scoreboard, parse_mode='Markdown')

# Helper for user id extraction (handle @username or user_id)
async def extract_user_id(arg, context):
    if arg.startswith("@"):
        user = await context.bot.get_chat(arg)
        return user.id
    try:
        return int(arg)
    except:
        return None

# Helper function for building scoreboard (implement yourself)
def build_scoreboard(game):
    # build a neat formatted scoreboard string
    return "Full scoreboard will be here."

# Register all handlers:

def register_all_handlers(dispatcher):
    dispatcher.add_handler(CommandHandler("start", cmd_start))
    dispatcher.add_handler(CommandHandler("cclgroup", cmd_cclgroup))
    dispatcher.add_handler(CommandHandler("addA", cmd_addA))
    dispatcher.add_handler(CommandHandler("addB", cmd_addB))
    dispatcher.add_handler(CommandHandler("removeA", cmd_removeA))
    dispatcher.add_handler(CommandHandler("removeB", cmd_removeB))
    dispatcher.add_handler(CommandHandler("CapA", cmd_CapA))
    dispatcher.add_handler(CommandHandler("CapB", cmd_CapB))
    dispatcher.add_handler(CommandHandler("team", cmd_team))
    dispatcher.add_handler(CommandHandler("toss", cmd_toss))
    dispatcher.add_handler(CallbackQueryHandler(button_toss, pattern="toss_.*"))
    dispatcher.add_handler(CommandHandler("bat", cmd_bat))
    dispatcher.add_handler(CommandHandler("bowl", cmd_bowl))
    dispatcher.add_handler(CommandHandler("setovers", cmd_setovers))
    dispatcher.add_handler(CommandHandler("bonus", cmd_bonus))
    dispatcher.add_handler(CommandHandler("penalty", cmd_penalty))
    dispatcher.add_handler(CommandHandler("retiredhurt", cmd_retiredhurt))
    dispatcher.add_handler(CommandHandler("retiredout", cmd_retiredout))
    dispatcher.add_handler(CommandHandler("inningswap", cmd_inningswap))
    dispatcher.add_handler(CommandHandler("score", cmd_score))
    dispatcher.add_handler(CommandHandler("guide", cmd_guide))
    # Add Part 6 handlers here as well:
    dispatcher.add_handler(CommandHandler("hostchange", cmd_hostchange))
    dispatcher.add_handler(CallbackQueryHandler(button_hostchange, pattern="hostchange_.*"))
    dispatcher.add_handler(CommandHandler("endmatch", cmd_endmatch))
    dispatcher.add_handler(CallbackQueryHandler(button_endmatch, pattern="endmatch_.*"))
