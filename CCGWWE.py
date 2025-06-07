import logging
import asyncio
from datetime import datetime, timedelta
from pymongo import MongoClient
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackContext,
)

# === CONFIG ===
BOT_TOKEN = "8133604799:AAF2dE86UjRxfAdUcqyoz3O9RgaCeTwaoHM"
MONGO_URL = "mongodb://mongo:GhpHMiZizYnvJfKIQKxoDbRyzBCpqEyC@mainline.proxy.rlwy.net:54853"

# === LOGGING ===
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# === MONGODB SETUP ===
client = MongoClient(MONGO_URL)
db = client['mafia_game_db']
games_col = db['games']
users_col = db['users']

# === ROLE DEFINITIONS ===
ROLES = {
    'don': {
        'name': '🤵🏻 Don',
        'team': 'mafia',
        'summary': "You are the Don, leader of the Mafia. Your vote overrides the Mafia's vote.",
    },
    'mafia': {
        'name': '🤵🏼 Mafia',
        'team': 'mafia',
        'summary': "You are a Mafia member. Work with your team to eliminate the town.",
    },
    'framer': {
        'name': '🕵️‍♂️ Framer',
        'team': 'mafia',
        'summary': "You can frame a player each night to confuse the Detective.",
    },
    'detective': {
        'name': '🕵️‍ Detective',
        'team': 'town',
        'summary': "Each night, you can Check or Kill a player.",
    },
    'doctor': {
        'name': '👨🏼‍⚕️ Doctor',
        'team': 'town',
        'summary': "You can save someone each night. Self-save allowed only once.",
    },
    'follower': {
        'name': '🤞 Lucky',
        'team': 'town',
        'summary': "You are a Lucky follower who can survive a kill once.",
    },
    'townie': {
        'name': '👨🏼 Townie',
        'team': 'town',
        'summary': "You are a regular townsperson. Help find the Mafia!",
    },
}

# === GAME STATES ===
STATE_WAITING = "waiting"  # Waiting for registration
STATE_NIGHT = "night"      # Night phase
STATE_DAY = "day"          # Day phase - discussion & voting
STATE_ENDED = "ended"      # Game ended

# === NIGHT PHASE TIMER SECONDS ===
NIGHT_DURATION = 45
DAY_VOTING_DURATION = 45
LYNCH_CONFIRM_DURATION = 30

# === UTILITIES ===
def format_player_mention(user_id: int, name: str) -> str:
    return f"[{name}](tg://user?id={user_id})"

def get_role_summary(role_key: str) -> str:
    role = ROLES.get(role_key, {})
    return role.get('summary', '')

# === GAME DATA STRUCTURE SAMPLE ===
# game = {
#   'chat_id': int,
#   'state': STATE_WAITING|STATE_NIGHT|STATE_DAY|STATE_ENDED,
#   'players': { user_id: { 'name': str, 'role': str, 'alive': bool, 'saved_self': bool, 'vote': None or user_id } },
#   'mafia_chat_id': None or int,
#   'night_actions': { 'detective': { 'action': 'check' or 'kill', 'target': user_id }, 'doctor': user_id or None, 'framer': user_id or None, 'mafia_votes': {user_id: target_id} },
#   'votes': { voter_id: target_id },  # For lynching phase
#   ...
# }

# === APPLICATION SETUP ===
app = ApplicationBuilder().token(BOT_TOKEN).build()

# --- More handlers and logic in next parts ---
# === GLOBAL VARIABLES ===
active_games = {}  # chat_id: game_data

# === COMMAND HANDLERS ===

async def start_mafia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("This command can only be used in group chats.")
        return

    if chat.id in active_games and active_games[chat.id]['state'] != STATE_ENDED:
        await update.message.reply_text("A game is already active in this group.")
        return

    # Initialize game data
    game_data = {
        'chat_id': chat.id,
        'state': STATE_WAITING,
        'players': {},
        'mafia_chat_id': None,
        'night_actions': {
            'detective': {},
            'doctor': None,
            'framer': None,
            'mafia_votes': {}
        },
        'votes': {},
        'lynch_confirmation': None,
        'lynch_votes': {},
        'start_time': datetime.utcnow(),
    }

    active_games[chat.id] = game_data

    await update.message.reply_text(
        "A new Mafia game has started! Players can register by sending /join to the bot in private chat."
    )

async def join_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    user_name = user.full_name

    # Find all active games where registration is open and user not joined yet
    games = [g for g in active_games.values() if g['state'] == STATE_WAITING and user_id not in g['players']]
    if not games:
        await update.message.reply_text(
            "No active game available for registration currently."
        )
        return

    # For simplicity, join the first available game
    game = games[0]
    game['players'][user_id] = {
        'name': user_name,
        'role': None,
        'alive': True,
        'saved_self': False,
        'vote': None,
    }

    await update.message.reply_text(
        f"You have successfully joined the Mafia game in group {game['chat_id']}.\n"
        "Please wait for the game to start."
    )

    # Notify group
    group_chat_id = game['chat_id']
    try:
        await context.bot.send_message(
            chat_id=group_chat_id,
            text=f"{user_name} has joined the game! Total players: {len(game['players'])}"
        )
    except Exception as e:
        logger.error(f"Failed to notify group about new join: {e}")

# --- More handlers like /cancel, role assignment, night actions etc will be in next parts ---
# === CONTINUED: ROLE ASSIGNMENT AND GAME START ===

