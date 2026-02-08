import asyncio, logging, urllib.parse, aiohttp, random, os, threading, feedparser
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# --- НАСТРОЙКИ ---
BOT_TOKEN = "8262668090:AAE3UJkjIeEVPKotGV1HfGyfkWtNP9TDnaQ"
TMDB_API_KEY = "043f357a705bad3b63ba075408d399a2"
CHANNEL_ID = "@CineDigests"
REDDIT_RSS = "https://www.reddit.com/r/ArcRaiders/new/.rss"

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
sent_posts = set()

# --- СЕРВЕР-БУДИЛЬНИК ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Bot is active")

def run_health_check():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

# --- REDDIT ---
async def check_reddit(context: ContextTypes.DEFAULT_TYPE):
    global sent_posts
    try:
        feed = feedparser.parse(f"{REDDIT_RSS}?t={random.random()}", agent='Mozilla/5.0')
        if not feed or not feed.entries: return
        for entry in reversed(feed.entries[:3]):
            if entry.id not in sent_posts:
                text = f"🚀 **Новое в r/ArcRaiders**\n\n🔗 [{entry.title}]({entry.link})"
                await context.bot.send_message(chat_id=CHANNEL_ID, text=text, parse_mode="Markdown")
                sent_posts.add(entry.id)
        if len(sent_posts) > 100: sent_posts = list(sent_posts)[-50:]
    except Exception as e: logging.error(f"Reddit error: {e}")

# --- TMDB API ---
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
    kbd = [[KeyboardButton("🔥 Популярные"), KeyboardButton("🆕 Новинки")], [KeyboardButton("🎲 Рандом")]]
    await update.message.reply_text("🎬 *CineIntellect v51.13.6*\nПоиск по 30 фильмам настроен.", 
                                   reply_markup=ReplyKeyboardMarkup(kbd, resize_keyboard=True), parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text
    chat_id = update.effective_chat.id

    if text == "🔥 Популярные":
        data = await fetch_tmdb("trending/movie/week")
        await send_list(chat_id, context, "🔥 В тренде:", data.get('results', []), "movie")
    elif text == "🆕 Новинки":
        data = await fetch_tmdb("movie/now_playing")
        await send_list(chat_id, context, "🆕 Сейчас в кино:", data.get('results', []), "movie")
    elif text == "🎲 Рандом":
        data = await fetch_tmdb("movie/top_rated", {"page": random.randint(1, 20)})
        if data.get('results'): await show_card(chat_id, context, random.choice(data['results'])['id'], "movie")
    else:
        data = await fetch_tmdb("search/multi", {"query": text})
        results = data.get('results', [])
        kbd = []
        for item in results[:10]:
            m_type = item.get('media_type', 'movie')
            name = item.get('title') or item.get('name')
            icon = "👤" if m_type == 'person' else "🎬"
            if name: kbd.append([InlineKeyboardButton(f"{icon} {name}", callback_data=f"{m_type}:{item['id']}")])
        if kbd: await context.bot.send_message(chat_id, "🔎 Найдено:", reply_markup=InlineKeyboardMarkup(kbd))

async def send_list(chat_id, context, title, items, force_type=None):
    kbd = []
    for i in items[:12]:
        name = i.get('title') or i.get('name')
        m_type = force_type or i.get('media_type', 'movie')
        if name: kbd.append([InlineKeyboardButton(f"🎬 {name}", callback_data=f"{m_type}:{i['id']}")])
    if kbd: await context.bot.send_message(chat_id, title, reply_markup=InlineKeyboardMarkup(kbd))

async def show_card(chat_id, context, mid, m_type):
    m = await fetch_tmdb(f"{m_type}/{mid}")
    if not m: return
    title = m.get('title') or m.get('name')
    yt_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(title + ' трейлер')}"
    google_url = f"https://www.google.com/search?q={urllib.parse.quote(title + ' смотреть онлайн')}"
    
    cap = f"🎥 *{title}*\n⭐ Рейтинг: {m.get('vote_average', 0):.1f}\n\n{m.get('overview', 'Описания нет.')[:800]}"
    kbd = [
        [InlineKeyboardButton("📺 Трейлер", url=yt_url), InlineKeyboardButton("🌐 Смотреть онлайн", url=google_url)],
        [InlineKeyboardButton("🎭 Похожее", callback_data=f"similar:{m_type}:{mid}")]
    ]
    poster = f"https://image.tmdb.org/t/p/w500{m.get('poster_path')}"
    try:
        if m.get('poster_path'): await context.bot.send_photo(chat_id, poster, cap, reply_markup=InlineKeyboardMarkup(kbd), parse_mode="Markdown")
        else: await context.bot.send_message(chat_id, cap, reply_markup=InlineKeyboardMarkup(kbd), parse_mode="Markdown")
    except: pass

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    chat_id = update.effective_chat.id
    
    if q.data.startswith("person:"):
        pid = q.data.split(":")[1]
        p = await fetch_tmdb(f"person/{pid}")
        # Получаем и актерские, и режиссерские работы
        credits = await fetch_tmdb(f"person/{pid}/combined_credits")
        
        bio = f"👤 *{p.get('name')}*\n🎂 {p.get('birthday', '-')}\n\n🎬 *Топ-30 работ:* "
        
        # Объединяем cast и crew (для режиссеров)
        all_works = credits.get('cast', []) + credits.get('crew', [])
        
        # Фильтруем откровенный мусор
        stop_words = ["awards", "ceremony", "grammy", "oscar", "special", "documentary", "pre-show"]
        unique_works = {}
        
        for c in all_works:
            mid = c.get('id')
            title = c.get('title') or c.get('name') or ""
            if mid not in unique_works and not any(w in title.lower() for w in stop_words):
                unique_works[mid] = c
        
        # Сортируем по популярности и берем 30
        sorted_works = sorted(unique_works.values(), key=lambda x: x.get('popularity', 0), reverse=True)[:30]
        
        kbd = [[InlineKeyboardButton(f"🎬 {w.get('title') or w.get('name')}", callback_data=f"movie:{w['id']}")] for w in sorted_works]
        
        photo = f"https://image.tmdb.org/t/p/w500{p.get('profile_path')}"
        if p.get('profile_path'): await context.bot.send_photo(chat_id, photo, bio, reply_markup=InlineKeyboardMarkup(kbd), parse_mode="Markdown")
        else: await context.bot.send_message(chat_id, bio, reply_markup=InlineKeyboardMarkup(kbd), parse_mode="Markdown")
        
    elif q.data.startswith("similar:"):
        _, m_type, mid = q.data.split(":")
        res = await fetch_tmdb(f"{m_type}/{mid}/recommendations")
        await send_list(chat_id, context, "🎭 Похожее:", res.get('results', [])[:10], m_type)
    elif ":" in q.data:
        m_type, mid = q.data.split(":")
        await show_card(chat_id, context, mid, m_type)

if __name__ == "__main__":
    threading.Thread(target=run_health_check, daemon=True).start()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    if app.job_queue: 
        app.job_queue.run_repeating(check_reddit, interval=600, first=10)
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🚀 БОТ ЗАПУЩЕН!")
    app.run_polling(drop_pending_updates=True)
