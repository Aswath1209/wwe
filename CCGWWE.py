import asyncio
import logging
from datetime import datetime
from collections import Counter

from telegram import (
    BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update,
    ChatPermissions, ParseMode
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler,
    MessageHandler, filters
)
from telegram.helpers import mention_html

# ----- CONFIG -----
BOT_TOKEN = '8133604799:AAF2dE86UjRxfAdUcqyoz3O9RgaCeTwaoHM'
MONGO_URL = 'mongodb://mongo:GhpHMiZizYnvJfKIQKxoDbRyzBCpqEyC@mainline.proxy.rlwy.net:54853'  # Optional, if you want to store coins etc

GROUP_LINK = "https://t.me/YourGroupLink"  # Group players join, used in join message

# ----- LOGGING -----
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# ----- GAME STORAGE -----
games = {}  
# Structure per chat_id:
# {
#   'players': set(user_id),
#   'usernames': {user_id: username},
#   'roles': {user_id: role_str},
#   'alive': set(user_id),
#   'votes': {}, # voting data
#   'doctor_used': False,
#   'don_id': None,
#   'mafia_ids': set(),
#   'framer_ids': set(),
#   'watcher_ids': set(),
#   'detective_id': None,
#   'doctor_id': None,
#   'lynch_votes': {},
#   'started': False,
#   'start_time': datetime,
#   'coins': {}, # user_id: int
# }

# ----- ROLES & MESSAGES -----
ROLE_SUMMARIES = {
    'Don': "🤵🏻‍♂️ *Don*\nHead of the Mafia. Your vote decides who gets killed each night.",
    'Mafia': "🤵🏼 *Mafia*\nKill townies with the Don. Your votes combine unless Don overrides.",
    'Framer': "🎭 *Framer*\nFrame townies to confuse the Detective. You cannot kill.",
    'Watcher': "👀 *Watcher*\nObserve players at night to gather info.",
    'Detective': "🕵️ *Detective*\nCheck players' roles or kill suspicious ones at night.",
    'Doctor': "👨🏼‍⚕️ *Doctor*\nSave players from death once per game. You can save yourself once only.",
    'Townie': "👨🏼 *Townie*\nInnocent town member. Vote wisely during the day.",
    'Suicide': "💀 *Suicide*\nYour mission is to get lynched by the town.",
}

# Button to join the game, with group link text in DM message
JOIN_BUTTON = InlineKeyboardMarkup([
    [InlineKeyboardButton("Join", url=f"t.me/{BOT_TOKEN.split(':')[0]}?start=join")]
])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user

    if update.effective_chat.type != 'private':
        # Group message: send registration message with inline Join button
        text = ("📝 *Registration for Trust Test Open!*\n\n"
                "Registered Players:\n"
                "None yet. Click below to join!\n\n"
                "Click the *Join* button below to join the game via bot DM.")

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Join", url=f"https://t.me/{context.bot.username}?start=join")]
        ])

        await update.message.reply_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    else:
        # Private chat DM
        args = context.args
        if args and args[0] == 'join':
            # Add user to registration of last game or create if none
            # For demo, just send join confirmation
            await update.message.reply_text(
                f"You joined the game in [CCG TOURNAMENTS]({GROUP_LINK})! 🎉",
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True
            )
            # Logic to add user to game registration to be added later
        else:
            await update.message.reply_text(
                "Hello! Use this bot to play Mafia in groups.\n"
                "Join a game from your group using the Join button."
            )