async def assign_roles(game_data):
    players = list(game_data['players'].keys())
    total_players = len(players)

    # Role distribution based on player count (example)
    # You can customize roles and counts here
    roles_distribution = []

    # Basic example for 8 players:
    # 1 Don, 2 Mafia, 1 Framer, 1 Detective, 1 Doctor, rest Townie
    if total_players < 6:
        # Minimum players condition
        roles_distribution = ['Don', 'Mafia', 'Detective', 'Doctor']
        roles_distribution += ['Townie'] * (total_players - len(roles_distribution))
    else:
        roles_distribution = ['Don', 'Mafia', 'Mafia', 'Framer', 'Detective', 'Doctor']
        roles_distribution += ['Townie'] * (total_players - len(roles_distribution))

    random.shuffle(roles_distribution)
    random.shuffle(players)

    for i, user_id in enumerate(players):
        game_data['players'][user_id]['role'] = roles_distribution[i]

async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.id not in active_games:
        await update.message.reply_text("No active game in this group. Use /startmafia to start a new game.")
        return

    game = active_games[chat.id]

    if game['state'] != STATE_WAITING:
        await update.message.reply_text("Game already started or ended.")
        return

    if len(game['players']) < 4:
        await update.message.reply_text("Need at least 4 players to start the game.")
        return

    # Assign roles
    await assign_roles(game)

    # Update game state
    game['state'] = STATE_NIGHT

    # Send role messages to each player privately
    for user_id, pdata in game['players'].items():
        try:
            role = pdata['role']
            member_name = pdata['name']

            text = f"Your role is: {role}\n"

            if role in ['Don', 'Mafia', 'Framer']:
                # Show team members
                mafia_members = [p['name'] for p in game['players'].values() if p['role'] in ['Don', 'Mafia', 'Framer'] and p != pdata]
                text += "Remember your team members:\n"
                for m in mafia_members:
                    text += f"  {m}\n"

            await context.bot.send_message(chat_id=user_id, text=text)
        except Exception as e:
            logger.error(f"Error sending role DM: {e}")

    await context.bot.send_message(chat_id=chat.id, text="Game started! Night phase begins. All players check your DMs.")

    # Start night phase logic here (in next parts)

# Handler registration for /startgame command
# This will be called by admin or after enough players join
# === NIGHT PHASE HANDLING ===

async def send_night_actions(game, context):
    """
    Send DM messages to players to perform their night actions.
    Roles with actions: Detective, Doctor, Mafia, Framer, Watcher (if implemented)
    """
    for user_id, pdata in game['players'].items():
        role = pdata['role']
        if not pdata.get('alive', True):
            continue  # skip dead players

        if role == 'Detective':
            text = "Night phase: Choose your action.\nWhat do you want to do?"
            buttons = [
                [InlineKeyboardButton("Check", callback_data='detective_check')],
                [InlineKeyboardButton("Kill", callback_data='detective_kill')],
            ]
            await context.bot.send_message(user_id, text, reply_markup=InlineKeyboardMarkup(buttons))

        elif role == 'Doctor':
            text = "Night phase: Choose who to save."
            alive_players = [p for p in game['players'].values() if p.get('alive', True)]
            buttons = []
            for p in alive_players:
                buttons.append([InlineKeyboardButton(p['name'], callback_data=f'doctor_save_{p["user_id"]}')])
            await context.bot.send_message(user_id, text, reply_markup=InlineKeyboardMarkup(buttons))

        elif role in ['Don', 'Mafia', 'Framer']:
            text = "Night phase: Discuss with your Mafia team and choose someone to kill."
            # Mafia chat handled separately; for killing:
            alive_players = [p for p in game['players'].values() if p.get('alive', True) and p['user_id'] != user_id]
            buttons = []
            for p in alive_players:
                buttons.append([InlineKeyboardButton(p['name'], callback_data=f'mafia_kill_{p["user_id"]}')])
            await context.bot.send_message(user_id, text, reply_markup=InlineKeyboardMarkup(buttons))

        # Add other roles if needed...

# Placeholder function for handling callback queries for night actions
async def night_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    # Find game where user is playing
    game = None
    for g in active_games.values():
        if user_id in g['players']:
            game = g
            break
    if not game:
        await query.edit_message_text("You are not in an active game.")
        return

    pdata = game['players'][user_id]
    role = pdata['role']

    if data.startswith('detective_check'):
        # Send list of players to check
        alive_players = [p for p in game['players'].values() if p.get('alive', True) and p['user_id'] != user_id]
        buttons = [[InlineKeyboardButton(p['name'], callback_data=f'detective_check_target_{p["user_id"]}')] for p in alive_players]
        buttons.append([InlineKeyboardButton("Back", callback_data='detective_back')])
        await query.edit_message_text("Who will you check?", reply_markup=InlineKeyboardMarkup(buttons))

    elif data.startswith('detective_kill'):
        # Send list of players to kill
        alive_players = [p for p in game['players'].values() if p.get('alive', True) and p['user_id'] != user_id]
        buttons = [[InlineKeyboardButton(p['name'], callback_data=f'detective_kill_target_{p["user_id"]}')] for p in alive_players]
        buttons.append([InlineKeyboardButton("Back", callback_data='detective_back')])
        await query.edit_message_text("Who will you kill?", reply_markup=InlineKeyboardMarkup(buttons))

    elif data == 'detective_back':
        # Show main detective action buttons again
        buttons = [
            [InlineKeyboardButton("Check", callback_data='detective_check')],
            [InlineKeyboardButton("Kill", callback_data='detective_kill')],
        ]
        await query.edit_message_text("Choose your action:", reply_markup=InlineKeyboardMarkup(buttons))

    # Further handle target selection for detective check or kill
    elif data.startswith('detective_check_target_'):
        target_id = int(data.split('_')[-1])
        # Record detective check action
        game['night_actions'][user_id] = {'action': 'check', 'target': target_id}
        await query.edit_message_text(f"You chose to check {game['players'][target_id]['name']}.")
        # Send notification to group chat about detective action starting
        await context.bot.send_message(game['group_id'], "🕵️‍ Detective is looking for the criminals...")
        # Further logic to process after night ends...

    elif data.startswith('detective_kill_target_'):
        target_id = int(data.split('_')[-1])
        # Record detective kill action
        game['night_actions'][user_id] = {'action': 'kill', 'target': target_id}
        await query.edit_message_text(f"You chose to kill {game['players'][target_id]['name']}.")
        # Notify group chat
        await context.bot.send_message(game['group_id'], "🕵️‍ Detective has his weapons lock'n'loaded...")
        # Further logic...

    # Add callbacks for doctor save, mafia kill, framer framing similarly...

