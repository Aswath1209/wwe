import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from collections import defaultdict
import threading
import time

TOKEN = "8133604799:AAF2dE86UjRxfAdUcqyoz3O9RgaCeTwaoHM"
bot = telebot.TeleBot(TOKEN)

games = {}
ROUND_DURATION = 20
MAX_ROUNDS = 5

def reset_game(chat_id):
    games[chat_id] = {
        "players": {},              # { @username: user_id }
        "choices": {},              # { @username: 'launch' or 'loot' }
        "scores": defaultdict(int), # { @username: points }
        "round_active": False,
        "round_count": 0
    }

@bot.message_handler(commands=['start_launch'])
def start_game(message):
    chat_id = message.chat.id
    reset_game(chat_id)
    bot.reply_to(message, "🎮 Game started!\nPlayers join with /join_launch")

@bot.message_handler(commands=['join_launch'])
def join_game(message):
    chat_id = message.chat.id
    user = message.from_user
    if not user.username:
        bot.reply_to(message, "⚠️ You need a username to join.")
        return
    player = f"@{user.username}"
    game = games.get(chat_id)
    if not game:
        bot.reply_to(message, "❌ No game found. Use /start_launch first.")
        return
    if player in game["players"]:
        bot.reply_to(message, "🔁 You already joined.")
    else:
        game["players"][player] = user.id
        bot.reply_to(message, f"✅ {player} joined the game.")

@bot.message_handler(commands=['begin_launch'])
def begin_round(message):
    chat_id = message.chat.id
    game = games.get(chat_id)
    if not game or len(game["players"]) < 2:
        bot.reply_to(message, "❌ Need at least 2 players.")
        return
    if game["round_active"]:
        bot.reply_to(message, "⚠️ A round is already in progress.")
        return
    if game["round_count"] >= MAX_ROUNDS:
        bot.send_message(chat_id, "🛑 Max rounds reached! Game over.\nUse /end_launch to reset.")
        return

    game["choices"] = {}
    game["round_active"] = True
    game["round_count"] += 1

    bot.send_message(chat_id, f"🚨 Round {game['round_count']} started!\nPlayers, check your DMs.")

    for player, user_id in game["players"].items():
        try:
            markup = InlineKeyboardMarkup()
            markup.row(
                InlineKeyboardButton("🚀 Launch", callback_data=f"launch|{chat_id}"),
                InlineKeyboardButton("💰 Loot", callback_data=f"loot|{chat_id}")
            )
            bot.send_message(user_id, "🤫 Choose your move for this round:", reply_markup=markup)
        except Exception as e:
            bot.send_message(chat_id, f"⚠️ Can't DM {player}. Tell them to start the bot in PM.")

    threading.Thread(target=finish_round, args=(chat_id,)).start()

@bot.callback_query_handler(func=lambda call: True)
def handle_choice(call):
    try:
        choice, chat_id = call.data.split("|")
        chat_id = int(chat_id)
        game = games.get(chat_id)
        if not game or not game["round_active"]:
            bot.answer_callback_query(call.id, "❌ No active round.")
            return

        player = f"@{call.from_user.username}"
        if player not in game["players"]:
            bot.answer_callback_query(call.id, "❌ You're not in this game.")
            return
        if player in game["choices"]:
            bot.answer_callback_query(call.id, "⚠️ Already chosen.")
            return

        game["choices"][player] = choice
        bot.answer_callback_query(call.id, f"✅ You chose {choice.upper()}")
        bot.edit_message_text("✅ Choice received!", chat_id=call.message.chat.id, message_id=call.message.message_id)
    except Exception as e:
        print("Callback error:", e)

def finish_round(chat_id):
    time.sleep(ROUND_DURATION)
    game = games.get(chat_id)
    if not game or not game["round_active"]:
        return

    game["round_active"] = False
    choices = game["choices"]
    launchers = [p for p, c in choices.items() if c == "launch"]
    looters = [p for p, c in choices.items() if c == "loot"]

    result = f"🕛 Time’s up!\n\n🎲 Round {game['round_count']} Results:\n"
    if not choices:
        result += "😴 No one made a choice!"
    elif len(looters) == 1:
    winner = looters[0]
    game["scores"][winner] += 5
    result += f"💰 {winner} looted alone and got 5 points!\n"
    if launchers:
        for p in launchers:
            game["scores"][p] += 1
        result += f"🚀 Launchers still launched safely and got 1 point each."
    elif len(looters) > 1:
        result += f"💥 Boom! Multiple looters exploded: {', '.join(looters)}"
    else:
        for p in launchers:
            game["scores"][p] += 1
        result += f"🚀 Everyone launched. All safe! +1 point each."

    result += "\n\n🏆 Scores:\n"
    for p, s in sorted(game["scores"].items(), key=lambda x: -x[1]):
        result += f"{p}: {s} pts\n"

    if game["round_count"] >= MAX_ROUNDS:
        result += "\n🏁 Game Over! Max rounds reached."
    else:
        result += "\n➡️ Use /begin_launch for next round."

    bot.send_message(chat_id, result)

@bot.message_handler(commands=['end_launch'])
def end_game(message):
    chat_id = message.chat.id
    if chat_id in games:
        del games[chat_id]
    bot.send_message(chat_id, "🛑 Game session ended.")

print("🚀 Launch or Loot bot running...")
bot.infinity_polling()
