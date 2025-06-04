import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from collections import defaultdict
import threading
import time

TOKEN = "8133604799:AAF2dE86UjRxfAdUcqyoz3O9RgaCeTwaoHM"
bot = telebot.TeleBot(TOKEN)

games = {}

ROUND_DURATION = 30  # seconds

def reset_game(chat_id):
    games[chat_id] = {
        "players": {},
        "choices": {},
        "scores": defaultdict(int),
        "round_active": False
    }

@bot.message_handler(commands=['start_launch'])
def start_game(message):
    chat_id = message.chat.id
    reset_game(chat_id)
    bot.reply_to(message, "🎮 Launch or Loot game started!\nPlayers, join using /join_launch")

@bot.message_handler(commands=['join_launch'])
def join_game(message):
    chat_id = message.chat.id
    user = message.from_user
    if not user.username:
        bot.reply_to(message, "⚠️ You must have a Telegram username to play.")
        return
    player = f"@{user.username}"
    game = games.get(chat_id)
    if not game:
        bot.reply_to(message, "❌ Game not started. Use /start_launch")
        return
    if player in game["players"]:
        bot.reply_to(message, f"{player}, you're already in.")
    else:
        game["players"][player] = user.id
        bot.reply_to(message, f"✅ {player} joined the game!")

@bot.message_handler(commands=['begin_launch'])
def begin_round(message):
    chat_id = message.chat.id
    game = games.get(chat_id)
    if not game or len(game["players"]) < 2:
        bot.reply_to(message, "❌ Need at least 2 players to begin.")
        return
    if game["round_active"]:
        bot.reply_to(message, "⚠️ Round already active. Wait.")
        return

    game["choices"] = {}
    game["round_active"] = True
    bot.send_message(chat_id, "🚀 New round started!\nChoices will be made secretly via DM. You have 30 seconds ⏳")

    for player, user_id in game["players"].items():
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("🚀 Launch", callback_data=f"launch|{chat_id}"),
            InlineKeyboardButton("💰 Loot", callback_data=f"loot|{chat_id}")
        )
        try:
            bot.send_message(user_id, "🤫 Choose your move for this round:", reply_markup=markup)
        except:
            bot.send_message(chat_id, f"⚠️ Couldn't send DM to {player}. They may need to start the bot in PM.")

    threading.Thread(target=finish_round, args=(chat_id,)).start()

@bot.callback_query_handler(func=lambda call: True)
def handle_choice(call):
    try:
        choice, chat_id = call.data.split("|")
        chat_id = int(chat_id)
        game = games.get(chat_id)
        if not game or not game["round_active"]:
            bot.answer_callback_query(call.id, "❌ Round is not active.")
            return

        player = f"@{call.from_user.username}"
        if player not in game["players"]:
            bot.answer_callback_query(call.id, "❌ You're not part of the game.")
            return
        if player in game["choices"]:
            bot.answer_callback_query(call.id, "⚠️ You've already chosen.")
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

    result = "🔔 Round Over!\n\n"
    if not choices:
        result += "😴 No one made a choice."
    elif len(looters) == 1:
        winner = looters[0]
        game["scores"][winner] += 5
        result += f"💰 {winner} looted successfully and got 5 points!"
    elif len(looters) > 1:
        result += f"💥 Multiple looters! They all exploded: {', '.join(looters)}"
    else:
        for p in launchers:
            game["scores"][p] += 1
        result += f"🚀 All launched safely. Each gets 1 point!"

    result += "\n\n🏆 Current Scores:\n"
    for p, s in sorted(game["scores"].items(), key=lambda x: -x[1]):
        result += f"{p}: {s} pts\n"

    bot.send_message(chat_id, result)
    bot.send_message(chat_id, "➡️ Use /begin_launch for the next round.")

@bot.message_handler(commands=['end_launch'])
def end_game(message):
    chat_id = message.chat.id
    if chat_id in games:
        del games[chat_id]
    bot.send_message(chat_id, "🛑 Game ended.")

print("🚀 Bot is running...")
bot.infinity_polling()