# You will continue this night actions resolution and then transition to day phase with voting
# === VOTING PHASE ===

async def start_voting_phase(game, context):
    """
    Sends voting message in group chat with inline button 'Vote' that opens bot DM.
    Voting lasts 45 seconds.
    """
    group_id = game['group_id']
    text = (
        "It's mob justice time! Vote for the most suspicious player.\n"
        "Voting will last 45 seconds."
    )
    vote_button = InlineKeyboardButton("Vote 🗳️", url=f"tg://user?id={context.bot.id}")
    keyboard = InlineKeyboardMarkup([[vote_button]])
    await context.bot.send_message(group_id, text, reply_markup=keyboard)
    # After sending, start timer for voting (could use asyncio sleep or job queue)

async def send_vote_dm(user_id, game, context):
    """
    Sends DM to user with buttons for alive players (except self) to vote for lynching.
    """
    alive_players = [p for p in game['players'].values() if p.get('alive', True) and p['user_id'] != user_id]
    buttons = [[InlineKeyboardButton(p['name'], callback_data=f'vote_{p["user_id"]}')] for p in alive_players]
    if not buttons:
        await context.bot.send_message(user_id, "No players available to vote for.")
        return
    await context.bot.send_message(user_id, "Time to seek the guilty!\nWho are you going to lynch?", reply_markup=InlineKeyboardMarkup(buttons))

async def vote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    voter_id = query.from_user.id
    data = query.data
    await query.answer()

    if not data.startswith("vote_"):
        await query.edit_message_text("Invalid vote action.")
        return

    voted_id = int(data.split('_')[1])
    # Find game of voter
    game = None
    for g in active_games.values():
        if voter_id in g['players']:
            game = g
            break
    if not game:
        await query.edit_message_text("You are not in an active game.")
        return

    # Record vote
    game.setdefault('votes', {})
    game['votes'][voter_id] = voted_id

    # Announce in group chat who voted for whom with tagged names
    group_id = game['group_id']
    voter_name = game['players'][voter_id]['name']
    voted_name = game['players'][voted_id]['name']

    mention_voter = f"[{voter_name}](tg://user?id={voter_id})"
    mention_voted = f"[{voted_name}](tg://user?id={voted_id})"
    msg = f"𝗩𝗢𝗧𝗘: {mention_voter} voted for {mention_voted}"
    await context.bot.send_message(group_id, msg, parse_mode=ParseMode.MARKDOWN)

    await query.edit_message_text(f"You voted for {voted_name}.")

async def tally_votes_and_confirm_lynch(game, context):
    """
    After voting ends, tally votes and find the player with most votes.
    Send confirmation message with 👍 and 👎 buttons in group chat.
    Voting for lynch confirmation lasts 30 seconds.
    """
    votes = game.get('votes', {})
    if not votes:
        await context.bot.send_message(game['group_id'], "No votes were cast. No lynching today.")
        return

    # Count votes for each player
    vote_counts = {}
    for voted_id in votes.values():
        vote_counts[voted_id] = vote_counts.get(voted_id, 0) + 1

    # Find max voted player(s)
    max_votes = max(vote_counts.values())
    candidates = [pid for pid, c in vote_counts.items() if c == max_votes]
    if len(candidates) > 1:
        # Tie - no lynch
        await context.bot.send_message(game['group_id'], "The citizens couldn't come up with a decision... They dispersed, lynching nobody today...")
        return

    lynch_id = candidates[0]
    lynch_name = game['players'][lynch_id]['name']
    # Prepare confirmation message
    text = f"Are you sure about lynching {lynch_name}?"
    buttons = [
        [
            InlineKeyboardButton(f"👍 0", callback_data=f'confirm_lynch_yes_{lynch_id}'),
            InlineKeyboardButton(f"👎 0", callback_data=f'confirm_lynch_no_{lynch_id}')
        ]
    ]
    message = await context.bot.send_message(game['group_id'], text, reply_markup=InlineKeyboardMarkup(buttons))
    # Store confirmation voting data
    game['lynch_confirmation'] = {
        'message_id': message.message_id,
        'yes_votes': set(),
        'no_votes': set(),
        'lynch_id': lynch_id,
        'group_id': game['group_id']
    }

async def lynch_confirmation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    # Parse callback data: confirm_lynch_yes_12345 or confirm_lynch_no_12345
    parts = data.split('_')
    if len(parts) != 4:
        await query.edit_message_text("Invalid lynch confirmation data.")
        return

    vote_type = parts[2]  # 'yes' or 'no'
    lynch_id = int(parts[3])

    # Find game by group id and message id
    game = None
    for g in active_games.values():
        if g.get('lynch_confirmation') and g['lynch_confirmation']['lynch_id'] == lynch_id:
            game = g
            break
    if not game:
        await query.edit_message_text("No lynch confirmation active.")
        return

    conf = game['lynch_confirmation']
    if user_id in conf['yes_votes'] or user_id in conf['no_votes']:
        await query.answer("You already voted in lynch confirmation.", show_alert=True)
        return

    if vote_type == 'yes':
        conf['yes_votes'].add(user_id)
    else:
        conf['no_votes'].add(user_id)

    # Update button text with counts
    yes_count = len(conf['yes_votes'])
    no_count = len(conf['no_votes'])
    buttons = [
        [
            InlineKeyboardButton(f"👍 {yes_count}", callback_data=f'confirm_lynch_yes_{lynch_id}'),
            InlineKeyboardButton(f"👎 {no_count}", callback_data=f'confirm_lynch_no_{lynch_id}')
        ]
    ]
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(buttons))

    # Check if time or majority reached
    # For simplicity, no timer here, you can implement job queue to end voting after 30s
    # Here just a placeholder to call function when enough votes gathered or time elapsed

    # If yes votes > no votes => lynch
    # else no lynch and announce accordingly

    # This function to be called externally after 30 seconds or votes threshold