async def join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user clicking Join button in DM or starting bot with /start join"""
    user = update.effective_user
    chat_id = update.effective_chat.id

    # Find the group chat where registration is open
    # For demo, we assume only one game per group - simplified
    # Add user to the game players
    # This requires mapping of user to group, we keep a simple approach here

    # You can customize this according to your logic
    await update.message.reply_text(
        f"You joined the game in [CCG TOURNAMENTS]({GROUP_LINK})! 🎉",
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True
    )

# Register handlers to be added later
import random

# --- Helper functions ---

def get_role_summary(role: str) -> str:
    return ROLE_SUMMARIES.get(role, "No summary available.")

def assign_roles(player_ids):
    """
    Assign roles based on number of players with your custom logic.
    Returns dict: user_id -> role
    """

    n = len(player_ids)
    roles = []

    # Role distribution example from earlier chat (adjusted):

    # Minimum: 4 players - Don, Mafia, Detective, Doctor
    # Max 4 Mafia side incl Don & Framer
    # Suicide role if Mafia <4

    if n < 4:
        raise ValueError("Minimum 4 players required")

    # Basic sets depending on count (example):
    if n == 4:
        roles = ['Don', 'Mafia', 'Detective', 'Doctor']
    elif n == 5:
        roles = ['Don', 'Mafia', 'Framer', 'Detective', 'Doctor']
    elif n == 6:
        roles = ['Don', 'Mafia', 'Mafia', 'Framer', 'Detective', 'Doctor']
    elif n == 7:
        roles = ['Don', 'Mafia', 'Mafia', 'Framer', 'Watcher', 'Detective', 'Doctor']
    elif n == 8:
        roles = ['Don', 'Mafia', 'Mafia', 'Framer', 'Watcher', 'Detective', 'Doctor', 'Townie']
    elif n == 9:
        roles = ['Don', 'Mafia', 'Mafia', 'Framer', 'Watcher', 'Detective', 'Doctor', 'Townie', 'Suicide']
    elif n == 10:
        roles = ['Don', 'Mafia', 'Mafia', 'Framer', 'Watcher', 'Detective', 'Doctor', 'Townie', 'Townie', 'Suicide']
    else:
        # For larger groups just add more Townies or Suicide to balance
        roles = ['Don', 'Mafia', 'Mafia', 'Framer', 'Watcher', 'Detective', 'Doctor']
        extra = n - len(roles)
        # Add Townies mostly, add 1 Suicide if mafia <4
        for _ in range(extra-1):
            roles.append('Townie')
        roles.append('Suicide')

    random.shuffle(roles)
    assigned = dict(zip(player_ids, roles))
    return assigned


async def send_role_dm(bot, user_id: int, role: str, players_roles: dict):
    """
    Sends role message + summary + team members (if Mafia side)
    """

    text = f"Your role:\n\n*{role}*\n{get_role_summary(role)}\n\n"

    mafia_side = {'Don', 'Mafia', 'Framer'}
    if role in mafia_side:
        team_members = []
        for uid, r in players_roles.items():
            if r in mafia_side and uid != user_id:
                team_members.append(f"- {mention_html(uid, 'Player')}")
        if team_members:
            text += "Remember your team members:\n" + "\n".join(team_members)

    await bot.send_message(chat_id=user_id, text=text, parse_mode=ParseMode.HTML)


# --- Player registration and starting game ---

async def register_player(chat_id: int, user_id: int, username: str):
    """Add player to game registration"""
    game = games.setdefault(chat_id, {})
    players = game.setdefault('players', set())
    usernames = game.setdefault('usernames', {})
    if user_id not in players:
        players.add(user_id)
        usernames[user_id] = username

async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = games.get(chat_id)
    if not game or len(game.get('players', [])) < 4:
        await update.message.reply_text("Not enough players registered to start the game (minimum 4).")
        return

    if game.get('started'):
        await update.message.reply_text("Game already started!")
        return

    game['started'] = True
    game['start_time'] = datetime.now()

    players = list(game['players'])
    assigned_roles = assign_roles(players)
    game['roles'] = assigned_roles
    game['alive'] = set(players)
    game['doctor_used'] = False
    game['coins'] = game.get('coins', {})

    # Find key roles
    for uid, role in assigned_roles.items():
        if role == 'Don':
            game['don_id'] = uid
        elif role == 'Detective':
            game['detective_id'] = uid
        elif role == 'Doctor':
            game['doctor_id'] = uid

    # Mafia and Framer sets
    game['mafia_ids'] = {uid for uid, r in assigned_roles.items() if r in ('Don', 'Mafia')}
    game['framer_ids'] = {uid for uid, r in assigned_roles.items() if r == 'Framer'}
    game['watcher_ids'] = {uid for uid, r in assigned_roles.items() if r == 'Watcher'}

    # Send roles DM
    for uid, role in assigned_roles.items():
        try:
            await send_role_dm(context.bot, uid, role, assigned_roles)
        except Exception as e:
            logger.warning(f"Could not send role DM to {uid}: {e}")

    await update.message.reply_text(f"Game started with {len(players)} players! Roles have been sent privately.")

# Register these handlers in your application:
# app.add_handler(CommandHandler('startmafia', start_game))
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

async def send_night_actions(game, bot):
    alive = game['alive']
    roles = game['roles']

    for uid in alive:
        role = roles.get(uid)
        if role == 'Detective':
            buttons = []
            for target in alive:
                if target != uid:
                    buttons.append(
                        [InlineKeyboardButton(text=game['usernames'].get(target, "Player"), callback_data=f"detective_check_{target}")]
                    )
            buttons.append([InlineKeyboardButton(text="Kill Player", callback_data="detective_kill")])
            markup = InlineKeyboardMarkup(buttons)
            try:
                await bot.send_message(uid, "Detective, choose a player to check or click Kill Player button.", reply_markup=markup)
            except:
                pass

        elif role == 'Doctor':
            if not game.get('doctor_used', False):
                buttons = []
                for target in alive:
                    buttons.append([InlineKeyboardButton(text=game['usernames'].get(target, "Player"), callback_data=f"doctor_save_{target}")])
                markup = InlineKeyboardMarkup(buttons)
                try:
                    await bot.send_message(uid, "Doctor, choose a player to save (including yourself once).", reply_markup=markup)
                except:
                    pass

        elif role in ('Don', 'Mafia', 'Framer'):
            buttons = []
            for target in alive:
                if target != uid:
                    buttons.append([InlineKeyboardButton(text=game['usernames'].get(target, "Player"), callback_data=f"mafia_vote_{target}")])
            markup = InlineKeyboardMarkup(buttons)
            try:
                await bot.send_message(uid, "Mafia team, choose who to kill tonight.", reply_markup=markup)
            except:
                pass

        elif role == 'Watcher':
            buttons = []
            for target in alive:
                if target != uid:
                    buttons.append([InlineKeyboardButton(text=game['usernames'].get(target, "Player"), callback_data=f"watcher_watch_{target}")])
            markup = InlineKeyboardMarkup(buttons)
            try:
                await bot.send_message(uid, "Watcher, choose a player to watch tonight.", reply_markup=markup)
            except:
                pass

async def process_mafia_votes(game, bot):
    mafia_votes = game.get('mafia_votes', {})
    don_id = game.get('don_id')
    don_vote = mafia_votes.get(don_id)
    if don_vote:
        kill_target = don_vote
    else:
        vote_counts = {}
        for v in mafia_votes.values():
            vote_counts[v] = vote_counts.get(v, 0) + 1
        kill_target = max(vote_counts, key=vote_counts.get) if vote_counts else None
    return kill_target

def calculate_lynch(game):
    votes = game.get('lynch_votes', {})
    if not votes:
        return None, 0, 0
    counts = {}
    for vote in votes.values():
        counts[vote] = counts.get(vote, 0) + 1
    max_votes = max(counts.values())
    candidates = [player for player, count in counts.items() if count == max_votes]
    if len(candidates) == 1:
        return candidates[0], max_votes, len(votes) - max_votes
    return None, max_votes, len(votes) - max_votes
# Part 4

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ParseMode
from telegram.ext import CallbackContext

# Example: Handle player joining via button in group
async def join_game_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    user = query.from_user
    group_id = query.message.chat_id  # Group chat where join button was pressed

    # Fetch the game data for this group from DB or memory
    game = await get_game_by_group(group_id)
    if not game or game['status'] != 'registration':
        await query.answer("Registration is not open now.", show_alert=True)
        return

    # Check if user already registered
    if user.id in game['players']:
        await query.answer("You have already joined!", show_alert=True)
        return

    # Add user to players list
    game['players'].append(user.id)
    await save_game(game)  # Save updated game data

    # Notify user in group and via callback answer
    await query.answer(f"You joined the game! Players: {len(game['players'])}/{game['max_players']}")
    
    # Update group message listing registered players
    players_mentions = []
    for pid in game['players']:
        try:
            member = await context.bot.get_chat_member(group_id, pid)
            players_mentions.append(f"[{member.user.first_name}](tg://user?id={pid})")
        except:
            players_mentions.append(f"Player_{pid}")
    registered_text = "Registration Open!\n\nRegistered Players:\n" + "\n".join(players_mentions)

    keyboard = [[InlineKeyboardButton("Join", callback_data="join_game")]]
    await context.bot.edit_message_text(
        chat_id=group_id,
        message_id=query.message.message_id,
        text=registered_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

# Helper functions to get and save game data
async def get_game_by_group(group_id):
    # Example fetch game data from your DB or in-memory dict
    # Return None if no game or registration closed
    # Implement this function as per your storage logic
    pass

async def save_game(game_data):
    # Save updated game data back to DB or memory
    pass

# You should also have command handlers like /startmafia, /cancel, etc.
# Part 5

import random

# Role constants
ROLES = ['Don', 'Mafia', 'Framer', 'Watcher', 'Detective', 'Doctor', 'Citizen']

async def start_mafia_game(update: Update, context: CallbackContext):
    group_id = update.effective_chat.id
    game = await get_game_by_group(group_id)

    if not game or game['status'] != 'registration':
        await update.message.reply_text("No registration open right now.")
        return

    players = game['players']
    num_players = len(players)

    if num_players < 4:
        await update.message.reply_text("Need minimum 4 players to start.")
        return

    # Assign roles based on player count (implement your distribution logic here)
    roles_distribution = get_roles_distribution(num_players)

    # Shuffle players and assign roles
    random.shuffle(players)
    player_roles = {}
    for i, player_id in enumerate(players):
        player_roles[player_id] = roles_distribution[i]

    game['player_roles'] = player_roles
    game['status'] = 'playing'
    await save_game(game)

    # Send role DM to each player with summary and team info
    for player_id, role in player_roles.items():
        try:
            user = await context.bot.get_chat(player_id)
            text = f"Your role: *{role}*\n\n"
            text += role_summary(role) + "\n\n"

            # If mafia side, show team members
            if role in ['Don', 'Mafia', 'Framer']:
                mafia_members = [await context.bot.get_chat(pid) for pid, r in player_roles.items() if r in ['Don','Mafia','Framer']]
                mafia_names = "\n".join(f"- {m.first_name} ({player_roles[m.id]})" for m in mafia_members)
                text += "Remember your team members:\n" + mafia_names

            await context.bot.send_message(chat_id=player_id, text=text, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            print(f"Failed to send role to {player_id}: {e}")

    # Announce in group game started
    await context.bot.send_message(group_id, f"Game has started with {num_players} players! Roles have been sent privately.")

def get_roles_distribution(num_players):
    # Example simple distribution - customize as per your role counts logic
    dist = []
    # Add mandatory roles
    dist.append('Don')
    dist.append('Doctor')
    dist.append('Detective')

    mafia_count = min(3, max(1, num_players // 4))
    dist.extend(['Mafia'] * (mafia_count - 1))  # minus 1 Don already added
    framer_count = 1 if num_players >= 6 else 0
    watcher_count = 1 if num_players >= 8 else 0

    if framer_count:
        dist.append('Framer')
    if watcher_count:
        dist.append('Watcher')

    # Fill remaining with Citizens
    while len(dist) < num_players:
        dist.append('Citizen')

    return dist[:num_players]

def role_summary(role):
    summaries = {
        'Don': "You are the head of the Mafia. You have the final say in who gets killed at night.",
        'Mafia': "You are a member of the Mafia team. Work with your teammates to eliminate others.",
        'Framer': "You are a member of the Mafia but cannot kill. Your job is to confuse the town by framing innocent players.",
        'Watcher': "You observe players at night and learn about their actions.",
        'Detective': "You can check or kill a player at night. Use your powers wisely.",
        'Doctor': "You can save a player from being killed at night, including yourself but only once.",
        'Citizen': "You are a normal townsperson. Work with others to find the Mafia.",
    }
    return summaries.get(role, "You are a participant in the game.")
# Part 6

from telegram.constants import ParseMode
from telegram.helpers import mention_html
import asyncio
from collections import Counter

async def start_night_phase(context: CallbackContext, group_id):
    game = await get_game_by_group(group_id)
    if not game or game['status'] != 'playing':
        return

    await context.bot.send_message(group_id, "🌙 Night has fallen... Special characters are choosing their actions... You have 45 seconds.")

    game['night_actions'] = {
        'doctor': {},
        'detective': {},
        'mafia_votes': {},
        'framer': None,
        'watcher': None
    }

    players = game['players']
    roles = game['player_roles']

    for player_id in players:
        role = roles.get(player_id)
        if role == 'Doctor':
            text = "👨🏼‍⚕️ Doctor went on night duty...\nWho will you save tonight?\n(You can save yourself only once)"
            await send_player_action(context, player_id, text, players)
        elif role == 'Detective':
            text = "🕵️‍ Detective is in action tonight.\nChoose an action:"
            await context.bot.send_message(chat_id=player_id, text=text, reply_markup=detective_action_markup())
        elif role in ['Mafia', 'Don']:
            text = "🤵🏼 It's time to decide who to eliminate.\nWho should be the target?"
            await send_player_action(context, player_id, text, players)
        elif role == 'Framer':
            text = "🎭 Framer, who will you frame tonight?"
            await send_player_action(context, player_id, text, players)
        elif role == 'Watcher':
            text = "🔍 Watcher, who do you want to observe tonight?"
            await send_player_action(context, player_id, text, players)

    await asyncio.sleep(45)
    await process_night_results(context, group_id)

async def process_night_results(context: CallbackContext, group_id):
    game = await get_game_by_group(group_id)
    if not game or game['status'] != 'playing':
        return

    actions = game['night_actions']
    roles = game['player_roles']
    players = game['players']

    killed = None
    saved = None
    saved_by_doctor = actions['doctor'].get('target')
    doctor_self = actions['doctor'].get('self_saved', False)

    mafia_votes = actions['mafia_votes']
    if mafia_votes:
        vote_counter = Counter(mafia_votes.values())
        most_voted = vote_counter.most_common(1)[0][0]
        killed = most_voted

    # Don has final say
    don_id = next((pid for pid in players if roles[pid] == 'Don'), None)
    if don_id in mafia_votes:
        killed = mafia_votes[don_id]

    # Announce special messages
    if 'Detective' in roles.values():
        await context.bot.send_message(group_id, "🕵️‍ Detective is looking for the criminals..." if actions['detective'].get('action') == 'check' else "🕵️‍ Detective has his weapons lock'n'loaded...")

    if saved_by_doctor == killed:
        saved = killed
        killed = None

    # Announce death
    if killed:
        dead_name = await get_mention(context, killed)
        role = roles[killed]
        await context.bot.send_message(group_id, f"💀 {dead_name} was brutally murdered last night... They were a {role_emoji(role)} {role}")
        players.remove(killed)

    if saved:
        await context.bot.send_message(group_id, f"👨🏼‍⚕️ Someone was saved by the Doctor tonight...")

    await asyncio.sleep(20)

    if len(players) < 3:
        await end_game(context, group_id)
        return

    await start_voting_phase(context, group_id)

async def start_voting_phase(context: CallbackContext, group_id):
    game = await get_game_by_group(group_id)
    if not game or game['status'] != 'playing':
        return

    await context.bot.send_message(group_id, "🗳️ It's mob justice time!\nVote for the most suspicious player.\nVoting will last 45 seconds.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Vote", url=f"https://t.me/{context.bot.username}")]]))

    game['vote_phase'] = True
    game['votes'] = {}
    await save_game(game)

    await asyncio.sleep(45)
    await count_votes_and_decide_lynch(context, group_id)

async def count_votes_and_decide_lynch(context: CallbackContext, group_id):
    game = await get_game_by_group(group_id)
    if not game or not game.get('vote_phase'):
        return

    votes = game.get('votes', {})
    if not votes:
        await context.bot.send_message(group_id, "No one voted. Skipping lynching this round.")
        return

    vote_counter = Counter(votes.values())
    most_voted, count = vote_counter.most_common(1)[0]
    total_votes = sum(vote_counter.values())

    thumbs_up = 0
    thumbs_down = 0

    # Send confirmation with 👍👎 buttons
    msg = await context.bot.send_message(group_id, f"Are you sure about lynching {await get_mention(context, most_voted)}?", 
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👍 Yes", callback_data=f"confirm_lynch:{most_voted}")],
            [InlineKeyboardButton("👎 No", callback_data=f"cancel_lynch:{most_voted}")]
        ]))

    # Store in temp data for tracking
    context.chat_data['lynch_msg_id'] = msg.message_id
    context.chat_data['lynch_votes'] = {'👍': 0, '👎': 0, 'target': most_voted}

    await asyncio.sleep(30)

    if context.chat_data['lynch_votes']['👍'] > context.chat_data['lynch_votes']['👎']:
        lynched = context.chat_data['lynch_votes']['target']
        role = game['player_roles'][lynched]
        await context.bot.send_message(group_id, f"{await get_mention(context, lynched)} was a {role_emoji(role)} {role}")
        game['players'].remove(lynched)
    else:
        thumbs_up = context.chat_data['lynch_votes']['👍']
        thumbs_down = context.chat_data['lynch_votes']['👎']
        await context.bot.send_message(group_id, f"The citizens couldn't come up with a decision ({thumbs_up} 👍 | {thumbs_down} 👎)... They dispersed, lynching nobody today...")

    game['vote_phase'] = False
    await save_game(game)

    if len(game['players']) < 3:
        await end_game(context, group_id)
    else:
        await start_night_phase(context, group_id)

# Utility functions (examples)
def role_emoji(role):
    return {
        'Don': '🤵🏻',
        'Mafia': '🤵🏼',
        'Framer': '🎭',
        'Doctor': '👨🏼‍⚕️',
        'Detective': '🕵️‍',
        'Watcher': '🔍',
        'Citizen': '👨🏼'
    }.get(role, '')

async def get_mention(context, user_id):
    user = await context.bot.get_chat(user_id)
    return mention_html(user.id, user.first_name)
# Part 7

from telegram import CallbackQuery

async def handle_vote_callback(update: Update, context: CallbackContext):
    query: CallbackQuery = update.callback_query
    user_id = query.from_user.id
    game = await get_game_by_group(update.effective_chat.id)
    if not game or not game.get("vote_phase"):
        await query.answer("Voting has ended.")
        return

    data = query.data
    if data.startswith("vote:"):
        target = int(data.split(":")[1])
        game['votes'][str(user_id)] = target
        await query.answer("Vote submitted.")
        voter = mention_html(user_id, query.from_user.first_name)
        voted = mention_html(target, (await context.bot.get_chat(target)).first_name)
        await context.bot.send_message(update.effective_chat.id, f"{voter} voted for {voted}", parse_mode=ParseMode.HTML)
        await save_game(game)

    elif data.startswith("confirm_lynch:"):
        target = int(data.split(":")[1])
        context.chat_data['lynch_votes']['👍'] += 1
        await query.answer("You confirmed the lynch.")

    elif data.startswith("cancel_lynch:"):
        target = int(data.split(":")[1])
        context.chat_data['lynch_votes']['👎'] += 1
        await query.answer("You rejected the lynch.")

# End Game
async def end_game(context: CallbackContext, group_id):
    game = await get_game_by_group(group_id)
    if not game:
        return

    roles = game['player_roles']
    players = game['players']
    mafia_alive = [uid for uid in players if roles[uid] in ['Mafia', 'Don', 'Framer']]
    town_alive = [uid for uid in players if roles[uid] not in ['Mafia', 'Don', 'Framer']]

    if mafia_alive and not town_alive:
        winners = mafia_alive
        team = "Mafia"
    else:
        winners = town_alive
        team = "Town"

    result_lines = [f"The game is over!\nThe victorious team: {team}\n\nWinners:"]
    for uid in winners:
        uname = (await context.bot.get_chat(uid)).first_name
        role = roles[uid]
        result_lines.append(f"    {uname} - {role_emoji(role)} {role}")

    result_lines.append("\nOther players:")
    for uid, role in roles.items():
        if uid not in winners:
            uname = (await context.bot.get_chat(uid)).first_name
            result_lines.append(f"    {uname} - {role_emoji(role)} {role}")

    result_lines.append("\nThe game lasted: 12 min. 19 sec.")
    await context.bot.send_message(group_id, "\n".join(result_lines))

    # Award coins
    for uid in winners:
        user = await get_user(uid)
        user['coins'] = user.get('coins', 0) + 10
        await save_user(uid, user)

    await delete_game(group_id)

# Cancel command
@group_cmd
async def cancel(update: Update, context: CallbackContext):
    game = await get_game_by_group(update.effective_chat.id)
    if not game:
        await update.message.reply_text("❌ No game is currently running.")
        return
    # Only admins can cancel
    user = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
    if user.status not in ['administrator', 'creator']:
        await update.message.reply_text("Only admins can cancel the game.")
        return

    btns = [
        [InlineKeyboardButton("✅ Confirm", callback_data="confirm_cancel")],
        [InlineKeyboardButton("❌ Cancel", callback_data="dismiss_cancel")]
    ]
    await update.message.reply_text("Are you sure you want to cancel the game?", reply_markup=InlineKeyboardMarkup(btns))

@dp.callback_query_handler(lambda q: q.data in ["confirm_cancel", "dismiss_cancel"])
async def confirm_cancel(update: Update, context: CallbackContext):
    query = update.callback_query
    if query.data == "confirm_cancel":
        await delete_game(query.message.chat_id)
        await query.edit_message_text("✅ Game has been cancelled.")
    else:
        await query.edit_message_text("❌ Cancelled request to end the game.")
async def process_mafia_votes(group_id):
    game = games[group_id]
    votes = game['mafia_votes']
    if not votes:
        return

    target_id = max(set(votes.values()), key=list(votes.values()).count)
    target_user = game['players'][target_id]
    game['night_kills'].append(target_id)

    # Announce in group
    voter_names = []
    for voter_id, voted_id in votes.items():
        role = game['roles'][voter_id]
        voter_name = (await app.get_users(voter_id)).mention
        victim_name = (await app.get_users(voted_id)).mention
        emoji = "🤵🏻 Don" if role == 'don' else "🤵🏼 Mafia"
        await app.send_message(group_id, f"{emoji} {voter_name} voted for {victim_name}")
    await app.send_message(group_id, f"The Mafia Vote is over\nMafia sacrificed {(await app.get_users(target_id)).mention}.")
    game['mafia_votes'] = {}

async def announce_night_results(group_id):
    game = games[group_id]
    killed = game['night_kills']
    saved = game['saved']
    for uid in killed:
        if uid in saved:
            await app.send_message(uid, "🩺 Doctor patched you up and saved your life!")
            await app.send_message(group_id, "🩺 Someone was attacked but survived the night...")
        else:
            game['alive'].remove(uid)
            name = (await app.get_users(uid)).mention
            role_emoji = role_emojis.get(game['roles'][uid], '❓')
            await app.send_message(group_id, f"{role_emoji} {name} was brutally murdered tonight...")

    await asyncio.sleep(20)
    await app.send_message(group_id, "🧠 It's mob justice time! Vote for the most suspicious player.\nVoting will last 45 seconds.", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🗳 Vote", url=f"https://t.me/{BOT_USERNAME}")]
    ]))
    game['votes'] = {}
    game['vote_confirmations'] = {}
    asyncio.create_task(collect_votes(group_id))

async def collect_votes(group_id):
    await asyncio.sleep(45)
    game = games[group_id]
    if not game['votes']:
        await app.send_message(group_id, "No votes were cast. Nobody is lynched.")
        return

    voted_user_id = max(set(game['votes'].values()), key=list(game['votes'].values()).count)
    voted_name = (await app.get_users(voted_user_id)).mention
    game['current_vote_target'] = voted_user_id
    await app.send_message(group_id, f"Are you sure about lynching {voted_name}?", reply_markup=InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👍", callback_data="confirm_lynch"),
            InlineKeyboardButton("👎", callback_data="cancel_lynch")
        ]
    ]))

    game['lynch_votes'] = {'yes': set(), 'no': set()}
    await asyncio.sleep(30)

    yes_votes = len(game['lynch_votes']['yes'])
    no_votes = len(game['lynch_votes']['no'])
    if yes_votes > no_votes:
        await lynch_player(group_id, voted_user_id)
    else:
        await app.send_message(group_id, f"The citizens couldn't come up with a decision ({yes_votes} 👍 | {no_votes} 👎)... They dispersed, lynching nobody today...")
async def lynch_player(group_id, user_id):
    game = games[group_id]
    game['alive'].remove(user_id)
    player_name = (await app.get_users(user_id)).mention
    role = game['roles'][user_id]
    emoji = role_emojis.get(role, '❓')
    await app.send_message(group_id, f"{player_name} was a {emoji}")

    await check_win_conditions(group_id)

async def check_win_conditions(group_id):
    game = games[group_id]
    alive_roles = [game['roles'][uid] for uid in game['alive']]
    mafia_count = sum(1 for r in alive_roles if r in ['mafia', 'don', 'framer'])
    town_count = sum(1 for r in alive_roles if r not in ['mafia', 'don', 'framer', 'suicide'])

    if mafia_count == 0:
        await end_game(group_id, winner="Town")
    elif mafia_count >= town_count:
        await end_game(group_id, winner="Mafia")
    elif all(game['roles'][uid] == 'suicide' for uid in game['alive']):
        await end_game(group_id, winner="Suicide")

async def end_game(group_id, winner):
    game = games[group_id]
    duration = int(time.time() - game['start_time'])
    mins, secs = divmod(duration, 60)

    winner_players = []
    other_players = []
    for uid in game['players']:
        uname = (await app.get_users(uid)).first_name
        emoji = role_emojis.get(game['roles'][uid], '❓')
        line = f"    {uname} - {emoji}"
        if uid in game['alive']:
            if winner == "Town" and game['roles'][uid] not in ['mafia', 'don', 'framer', 'suicide']:
                winner_players.append(line)
                users.update_one({"_id": uid}, {"$inc": {"coins": 10}}, upsert=True)
            elif winner == "Mafia" and game['roles'][uid] in ['mafia', 'don', 'framer']:
                winner_players.append(line)
                users.update_one({"_id": uid}, {"$inc": {"coins": 10}}, upsert=True)
            elif winner == "Suicide" and game['roles'][uid] == "suicide":
                winner_players.append(line)
                users.update_one({"_id": uid}, {"$inc": {"coins": 10}}, upsert=True)
            else:
                other_players.append(line)
        else:
            other_players.append(line)

    final_msg = f"🎉 The game is over!\nThe victorious team: {winner}\n\nWinners:\n"
    final_msg += "\n".join(winner_players or ["None"])
    final_msg += "\n\nOther players:\n" + "\n".join(other_players)
    final_msg += f"\n\nThe game lasted: {mins} min. {secs} sec."

    await app.send_message(group_id, final_msg)
    del games[group_id]
