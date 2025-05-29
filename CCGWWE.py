# CCGWWE.py — PART 1

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    CallbackQueryHandler, ContextTypes
)
import random

fights = {}

MOVES = {
    "RKO": {"type": "attack", "power": 30},
    "Spear": {"type": "attack", "power": 25},
    "Superman Punch": {"type": "attack", "power": 20},
    "Block": {"type": "defend", "power": 20},
    "Heal": {"type": "heal", "power": 20},
}

def move_buttons():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("RKO", callback_data="RKO"),
         InlineKeyboardButton("Spear", callback_data="Spear"),
         InlineKeyboardButton("Superman Punch", callback_data="Superman Punch")],
        [InlineKeyboardButton("Block", callback_data="Block"),
         InlineKeyboardButton("Heal", callback_data="Heal")]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤼 Welcome to Wrestling Fight Bot!\n\n"
        "Use /fight to start a match.\n"
        "Use /help for moves guide."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 Moves Guide:\n\n"
        "🌀 RKO – Strong attack (30 dmg)\n"
        "⚡ Spear – Mid attack (25 dmg)\n"
        "👊 Superman Punch – Fast attack (20 dmg)\n"
        "🛡️ Block – Reduces next damage\n"
        "❤️ Heal – Recover 20 HP\n\n"
        "Moves are revealed after both choose.\n"
        "Use /forfeit to quit a match."
    )

async def fight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id

    if chat_id in fights:
        await update.message.reply_text("⚠️ A match is already running.")
        return

    fights[chat_id] = {
        "players": {user.id: {"name": user.first_name, "hp": 100, "move": None}},
        "state": "waiting"
    }
    await update.message.reply_text(
        f"👤 {user.first_name} started a fight!\n"
        "Type /join to enter."
    )

async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id

    if chat_id not in fights or fights[chat_id]["state"] != "waiting":
        await update.message.reply_text("⚠️ No match to join.")
        return

    if user.id in fights[chat_id]["players"]:
        await update.message.reply_text("You're already in the match.")
        return

    fights[chat_id]["players"][user.id] = {
        "name": user.first_name, "hp": 100, "move": None
    }
    fights[chat_id]["state"] = "playing"

    p1, p2 = fights[chat_id]["players"].values()
    await update.message.reply_text(
        f"🔥 Match: {p1['name']} vs {p2['name']}\n\n"
        f"{p1['name']} HP: {p1['hp']}\n"
        f"{p2['name']} HP: {p2['hp']}\n\n"
        "Choose your move 👇",
        reply_markup=move_buttons()
    )

async def handle_move(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    chat_id = query.message.chat_id
    move = query.data

    if chat_id not in fights:
        await query.message.reply_text("⚠️ No active fight.")
        return

    game = fights[chat_id]
    if user.id not in game["players"]:
        await query.message.reply_text("⚠️ You're not in the match.")
        return

    player = game["players"][user.id]
    if player["move"] is not None:
        await query.message.reply_text("You already chose a move.")
        return

    player["move"] = move
    await query.message.edit_text(f"{player['name']} chose a move...")

    if all(p["move"] for p in game["players"].values()):
        await resolve_turn(update, context, chat_id)
# CCGWWE.py — PART 2

async def resolve_turn(update, context, chat_id):
    game = fights[chat_id]
    ids = list(game["players"].keys())
    p1, p2 = game["players"][ids[0]], game["players"][ids[1]]
    m1, m2 = p1["move"], p2["move"]
    log = ""

    def apply(p, m, enemy_move, opponent):
        info = MOVES[m]
        if info["type"] == "attack":
            dmg = info["power"]
            if MOVES[enemy_move]["type"] == "defend":
                dmg -= MOVES[enemy_move]["power"]
                dmg = max(0, dmg)
            opponent["hp"] -= dmg
            return f"{p['name']} used {m} ➡️ -{dmg} HP\n"
        elif info["type"] == "defend":
            return f"{p['name']} blocked!\n"
        elif info["type"] == "heal":
            p["hp"] = min(100, p["hp"] + info["power"])
            return f"{p['name']} healed +{info['power']} HP\n"

    log += apply(p1, m1, m2, p2)
    log += apply(p2, m2, m1, p1)

    p1["move"], p2["move"] = None, None

    if p1["hp"] <= 0 or p2["hp"] <= 0:
        winner = p1["name"] if p1["hp"] > 0 else p2["name"]
        await context.bot.send_message(chat_id,
            f"{log}\n"
            f"{p1['name']} HP: {p1['hp']}\n"
            f"{p2['name']} HP: {p2['hp']}\n\n"
            f"🏆 {winner} wins!"
        )
        del fights[chat_id]
    else:
        await context.bot.send_message(chat_id,
            f"{log}\n"
            f"{p1['name']} HP: {p1['hp']}\n"
            f"{p2['name']} HP: {p2['hp']}\n\n"
            "Next move 👇",
            reply_markup=move_buttons()
        )

async def forfeit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id

    if chat_id not in fights:
        await update.message.reply_text("⚠️ No fight to forfeit.")
        return

    if user.id not in fights[chat_id]["players"]:
        await update.message.reply_text("⚠️ You're not in this match.")
        return

    name = fights[chat_id]["players"][user.id]["name"]
    del fights[chat_id]
    await update.message.reply_text(f"🚪 {name} forfeited the match!")

def main():
    # 👉 PUT YOUR BOT TOKEN BELOW7821453313:AAHKskxl8WLbRKTFYccvH3SPSVDeVoEzo6U
    application = ApplicationBuilder().token("7821453313:AAHKskxl8WLbRKTFYccvH3SPSVDeVoEzo6U").build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("fight", fight))
    application.add_handler(CommandHandler("join", join))
    application.add_handler(CommandHandler("forfeit", forfeit))
    application.add_handler(CallbackQueryHandler(handle_move))

    print("🤖 Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