async def finalize_lynch(game, context):
    conf = game.get('lynch_confirmation')
    if not conf:
        return
    yes = len(conf['yes_votes'])
    no = len(conf['no_votes'])
    lynch_id = conf['lynch_id']
    lynch_name = game['players'][lynch_id]['name']

    if yes > no:
        # Lynch player
        game['players'][lynch_id]['alive'] = False
        role = game['players'][lynch_id]['role']
        # Announce lynch
        text = f"𝗟𝗬𝗡𝗖𝗛𝗘𝗗: {lynch_name} was a {role}."
        await context.bot.send_message(game['group_id'], text)
    else:
        text = f"The citizens couldn't come up with a decision ({yes} 👍 | {no} 👎)... They dispersed, lynching nobody today..."
        await context.bot.send_message(game['group_id'], text)
    # Clean up confirmation data
    game['lynch_confirmation'] = None
    # === MAFIA NIGHT CHAT ===

async def mafia_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Receive mafia chat messages from mafia members in DM and forward to other mafia members with sender name.
    """
    user_id = update.message.from_user.id
    # Find game and check if user is mafia/don/framer and alive
    game = None
    for g in active_games.values():
        p = g['players'].get(user_id)
        if p and p.get('alive', True) and p['role'] in ['Don', 'Mafia', 'Framer']:
            game = g
            break
    if not game:
        await update.message.reply_text("You are not part of any active mafia group or not alive.")
        return

    sender_name = game['players'][user_id]['name']
    text = update.message.text

    # Forward message to all mafia team except sender
    for pid, pdata in game['players'].items():
        if pdata.get('alive', True) and pdata['role'] in ['Don', 'Mafia', 'Framer'] and pid != user_id:
            try:
                await context.bot.send_message(pid, f"ᎠᎪᏃᎪᎥ {sender_name}: {text}")
            except Exception as e:
                print(f"Failed to send mafia chat to {pid}: {e}")

# === ROLE ACTIONS BUTTONS ===

def get_role_action_buttons(role, game):
    """
    Return InlineKeyboardMarkup for role-specific actions during night phase.
    """
    alive_players = [p for p in game['players'].values() if p.get('alive', True)]

    buttons = []
    if role == 'Doctor':
        # Doctor picks one to save
        for p in alive_players:
            buttons.append([InlineKeyboardButton(p['name'], callback_data=f'doc_save_{p["user_id"]}')])
    elif role == 'Watcher':
        # Watcher picks one to watch
        for p in alive_players:
            buttons.append([InlineKeyboardButton(p['name'], callback_data=f'watch_{p["user_id"]}')])
    elif role == 'Framer':
        # Framer picks one to frame
        for p in alive_players:
            buttons.append([InlineKeyboardButton(p['name'], callback_data=f'frame_{p["user_id"]}')])
    elif role == 'Detective':
        # Detective action is handled separately (check/kill choice)
        buttons = []  # Will be dynamic in callback handlers
    else:
        buttons = []

    return InlineKeyboardMarkup(buttons) if buttons else None

# === NIGHT ACTION CALLBACKS ===

async def doctor_save_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    if not data.startswith('doc_save_'):
        await query.edit_message_text("Invalid doctor action.")
        return

    target_id = int(data.split('_')[2])
    # Find game and verify user is doctor and alive
    game = None
    for g in active_games.values():
        p = g['players'].get(user_id)
        if p and p.get('alive', True) and p['role'] == 'Doctor':
            game = g
            break
    if not game:
        await query.edit_message_text("You are not the doctor or not alive.")
        return

    # Record save target
    game['night_actions'] = game.get('night_actions', {})
    game['night_actions']['doctor_save'] = target_id

    await query.edit_message_text(f"You chose to save {game['players'][target_id]['name']} tonight.")

async def watcher_watch_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    if not data.startswith('watch_'):
        await query.edit_message_text("Invalid watcher action.")
        return

    target_id = int(data.split('_')[1])
    # Find game and verify user is watcher and alive
    game = None
    for g in active_games.values():
        p = g['players'].get(user_id)
        if p and p.get('alive', True) and p['role'] == 'Watcher':
            game = g
            break
    if not game:
        await query.edit_message_text("You are not the watcher or not alive.")
        return

    game['night_actions'] = game.get('night_actions', {})
    game['night_actions']['watcher_watch'] = target_id

    await query.edit_message_text(f"You chose to watch {game['players'][target_id]['name']} tonight.")

async def framer_frame_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    if not data.startswith('frame_'):
        await query.edit_message_text("Invalid framer action.")
        return

    target_id = int(data.split('_')[1])
    # Find game and verify user is framer and alive
    game = None
    for g in active_games.values():
        p = g['players'].get(user_id)
        if p and p.get('alive', True) and p['role'] == 'Framer':
            game = g
            break
    if not game:
        await query.edit_message_text("You are not the framer or not alive.")
        return

    game['night_actions'] = game.get('night_actions', {})
    game['night_actions']['framer_frame'] = target_id

    await query.edit_message_text(f"You chose to frame {game['players'][target_id]['name']} tonight.")

# === DETECTIVE CHECK/KILL FLOW ===

async def detective_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Detective receives buttons to choose Check or Kill.
    """
    user_id = update.message.from_user.id
    # Find game and verify user is detective and alive
    game = None
    for g in active_games.values():
        p = g['players'].get(user_id)
        if p and p.get('alive', True) and p['role'] == 'Detective':
            game = g
            break
    if not game:
        await update.message.reply_text("You are not the detective or not alive.")
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Check 🕵️‍♂️", callback_data="det_check")],
        [InlineKeyboardButton("Kill 🔪", callback_data="det_kill")]
    ])
    await update.message.reply_text("Choose your action:", reply_markup=keyboard)

