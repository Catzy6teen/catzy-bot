from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler
)
from groq import Groq
import psycopg
import os

# ================== CONFIG ==================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
DATABASE_URL = os.environ.get("DATABASE_URL")

# ================== SAFETY CHECK ==================

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN missing")

if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY missing")

if not CHANNEL_ID:
    raise ValueError("CHANNEL_ID missing")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL missing")

CHANNEL_ID = int(CHANNEL_ID)

# ================== GROQ SETUP ==================

client = Groq(api_key=GROQ_API_KEY)

# ================== DATABASE HELPER ==================

def get_db():
    return psycopg.connect(DATABASE_URL, sslmode="require")

# ================== CREATE TABLE ==================

with get_db() as conn:
    with conn.cursor() as cursor:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS movies (
            id SERIAL PRIMARY KEY,
            movie_name TEXT,
            message_id BIGINT
        )
        """)
        conn.commit()

# ================== SAVE MOVIES FROM CHANNEL ==================

async def save_movie(update, context):
    if update.channel_post:
        msg = update.channel_post

        if (msg.document or msg.video) and msg.caption:
            movie_name = msg.caption.split("\n")[0].strip()

            with get_db() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO movies (movie_name, message_id) VALUES (%s, %s)",
                        (movie_name, msg.message_id)
                    )
                    conn.commit()

# ================== AUTO HANDLER ==================

async def auto_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message or not update.message.text:
        return

    user_text = update.message.text.strip()

    with get_db() as conn:
        with conn.cursor() as cursor:
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

    # ---------- AI Fallback ----------

    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "user", "content": user_text}
            ]
        )

        reply = response.choices[0].message.content
        await update.message.reply_text(reply)

    except Exception:
        await update.message.reply_text("AI Error")

# ================== SEND MOVIE ==================

async def send_movie(update, context):
    query = update.callback_query
    await query.answer()

    movie_id = query.data

    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT message_id FROM movies WHERE id=%s",
                (movie_id,)
            )
            result = cursor.fetchone()

    if result:
        await context.bot.forward_message(
            chat_id=query.message.chat.id,
            from_chat_id=CHANNEL_ID,
            message_id=result[0]
        )

# ================== BUILD APP ==================

app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

app.add_handler(MessageHandler(filters.ChatType.CHANNEL, save_movie))
app.add_handler(CallbackQueryHandler(send_movie))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, auto_handler))

print("Bot running successfully with Railway PostgreSQL...")
app.run_polling()
