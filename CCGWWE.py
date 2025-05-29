import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
import asyncio

BOT_TOKEN = "7821453313:AAHKskxl8WLbRKTFYccvH3SPSVDeVoEzo6U"  # <-- Put your bot token here!

logging.basicConfig(level=logging.INFO)

# Moves: name, type, beats (attack/defense/heal)
MOVES = {
    "Spear": {"type": "attack", "beats": ["Block", "Heal"]},
    "RKO": {"type": "attack", "beats": ["Dodge", "Heal"]},
    "Superman": {"type": "attack", "beats": ["Block", "Dodge"]},
    "Block": {"type": "defense"},
    "Dodge": {"type": "defense"},
    "Heal": {"type": "heal"},
}

# Keyboard buttons (2 rows)
BUTTONS = [
    [InlineKeyboardButton("🔥 Spear", callback_data="Spear"),
     InlineKeyboardButton("🐍 RKO", callback_data="RKO"),
     InlineKeyboardButton("✊ Superman", callback_data="Superman")],
    [InlineKeyboardButton("🛡️ Block", callback_data="Block"),
     InlineKeyboardButton("🌀 Dodge", callback_data="Dodge"),
     InlineKeyboardButton("❤️ Heal", callback_data="Heal")]
]

# Matches data: chat_id -> {players, hp, choices, turn}
matches = {}

def fit_text(text):
    # Split long text into <=40 char lines
    words = text.split()
    lines = []
    current = ""
    for w in words:
        if len(current) + len(w) + 1 > 40:
            lines.append(current.rstrip())
            current = w + " "
        else:
            current += w + " "
    if current:
        lines.append(current.rstrip())
    return "\n".join(lines)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👊 Welcome to WWE Fight Bot!\n"
        "Use /fight @user to start.\n"
        "Use /help for move guide.\n"
        "Use /forfeit to quit fight."
    )
    await update.message.reply_text(fit_text(text))

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🎯 Move Guide:\n"
        "🔥 Spear beats 🛡️ Block, ❤️ Heal\n"
        "🐍 RKO beats 🌀 Dodge, ❤️ Heal\n"
        "✊ Superman beats 🛡️ Block, 🌀 Dodge\n"
        "🛡️ Block & 🌀 Dodge defend attacks\n"
        "❤️ Heal restores 20 HP\n"
        "Choose wisely each turn!"
    )
    await update.message.reply_text(fit_text(text))

async def fight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❗ Usage: /fight @username")
        return
    opponent = context.args[0]
    if not opponent.startswith("@"):
        await update.message.reply_text("❗ Please tag your opponent with @")
        return
    user = update.effective_user
    chat_id = update.effective_chat.id

    if chat_id in matches:
        await update.message.reply_text("❗ Match in progress here.")
        return

    matches[chat_id] = {
        "players": [user.id, opponent[1:]],  # store opponent as username string
        "usernames": [user.username or user.first_name, opponent[1:]],
        "hp": [100, 100],
        "choices": [None, None],
        "turn": 0,  # 0 = player 1 picks, 1 = player 2 picks
    }

    text = (
        f"⚔️ Fight Started!\n"
        f"{matches[chat_id]['usernames'][0]} VS {matches[chat_id]['usernames'][1]}\n"
        "Both pick your move!"
    )
    keyboard = InlineKeyboardMarkup(BUTTONS)
    await update.message.reply_text(fit_text(text), reply_markup=keyboard)

async def forfeit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in matches:
        await update.message.reply_text("❗ No active fight here.")
        return

    loser = update.effective_user.username or update.effective_user.first_name
    winner = None
    match = matches[chat_id]
    # Determine winner (the other player)
    if match["usernames"][0] == loser:
        winner = match["usernames"][1]
    else:
        winner = match["usernames"][0]

    text = f"🏳️ {loser} forfeited.\nWinner: {winner}"
    del matches[chat_id]
    await update.message.reply_text(fit_text(text))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    user_id = query.from_user.id
    username = query.from_user.username or query.from_user.first_name
    move = query.data

    if chat_id not in matches:
        await query.edit_message_text("❗ No fight here. Use /fight @user to start.")
        return

    match = matches[chat_id]
    players = match["players"]
    hp = match["hp"]
    choices = match["choices"]
    turn = match["turn"]
    usernames = match["usernames"]

    # Identify player index
    if user_id == players[0]:
        idx = 0
    elif str(user_id) == players[1]:  # stored opponent as string username id (simplify)
        idx = 1
    else:
        await query.answer("❗ You are not in this fight.", show_alert=True)
        return

    # Check if this player already chose this turn
    if choices[idx] is not None:
        await query.answer("⌛ Move already chosen, wait for opponent.")
        return

    # Save choice
    choices[idx] = move

    # If both chose, resolve turn
    if choices[0] and choices[1]:
        # Process fight logic
        result_text = f"🕹️ Moves:\n{usernames[0]} → {choices[0]}\n{usernames[1]} → {choices[1]}\n\n"
        # Resolve damage
        def move_effect(attacker_move, defender_move):
            if MOVES[attacker_move]["type"] == "attack":
                if defender_move in MOVES[attacker_move].get("beats", []):
                    return 20
                else:
                    return 10
            elif MOVES[attacker_move]["type"] == "heal":
                return -20  # heal 20 HP
            return 0

        # Player 0 attack on 1
        dmg_p0 = move_effect(choices[0], choices[1])
        # Player 1 attack on 0
        dmg_p1 = move_effect(choices[1], choices[0])

        # Apply damage or heal
        hp[1] -= dmg_p0
        hp[0] -= dmg_p1
        # Heal moves are negative damage -> add HP
        if dmg_p0 < 0:
            hp[0] = min(100, hp[0] - dmg_p0)  # heal self
            hp[1] += 0  # no damage to opponent
        if dmg_p1 < 0:
            hp[1] = min(100, hp[1] - dmg_p1)
            hp[0] += 0

        # Prevent negative HP
        hp[0] = max(hp[0], 0)
        hp[1] = max(hp[1], 0)

        # Show current HP
        result_text += f"❤️ HP:\n{usernames[0]}: {hp[0]}\n{usernames[1]}: {hp[1]}\n"

        # Clear choices for next turn
        match["choices"] = [None, None]

        # Check for win
        if hp[0] == 0 and hp[1] == 0:
            result_text += "\n🤝 Draw!"
            del matches[chat_id]
        elif hp[0] == 0:
            result_text += f"\n🏆 {usernames[1]} wins!"
            del matches[chat_id]
        elif hp[1] == 0:
            result_text += f"\n🏆 {usernames[0]} wins!"
            del matches[chat_id]
        else:
            result_text += "\n▶️ Next turn! Pick your move."
            # Send next buttons
            keyboard = InlineKeyboardMarkup(BUTTONS)
            await query.edit_message_text(fit_text(result_text), reply_markup=keyboard)
            return

        await query.edit_message_text(fit_text(result_text))
        return

    else:
        # Wait for opponent
        waiting_text = f"⌛ {username} chose a move.\nWaiting for opponent..."
        await query.edit_message_text(fit_text(waiting_text))

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("fight", fight))
    app.add_handler(CommandHandler("forfeit", forfeit))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("Bot started.")
    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