async def detective_action_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    if data not in ("det_check", "det_kill"):
        await query.edit_message_text("Invalid detective action.")
        return

    # Find game
    game = None
    for g in active_games.values():
        p = g['players'].get(user_id)
        if p and p.get('alive', True) and p['role'] == 'Detective':
            game = g
            break
    if not game:
        await query.edit_message_text("You are not the detective or not alive.")
        return

    alive_players = [p for p in game['players'].values() if p.get('alive', True) and p['user_id'] != user_id]

    buttons = [[InlineKeyboardButton(p['name'], callback_data=f"det_target_{data}_{p['user_id']}")] for p in alive_players]
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="det_back")])

    await query.edit_message_text("Select a target:", reply_markup=InlineKeyboardMarkup(buttons))

async def detective_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await detective_start(update, context)

async def detective_target_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    # data format: det_target_det_check_userid or det_target_det_kill_userid
    parts = data.split('_')
    if len(parts) != 4:
        await query.edit_message_text("Invalid target selection.")
        return

    action = parts[2]  # det_check or det_kill
    target_id = int(parts[3])

    # Find game and verify detective
    game = None
    for g in active_games.values():
        p = g['players'].get(user_id)
        if p and p.get('alive', True) and p['role'] == 'Detective':
            game = g
            break
    if not game:
        await query.edit_message_text("You are not the detective or not alive.")
        return

    if action == 'det_check':
        target_role = game['players'][target_id]['role']
        # Maybe fake framing info if framer targeted them
        framed_id = game.get('night_actions', {}).get('framer_frame')
        if framed_id == target_id:
            target_role = "Mafia"  # Framed as mafia
        await query.edit_message_text(f"{game['players'][target_id]['name']} is a {target_role}.")
        # Record detective check action for game logs or future usage
        game.setdefault('night_actions', {})['detective_check'] = target_id
    else:
        # Kill action
        game.setdefault('night_actions', {})['detective_kill'] = target_id
        await query.edit_message_text(f"You decided to kill {game['players'][target_id]['name']} tonight.")

# === END OF PART 6 ===
# === NIGHT PHASE PROCESSING ===

async def process_night_phase(context: ContextTypes.DEFAULT_TYPE):
    """
    After night actions are collected or time runs out,
    process all night actions and update game state.
    """
    for game_id, game in list(active_games.items()):
        night_actions = game.get('night_actions', {})

        # Variables to track night deaths and saves
        death_candidates = []

        # Mafia kill - for simplicity, mafia collectively choose one target (could be enhanced)
        mafia_target = night_actions.get('mafia_kill')
        if mafia_target:
            death_candidates.append(mafia_target)

        # Detective kill
        det_kill = night_actions.get('detective_kill')
        if det_kill:
            death_candidates.append(det_kill)

        # Doctor save
        doctor_save = night_actions.get('doctor_save')

        # Framer target - no death, but may affect detective results
        # Watcher watch - no death

        # Resolve deaths after doctor save
        final_deaths = []
        for candidate in death_candidates:
            if candidate != doctor_save:
                final_deaths.append(candidate)

        # Mark players as dead
        for pid in final_deaths:
            if pid in game['players']:
                game['players'][pid]['alive'] = False

        # Compose night summary message
        messages = []
        if final_deaths:
            death_names = [game['players'][pid]['name'] for pid in final_deaths]
            messages.append(f"🌙 Night ended. The following players died: {', '.join(death_names)}")
        else:
            messages.append("🌙 Night ended peacefully. No deaths tonight.")

        # Send night summary to group
        try:
            await context.bot.send_message(game_id, "\n".join(messages))
        except Exception as e:
            print(f"Failed to send night summary to group {game_id}: {e}")

        # Clear night actions for next night
        game['night_actions'] = {}

        # Check for win conditions after night
        winner = check_win_conditions(game)
        if winner:
            await announce_winner(game, context)

        else:
            # Proceed to day phase or voting phase as needed
            await start_day_phase(game, context)

# === WIN CONDITION CHECK ===

def check_win_conditions(game):
    """
    Check if either Town (good guys) or Mafia side won.
    Return winner string: 'Town' or 'Mafia' or None
    """
    alive_players = [p for p in game['players'].values() if p.get('alive', True)]
    mafia_alive = [p for p in alive_players if p['role'] in ['Don', 'Mafia', 'Framer']]
    town_alive = [p for p in alive_players if p['role'] not in ['Don', 'Mafia', 'Framer']]

    # Town wins if all mafia are dead
    if not mafia_alive:
        return 'Town'

    # Mafia wins if mafia >= town
    if len(mafia_alive) >= len(town_alive):
        return 'Mafia'

    return None

async def announce_winner(game, context: ContextTypes.DEFAULT_TYPE):
    """
    Announce game winner in group and end game.
    """
    winner = check_win_conditions(game)
    group_id = game['group_id']
    text = f"🏆 Game Over! The {winner} team has won!\n\nFinal roles:\n"
    for p in game['players'].values():
        status = "Alive" if p.get('alive', True) else "Dead"
        text += f"- {p['name']} ({p['role']}) - {status}\n"

    await context.bot.send_message(group_id, text)
    # Optionally reward winners here (e.g. add coins)

    # Remove game from active_games
    active_games.pop(group_id, None)

