import os
import uuid
import glob
import html
import asyncio
import logging
import subprocess
import re
import urllib.parse
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp
from aiohttp import web

# TODO: xavfsizlik uchun tokenni keyinroq environment variable orqali oling:
# BOT_TOKEN = os.environ["BOT_TOKEN"]
BOT_TOKEN = "8870665375:AAEtD8oMB-qEBQyMxPzn53pLwrJigWHk_rI"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

MAX_FILE_SIZE = 49 * 1024 * 1024  # Telegram bot API ~50MB limiti


# ---------- URL aniqlash ----------

def parse_media_url(url: str):
    ig_match = re.search(r'/(?:reel|p|reels)/([A-Za-z0-9_-]+)', url)
    if ig_match:
        code = ig_match.group(1)
        return "ig", code, f"https://www.instagram.com/reel/{code}/"

    yt_shorts = re.search(r'/shorts/([A-Za-z0-9_-]+)', url)
    if yt_shorts:
        code = yt_shorts.group(1)
        return "yts", code, f"https://www.youtube.com/shorts/{code}"

    if "youtu.be/" in url:
        code = url.split("youtu.be/")[-1].split("?")[0].split("/")[0]
        if code:
            return "ytw", code, f"https://www.youtube.com/watch?v={code}"

    if "youtube.com" in url:
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        if 'v' in query:
            code = query['v'][0]
            return "ytw", code, f"https://www.youtube.com/watch?v={code}"

    return None, None, url


def build_url(platform: str, code: str) -> str:
    if platform == "ig":
        return f"https://www.instagram.com/reel/{code}/"
    if platform == "yts":
        return f"https://www.youtube.com/shorts/{code}"
    if platform == "ytw":
        return f"https://www.youtube.com/watch?v={code}"
    return ""


def cleanup(base_path: str):
    """base_path bilan boshlanadigan barcha vaqtinchalik fayllarni o'chiradi."""
    for f in glob.glob(base_path + "*"):
        try:
            os.remove(f)
        except OSError:
            pass


# ---------- Yuklab olish funksiyalari ----------

def download_video(url: str, output_path: str):
    ydl_opts = {
        'format': 'best',
        'outtmpl': output_path,
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'user_agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'mweb']
            }
        },
        'postprocessors': [{
            'key': 'FFmpegVideoConvertor',
            'preferedformat': 'mp4',
        }],
        'postprocessor_args': {
            'ffmpeg': ['-movflags', '+faststart']
        }
    }
    duration = 0
    width = 0
    height = 0
    title = "Video"
    uploader = "Noma'lum"
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info:
            duration = int(info.get('duration', 0) or 0)
            width = int(info.get('width', 0) or 0)
            height = int(info.get('height', 0) or 0)
            title = info.get('title') or "Video"
            uploader = info.get('uploader') or info.get('channel') or "Noma'lum"
    return output_path, duration, width, height, title, uploader


def download_audio_file(url: str, output_path: str):
    base_path = output_path.replace('.mp4', '')
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': base_path + '.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'user_agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'mweb']
            }
        },
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }
    title = "Qo'shiq"
    duration = 0
    performer = "Mix Video Bot"
    mp3_path = base_path + '.mp3'

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info:
            title = info.get('title') or "Qo'shiq"
            duration = int(info.get('duration', 0) or 0)
            performer = info.get('uploader') or info.get('artist') or info.get('channel') or "Mix Video Bot"

    return mp3_path, title, duration, performer


