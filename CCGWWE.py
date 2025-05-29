import os
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes
)

# ⬇️ Replace with your actual bot token
BOT_TOKEN = "7821453313:AAHKskxl8WLbRKTFYccvH3SPSVDeVoEzo6U"

# 🗂 Match data
match_data = {
    "players": [],
    "hp": {},
    "turn": 0,
    "special_used": {},
    "finisher_ready": {}
}

# 🎞 GIFs
special_moves = {
    "RKO": "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif",
    "Spear": "https://media.giphy.com/media/3o6ZtaO9BZHcOjmErm/giphy.gif"
}

finishers = {
    "Tombstone": "https://media.giphy.com/media/3o6Zt6ML6BklcajjsA/giphy.gif",
    "F5": "https://media.giphy.com/media/3o6ZsY8gZ1uV3gYxkU/giphy.gif"
}

# 🟢 /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👊 Welcome to WWE Bot!\nUse /fight to challenge someone!"
    )

# ⚔️ /fight command
async def fight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if len(match_data["players"]) == 0:
        match_data["players"].append(user.username)
        await update.message.reply_text(
            f"👑 {user.username} is waiting for an opponent...\nAsk someone to use /fight to join."
        )
    elif len(match_data["players"]) == 1 and user.username != match_data["players"][0]:
        match_data["players"].append(user.username)
        for p in match_data["players"]:
            match_data["hp"][p] = 100
            match_data["special_used"][p] = False
            match_data["finisher_ready"][p] = False
        match_data["turn"] = 0
        await update.message.reply_text(
            f"🔥 Match started: {match_data['players'][0]} vs {match_data['players'][1]}!\n"
            f"{match_data['players'][0]} goes first!"
        )
        await send_turn_buttons(update, context)
    else:
        await update.message.reply_text("⚠️ Match already in progress!")

# 🎮 Buttons for moves
async def send_turn_buttons(update, context):
    current = match_data["players"][match_data["turn"]]
    keyboard = [
        [InlineKeyboardButton("👊 Attack", callback_data="attack")],
        [InlineKeyboardButton("💥 Special", callback_data="special")],
        [InlineKeyboardButton("🔥 Finisher", callback_data="finisher")]
    ]
    markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🎯 {current}, it's your turn!\nChoose your move:",
        reply_markup=markup
    )

# 🎬 Move logic
async def handle_move(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user.username
    if user != match_data["players"][match_data["turn"]]:
        await query.answer("⏳ Wait for your turn.")
        return

    move = query.data
    attacker = user
    defender = match_data["players"][1 - match_data["turn"]]

    if move == "attack":
        dmg = random.randint(10, 20)
        match_data["hp"][defender] -= dmg
        await query.edit_message_text(f"👊 {attacker} punches {defender} for {dmg} HP!")
    elif move == "special":
        if match_data["special_used"][attacker]:
            await query.answer("❌ Special already used.")
            return
        move_name, gif = random.choice(list(special_moves.items()))
        dmg = random.randint(20, 30)
        match_data["hp"][defender] -= dmg
        match_data["special_used"][attacker] = True
        await context.bot.send_animation(
            chat_id=update.effective_chat.id,
            animation=gif,
            caption=f"💥 {attacker} hits {move_name} on {defender} (-{dmg})"
        )
    elif move == "finisher":
        if match_data["hp"][defender] > 30:
            await query.answer("❌ Not ready yet!")
            return
        move_name, gif = random.choice(list(finishers.items()))
        dmg = random.randint(35, 50)
        match_data["hp"][defender] -= dmg
        await context.bot.send_animation(
            chat_id=update.effective_chat.id,
            animation=gif,
            caption=f"🔥 {attacker} finishes with {move_name}!\n{defender} loses {dmg} HP!"
        )

    # 💀 Check winner
    if match_data["hp"][defender] <= 0:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"🏆 {attacker} wins! 🎉"
        )
        reset_match()
        return

    # 🔁 Next turn
    match_data["turn"] = 1 - match_data["turn"]
    await send_turn_buttons(update, context)

# 🔁 Reset
def reset_match():
    match_data["players"].clear()
    match_data["hp"].clear()
    match_data["special_used"].clear()
    match_data["finisher_ready"].clear()
    match_data["turn"] = 0

# 🚀 Main
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("fight", fight))
    app.add_handler(CallbackQueryHandler(handle_move))
    app.run_polling()

if __name__ == "__main__":
    main()
