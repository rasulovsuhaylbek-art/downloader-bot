import os
import asyncio
import logging
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

@dp.message(CommandStart())
async def start_handler(message: types.Message):
    await message.answer("Salom! Menga Instagram yoki boshqa tarmoq havolasini yuboring, chiroyli qilib yuklab beraman.")

@dp.message(F.text.contains("http"))
async def media_handler(message: types.Message):
    url = message.text.strip()
    status_msg = await message.answer("⏳ Media yuklanmoqda, kuting...")
    output_file = f"file_{message.from_user.id}.mp4"

    try:
        loop = asyncio.get_event_loop()
        output_file, duration, width, height = await loop.run_in_executor(
            None, download_media, url, output_file
        )

        if os.path.exists(output_file):
            video = FSInputFile(output_file)
            
            # Professional botlardek ostiga tugma qo'shamiz
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🚀 Botimizdan foydalanish", url="https://t.me/UniversalDownloaderBot")]
            ])
            
            # Videoni katta va sifatli qilib yuborish parametrlari
            kwargs = {
                "video": video,
                "caption": "✅ **Muvaffaqiyatli yuklab olindi!**",
                "parse_mode": "Markdown",
                "reply_markup": keyboard
            }
            if duration > 0:
                kwargs["duration"] = duration
            if width > 0:
                kwargs["width"] = width
            if height > 0:
                kwargs["height"] = height

            await message.answer_video(**kwargs)
            os.remove(output_file)
        else:
            await message.answer("❌ Videoni yuklab bo'lmadi.")

    except Exception as e:
        await message.answer("❌ Videoni yuklashda xatolik yuz berdi. Havola to'g'riligini tekshiring.")
        if os.path.exists(output_file):
            os.remove(output_file)
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
    