async def start_day_phase(game, context: ContextTypes.DEFAULT_TYPE):
    """
    Send message to group that day has started and voting begins.
    """
    group_id = game['group_id']
    await context.bot.send_message(group_id, "☀️ Day has started! Discuss and prepare to vote out suspects. Use /vote command or buttons.")

# === VOTING PHASE ===

async def vote_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle /vote command: send inline buttons for alive players to vote.
    """
    group_id = update.effective_chat.id
    game = active_games.get(group_id)
    if not game:
        await update.message.reply_text("No active game in this group.")
        return

    alive_players = [p for p in game['players'].values() if p.get('alive', True)]

    buttons = [[InlineKeyboardButton(p['name'], callback_data=f"vote_{p['user_id']}")] for p in alive_players]
    reply_markup = InlineKeyboardMarkup(buttons)
    await update.message.reply_text("Vote to lynch a player:", reply_markup=reply_markup)

async def vote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle voting button presses, tally votes.
    """
    query = update.callback_query
    voter_id = query.from_user.id
    data = query.data
    await query.answer()

    if not data.startswith("vote_"):
        await query.edit_message_text("Invalid vote.")
        return

    target_id = int(data.split('_')[1])
    group_id = query.message.chat.id
    game = active_games.get(group_id)
    if not game:
        await query.edit_message_text("No active game found.")
        return

    # Check voter is alive
    if voter_id not in game['players'] or not game['players'][voter_id].get('alive', True):
        await query.edit_message_text("You are not alive in the game and cannot vote.")
        return

    # Record vote
    game.setdefault('votes', {})
    game['votes'][voter_id] = target_id

    await query.edit_message_text(f"Your vote for {game['players'][target_id]['name']} has been recorded.")

    # Optionally, if all alive players voted, tally votes immediately
    alive_voters = [p['user_id'] for p in game['players'].values() if p.get('alive', True)]
    if all(v in game['votes'] for v in alive_voters):
        await tally_votes(group_id, game, context)

async def tally_votes(group_id, game, context: ContextTypes.DEFAULT_TYPE):
    """
    Count votes and lynch player with highest votes.
    """
    from collections import Counter
    vote_counts = Counter(game.get('votes', {}).values())
    if not vote_counts:
        await context.bot.send_message(group_id, "No votes cast this day.")
        return

    max_votes = max(vote_counts.values())
    candidates = [pid for pid, count in vote_counts.items() if count == max_votes]

    # If tie, no one lynched
    if len(candidates) > 1:
        await context.bot.send_message(group_id, "Tie in votes. No one is lynched today.")
    else:
        lynched_id = candidates[0]
        game['players'][lynched_id]['alive'] = False
        await context.bot.send_message(group_id, f"🔨 {game['players'][lynched_id]['name']} has been lynched!")

    # Clear votes for next day
    game['votes'] = {}

    # Check win condition after lynch
    winner = check_win_conditions(game)
    if winner:
        await announce_winner(game, context)
    else:
        # Start next night phase or continue game
        await context.bot.send_message(group_id, "Night will fall soon... Prepare for night actions.")

# === MAIN FUNCTION AND HANDLERS SETUP ===

def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Command handlers
    application.add_handler(CommandHandler('start_mafia', start_mafia_command))
    application.add_handler(CommandHandler('cancel', cancel_command))
    application.add_handler(CommandHandler('vote', vote_command))
    application.add_handler(CommandHandler('detective', detective_start))

    # Message handlers
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, mafia_chat))

    # Callback query handlers
    application.add_handler(CallbackQueryHandler(doctor_save_callback, pattern=r'^doc_save_'))
    application.add_handler(CallbackQueryHandler(watcher_watch_callback, pattern=r'^watch_'))
    application.add_handler(CallbackQueryHandler(framer_frame_callback, pattern=r'^frame_'))
    application.add_handler(CallbackQueryHandler(detective_action_choice_callback, pattern=r'^det_(check|kill)$'))
    application.add_handler(CallbackQueryHandler(detective_target_callback, pattern=r'^det_target_'))
    application.add_handler(CallbackQueryHandler(detective_back_callback, pattern=r'^det_back$'))
    application.add_handler(CallbackQueryHandler(vote_callback, pattern=r'^vote_'))

    # Start polling
    application.run_polling()

if __name__ == '__main__':
    main()
# === CALLBACKS FOR SPECIAL ROLES ===

async def doctor_save_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data  # format: doc_save_<target_user_id>
    target_id = int(data.split('_')[-1])
    await query.answer()

    # Validate doctor role and alive
    group_id = find_game_by_user(user_id)
    if not group_id:
        await query.edit_message_text("You are not in any active game.")
        return
    game = active_games[group_id]
    player = game['players'].get(user_id)
    if not player or player['role'] != 'Doctor' or not player.get('alive', True):
        await query.edit_message_text("You cannot perform this action.")
        return

    # Save the target for doctor save
    game.setdefault('night_actions', {})
    game['night_actions']['doctor_save'] = target_id

    await query.edit_message_text(f"You have decided to save {game['players'][target_id]['name']} tonight.")

async def watcher_watch_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data  # format: watch_<target_user_id>
    target_id = int(data.split('_')[-1])
    await query.answer()

    # Validate watcher role and alive
    group_id = find_game_by_user(user_id)
    if not group_id:
        await query.edit_message_text("You are not in any active game.")
        return
    game = active_games[group_id]
    player = game['players'].get(user_id)
    if not player or player['role'] != 'Watcher' or not player.get('alive', True):
        await query.edit_message_text("You cannot perform this action.")
        return

    # Save the target for watcher watch
    game.setdefault('night_actions', {})
    game['night_actions']['watcher_watch'] = target_id

    await query.edit_message_text(f"You have decided to watch {game['players'][target_id]['name']} tonight.")

