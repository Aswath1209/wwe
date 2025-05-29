# CCGWWE.py — PART 1

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    CallbackQueryHandler, ContextTypes
)
import random

# Store active fight data
fights = {}

# Move definitions
MOVES = {
    "RKO": {"type": "attack", "power": 30},
    "Spear": {"type": "attack", "power": 25},
    "Superman Punch": {"type": "attack", "power": 20},
    "Block": {"type": "defend", "power": 15},
    "Heal": {"type": "heal", "power": 20},
}

# Show health bar
def health_bar(hp):
    filled = "🟩" * (hp // 10)
    empty = "⬛" * (10 - (hp // 10))
    return filled + empty

# Create move buttons
def move_buttons():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("RKO", callback_data="RKO"),
         InlineKeyboardButton("Spear", callback_data="Spear"),
         InlineKeyboardButton("Superman Punch", callback_data="Superman Punch")],
        [InlineKeyboardButton("Block", callback_data="Block"),
         InlineKeyboardButton("Heal", callback_data="Heal")]
    ])

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👊 Welcome to Telegram Wrestling!\n"
        "Use /fight to start a match.\n"
        "Moves: RKO, Spear, Superman Punch, Block, Heal."
    )

# Fight command
async def fight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id

    if chat_id in fights:
        await update.message.reply_text("⚠️ A fight is already in progress.")
        return

    fights[chat_id] = {
        "players": {user.id: {"name": user.first_name, "hp": 100, "move": None}},
        "state": "waiting"
    }
    await update.message.reply_text(
        f"👤 {user.first_name} started a fight!\n"
        "Another player, type /join to enter."
    )

# Join command
async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id

    if chat_id not in fights or fights[chat_id]["state"] != "waiting":
        await update.message.reply_text("⚠️ No match available to join.")
        return

    if user.id in fights[chat_id]["players"]:
        await update.message.reply_text("You're already in this fight.")
        return

    fights[chat_id]["players"][user.id] = {
        "name": user.first_name, "hp": 100, "move": None
    }
    fights[chat_id]["state"] = "playing"

    p1, p2 = fights[chat_id]["players"].values()
    await update.message.reply_text(
        f"🔥 Match started!\n\n"
        f"{p1['name']} 🆚 {p2['name']}\n\n"
        f"{p1['name']} HP: {health_bar(p1['hp'])}\n"
        f"{p2['name']} HP: {health_bar(p2['hp'])}\n\n"
        "Choose your move:",
        reply_markup=move_buttons()
    )

# Move handler
async def handle_move(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    chat_id = query.message.chat_id
    move = query.data

    if chat_id not in fights:
        await query.message.reply_text("⚠️ No active match.")
        return

    game = fights[chat_id]
    if user.id not in game["players"]:
        await query.message.reply_text("⚠️ You're not in this fight.")
        return

    game["players"][user.id]["move"] = move
    await query.message.edit_text(f"{user.first_name} chose their move...")

    # Check if both have selected
    moves = [p["move"] for p in game["players"].values()]
    if None not in moves:
        await resolve_turn(update, context, chat_id)

# Turn resolver
async def resolve_turn(update, context, chat_id):
    game = fights[chat_id]
    ids = list(game["players"].keys())
    p1, p2 = game["players"][ids[0]], game["players"][ids[1]]

    m1, m2 = p1["move"], p2["move"]
    log = ""

    # Apply logic
    def calc(p, m, enemy_m, enemy):
        info = MOVES[m]
        if info["type"] == "attack":
            dmg = info["power"]
            if MOVES[enemy_m]["type"] == "defend":
                dmg -= MOVES[enemy_m]["power"]
                dmg = max(0, dmg)
            game["players"][enemy]["hp"] -= dmg
            return f"{p['name']} used {m} ➡️ -{dmg} HP\n"
        elif info["type"] == "defend":
            return f"{p['name']} blocked!\n"
        elif info["type"] == "heal":
            game["players"][enemy]["hp"] += info["power"]
            if game["players"][enemy]["hp"] > 100:
                game["players"][enemy]["hp"] = 100
            return f"{p['name']} healed +{info['power']} HP\n"

    log += calc(p1, m1, m2, ids[1])
    log += calc(p2, m2, m1, ids[0])

    # Reset moves
    for pid in ids:
        game["players"][pid]["move"] = None

    hp1 = health_bar(p1["hp"])
    hp2 = health_bar(p2["hp"])

    if p1["hp"] <= 0 or p2["hp"] <= 0:
        winner = p1["name"] if p1["hp"] > 0 else p2["name"]
        await context.bot.send_message(chat_id,
            f"💥 {log}\n"
            f"{p1['name']} HP: {hp1}\n"
            f"{p2['name']} HP: {hp2}\n\n"
            f"🏆 {winner} wins the match!"
        )
        del fights[chat_id]
    else:
        await context.bot.send_message(chat_id,
            f"💥 {log}\n"
            f"{p1['name']} HP: {hp1}\n"
            f"{p2['name']} HP: {hp2}\n\n"
            "Choose your next move:",
            reply_markup=move_buttons()
    )
# CCGWWE.py — PART 2

def main():
    # 👉 PUT YOUR BOT TOKEN BELOW
    application = ApplicationBuilder().token("8198938492:AAFE0CxaXVeB8cpyphp7pSV98oiOKlf5Jwo").build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("fight", fight))
    application.add_handler(CommandHandler("join", join))
    application.add_handler(CallbackQueryHandler(handle_move))

    print("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
