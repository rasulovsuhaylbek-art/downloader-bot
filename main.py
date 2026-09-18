import os
import asyncio
import logging
import subprocess
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp
from aiohttp import web

BOT_TOKEN = "8870665375:AAEtD8oMB-qEBQyMxPzn53pLwrJigWHk_rI"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def download_media(url: str, output_path: str):
    ydl_opts = {
        'format': 'best',
        'outtmpl': output_path,
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
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
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info:
                duration = int(info.get('duration', 0) or 0)
                width = int(info.get('width', 0) or 0)
                height = int(info.get('height', 0) or 0)
    except Exception as e:
        print(f"Download error: {e}")
    return output_path, duration, width, height

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
    except Exception as e:
        print(f"Thumb error: {e}")
    return None

@dp.message(CommandStart())
async def start_handler(message: types.Message):
    await message.answer("Salom! Menga Instagram havolasini yuboring, videoni chiroyli muqova va pleyerda yuklab beraman.")

@dp.message(F.text.contains("http"))
async def media_handler(message: types.Message):
    url = message.text.strip()
    status_msg = await message.answer("⏳ Media yuklanmoqda, kuting...")
    
    output_file = f"file_{message.from_user.id}.mp4"
    thumb_file = f"thumb_{message.from_user.id}.jpg"

    try:
        loop = asyncio.get_event_loop()
        output_file, duration, width, height = await loop.run_in_executor(
            None, download_media, url, output_file
        )

        thumb_path = None
        if os.path.exists(output_file):
            thumb_path = await loop.run_in_executor(
                None, generate_thumbnail, output_file, thumb_file
            )

            video = FSInputFile(output_file)
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🚀 Botdan foydalanish", url="https://t.me/mix_videobot")]
            ])
            
            final_width = width if width > 0 else 1080
            final_height = height if height > 0 else 1920
            
            # parse_mode=None orqali har qanday formatlashni butunlay o'chiramiz
            kwargs = {
                "video": video,
                "caption": "✅ @mix_videobot orqali yuklab olindi",
                "parse_mode": None,
                "supports_streaming": True,
                "width": final_width,
                "height": final_height,
                "reply_markup": keyboard
            }
            if duration > 0:
                kwargs["duration"] = duration
            
            if thumb_path and os.path.exists(thumb_path):
                kwargs["thumbnail"] = FSInputFile(thumb_path)

            await message.answer_video(**kwargs)
            
            os.remove(output_file)
            if thumb_path and os.path.exists(thumb_path):
                os.remove(thumb_path)
        else:
            await message.answer("❌ Videoni yuklab bo'lmadi.")

    except Exception as e:
        await message.answer(f"❌ Xatolik yuz berdi: {e}")
        if os.path.exists(output_file):
            os.remove(output_file)
        if os.path.exists(thumb_file):
            os.remove(thumb_file)
    finally:
        await status_msg.delete()

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
    