async def framer_frame_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data  # format: frame_<target_user_id>
    target_id = int(data.split('_')[-1])
    await query.answer()

    # Validate framer role and alive
    group_id = find_game_by_user(user_id)
    if not group_id:
        await query.edit_message_text("You are not in any active game.")
        return
    game = active_games[group_id]
    player = game['players'].get(user_id)
    if not player or player['role'] != 'Framer' or not player.get('alive', True):
        await query.edit_message_text("You cannot perform this action.")
        return

    # Save the target for framing
    game.setdefault('night_actions', {})
    game['night_actions']['framer_frame'] = target_id

    await query.edit_message_text(f"You have decided to frame {game['players'][target_id]['name']} tonight.")

# === DETECTIVE ACTION CALLBACKS ===

async def detective_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    group_id = find_game_by_user(user_id)
    if not group_id:
        await update.message.reply_text("You are not part of any active game.")
        return
    game = active_games[group_id]
    player = game['players'].get(user_id)
    if not player or player['role'] != 'Detective' or not player.get('alive', True):
        await update.message.reply_text("You cannot perform detective actions.")
        return

    buttons = [
        [InlineKeyboardButton("Check 🕵️‍♂️", callback_data="det_check")],
        [InlineKeyboardButton("Kill 🔪", callback_data="det_kill")],
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    await update.message.reply_text("Choose an action:", reply_markup=reply_markup)

async def detective_action_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    action = query.data.split('_')[1]  # 'check' or 'kill'
    await query.answer()

    group_id = find_game_by_user(user_id)
    if not group_id:
        await query.edit_message_text("No active game found.")
        return
    game = active_games[group_id]
    player = game['players'].get(user_id)
    if not player or player['role'] != 'Detective' or not player.get('alive', True):
        await query.edit_message_text("You cannot perform this action.")
        return

    alive_targets = [p for p in game['players'].values() if p.get('alive', True) and p['user_id'] != user_id]

    buttons = [[InlineKeyboardButton(p['name'], callback_data=f"det_target_{p['user_id']}")] for p in alive_targets]
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="det_back")])
    reply_markup = InlineKeyboardMarkup(buttons)

    # Save chosen action temporarily in user context
    context.user_data['det_action'] = action

    await query.edit_message_text(f"Select a player to {action}:", reply_markup=reply_markup)

async def detective_target_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    target_id = int(data.split('_')[-1])
    action = context.user_data.get('det_action')
    if not action:
        await query.edit_message_text("Please choose an action first.")
        return

    group_id = find_game_by_user(user_id)
    if not group_id:
        await query.edit_message_text("No active game found.")
        return
    game = active_games[group_id]
    player = game['players'].get(user_id)
    if not player or player['role'] != 'Detective' or not player.get('alive', True):
        await query.edit_message_text("You cannot perform this action.")
        return

    if action == 'check':
        # Reveal role info to detective
        role = game['players'][target_id]['role']
        # Consider framing effect here if implemented
        await query.edit_message_text(f"{game['players'][target_id]['name']}'s role is: {role}")
        # Reset action
        context.user_data.pop('det_action', None)
    elif action == 'kill':
        # Mark detective kill target
        game.setdefault('night_actions', {})
        game['night_actions']['detective_kill'] = target_id
        await query.edit_message_text(f"You have chosen to kill {game['players'][target_id]['name']} tonight.")
        context.user_data.pop('det_action', None)
    else:
        await query.edit_message_text("Unknown action.")

