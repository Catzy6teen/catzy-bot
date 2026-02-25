from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler
)
from groq import Groq
import psycopg2
import os

# ================= CONFIG =================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID"))
DATABASE_URL = os.environ.get("DATABASE_URL")
# ==========================================

# Safety check
if not TELEGRAM_TOKEN or not GROQ_API_KEY or not CHANNEL_ID or not DATABASE_URL:
    raise ValueError("Missing environment variables!")

# Groq AI setup
client = Groq(api_key=GROQ_API_KEY)

# PostgreSQL connection
conn = psycopg2.connect(DATABASE_URL)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS movies (
    id SERIAL PRIMARY KEY,
    movie_name TEXT,
    message_id BIGINT
)
""")
conn.commit()


# ========= AUTO SAVE MOVIES FROM CHANNEL =========
async def save_movie(update, context):
    if update.channel_post:
        msg = update.channel_post
        if (msg.document or msg.video) and msg.caption:
            cursor.execute(
                "INSERT INTO movies (movie_name, message_id) VALUES (%s, %s)",
                (msg.caption, msg.message_id)
            )
            conn.commit()


# ========= AUTO HANDLER (Movie First, AI Fallback) =========
async def auto_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text

    # 1️⃣ Search movie database
    cursor.execute(
        "SELECT id, movie_name FROM movies WHERE movie_name ILIKE %s",
        ('%' + user_text + '%',)
    )
    results = cursor.fetchall()

    if results:
        buttons = [
            [InlineKeyboardButton(movie[1], callback_data=str(movie[0]))]
            for movie in results[:5]
        ]
        await update.message.reply_text(
            "🎬 Movies Found:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    # 2️⃣ If no movie found → AI reply
    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "user", "content": user_text}
            ]
        )
        reply = response.choices[0].message.content
        await update.message.reply_text(reply)

    except Exception as e:
        await update.message.reply_text("Error: " + str(e))


# ========= SEND MOVIE ON BUTTON CLICK =========
async def send_movie(update, context):
    query = update.callback_query
    await query.answer()

    movie_id = query.data

    cursor.execute(
        "SELECT message_id FROM movies WHERE id=%s",
        (movie_id,)
    )
    result = cursor.fetchone()

    if result:
        await context.bot.forward_message(
            chat_id=query.message.chat_id,
            from_chat_id=CHANNEL_ID,
            message_id=result[0]
        )


# ========= BUILD APP =========
app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

app.add_handler(MessageHandler(filters.ChatType.CHANNEL, save_movie))
app.add_handler(CallbackQueryHandler(send_movie))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, auto_handler))

print("Bot is running with PostgreSQL...")
app.run_polling()