def generate_thumbnail(video_path: str, thumb_path: str):
    try:
        cmd = [
            'ffmpeg', '-y', '-i', video_path,
            '-ss', '00:00:01', '-vframes', '1',
            '-vf', 'scale=320:-1', thumb_path
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        if os.path.exists(thumb_path):
            return thumb_path
    except Exception:
        pass
    return None


# ---------- Chiroyli caption'lar ----------

def video_caption(title: str, uploader: str) -> str:
    safe_title = html.escape(title.strip())[:150]
    safe_uploader = html.escape(uploader.strip())[:80]
    return (
        f"🎬 <b>{safe_title}</b>\n"
        f"👤 {safe_uploader}\n\n"
        f"✅ @mix_videobot orqali yuklab olindi"
    )


def audio_caption(title: str, performer: str) -> str:
    safe_title = html.escape(title.strip())[:150]
    safe_performer = html.escape(performer.strip())[:80]
    return (
        f"🎧 <b>{safe_title}</b>\n"
        f"🎤 {safe_performer}\n\n"
        f"✅ @mix_videobot orqali yuklab olindi"
    )


# ---------- Handlerlar ----------

@dp.message(CommandStart())
async def start_handler(message: types.Message):
    await message.answer(
        "👋 <b>Salom!</b>\n\n"
        "Menga quyidagilardan birini yuboring:\n"
        "📸 Instagram (Reels) havolasi\n"
        "▶️ YouTube video yoki Shorts havolasi\n\n"
        "Video darhol yuklab beriladi, xohlasangiz o'sha videoning "
        "audiosini ham alohida ajratib beraman 🎧",
        parse_mode="HTML"
    )


@dp.message(F.text.contains("http"))
async def link_handler(message: types.Message):
    url = message.text.strip()

    if "/reels/audio/" in url:
        await message.answer("⚠️ Iltimos, audio sahifa havolasini emas, aniq bir video havolasini yuboring.")
        return

    platform, code, clean_url = parse_media_url(url)
    if not code:
        await message.answer("❌ Havolani aniqlab bo'lmadi. Iltimos, to'g'ri Instagram yoki YouTube havolasini yuboring.")
        return

    status_msg = await message.answer("⏳ Video yuklanmoqda, kuting...")
    user_id = message.from_user.id
    req_id = uuid.uuid4().hex[:8]

    base_name = f"file_{user_id}_{req_id}"
    thumb_base = f"thumb_{user_id}_{req_id}"
    output_file = f"{base_name}.mp4"
    thumb_file = f"{thumb_base}.jpg"

    try:
        await bot.send_chat_action(chat_id=message.chat.id, action="typing")
        loop = asyncio.get_event_loop()
        output_file, duration, width, height, title, uploader = await loop.run_in_executor(
            None, download_video, clean_url, output_file
        )

        if not os.path.exists(output_file):
            await message.answer("❌ Videoni yuklab bo'lmadi.")
            return

        if os.path.getsize(output_file) > MAX_FILE_SIZE:
            await message.answer("⚠️ Video hajmi juda katta (50MB dan oshadi), Telegram bot orqali yuborib bo'lmaydi.")
            return

        thumb_path = await loop.run_in_executor(
            None, generate_thumbnail, output_file, thumb_file
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎵 Audiosini yuklab olish", callback_data=f"aud|{platform}|{code}")]
        ])

        await bot.send_chat_action(chat_id=message.chat.id, action="upload_video")

        kwargs = {
            "video": FSInputFile(output_file),
            "caption": video_caption(title, uploader),
            "parse_mode": "HTML",
            "supports_streaming": True,
            "reply_markup": keyboard
        }
        if duration > 0:
            kwargs["duration"] = duration
        if width > 0 and height > 0:
            kwargs["width"] = width
            kwargs["height"] = height
        if thumb_path and os.path.exists(thumb_path):
            kwargs["thumbnail"] = FSInputFile(thumb_path)

        await message.answer_video(**kwargs)

    except Exception as e:
        logging.exception("Video yuklashda xatolik")
        await message.answer(f"❌ Xatolik yuz berdi: {e}")
    finally:
        cleanup(base_name)
        cleanup(thumb_base)
        await status_msg.delete()


@dp.callback_query(F.data.startswith("aud|"))
async def callback_audio(callback: types.CallbackQuery):
    parts = callback.data.split("|")
    if len(parts) != 3:
        await callback.answer("❌ Xatolik: Havola ma'lumotlari topilmadi.", show_alert=True)
        return

    _, platform, code = parts
    url = build_url(platform, code)
    if not url:
        await callback.answer("❌ Noma'lum platforma.", show_alert=True)
        return

    await callback.answer("⏳ Qo'shiq yuklanmoqda...")
    user_id = callback.from_user.id
    req_id = uuid.uuid4().hex[:8]
    base_name = f"file_aud_{user_id}_{req_id}"
    output_file = f"{base_name}.mp4"

    try:
        await bot.send_chat_action(chat_id=callback.message.chat.id, action="typing")
        loop = asyncio.get_event_loop()
        mp3_path, title, duration, performer = await loop.run_in_executor(
            None, download_audio_file, url, output_file
        )

        if not os.path.exists(mp3_path):
            await callback.message.answer("❌ Qo'shiqni yuklab bo'lmadi.")
            return

        if os.path.getsize(mp3_path) > MAX_FILE_SIZE:
            await callback.message.answer("⚠️ Audio hajmi juda katta, Telegram bot orqali yuborib bo'lmaydi.")
            return

        await bot.send_chat_action(chat_id=callback.message.chat.id, action="upload_voice")

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 @mix_videobot", url="https://t.me/mix_videobot")]
        ])

        await callback.message.answer_audio(
            audio=FSInputFile(mp3_path),
            title=title[:60],
            performer=performer[:60],
            duration=duration,
            caption=audio_caption(title, performer),
            parse_mode="HTML",
            reply_markup=keyboard
        )

    except Exception as e:
        logging.exception("Audio yuklashda xatolik")
        await callback.message.answer(f"❌ Xatolik yuz berdi: {e}")
    finally:
        cleanup(base_name)


# ---------- Web server (deploy uchun health-check) ----------

async def handle(request):
    return web.Response(text="Bot is running!")


async def main():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
    
