from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
import logging

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)

# Put yur bot toen here
BOT_TOKEN = "7821453313:AAHKskxl8WLbRKTFYccvH3SPSVDeVoEzo6U"

active_matches = {}  # chat_id -> match data
user_to_match_chat = {}  # user_id -> chat_id of their active match

MOVES = {
    "punch": {"damage": 15, "text": "👊 Punch"},
    "kick": {"damage": 20, "text": "🦶 Kick"},
    "block": {"damage": 0, "text": "🛡️ Block"},
}


def get_move_buttons():
    buttons = [
        InlineKeyboardButton(text=info["text"], callback_data=key)
        for key, info in MOVES.items()
    ]
    return InlineKeyboardMarkup([buttons])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to Telegram Fight Bot! 🤼\n\n"
        "Use /fight to start a match.\n"
        "First player runs /fight, second player clicks Join."
    )


async def fight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user

    if chat_id in active_matches:
        await update.message.reply_text("A match is already active here.")
        return

    active_matches[chat_id] = {
        "players": [user.id],
        "names": {user.id: user.first_name},
        "hp": {user.id: 100},
        "moves": {},
        "turn": 1,
    }
    user_to_match_chat[user.id] = chat_id

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Join Match", callback_data="join")]]
    )

    await update.message.reply_text(
        f"{user.first_name} started a fight! Waiting for opponent...",
        reply_markup=keyboard,
    )


async def join_fight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    # Find the chat where the join button was pressed
    chat_id = query.message.chat.id
    if chat_id not in active_matches:
        await query.edit_message_text("❌ No active match here.")
        return

    match = active_matches[chat_id]

    if len(match["players"]) >= 2:
        await query.edit_message_text("Match already has 2 players.")
        return

    if user.id in match["players"]:
        await query.edit_message_text("You are already in this match.")
        return

    # Add second player
    match["players"].append(user.id)
    match["names"][user.id] = user.first_name
    match["hp"][user.id] = 100
    user_to_match_chat[user.id] = chat_id

    # Start the fight
    await query.edit_message_text(
        f"Fight started between {match['names'][match['players'][0]]} "
        f"and {match['names'][match['players'][1]]}!\n\n"
        f"Both players, check your private chats and pick your moves."
    )

    # Send move buttons privately
    for pid in match["players"]:
        try:
            await context.bot.send_message(
                chat_id=pid,
                text=f"Your HP: {match['hp'][pid]}\nChoose your move:",
                reply_markup=get_move_buttons(),
            )
        except Exception as e:
            logging.warning(f"Failed to send move buttons to {pid}: {e}")


async def move_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    move = query.data

    if move not in MOVES:
        await query.edit_message_text("Invalid move!")
        return

    match_chat_id = user_to_match_chat.get(user.id)
    if not match_chat_id or match_chat_id not in active_matches:
        await query.edit_message_text("❌ No active match found.")
        return

    match = active_matches[match_chat_id]

    if user.id not in match["players"]:
        await query.edit_message_text("You are not in the current match.")
        return

    if user.id in match["moves"]:
        await query.edit_message_text("You already made your move. Wait for opponent.")
        return

    match["moves"][user.id] = move
    await query.edit_message_text(f"You chose {MOVES[move]['text']}")

    if len(match["moves"]) < 2:
        # Wait for opponent
        return

    # Both players moved - resolve round
    p1, p2 = match["players"]
    m1, m2 = match["moves"][p1], match["moves"][p2]
    d1 = MOVES[m1]["damage"]
    d2 = MOVES[m2]["damage"]

    # Calculate damage done taking into account blocks
    def damage_dealt(attacker_move, defender_move):
        if defender_move == "block":
            return max(0, MOVES[attacker_move]["damage"] - 10)
        return MOVES[attacker_move]["damage"]

    damage_to_p2 = damage_dealt(m1, m2)
    damage_to_p1 = damage_dealt(m2, m1)

    match["hp"][p1] = max(0, match["hp"][p1] - damage_to_p1)
    match["hp"][p2] = max(0, match["hp"][p2] - damage_to_p2)

    summary = (
        f"Round {match['turn']} results:\n"
        f"{match['names'][p1]} used {MOVES[m1]['text']}, {match['names'][p2]} used {MOVES[m2]['text']}.\n\n"
        f"{match['names'][p1]} took {damage_to_p1} dmg, HP left: {match['hp'][p1]}\n"
        f"{match['names'][p2]} took {damage_to_p2} dmg, HP left: {match['hp'][p2]}"
    )

    # Check if fight ended
    if match["hp"][p1] == 0 and match["hp"][p2] == 0:
        result = "It's a draw! 🤝"
    elif match["hp"][p1] == 0:
        result = f"{match['names'][p2]} wins! 🏆"
    elif match["hp"][p2] == 0:
        result = f"{match['names'][p1]} wins! 🏆"
    else:
        result = None

    match["moves"] = {}
    match["turn"] += 1

    # Send summary to group chat
    await context.bot.send_message(chat_id=match_chat_id, text=summary)

    if result:
        await context.bot.send_message(chat_id=match_chat_id, text=f"🛑 Fight Over! {result}")
        # Cleanup
        for pid in match["players"]:
            user_to_match_chat.pop(pid, None)
        active_matches.pop(match_chat_id, None)
        return

    # Ask both players for next move
    for pid in match["players"]:
        try:
            await context.bot.send_message(
                chat_id=pid,
                text=f"Your HP: {match['hp'][pid]}\nChoose your next move:",
                reply_markup=get_move_buttons(),
            )
        except Exception as e:
            logging.warning(f"Failed to send move buttons to {pid}: {e}")


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("fight", fight))
    app.add_handler(CallbackQueryHandler(join_fight, pattern="^join$"))
    app.add_handler(CallbackQueryHandler(move_handler, pattern="^(punch|kick|block)$"))

    print("Bot started...")
    app.run_polling()


if __name__ == "__main__":
    main()
