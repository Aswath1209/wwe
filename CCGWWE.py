import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

# 🔐 Your Bot Token
BOT_TOKEN = "8198938492:AAFE0CxaXVeB8cpyphp7pSV98oiOKlf5Jwo"

match_data = {
    "players": [],
    "hp": {},
    "turn": 0,
    "special_used": {},
    "focus_used": {},
    "status": {}
}

# 🎮 Fight buttons
def move_buttons():
    keyboard = [
        [InlineKeyboardButton("🥊 Attack", callback_data="attack"),
         InlineKeyboardButton("🛡️ Block", callback_data="block")],
        [InlineKeyboardButton("🔄 Counter", callback_data="counter"),
         InlineKeyboardButton("🧠 Focus", callback_data="focus")],
        [InlineKeyboardButton("💥 Special", callback_data="special"),
         InlineKeyboardButton("🔥 Finisher", callback_data="finisher")]
    ]
    return InlineKeyboardMarkup(keyboard)

# 🔁 Reset match
def reset():
    match_data.update({
        "players": [],
        "hp": {},
        "turn": 0,
        "special_used": {},
        "focus_used": {},
        "status": {}
    })

# 🟢 /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤼 Welcome to Strategic WWE Bot!\nType /fight to challenge someone.")

# ⚔️ /fight
async def fight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.username
    if user in match_data["players"]:
        await update.message.reply_text("⚠️ You're already in the match.")
        return
    if len(match_data["players"]) < 2:
        match_data["players"].append(user)
        if len(match_data["players"]) == 1:
            await update.message.reply_text(f"👑 {user} is waiting for an opponent...")
        else:
            for p in match_data["players"]:
                match_data["hp"][p] = 100
                match_data["special_used"][p] = False
                match_data["focus_used"][p] = False
                match_data["status"][p] = {"block": False, "focus": False, "counter": False}
            await update.message.reply_text(
                f"🔥 Match: {match_data['players'][0]} vs {match_data['players'][1]}!\n"
                f"{match_data['players'][0]} goes first!"
            )
            await send_turn(update, context)
    else:
        await update.message.reply_text("⚔️ Match already in progress.")

# 📤 Send move options
async def send_turn(update, context):
    player = match_data["players"][match_data["turn"]]
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🎯 {player}, choose your move:",
        reply_markup=move_buttons()
    )

# 🎯 Handle move
async def handle_move(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    player = query.from_user.username
    if player != match_data["players"][match_data["turn"]]:
        await query.answer("⏳ Not your turn.")
        return

    opponent = match_data["players"][1 - match_data["turn"]]
    move = query.data
    msg = ""

    # Finisher check
    if move == "finisher":
        if match_data["hp"][opponent] > 30:
            await query.answer("❌ Opponent HP too high!")
            return
        dmg = random.randint(35, 50)
        match_data["hp"][opponent] -= dmg
        msg += f"🔥 {player} uses FINISHER!\n{opponent} takes {dmg} damage!\n"

    elif move == "special":
        if match_data["special_used"][player]:
            await query.answer("❌ Special already used!")
            return
        dmg = random.randint(20, 30)
        match_data["hp"][opponent] -= dmg
        match_data["special_used"][player] = True
        match_data["status"][opponent]["block"] = False
        msg += f"💥 {player} hits a SPECIAL! {opponent} takes {dmg}!\nBlock disabled!"

    elif move == "attack":
        dmg = random.randint(10, 20)
        if match_data["status"][opponent]["block"]:
            dmg = dmg // 2
            msg += f"🛡️ {opponent} blocked! Damage reduced.\n"
        if match_data["status"][player]["focus"]:
            dmg += 5
            msg += f"🧠 Focus boost! +5 damage.\n"
        match_data["hp"][opponent] -= dmg
        msg += f"🥊 {player} attacks {opponent} for {dmg} HP!"

    elif move == "block":
        match_data["status"][player]["block"] = True
        msg += f"🛡️ {player} is blocking next attack!"

    elif move == "counter":
        match_data["status"][player]["counter"] = True
        msg += f"🔄 {player} is ready to counter!"

    elif move == "focus":
        match_data["status"][player]["focus"] = True
        msg += f"🧠 {player} is focusing for next move!"

    # Apply counter
    if match_data["status"][opponent]["counter"] and move == "attack":
        cdmg = random.randint(5, 10)
        match_data["hp"][player] -= cdmg
        msg += f"\n🔁 COUNTER! {player} takes {cdmg} reflected damage!"

    # Reset opponent status
    match_data["status"][opponent] = {"block": False, "focus": False, "counter": False}

    # Check winner
    if match_data["hp"][opponent] <= 0:
        msg += f"\n🏆 {player} wins!"
        await query.edit_message_text(msg)
        reset()
        return

    match_data["turn"] = 1 - match_data["turn"]
    await query.edit_message_text(msg)
    await send_turn(update, context)

# 🚀 Run bot
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("fight", fight))
    app.add_handler(CallbackQueryHandler(handle_move))
    app.run_polling()

if __name__ == "__main__":
    main()
