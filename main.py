"""
Instagram/YouTube Video & Audio Downloader — Telegram bot
Kutubxonalar: aiogram 3.x, yt-dlp, aiohttp, python-dotenv

Ish tartibi:
  1. Foydalanuvchi havola yuboradi
  2. Bot videoni darhol yuboradi (tagida "@bot orqali yuklab olindi" yozuvi
     va "Audiosini yuklab olish" tugmasi bilan)
  3. Tugma bosilsa, shu videoning audiosi yuboriladi
"""

import os
import re
import sys
import html
import uuid
import shutil
import asyncio
import logging
import tempfile
from collections import OrderedDict
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.exceptions import TelegramBadRequest, TelegramUnauthorizedError
import yt_dlp
from aiohttp import web

# --------------------------------------------------------------------------
# SOZLAMALAR
# --------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,  # Render loglarida ko'rinishi uchun
)
log = logging.getLogger("dl-bot")

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    log.critical("BOT_TOKEN environment variable topilmadi! Render > Environment bo'limini tekshiring.")
    raise SystemExit(1)

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

MAX_FILE_SIZE = 49 * 1024 * 1024  # Telegram bot limiti ~50MB
MAX_CONCURRENT_DOWNLOADS = 3
MAX_PENDING_URLS = 1000

URL_RE = re.compile(r"https?://\S+")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# Bot username (ishga tushganda get_me() dan yangilanadi)
BOT_USERNAME = "mix_videobot"

# ffmpeg bo'lsa audio mp3 ga aylantiriladi, bo'lmasa m4a shundayligicha yuboriladi
HAS_FFMPEG = shutil.which("ffmpeg") is not None

# Render "Secret Files" orqali cookies.txt qo'shsangiz (YouTube bloklasa kerak bo'ladi)
COOKIES_FILE = None
for _src in ("/etc/secrets/cookies.txt", "cookies.txt"):
    if os.path.exists(_src):
        # /etc/secrets faqat o'qish uchun — yt-dlp yozishi mumkin bo'lgan joyga nusxalaymiz
        COOKIES_FILE = str(Path(tempfile.gettempdir()) / "cookies.txt")
        shutil.copyfile(_src, COOKIES_FILE)
        log.info("cookies.txt topildi va ishlatiladi: %s", _src)
        break

# Video format: avval 48MB dan kichik, bo'lmasa oddiy, oxirida eng kichik sifat
VIDEO_FORMAT = (
    "best[ext=mp4][filesize<48M]/"
    "best[ext=mp4][filesize_approx<48M]/"
    "worst[ext=mp4]/worst"
)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# token -> havola (tugma bosilganda audio uchun kerak)
pending_urls: "OrderedDict[str, str]" = OrderedDict()
download_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)


# --------------------------------------------------------------------------
# YORDAMCHI FUNKSIYALAR
# --------------------------------------------------------------------------

def extract_url(text: str) -> str | None:
    match = URL_RE.search(text or "")
    return match.group(0) if match else None


def is_supported(url: str) -> bool:
    url = url.lower()
    return any(d in url for d in ("instagram.com", "youtube.com", "youtu.be"))


def remember_url(url: str) -> str:
    token = uuid.uuid4().hex[:12]
    pending_urls[token] = url
    while len(pending_urls) > MAX_PENDING_URLS:
        pending_urls.popitem(last=False)
    return token


def caption_text() -> str:
    return f"📥 @{BOT_USERNAME} orqali yuklab olindi"


def audio_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🎵 Audiosini yuklab olish", callback_data=f"au:{token}")
    ]])


def clean_error(e: Exception) -> str:
    text = ANSI_RE.sub("", str(e)).replace("ERROR: ", "").strip()
    return text[:250]


def build_ydl_opts(mode: str, out_template: str) -> dict:
    opts = {
        "outtmpl": out_template,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "concurrent_fragment_downloads": 4,
        "retries": 3,
        "socket_timeout": 30,
        "nocheckcertificate": True,
    }
    if COOKIES_FILE:
        opts["cookiefile"] = COOKIES_FILE

    if mode == "audio":
        if HAS_FFMPEG:
            opts.update({
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            })
        else:
            opts["format"] = "bestaudio[ext=m4a]/bestaudio/best"
    else:
        opts["format"] = VIDEO_FORMAT
    return opts


def run_download(url: str, mode: str) -> Path:
    file_id = uuid.uuid4().hex
    out_template = str(DOWNLOAD_DIR / f"{file_id}.%(ext)s")
    opts = build_ydl_opts(mode, out_template)

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    matches = list(DOWNLOAD_DIR.glob(f"{file_id}.*"))
    if not matches:
        raise FileNotFoundError("Yuklab olingan fayl topilmadi")
    return matches[0]


async def safe_edit(msg: Message, text: str):
    try:
        await msg.edit_text(text)
    except TelegramBadRequest:
        pass


