"""
Instagram/YouTube Video & Audio Downloader — Telegram bot
Kutubxonalar: aiogram 3.x, yt-dlp, aiohttp, python-dotenv
"""

import os
import re
import sys
import uuid
import asyncio
import logging
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
    stream=sys.stdout,  # Render loglarida ko'rinishi uchun stdout'ga majburlash
)
log = logging.getLogger("dl-bot")

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    log.critical("BOT_TOKEN environment variable topilmadi! Render > Environment bo'limini tekshiring.")
    raise SystemExit(1)

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

MAX_FILE_SIZE = 49 * 1024 * 1024
MAX_CONCURRENT_DOWNLOADS = 3

URL_RE = re.compile(r"https?://\S+")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

pending_urls: dict[str, str] = {}
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


def build_ydl_opts(mode: str, out_template: str) -> dict:
    common = {
        "outtmpl": out_template,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "concurrent_fragment_downloads": 4,
        "retries": 3,
        "socket_timeout": 30,
        "nocheckcertificate": True,
    }
    if mode == "audio":
        common.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        })
    else:
        common.update({
            "format": "best[filesize<48M]/best",
            "merge_output_format": "mp4",
        })
    return common


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


def format_choice_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎬 Video", callback_data=f"dl:video:{token}"),
            InlineKeyboardButton(text="🎵 Audio (mp3)", callback_data=f"dl:audio:{token}"),
        ]
    ])


# --------------------------------------------------------------------------
# HANDLERLAR
# --------------------------------------------------------------------------

@dp.message(CommandStart())
async def cmd_start(message: Message):
    log.info("/start qabul qilindi: user_id=%s", message.from_user.id)
    await message.answer(
        "👋 Salom!\n\n"
        "Menga <b>Instagram</b> yoki <b>YouTube</b> havolasini yuboring — "
        "video yoki faqat audio (mp3) shaklida yuklab beraman.\n\n"
        "Shunchaki linkni tashlang 🙂"
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📌 Qo'llab-quvvatlanadigan manbalar: Instagram, YouTube.\n"
        "Havolani yuboring, keyin video yoki audio formatini tanlang."
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

    token = uuid.uuid4().hex[:12]
    pending_urls[token] = url

    await message.answer(
        "Qanday formatda yuklab olay?",
        reply_markup=format_choice_keyboard(token),
    )


@dp.callback_query(F.data.startswith("dl:"))
async def handle_download_choice(callback: CallbackQuery):
    try:
        _, mode, token = callback.data.split(":", 2)
    except ValueError:
        await callback.answer("Xato so'rov.", show_alert=True)
        return

    url = pending_urls.pop(token, None)
    if not url:
        await callback.answer("Havola muddati tugagan, iltimos qayta yuboring.", show_alert=True)
        return

    await callback.answer()
    status_msg = await callback.message.edit_text("⏳ Yuklab olinmoqda, biroz kuting...")

    file_path: Path | None = None
    try:
        async with download_semaphore:
            loop = asyncio.get_running_loop()
            file_path = await loop.run_in_executor(None, run_download, url, mode)

        size = file_path.stat().st_size
        if size > MAX_FILE_SIZE:
            await status_msg.edit_text("⚠️ Fayl hajmi juda katta (50MB limitidan oshib ketdi).")
            return

        await status_msg.edit_text("📤 Yuborilmoqda...")
        input_file = FSInputFile(file_path)

        if mode == "audio":
            await callback.message.answer_audio(input_file)
        else:
            await callback.message.answer_video(input_file)

        await status_msg.delete()

    except yt_dlp.utils.DownloadError as e:
        log.warning("Download error: %s", e)
        await status_msg.edit_text("❌ Yuklab bo'lmadi. Havola noto'g'ri yoki video yopiq bo'lishi mumkin.")
    except TelegramBadRequest as e:
        log.warning("Telegram send error: %s", e)
        await status_msg.edit_text("❌ Faylni yuborishda xatolik yuz berdi.")
    except Exception:
        log.exception("Unexpected error")
        await status_msg.edit_text("❌ Kutilmagan xatolik yuz berdi. Qayta urinib ko'ring.")
    finally:
        if file_path and file_path.exists():
            try:
                file_path.unlink()
            except OSError:
                pass


# --------------------------------------------------------------------------
# RENDER SERVER VA ISHGA TUSHIRISH
# --------------------------------------------------------------------------

async def handle_web(request):
    return web.Response(text="Bot is running!")


async def main():
    # 1) Render "Web Service" portni talab qiladi — health-check server
    app = web.Application()
    app.router.add_get("/", handle_web)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info("Web server %s-portda ishga tushdi.", port)

    # 2) Tokenni tekshirish — noto'g'ri token bo'lsa DARHOL aniq xato beradi
    try:
        me = await bot.get_me()
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

    # 3) Eski webhook/pollingni tozalab, yagona polling boshlanadi
    await bot.delete_webhook(drop_pending_updates=True)
    log.info("Polling boshlanmoqda...")
    try:
        await dp.start_polling(bot)
    except Exception:
        log.exception(
            "Polling to'xtadi. Agar 'TerminatedByOtherGetUpdates' xatosi bo'lsa — "
            "shu tokenda BOSHQA joyda (masalan kompyuteringizda) bot ishlab turgani uchun shunday bo'ladi. "
            "Faqat bitta joyda ishga tushiring."
        )


if __name__ == "__main__":
    asyncio.run(main())
    