async def detective_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    buttons = [
        [InlineKeyboardButton("Check 🕵️‍♂️", callback_data="det_check")],
        [InlineKeyboardButton("Kill 🔪", callback_data="det_kill")],
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.edit_message_text("Choose an action:", reply_markup=reply_markup)

# === UTILITY FUNCTIONS ===

def find_game_by_user(user_id: int):
    """
    Find group ID where user is playing in active games.
    """
    for gid, game in active_games.items():
        if user_id in game['players']:
            return gid
    return None

# === MAFIA TEAM CHAT ===

async def mafia_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles mafia team chat messages sent in private DM.
    """
    user_id = update.effective_user.id
    text = update.message.text
    group_id = find_game_by_user(user_id)
    if not group_id:
        await update.message.reply_text("You are not part of any active game.")
        return
    game = active_games[group_id]
    player = game['players'].get(user_id)
    if player['role'] not in ['Don', 'Mafia', 'Framer'] or not player.get('alive', True):
        await update.message.reply_text("Only alive Mafia members can use mafia chat.")
        return

    # Send message to all mafia players alive except sender
    for pid, p in game['players'].items():
        if p['role'] in ['Don', 'Mafia', 'Framer'] and p.get('alive', True) and pid != user_id:
            try:
                await context.bot.send_message(pid, f"[Mafia Chat] {player['name']}: {text}")
            except:
                pass

    await update.message.reply_text("Message sent to Mafia team.")
# === END NIGHT PHASE AND START VOTING PHASE ===

async def resolve_night_actions(context: ContextTypes.DEFAULT_TYPE, group_id: int):
    game = active_games[group_id]
    night = game.get('night_actions', {})

    killed = set()
    saved = night.get('doctor_save')
    framed = night.get('framer_frame')
    detective_kill = night.get('detective_kill')

    # Mafia kill target (assume stored as mafia_kill in night_actions)
    mafia_kill = night.get('mafia_kill')

    # Process kills considering doctor save
    if mafia_kill and mafia_kill != saved:
        killed.add(mafia_kill)
    if detective_kill and detective_kill != saved:
        killed.add(detective_kill)

    # Process framing (if any special logic)
    if framed:
        # Mark framed player - could influence detective check later
        game['players'][framed]['framed'] = True

    # Kill all players in killed set
    for uid in killed:
        game['players'][uid]['alive'] = False

    # Announce night results
    chat_id = group_id
    if killed:
        killed_names = ', '.join([game['players'][uid]['name'] for uid in killed])
        await context.bot.send_message(chat_id, f"Night is over.\nThe following players were killed:\n{killed_names}")
    else:
        await context.bot.send_message(chat_id, "Night is over.\nNo one died tonight.")

    # Clear night actions
    game['night_actions'] = {}

    # Check if game over
    winners = check_game_winner(game)
    if winners:
        await announce_winners(context, chat_id, winners)
        del active_games[group_id]
        return

    # Start voting phase (lynch)
    game['phase'] = 'voting'
    game['votes'] = {}
    await start_voting_phase(context, group_id)

async def start_voting_phase(context: ContextTypes.DEFAULT_TYPE, group_id: int):
    game = active_games[group_id]
    chat_id = group_id

    alive_players = [p for p in game['players'].values() if p.get('alive', True)]
    buttons = []
    for p in alive_players:
        buttons.append([InlineKeyboardButton(p['name'], callback_data=f"vote_{p['user_id']}")])
    reply_markup = InlineKeyboardMarkup(buttons)

    await context.bot.send_message(chat_id, "Voting time! Choose a player to lynch:", reply_markup=reply_markup)

async def vote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    group_id = find_game_by_user(user_id)
    if not group_id:
        await query.answer("You are not in an active game.")
        return
    game = active_games[group_id]
    if game.get('phase') != 'voting':
        await query.answer("Voting is not active right now.")
        return

    vote_target_id = int(query.data.split('_')[1])
    player = game['players'].get(user_id)
    if not player or not player.get('alive', True):
        await query.answer("You are not alive to vote.")
        return

    game['votes'][user_id] = vote_target_id
    await query.answer(f"You voted for {game['players'][vote_target_id]['name']}.")

    # Optionally update vote counts message or wait till voting time ends

async def end_voting_phase(context: ContextTypes.DEFAULT_TYPE, group_id: int):
    game = active_games[group_id]
    chat_id = group_id

    votes = game.get('votes', {})
    if not votes:
        await context.bot.send_message(chat_id, "No votes were cast. No one is lynched.")
        return

    # Count votes
    vote_counts = {}
    for voter, target in votes.items():
        vote_counts[target] = vote_counts.get(target, 0) + 1

    max_votes = max(vote_counts.values())
    candidates = [uid for uid, count in vote_counts.items() if count == max_votes]

    if len(candidates) > 1:
        # Tie, no lynch
        await context.bot.send_message(chat_id, "Vote tie! No one is lynched this round.")
    else:
        lynched_id = candidates[0]
        game['players'][lynched_id]['alive'] = False
        await context.bot.send_message(chat_id, f"{game['players'][lynched_id]['name']} has been lynched by the town!")

    # Clear votes
    game['votes'] = {}

    # Check if game over
    winners = check_game_winner(game)
    if winners:
        await announce_winners(context, chat_id, winners)
        del active_games[group_id]
        return

    # Start next night phase
    game['phase'] = 'night'
    await context.bot.send_message(chat_id, "Night phase started. Mafia, do your moves.")

def check_game_winner(game):
    """
    Checks game end conditions.
    Returns 'Town', 'Mafia' or None.
    """
    alive = [p for p in game['players'].values() if p.get('alive', True)]
    mafia_alive = [p for p in alive if p['role'] in ['Don', 'Mafia', 'Framer']]
    town_alive = [p for p in alive if p['role'] not in ['Don', 'Mafia', 'Framer']]

    if not mafia_alive:
        return 'Town'
    if len(mafia_alive) >= len(town_alive):
        return 'Mafia'
    return None

async def announce_winners(context: ContextTypes.DEFAULT_TYPE, chat_id: int, winners: str):
    text = f"Game Over! The winners are: {winners}\n\nFinal roles:\n"
    game = active_games[chat_id]
    for p in game['players'].values():
        status = "Alive" if p.get('alive', True) else "Dead"
        text += f"{p['name']} - {p['role']} ({status})\n"
    await context.bot.send_message(chat_id, text)

    # Award coins to alive winners (dummy example)
    for p in game['players'].values():
        if p.get('alive', True) and ((winners == 'Town' and p['role'] not in ['Don', 'Mafia', 'Framer']) or (winners == 'Mafia' and p['role'] in ['Don', 'Mafia', 'Framer'])):
            # Here you would add code to add coins to the user in your DB
            pass

# === HANDLERS REGISTRATION ===

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start_mafia", start_mafia_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CallbackQueryHandler(confirm_cancel_callback, pattern=r"^confirm_cancel_"))
    app.add_handler(CallbackQueryHandler(register_callback, pattern=r"^register$"))
    app.add_handler(CallbackQueryHandler(start_game_callback, pattern=r"^start_game$"))

    app.add_handler(CallbackQueryHandler(mafia_kill_callback, pattern=r"^mafia_kill_"))
    app.add_handler(CallbackQueryHandler(doctor_save_callback, pattern=r"^doc_save_"))
    app.add_handler(CallbackQueryHandler(watcher_watch_callback, pattern=r"^watch_"))
    app.add_handler(CallbackQueryHandler(framer_frame_callback, pattern=r"^frame_"))
    app.add_handler(CallbackQueryHandler(detective_action_choice_callback, pattern=r"^det_(check|kill|target|back)"))
    app.add_handler(CallbackQueryHandler(vote_callback, pattern=r"^vote_"))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & (~filters.COMMAND), mafia_chat))

    # Add other handlers as necessary

    app.run_polling()

if __name__ == "__main__":
    main()
