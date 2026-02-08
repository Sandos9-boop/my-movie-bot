import asyncio, logging, urllib.parse, aiohttp, random, os, threading, feedparser
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from deep_translator import GoogleTranslator

# --- НАСТРОЙКИ ---
BOT_TOKEN = "8262668090:AAE3UJkjIeEVPKotGV1HfGyfkWtNP9TDnaQ"
TMDB_API_KEY = "043f357a705bad3b63ba075408d399a2"
CHANNEL_ID = "@CineDigests"
REDDIT_RSS = "https://www.reddit.com/r/ArcRaiders/new/.rss"

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
sent_posts = set()
translator = GoogleTranslator(source='en', target='ru')

# --- СЕРВЕР-БУДИЛЬНИК ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Bot is awake and running")
    def log_message(self, format, *args): return

def run_health_check():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

# --- УЛУЧШЕННЫЙ ПЕРЕВОД (ТВОЙ КОД) ---
async def safe_translate(text):
    if not text: return ""
    try:
        loop = asyncio.get_event_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(None, translator.translate, text[:200]),
            timeout=5.0
        )
    except asyncio.TimeoutError:
        logging.warning("Translation timeout")
        return text
    except Exception as e:
        logging.error(f"Translation error: {e}")
        return text

# --- ЛОГИКА REDDIT ---
async def get_reddit_news(limit=10):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(f"{REDDIT_RSS}?t={random.random()}", timeout=10) as resp:
                if resp.status == 200:
                    feed = feedparser.parse(await resp.text())
                    return feed.entries[:limit]
        return []
    except Exception as e:
        logging.error(f"Reddit error: {e}")
        return []

async def check_reddit_job(context: ContextTypes.DEFAULT_TYPE):
    global sent_posts
    entries = await get_reddit_news(3)
    for entry in reversed(entries):
        if entry.id not in sent_posts:
            rus_title = await safe_translate(entry.title) # Используем новый асинхронный перевод
            text = f"🚀 **Новое в r/ArcRaiders**\n\n🇷🇺 {rus_title}\n🇬🇧 _{entry.title}_\n\n🔗 [Открыть на Reddit]({entry.link})"
            try:
                await context.bot.send_message(chat_id=CHANNEL_ID, text=text, parse_mode="Markdown")
                sent_posts.add(entry.id)
            except Exception as e:
                logging.error(f"Failed to send Reddit post: {e}") # Твой лог ошибок
    if len(sent_posts) > 100: sent_posts = list(sent_posts)[-50:]

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

# --- КОМАНДЫ (БЕЗ ИЗМЕНЕНИЙ) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kbd = [[KeyboardButton("🔥 Популярные"), KeyboardButton("🆕 Новинки")], [KeyboardButton("🎲 Рандом"), KeyboardButton("📰 Новости ARC")]]
    await update.message.reply_text("🎬 *CineIntellect v51.14.3*\nПрименены улучшения стабильности перевода.", 
                                   reply_markup=ReplyKeyboardMarkup(kbd, resize_keyboard=True), parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text
    chat_id = update.effective_chat.id

    if text == "📰 Новости ARC":
        await update.message.reply_chat_action("typing")
        entries = await get_reddit_news(10)
        if not entries:
            await update.message.reply_text("📭 Reddit временно недоступен.")
            return
        msg = "🗞 **Последние новости Arc Raiders:**\n\n"
        for i, e in enumerate(entries, 1):
            msg += f"{i}. [{e.title}]({e.link})\n\n"
        await update.message.reply_text(msg, parse_mode="Markdown", disable_web_page_preview=True)

    elif text == "🔥 Популярные":
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
    q_suffix = " смотреть онлайн" if m_type == "movie" else " сериал смотреть онлайн"
    google_url = f"https://www.google.com/search?q={urllib.parse.quote(title + q_suffix)}"
    cap = f"🎥 *{title}*\n⭐ Рейтинг: {m.get('vote_average', 0):.1f}\n\n{m.get('overview', 'Описания нет.')[:800]}"
    kbd = [[InlineKeyboardButton("📺 Трейлер", url=yt_url), InlineKeyboardButton("🌐 Смотреть онлайн", url=google_url)],
           [InlineKeyboardButton("🎭 Похожее", callback_data=f"similar:{m_type}:{mid}")]]
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
        credits = await fetch_tmdb(f"person/{pid}/combined_credits")
        bio = f"👤 *{p.get('name')}*\n🎂 {p.get('birthday', '-')}\n\n🎬 *Топ-30 работ:* "
        all_works = credits.get('cast', []) + credits.get('crew', [])
        unique_works = {}
        for c in all_works:
            mid = c.get('id')
            title = c.get('title') or c.get('name') or ""
            if mid not in unique_works and not any(w in title.lower() for w in ["awards", "ceremony", "grammy", "oscar"]):
                unique_works[mid] = {"title": title, "type": c.get('media_type', 'movie'), "pop": c.get('popularity', 0)}
        sorted_works = sorted(unique_works.items(), key=lambda x: x[1]['pop'], reverse=True)[:30]
        kbd = [[InlineKeyboardButton(f"🎬 {w['title']}", callback_data=f"{w['type']}:{mid}")] for mid, w in sorted_works]
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
    if app.job_queue: app.job_queue.run_repeating(check_reddit_job, interval=600, first=10)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling(drop_pending_updates=True)
