import random
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = "8133604799:AAF2dE86UjRxfAdUcqyoz3O9RgaCeTwaoHM"

game_active = False
secret_number = 0
min_num = 1
max_num = 100
current_round = 0
max_rounds = 5

async def startgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global game_active, secret_number, min_num, max_num, current_round
    if game_active:
        await update.message.reply_text(f"⚠️ A game is already running! Round {current_round}/{max_rounds}")
        return
    game_active = True
    current_round = 1
    secret_number = random.randint(min_num, max_num)
    await update.message.reply_text(
        f"🎯 Guess The Number game started!\n"
        f"Round {current_round} of {max_rounds}\n"
        f"I'm thinking of a number between {min_num} and {max_num}.\n"
        "Send your guesses in this group."
    )

async def guess_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global game_active, secret_number, current_round, max_rounds

    if not game_active:
        return

    try:
        guess = int(update.message.text)
    except ValueError:
        return  # Ignore non-integers

    user = update.message.from_user
    if guess == secret_number:
        await update.message.reply_text(
            f"🎉 Congrats {user.mention_html()}! You guessed it right in round {current_round}. The number was {secret_number}.",
            parse_mode="HTML"
        )
        if current_round >= max_rounds:
            await update.message.reply_text("🏆 The game is over! Thanks for playing!")
            reset_game()
        else:
            current_round += 1
            secret_number = random.randint(min_num, max_num)
            await update.message.reply_text(
                f"🔔 Starting round {current_round} of {max_rounds}.\n"
                f"I'm thinking of a new number between {min_num} and {max_num}.\n"
                "Keep guessing!"
            )
    elif guess < secret_number:
        await update.message.reply_text(f"🔼 {user.first_name}, my number is higher than {guess}.")
    else:
        await update.message.reply_text(f"🔽 {user.first_name}, my number is lower than {guess}.")

def reset_game():
    global game_active, secret_number, current_round
    game_active = False
    secret_number = 0
    current_round = 0

async def stopgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global game_active
    if not game_active:
        await update.message.reply_text("No game is currently running.")
        return
    game_active = False
    await update.message.reply_text("🛑 Game stopped.")

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("startgame", startgame))
    app.add_handler(CommandHandler("stopgame", stopgame))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), guess_handler))

    print("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
