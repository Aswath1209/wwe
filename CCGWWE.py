import random
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    CallbackQueryHandler
)

TOKEN = "8133604799:AAF2dE86UjRxfAdUcqyoz3O9RgaCeTwaoHM"

players = []
points = {}
choices = {}
round_num = 0
game_active = False
group_id = None
group_title = None
MAX_ROUNDS = 5

async def startgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global players, points, choices, game_active, round_num, group_id, group_title
    if game_active:
        await update.message.reply_text("⚠️ A game is already running.")
        return
    players.clear()
    points.clear()
    choices.clear()
    round_num = 0
    game_active = True
    group_id = update.effective_chat.id
    group_title = update.effective_chat.title or "this group"

    text = (
        "🎲 *Trust Test - Registration is OPEN!*\n\n"
        "👥 *Registered Players:*\n"
        "_None yet_\n\n"
        "Tap the button below to *Join* the game!"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👉 Join", callback_data="join")]
    ])
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)

async def update_registration_message(context: ContextTypes.DEFAULT_TYPE):
    global players, group_id
    if not group_id:
        return
    if not players:
        text = (
            "🎲 *Trust Test - Registration is OPEN!*\n\n"
            "👥 *Registered Players:*\n"
            "_None yet_\n\n"
            "Tap the button below to *Join* the game!"
        )
    else:
        player_lines = []
        for uid in players:
            player_lines.append(f"• [{uid}](tg://user?id={uid})")
        text = (
            "🎲 *Trust Test - Registration is OPEN!*\n\n"
            "👥 *Registered Players:*\n" +
            "\n".join(player_lines) + 
            f"\n\n🧍 {len(players)} player(s) registered so far.\n\n"
            "Tap the button below to *Join* the game!"
        )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👉 Join", callback_data="join")]
    ])

    chat = await context.bot.get_chat(group_id)
    history = await chat.get_history(limit=10)
    for msg in history:
        if msg.from_user and msg.from_user.id == context.bot.id:
            try:
                await msg.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
                break
            except:
                pass

async def join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global players, points, group_title
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if user.id in players:
        await query.edit_message_text("❌ You already joined the game!")
        return

    players.append(user.id)
    points[user.id] = 0

    await update_registration_message(context)

    try:
        await context.bot.send_message(
            user.id,
            f"✅ You joined the game in *{group_title}*",
            parse_mode=ParseMode.MARKDOWN
        )
    except:
        await query.edit_message_text(
            "⚠️ Please start a private chat with me first and then click Join."
        )

async def begin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global game_active, players, round_num
    if not game_active:
        await update.message.reply_text("⚠️ No game is currently running. Use /startgame to start registration.")
        return
    if len(players) < 2:
        await update.message.reply_text("⚠️ Need at least 2 players to start the game.")
        return
    round_num = 1
    await update.message.reply_text(f"🔥 Trust Test Game is starting with {len(players)} players!")
    await start_round(context)

async def start_round(context: ContextTypes.DEFAULT_TYPE):
    global choices, round_num, players

    choices.clear()
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🤝 Trust", callback_data="choice_trust"),
            InlineKeyboardButton("🔪 Betray", callback_data="choice_betray")
        ]
    ])

    for user_id in players:
        try:
            await context.bot.send_message(
                user_id,
                f"🎯 *Round {round_num}*: Choose your move!",
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            pass

async def choice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global choices, round_num, players, points, game_active

    query = update.callback_query
    user = query.from_user
    data = query.data
    await query.answer()

    if user.id not in players:
        await query.edit_message_text("❌ You are not part of the current game.")
        return

    if user.id in choices:
        await query.edit_message_text("❌ You already chose this round.")
        return

    if data == "choice_trust":
        choices[user.id] = "trust"
        points[user.id] += 1
        await query.edit_message_text("✅ You chose 🤝 Trust")
    elif data == "choice_betray":
        choices[user.id] = "betray"
        points[user.id] += 2
        await query.edit_message_text("✅ You chose 🔪 Betray")
    else:
        await query.edit_message_text("❌ Invalid choice.")
        return

    if len(choices) == len(players):
        await announce_round(context)

        round_num += 1
        if round_num > MAX_ROUNDS:
            await announce_winner(context)
            game_active = False
        else:
            await start_round(context)

async def announce_round(context: ContextTypes.DEFAULT_TYPE):
    global choices, players, group_id, round_num

    if not group_id:
        return

    trusters = [uid for uid, ch in choices.items() if ch == "trust"]
    betrayers = [uid for uid, ch in choices.items() if ch == "betray"]

    text = f"📢 *Round {round_num} Results:*\n\n"
    text += f"🤝 Trust: {len(trusters)} player(s)\n"
    for uid in trusters:
        text += f"• [{uid}](tg://user?id={uid})\n"
    text += f"\n🔪 Betray: {len(betrayers)} player(s)\n"
    for uid in betrayers:
        text += f"• [{uid}](tg://user?id={uid})\n"

    text += "\n🏆 *Current Points:*\n"
    leaderboard = sorted(((p, uid) for uid, p in points.items()), reverse=True)
    for pts, uid in leaderboard:
        text += f"• [{uid}](tg://user?id={uid}): {pts} pts\n"

    await context.bot.send_message(group_id, text, parse_mode=ParseMode.MARKDOWN)

async def announce_winner(context: ContextTypes.DEFAULT_TYPE):
    global points, group_id

    if not group_id:
        return

    max_pts = max(points.values())
    winners = [uid for uid, p in points.items() if p == max_pts]

    if len(winners) == 1:
        text = f"🏅 The winner is [{winners[0]}](tg://user?id={winners[0]}) with *{max_pts} points*! 🎉🎉"
    else:
        text = f"🏅 It's a tie between {len(winners)} players with *{max_pts} points* each! 🤝\n"
        for uid in winners:
            text += f"• [{uid}](tg://user?id={uid})\n"

    await context.bot.send_message(group_id, text, parse_mode=ParseMode.MARKDOWN)

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("startgame", startgame))
    app.add_handler(CommandHandler("begin", begin))
    app.add_handler(CallbackQueryHandler(join_callback, pattern="^join$"))
    app.add_handler(CallbackQueryHandler(choice_handler, pattern="^choice_"))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
