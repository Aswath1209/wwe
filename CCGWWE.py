import telebot
import random
import time

# Replace this with your actual bot token
TOKEN = "8133604799:AAF2dE86UjRxfAdUcqyoz3O9RgaCeTwaoHM"
bot = telebot.TeleBot(TOKEN)

games = {}

def get_game(chat_id):
    if chat_id not in games:
        games[chat_id] = {
            "players": [],
            "eliminated": [],
            "holder": None,
            "last_holder": None,
            "active": False,
        }
    return games[chat_id]

@bot.message_handler(commands=['start_bomb'])
def start_bomb(message):
    game = get_game(message.chat.id)
    game.update({
        "players": [],
        "eliminated": [],
        "holder": None,
        "last_holder": None,
        "active": False,
    })
    bot.reply_to(message, "💣 Time Bomb game started! Use /join_bomb to enter.")

@bot.message_handler(commands=['join_bomb'])
def join_bomb(message):
    game = get_game(message.chat.id)
    player = '@' + message.from_user.username if message.from_user.username else message.from_user.first_name
    if player in game["players"]:
        bot.reply_to(message, f"{player}, you're already in the game.")
        return
    game["players"].append(player)
    bot.reply_to(message, f"✅ {player} joined the game!")

@bot.message_handler(commands=['begin_bomb'])
def begin_bomb(message):
    game = get_game(message.chat.id)
    if len(game["players"]) < 2:
        bot.reply_to(message, "At least 2 players are needed to start.")
        return
    game["active"] = True
    game["eliminated"] = []
    game["holder"] = random.choice(game["players"])
    game["last_holder"] = None
    bot.send_message(message.chat.id, f"🔥 Game started! 💣 {game['holder']} has the bomb!")

@bot.message_handler(commands=['pass'])
def pass_bomb(message):
    game = get_game(message.chat.id)
    sender = '@' + message.from_user.username if message.from_user.username else message.from_user.first_name

    if not game["active"]:
        bot.reply_to(message, "❌ No active game. Use /start_bomb first.")
        return
    if game["holder"] != sender:
        bot.reply_to(message, "❌ You don't have the bomb!")
        return
    if not message.text.split(" ", 1)[-1].strip():
        bot.reply_to(message, "Usage: /pass @username")
        return

    target = message.text.split(" ", 1)[-1].strip()
    if target.startswith("@") == False:
        bot.reply_to(message, "Please mention the target with @")
        return

    alive_players = [p for p in game["players"] if p not in game["eliminated"]]

    if target not in alive_players:
        bot.reply_to(message, "Invalid or eliminated player.")
        return

    if len(alive_players) > 2 and target == game["last_holder"]:
        bot.reply_to(message, "🚫 You can't pass it back to the last person!")
        return

    # 25% explosion chance
    if random.randint(1, 4) == 1:
        game["eliminated"].append(game["holder"])
        bot.send_message(message.chat.id, f"💥 BOOM! {game['holder']} exploded!")
        alive = [p for p in game["players"] if p not in game["eliminated"]]
        if len(alive) == 1:
            bot.send_message(message.chat.id, f"🏆 {alive[0]} is the winner!")
            game["active"] = False
        else:
            new_holder = random.choice(alive)
            game["holder"] = new_holder
            game["last_holder"] = None
            bot.send_message(message.chat.id, f"💣 Bomb respawned with {new_holder}!")
    else:
        game["last_holder"] = game["holder"]
        game["holder"] = target
        bot.send_message(message.chat.id, f"💣 {sender} passed the bomb to {target}!")

# Run bot
print("Bot running...")
bot.infinity_polling()
