import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    CallbackQueryHandler, MessageHandler, filters
)

TOKEN = "8133604799:AAF2dE86UjRxfAdUcqyoz3O9RgaCeTwaoHM"

players = []
alive_players = []
choices = {}
current_pairs = []
round_num = 0
game_active = False
group_id = None
max_rounds = 20

async def startgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global players, alive_players, choices, game_active, round_num, group_id
    if game_active:
        await update.message.reply_text("A game is already running.")
        return
    players = []
    alive_players = []
    choices = {}
    round_num = 0
    game_active = True
    group_id = update.effective_chat.id
    await update.message.reply_text("🎮 Trust Test is starting! Players, type /join to enter!")

async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in players:
        players.append(user.id)
        alive_players.append(user.id)
        await update.message.reply_text(f"{user.first_name} joined the game.")
    else:
        await update.message.reply_text("You already joined.")

async def begin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global round_num
    if not game_active or len(alive_players) < 2:
        await update.message.reply_text("❌ Not enough players to start.")
        return
    await update.message.reply_text("🔥 Game is starting!")
    await new_round(context)

async def new_round(context: ContextTypes.DEFAULT_TYPE):
    global current_pairs, choices, round_num

    round_num += 1
    random.shuffle(alive_players)
    current_pairs = []
    choices = {}

    # Pair players
    while len(alive_players) >= 2:
        p1 = alive_players.pop()
        p2 = alive_players.pop()
        current_pairs.append((p1, p2))

    # Handle unpaired
    if alive_players:
        await context.bot.send_message(group_id, f"⚠️ {alive_players[0]} is unpaired and will sit this round.")
    
    # Ask choices
    for p1, p2 in current_pairs:
        for pid, opponent in [(p1, p2), (p2, p1)]:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🤝 Trust", callback_data=f"trust:{opponent}")],
                [InlineKeyboardButton("🔪 Betray", callback_data=f"betray:{opponent}")]
            ])
            try:
                await context.bot.send_message(pid, f"Round {round_num}\nYour opponent: [{opponent}]\nChoose:", reply_markup=keyboard)
            except:
                pass  # if bot can't DM, skip

async def handle_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global choices
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if user_id in choices:
        await query.edit_message_text("✅ Choice already made.")
        return

    data = query.data.split(":")
    decision, opponent_id = data[0], int(data[1])
    choices[user_id] = (decision, opponent_id)
    await query.edit_message_text(f"You chose: {'🤝 Trust' if decision == 'trust' else '🔪 Betray'}")

    if all(p1 in choices and p2 in choices for p1, p2 in current_pairs):
        await resolve_round(context)

async def resolve_round(context: ContextTypes.DEFAULT_TYPE):
    global alive_players, current_pairs, game_active

    round_results = "🌀 *Round Results:*\n"
    new_alive = []

    for p1, p2 in current_pairs:
        c1, _ = choices.get(p1, ("betray", p2))
        c2, _ = choices.get(p2, ("betray", p1))

        if c1 == "trust" and c2 == "trust":
            round_results += f"🤝 Both trusted: [{p1}] and [{p2}] survive.\n"
            new_alive += [p1, p2]
        elif c1 == "trust" and c2 == "betray":
            round_results += f"🔪 [{p2}] betrayed [{p1}]: only [{p2}] survives.\n"
            new_alive.append(p2)
        elif c1 == "betray" and c2 == "trust":
            round_results += f"🔪 [{p1}] betrayed [{p2}]: only [{p1}] survives.\n"
            new_alive.append(p1)
        else:
            round_results += f"💥 Both betrayed: [{p1}] and [{p2}] eliminated.\n"

    alive_players[:] = new_alive
    await context.bot.send_message(group_id, round_results, parse_mode="Markdown")

    if len(alive_players) <= 2:
        if len(alive_players) == 2:
            await context.bot.send_message(group_id, f"🏆 Winners: {alive_players[0]} and {alive_players[1]}!")
        elif len(alive_players) == 1:
            await context.bot.send_message(group_id, f"🏆 Lone Survivor: {alive_players[0]}")
        else:
            await context.bot.send_message(group_id, "💀 No one survived.")
        reset_game()
    else:
        await new_round(context)

def reset_game():
    global players, alive_players, current_pairs, choices, round_num, game_active
    players = []
    alive_players = []
    current_pairs = []
    choices = {}
    round_num = 0
    game_active = False

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("startgame", startgame))
    app.add_handler(CommandHandler("join", join))
    app.add_handler(CommandHandler("begin", begin))
    app.add_handler(CallbackQueryHandler(handle_choice))

    print("Bot running...")
    app.run_polling()
