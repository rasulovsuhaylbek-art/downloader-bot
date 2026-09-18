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
        'playlist_end': 1,  # Audio sahifalar uchun birinchi videoni tanlaydi
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
            # Agar bu playlist (audio sahifa) bo'lsa, birinchi elementni olamiz
            if info and 'entries' in info:
                info = info['entries'][0]
            if info:
                duration = int(info.get('duration', 0) or 0)
                width = int(info.get('width', 0) or 0)
                height = int(info.get('height', 0) or 0)
    except Exception as e:
        print(f"Video download error: {e}")
    return output_path, duration, width, height

def download_audio_file(url: str, output_path: str):
    base_path = output_path.replace('.mp4', '')
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': base_path + '.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'playlist_end': 1,  # Audio sahifalar uchun birinchi trekni tanlaydi
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
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info and 'entries' in info:
                info = info['entries'][0]
            if info:
                title = info.get('title', 'Qo\'shiq')
                duration = int(info.get('duration', 0) or 0)
                performer = info.get('uploader', info.get('artist', 'Mix Video Bot'))
    except Exception as e:
        print(f"Audio download error: {e}")
        
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
    except Exception as e:
        print(f"Thumb error: {e}")
    return None

@dp.message(CommandStart())
async def start_handler(message: types.Message):
    await message.answer("Salom! Menga istalgan Instagram Reels, video yoki audio sahifa havolasini yuboring. Uni video yoki MP3 shaklida yuklab beraman.")

@dp.message(F.text.contains("http"))
async def link_handler(message: types.Message):
    url = message.text.strip()
    token = str(uuid.uuid4())[:8]
    url_cache[token] = url
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎬 Video", callback_data=f"vid_{token}"),
            InlineKeyboardButton(text="🎵 Qo'shiq (MP3)", callback_data=f"aud_{token}")
        ]
    ])
    
    await message.answer("📥 Qanday formatda yuklab olamiz?", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("vid_") | F.data.startswith("aud_"))
async def callback_handler(callback: types.CallbackQuery):
    action, token = callback.data.split("_", 1)
    url = url_cache.get(token)
    
    if not url:
        await callback.message.edit_text("❌ Havola muddati eskirgan yoki topilmadi. Iltimos, havolani qaytadan yuboring.")
        return
        
    await callback.message.edit_text("⏳ Yuklanmoqda, kuting...")
    user_id = callback.from_user.id
    
    if action == "vid":
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
                
                video = FSInputFile(output_file)
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🚀 Botdan foydalanish", url="https://t.me/mix_videobot")]
                ])
                
                final_width = width if width > 0 else 1080
                final_height = height if height > 0 else 1920
                
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
                
                await callback.message.answer_video(**kwargs)
                await callback.message.delete()
                
                os.remove(output_file)
                if thumb_path and os.path.exists(thumb_path):
                    os.remove(thumb_path)
            else:
                await callback.message.edit_text("❌ Videoni yuklab bo'lmadi.")
        except Exception as e:
            await callback.message.edit_text(f"❌ Xatolik yuz berdi: {e}")
            if os.path.exists(output_file):
                os.remove(output_file)
        finally:
            if token in url_cache:
                del url_cache[token]
                
    elif action == "aud":
        output_file = f"file_{user_id}.mp4"
        try:
            loop = asyncio.get_event_loop()
            mp3_path, title, duration, performer = await loop.run_in_executor(
                None, download_audio_file, url, output_file
            )
            
            if os.path.exists(mp3_path):
                audio = FSInputFile(mp3_path)
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🚀 Botdan foydalanish", url="https://t.me/mix_videobot")]
                ])
                
                await callback.message.answer_audio(
                    audio=audio,
                    title=title,
                    performer=performer,
                    duration=duration,
                    caption="✅ @mix_videobot orqali yuklab olindi",
                    reply_markup=keyboard
                )
                await callback.message.delete()
                os.remove(mp3_path)
            else:
                await callback.message.edit_text("❌ Qo'shiqni yuklab bo'lmadi.")
        except Exception as e:
            await callback.message.edit_text(f"❌ Xatolik yuz berdi: {e}")
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
    