async def send_media(message: Message, url: str, mode: str, token: str):
    """Havolani yuklab, video yoki audio sifatida yuboradi."""
    status = await message.answer("⏳ Yuklab olinmoqda, biroz kuting...")
    file_path: Path | None = None
    try:
        async with download_semaphore:
            loop = asyncio.get_running_loop()
            file_path = await loop.run_in_executor(None, run_download, url, mode)

        if file_path.stat().st_size > MAX_FILE_SIZE:
            await safe_edit(status, "⚠️ Fayl hajmi juda katta (Telegram limiti ~50MB dan oshib ketdi).")
            return

        await safe_edit(status, "📤 Yuborilmoqda...")
        media = FSInputFile(file_path)

        if mode == "audio":
            if file_path.suffix.lower() in (".mp3", ".m4a"):
                await message.answer_audio(media, caption=caption_text())
            else:
                await message.answer_document(media, caption=caption_text())
        else:
            await message.answer_video(
                media,
                caption=caption_text(),
                reply_markup=audio_keyboard(token),
                supports_streaming=True,
            )

        await status.delete()

    except yt_dlp.utils.DownloadError as e:
        log.warning("Download error: %s", e)
        await safe_edit(
            status,
            "❌ Yuklab bo'lmadi.\n"
            f"<code>{html.escape(clean_error(e))}</code>",
        )
    except TelegramBadRequest as e:
        log.warning("Telegram send error: %s", e)
        await safe_edit(status, "❌ Faylni yuborishda xatolik yuz berdi.")
    except Exception as e:
        log.exception("Unexpected error")
        await safe_edit(
            status,
            "❌ Kutilmagan xatolik yuz berdi. Qayta urinib ko'ring.\n"
            f"<code>{html.escape(clean_error(e))}</code>",
        )
    finally:
        if file_path and file_path.exists():
            try:
                file_path.unlink()
            except OSError:
                pass


# --------------------------------------------------------------------------
# HANDLERLAR
# --------------------------------------------------------------------------

@dp.message(CommandStart())
async def cmd_start(message: Message):
    log.info("/start qabul qilindi: user_id=%s", message.from_user.id)
    await message.answer(
        "👋 Salom!\n\n"
        "Menga <b>Instagram</b> yoki <b>YouTube</b> havolasini yuboring — "
        "videoni yuklab beraman. Videoning tagidagi tugma orqali audiosini ham olishingiz mumkin.\n\n"
        "Shunchaki linkni tashlang 🙂"
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📌 Qo'llab-quvvatlanadigan manbalar: Instagram, YouTube.\n"
        "Havolani yuboring — video keladi. Audio kerak bo'lsa, videoning tagidagi tugmani bosing."
    )


@dp.message(F.text)
async def handle_link(message: Message):
    url = extract_url(message.text)
    if not url:
        await message.answer("Iltimos, to'g'ri havola (link) yuboring.")
        return

    if not is_supported(url):
        await message.answer("Faqat Instagram va YouTube havolalarini qo'llab-quvvatlayman.")
        return

    token = remember_url(url)
    await send_media(message, url, "video", token)


@dp.callback_query(F.data.startswith("au:"))
async def handle_audio_button(callback: CallbackQuery):
    token = callback.data.split(":", 1)[1]
    url = pending_urls.get(token)
    if not url:
        await callback.answer("Havola muddati tugagan, iltimos linkni qayta yuboring.", show_alert=True)
        return

    await callback.answer("🎵 Audio tayyorlanmoqda...")
    await send_media(callback.message, url, "audio", token)


# --------------------------------------------------------------------------
# RENDER SERVER VA ISHGA TUSHIRISH
# --------------------------------------------------------------------------

async def handle_web(request):
    return web.Response(text="Bot is running!")


async def main():
    global BOT_USERNAME

    # 1) Render "Web Service" portni talab qiladi — health-check server
    app = web.Application()
    app.router.add_get("/", handle_web)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info("Web server %s-portda ishga tushdi.", port)

    # 2) Tokenni tekshirish
    try:
        me = await bot.get_me()
        BOT_USERNAME = me.username or BOT_USERNAME
        log.info("Bot muvaffaqiyatli ulandi: @%s (id=%s)", me.username, me.id)
    except TelegramUnauthorizedError:
        log.critical(
            "TOKEN NOTO'G'RI yoki BEKOR QILINGAN (401 Unauthorized). "
            "Render > Environment > BOT_TOKEN qiymatini yangilang va Manual Deploy qiling."
        )
        return
    except Exception:
        log.exception("Botga ulanishda kutilmagan xato.")
        return

    log.info("ffmpeg: %s | cookies: %s", "bor" if HAS_FFMPEG else "yo'q", "bor" if COOKIES_FILE else "yo'q")

    # 3) Eski webhook/pollingni tozalab, yagona polling boshlanadi
    await bot.delete_webhook(drop_pending_updates=True)
    log.info("Polling boshlanmoqda...")
    try:
        await dp.start_polling(bot)
    except Exception:
        log.exception(
            "Polling to'xtadi. Agar 'Conflict' xatosi bo'lsa — "
            "shu tokenda BOSHQA joyda bot ishlab turgani uchun shunday bo'ladi. "
            "Faqat bitta joyda ishga tushiring."
        )


if __name__ == "__main__":
    asyncio.run(main())
    
