import asyncio, logging, urllib.parse, aiohttp, sqlite3, random, os, threading, feedparser
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# --- НАСТРОЙКИ ---
BOT_TOKEN = "8262668090:AAE3UJkjIeEVPKotGV1HfGyfkWtNP9TDnaQ"
TMDB_API_KEY = "043f357a705bad3b63ba075408d399a2"
CHANNEL_ID = "@CineDigests"  # Твоя группа
REDDIT_RSS = "https://www.reddit.com/r/ArcRaiders/new/.rss"

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

# Список для хранения уже отправленных постов
sent_posts = set()

# --- СЕРВЕР-БУДИЛЬНИК ДЛЯ RENDER ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Bot is active")
    def do_HEAD(self):
        self.send_response(200); self.end_headers()

def run_health_check():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

# --- ФУНКЦИЯ ПРОВЕРКИ REDDIT ---
async def check_reddit(context: ContextTypes.DEFAULT_TYPE):
    global sent_posts
    try:
        feed = feedparser.parse(REDDIT_RSS, agent='Mozilla/5.0')
        if not feed.entries: return
        for entry in reversed(feed.entries[:3]):
            if entry.id not in sent_posts:
                text = f"🚀 **Новое в r/ArcRaiders**\n\n🔗 [{entry.title}]({entry.link})"
                await context.bot.send_message(chat_id=CHANNEL_ID, text=text, parse_mode="Markdown")
                sent_posts.add(entry.id)
        if len(sent_posts) > 100:
            sent_posts = set(list(sent_posts)[-50:])
    except Exception as e:
        logging.error(f"Reddit error: {e}")

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

# --- КОМАНДЫ БОТА ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kbd = [[KeyboardButton("🔥 Популярные"), KeyboardButton("🆕 Новинки")],
           [KeyboardButton("📅 По годам"), KeyboardButton("🎲 Рандом")],
           [KeyboardButton("📌 Мой список")]]
    await update.message.reply_text("🎬 *CineIntellect v51.13.1*\nФильмы + Новости Arc Raiders активны!", 
                                   reply_markup=ReplyKeyboardMarkup(kbd, resize_keyboard=True), parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text
    if text == "🔥 Популярные":
        data = await fetch_tmdb("trending/movie/week")
        await send_list(update, "🔥 В тренде:", data.get('results', []), "movie")
    elif text == "🆕 Новинки":
        data = await fetch_tmdb("movie/now_playing")
        await send_list(update, "🆕 Сейчас в кино:", data.get('results', []), "movie")
    elif text == "🎲 Рандом":
        data = await fetch_tmdb("movie/top_rated", {"page": random.randint(1, 20)})
        if data.get('results'): await show_card(update, context, random.choice(data['results'])['id'], "movie")
    else:
        data = await fetch_tmdb("search/multi", {"query": text})
        results = data.get('results', [])
        kbd = []
        for item in results[:10]:
            m_type, mid = item.get('media_type'), item.get('id')
            name = item.get('title') or item.get('name')
            icon = "👤" if m_type == 'person' else "🎬" if m_type == 'movie' else "📺"
            kbd.append([InlineKeyboardButton(f"{icon} {name}", callback_data=f"{m_type}:{mid}")])
        if kbd: await update.message.reply_text(f"🔎 Найдено:", reply_markup=InlineKeyboardMarkup(kbd))

async def send_list(update, title, items, force_type=None):
    kbd = []
    for i in items[:14]:
        name = i.get('title') or i.get('name')
        m_type = force_type or i.get('media_type', 'movie')
        if name: kbd.append([InlineKeyboardButton(f"🎬 {name}", callback_data=f"{m_type}:{i['id']}")])
    grid = [kbd[i:i+2] for i in range(0, len(kbd), 2)]
    await update.message.reply_text(title, reply_markup=InlineKeyboardMarkup(grid))

async def show_card(target, context, mid, m_type):
    m = await fetch_tmdb(f"{m_type}/{mid}")
    if not m: return
    title = m.get('title') or m.get('name')
    yt_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(title + ' трейлер на русском')}"
    watch_url = f"https://www.google.com/search?q={urllib.parse.quote(title + ' смотреть онлайн')}"
    cap = f"🎥 *{title}*\n⭐ Рейтинг: {m.get('vote_average', 0):.1f}\n\n{m.get('overview', 'Без описания.')[:900]}"
    kbd = [[InlineKeyboardButton("🍿 Смотреть", url=watch_url), InlineKeyboardButton("📺 Трейлер", url=yt_url)],
           [InlineKeyboardButton("🎭 Похожее", callback_data=f"similar:{m_type}:{mid}")]]
    poster = f"https://image.tmdb.org/t/p/w500{m.get('poster_path')}"
    chat_id = target.effective_chat.id
    try:
        if m.get('poster_path'): await context.bot.send_photo(chat_id, poster, cap, reply_markup=InlineKeyboardMarkup(kbd), parse_mode="Markdown")
        else: await context.bot.send_message(chat_id, cap, reply_markup=InlineKeyboardMarkup(kbd), parse_mode="Markdown")
    except: pass

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.data.startswith("person:"):
        pid = q.data.split(":")[1]
        p = await fetch_tmdb(f"person/{pid}")
        data = await fetch_tmdb(f"person/{pid}/combined_credits")
        bio = f"👤 *{p.get('name')}*\n📅 Родился: {p.get('birthday', 'Неизвестно')}\n📍 Место: {p.get('place_of_birth', '-')}\n\n🎬 *Лучшие работы:* "
        cast = sorted(data.get('cast', []), key=lambda x: x.get('popularity', 0), reverse=True)[:10]
        kbd = [[InlineKeyboardButton(f"🎬 {c.get('title') or c.get('name')}", callback_data=f"{c.get('media_type','movie')}:{c['id']}")] for c in cast]
        photo = f"https://image.tmdb.org/t/p/w500{p.get('profile_path')}"
        if p.get('profile_path'): await context.bot.send_photo(q.message.chat_id, photo, bio, reply_markup=InlineKeyboardMarkup(kbd), parse_mode="Markdown")
        else: await context.bot.send_message(q.message.chat_id, bio, reply_markup=InlineKeyboardMarkup(kbd), parse_mode="Markdown")
    elif q.data.startswith("similar:"):
        _, m_type, mid = q.data.split(":")
        data = await fetch_tmdb(f"{m_type}/{mid}/recommendations")
        res = data.get('results', [])[:10]
        kbd = [[InlineKeyboardButton(f"🎬 {i.get('title') or i.get('name')}", callback_data=f"{m_type}:{i['id']}")] for i in res]
        await context.bot.send_message(q.message.chat_id, "🎭 Похожее:", reply_markup=InlineKeyboardMarkup(kbd))
    elif ":" in q.data:
        m_type, mid = q.data.split(":")
        await show_card(q, context, mid, m_type)

# --- ЗАПУСК ---
if __name__ == "__main__":
    threading.Thread(target=run_health_check, daemon=True).start()
    # Инициализация приложения с поддержкой JobQueue
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Безопасная настройка фоновой проверки
    if app.job_queue:
        app.job_queue.run_repeating(check_reddit, interval=900, first=10)
        print("✅ Планировщик Reddit запущен")
    else:
        print("⚠️ JobQueue не активен (проверь установку библиотеки)")
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🚀 БОТ v51.13.1 ЗАПУЩЕН!")
    app.run_polling(drop_pending_updates=True)
