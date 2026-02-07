import asyncio, logging, re, urllib.parse, aiohttp, sqlite3, random, os, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# --- НАСТРОЙКИ ---
BOT_TOKEN = "8262668090:AAE3UJkjIeEVPKotGV1HfGyfkWtNP9TDnaQ"
TMDB_API_KEY = "043f357a705bad3b63ba075408d399a2"

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- ОБМАНКА ДЛЯ RENDER (Health Check) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is active")

def run_health_check():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('movies.db')
    conn.execute('CREATE TABLE IF NOT EXISTS watchlist (user_id INTEGER, movie_id TEXT, title TEXT)')
    conn.commit(); conn.close()
init_db()

# --- ФУНКЦИИ TMDB ---
async def fetch_tmdb(endpoint, params={}):
    p = {"api_key": TMDB_API_KEY, "language": "ru-RU"}
    p.update(params)
    async with aiohttp.ClientSession() as session:
        url = f"https://api.themoviedb.org/3/{endpoint}"
        try:
            async with session.get(url, params=p, timeout=15) as r:
                if r.status == 200: return await r.json()
        except: pass
        return {}

# --- КОМАНДЫ ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kbd = [[KeyboardButton("🔥 Популярные"), KeyboardButton("🆕 Новинки")],
           [KeyboardButton("📅 По годам"), KeyboardButton("🎲 Рандом")],
           [KeyboardButton("📌 Мой список")]]
    await update.message.reply_text("🎬 *CineIntellect v51.9.9*\nБот стабилизирован. Всё работает!", 
                                   reply_markup=ReplyKeyboardMarkup(kbd, resize_keyboard=True), parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return  # ЗАЩИТА ОТ ОШИБКИ NoneType
    
    text = update.message.text
    if text == "🔥 Популярные":
        data = await fetch_tmdb("trending/movie/week")
        await send_list(update, "🔥 В тренде:", data.get('results', []), "movie")
    elif text == "🆕 Новинки":
        data = await fetch_tmdb("movie/now_playing")
        await send_list(update, "🆕 Сейчас в кино:", data.get('results', []), "movie")
    elif text == "📅 По годам":
        years = ["2025", "2024", "2023", "2022"]
        kbd = [[InlineKeyboardButton(y, callback_data=f"y:{y}") for y in years[:2]],
               [InlineKeyboardButton(y, callback_data=f"y:{y}") for y in years[2:]]]
        await update.message.reply_text("Выберите год:", reply_markup=InlineKeyboardMarkup(kbd))
    elif text == "🎲 Рандом":
        data = await fetch_tmdb("movie/top_rated", {"page": random.randint(1, 20)})
        if data.get('results'): await show_card(update, context, random.choice(data['results'])['id'], "movie")
    elif text == "📌 Мой список":
        conn = sqlite3.connect('movies.db')
        res = conn.execute("SELECT movie_id, title FROM watchlist WHERE user_id = ?", (update.effective_user.id,)).fetchall()
        conn.close()
        if not res: await update.message.reply_text("Ваш список пуст.")
        else:
            txt = "📌 *Ваш список:*\n" + "\n".join([f"• {r[1]}" for r in res])
            await update.message.reply_text(txt, parse_mode="Markdown")
    else:
        data = await fetch_tmdb("search/multi", {"query": text})
        results = data.get('results', [])
        kbd = []
        for item in results[:10]:
            m_type = item.get('media_type')
            mid = item.get('id')
            if m_type == 'person':
                kbd.append([InlineKeyboardButton(f"👤 {item.get('name')}", callback_data=f"person:{mid}")])
            elif m_type in ['movie', 'tv']:
                name = item.get('title') or item.get('name')
                icon = "🎬" if m_type == 'movie' else "📺"
                kbd.append([InlineKeyboardButton(f"{icon} {name}", callback_data=f"{m_type}:{mid}")])
        
        if kbd: await update.message.reply_text(f"🔎 Результаты по запросу '{text}':", reply_markup=InlineKeyboardMarkup(kbd))
        else: await update.message.reply_text("😔 Ничего не найдено.")

async def send_list(update, title, items, force_type=None):
    kbd = []
    for i in items[:15]:
        name = i.get('title') or i.get('name')
        m_type = force_type or i.get('media_type', 'movie')
        if name: kbd.append([InlineKeyboardButton(f"🎬 {name}", callback_data=f"{m_type}:{i['id']}")])
    if kbd: await update.message.reply_text(title, reply_markup=InlineKeyboardMarkup(kbd))

async def show_card(target, context, mid, m_type):
    m = await fetch_tmdb(f"{m_type}/{mid}")
    if not m: return
    title = m.get('title') or m.get('name')
    url = f"https://www.google.com/search?q={urllib.parse.quote(title + ' смотреть онлайн')}"
    cap = f"🎥 *{title}*\n⭐ Рейтинг: {m.get('vote_average', 0):.1f}\n\n{m.get('overview', '')[:500]}..."
    kbd = [[InlineKeyboardButton("📌 В список", callback_data=f"add:{mid}:{title[:20]}")],
           [InlineKeyboardButton("🍿 Смотреть", url=url)]]
    poster = f"https://image.tmdb.org/t/p/w500{m.get('poster_path')}"
    chat_id = target.message.chat_id if hasattr(target, 'message') else target.effective_chat.id
    try:
        if m.get('poster_path'): await context.bot.send_photo(chat_id, poster, cap, reply_markup=InlineKeyboardMarkup(kbd), parse_mode="Markdown")
        else: await context.bot.send_message(chat_id, cap, reply_markup=InlineKeyboardMarkup(kbd), parse_mode="Markdown")
    except: pass

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.data.startswith("y:"):
        y = q.data.split(":")[1]
        data = await fetch_tmdb("discover/movie", {"primary_release_year": y, "sort_by": "popularity.desc"})
        results = data.get('results', [])[:20]
        kbd = []
        for i in range(0, len(results), 2):
            row = [InlineKeyboardButton(f"🎬 {results[i]['title']}", callback_data=f"movie:{results[i]['id']}")]
            if i+1 < len(results):
                row.append(InlineKeyboardButton(f"🎬 {results[i+1]['title']}", callback_data=f"movie:{results[i+1]['id']}"))
            kbd.append(row)
        await q.message.edit_text(f"📅 Хиты {y}:", reply_markup=InlineKeyboardMarkup(kbd))
    elif q.data.startswith("add:"):
        _, mid, title = q.data.split(":", 2)
        conn = sqlite3.connect('movies.db'); conn.execute("INSERT INTO watchlist VALUES (?, ?, ?)", (q.from_user.id, mid, title)); conn.commit(); conn.close()
        await context.bot.send_message(q.message.chat_id, f"✅ Добавлено: {title}")
    elif q.data.startswith("person:"):
        pid = q.data.split(":")[1]
        data = await fetch_tmdb(f"person/{pid}/combined_credits")
        cast = data.get('cast', []) + data.get('crew', [])
        unique_movies = {}
        stop_words = ["academy awards", "ceremony", "oscar", "video documentary", "the 7", "the 8", "the 9"]
        for m in cast:
            mid = m.get('id')
            title = m.get('title') or m.get('name', '')
            is_doc = 99 in m.get('genre_ids', [])
            is_ceremony = any(word in title.lower() for word in stop_words)
            if mid not in unique_movies and title and not is_doc and not is_ceremony:
                unique_movies[mid] = m
        sorted_m = sorted(unique_movies.values(), key=lambda x: x.get('popularity', 0), reverse=True)[:30]
        kbd = []
        for i in range(0, len(sorted_m), 2):
            m1 = sorted_m[i]; btn1 = InlineKeyboardButton(f"🎬 {m1.get('title') or m1.get('name')}", callback_data=f"{m1.get('media_type','movie')}:{m1['id']}")
            row = [btn1]
            if i+1 < len(sorted_m):
                m2 = sorted_m[i+1]; btn2 = InlineKeyboardButton(f"🎬 {m2.get('title') or m2.get('name')}", callback_data=f"{m2.get('media_type','movie')}:{m2['id']}")
                row.append(btn2)
            kbd.append(row)
        await q.message.edit_text(f"🎥 Лучшие работы деятеля:", reply_markup=InlineKeyboardMarkup(kbd))
    elif ":" in q.data:
        m_type, mid = q.data.split(":")
        await show_card(q, context, mid, m_type)

if __name__ == "__main__":
    threading.Thread(target=run_health_check, daemon=True).start()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🚀 БОТ v51.9.9 ЗАПУЩЕН!")
    app.run_polling()
