import os
import asyncio
import logging
import subprocess
import uuid
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp
from aiohttp import web

BOT_TOKEN = "8870665375:AAEtD8oMB-qEBQyMxPzn53pLwrJigWHk_rI"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

url_cache = {}

def download_video(url: str, output_path: str):
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
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info:
            duration = int(info.get('duration', 0) or 0)
            width = int(info.get('width', 0) or 0)
            height = int(info.get('height', 0) or 0)
    return output_path, duration, width, height

def download_audio_file(url: str, output_path: str):
    base_path = output_path.replace('.mp4', '')
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': base_path + '.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
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
            title = info.get('title', 'Qo\'shiq')
            duration = int(info.get('duration', 0) or 0)
            performer = info.get('uploader', info.get('artist', 'Mix Video Bot'))
            
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

@dp.message(CommandStart())
async def start_handler(message: types.Message):
    await message.answer("Salom! Menga Instagram havolasini yuboring. Men videoni darhol yuklab beraman.")

@dp.message(F.text.contains("http"))
async def link_handler(message: types.Message):
    url = message.text.strip()
    
    if "/reels/audio/" in url:
        await message.answer("⚠️ Iltimos, audio sahifa havolasini emas, aniq bir video (Reel) havolasini yuboring.")
        return

    status_msg = await message.answer("⏳ Video yuklanmoqda, kuting...")
    user_id = message.from_user.id
    
    output_file = f"file_{user_id}.mp4"
    thumb_file = f"thumb_{user_id}.jpg"

    try:
        loop = asyncio.get_event_loop()
        output_file, duration, width, height = await loop.run_in_executor(
            None, download_video, url, output_file
        )

        thumb_path = None
        if os.path.exists(output_file):
            thumb_path = await loop.run_in_executor(
                None, generate_thumbnail, output_file, thumb_file
            )

            token = str(uuid.uuid4())[:8]
            url_cache[token] = url

            video = FSInputFile(output_file)
            
            # Faqat bitta tugma: Audiosini yuklab olish
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎵 Audiosini yuklab olish", callback_data=f"aud_{token}")]
            ])
            
            kwargs = {
                "video": video,
                "caption": "✅ @mix_videobot orqali yuklab olindi",
                "parse_mode": None,
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
            
            os.remove(output_file)
            if thumb_path and os.path.exists(thumb_path):
                os.remove(thumb_path)
        else:
            await message.answer("❌ Videoni yuklab bo'lmadi.")

    except Exception as e:
        await message.answer(f"❌ Xatolik yuz berdi: {e}")
        if os.path.exists(output_file):
            os.remove(output_file)
    finally:
        await status_msg.delete()

@dp.callback_query(F.data.startswith("aud_"))
async def callback_audio(callback: types.CallbackQuery):
    token = callback.data.split("_", 1)[1]
    url = url_cache.get(token)
    
    if not url:
        await callback.answer("❌ Havola eskirgan yoki topilmadi.", show_alert=True)
        return
        
    await callback.answer("⏳ Qo'shiq yuklanmoqda...")
    user_id = callback.from_user.id
    output_file = f"file_aud_{user_id}.mp4"
    
    try:
        loop = asyncio.get_event_loop()
        mp3_path, title, duration, performer = await loop.run_in_executor(
            None, download_audio_file, url, output_file
        )
        
        if os.path.exists(mp3_path):
            audio = FSInputFile(mp3_path)
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🚀 @mix_videobot", url="https://t.me/mix_videobot")]
            ])
            
            await callback.message.answer_audio(
                audio=audio,
                title=title,
                performer=performer,
                duration=duration,
                caption="✅ @mix_videobot orqali yuklab olindi",
                reply_markup=keyboard
            )
            os.remove(mp3_path)
        else:
            await callback.message.answer("❌ Qo'shiqni yuklab bo'lmadi.")
    except Exception as e:
        await callback.message.answer(f"❌ Xatolik yuz berdi: {e}")
        if os.path.exists(output_file):
            os.remove(output_file)
    finally:
        if token in url_cache:
            del url_cache[token]

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
    
