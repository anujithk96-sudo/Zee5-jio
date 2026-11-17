import logging
import os
import time
import asyncio
import yt_dlp
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# ലോഗിങ് സെറ്റ് ചെയ്യുക
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# എൻവയോൺമെന്റ് വേരിയബിളുകൾ
API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# വലിയ URL-കൾ സേവ് ചെയ്തു വെക്കാനുള്ള ഡിക്ഷണറി
USER_URLS = {}

# ഇവന്റ് ലൂപ്പ് സെറ്റ് ചെയ്യുന്നു
try:
    loop = asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# Pyrogram ക്라이언트 initialization
app = Client(
    "zee5_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# ലൈവ് പ്രോഗ്രസ് ബാർ ഹുക്ക്
def get_progress_hook(client, message):
    last_update_time = 0
    def progress_hook(d):
        nonlocal last_update_time
        if d['status'] == 'downloading':
            current_time = time.time()
            if current_time - last_update_time > 3:
                percentage = d.get('_percent_str', '0%').strip()
                speed = d.get('_speed_str', 'N/A').strip()
                eta = d.get('_eta_str', 'N/A').strip()
                try:
                    asyncio.run_coroutine_threadsafe(
                        message.edit_text(
                            f"📥 Downloading Audio...\n\n"
                            f"📊 Percentage: {percentage}\n"
                            f"🚀 Speed: {speed}\n"
                            f"⏱️ ETA: {eta}"
                        ),
                        client.loop
                    )
                except Exception:
                    pass
                last_update_time = current_time
    return progress_hook

# /start കമാൻഡ്
@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    await message.reply_text(
        "👋 Hello! Welcome to Zee5 Audio Downloader Bot.\n\n"
        "Send any Zee5 link, and you can download it directly as MP3 Audio!"
    )

# Zee5 ലിങ്കുകൾ തിരിച്ചറിയുന്ന ഹാൻഡ്‌ലർ
@app.on_message(filters.text & filters.private & ~filters.command("start"))
async def get_link(client, message):
    url = message.text.strip()
    user_id = message.from_user.id

    if "zee5.com" in url:
        USER_URLS[user_id] = url
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🎵 Download MP3 Audio", callback_data="dl|audio|mp3")
            ]
        ])
        await message.reply_text("📥 Zee5 link detected! Click below to download MP3 Audio:", reply_markup=keyboard)
    else:
        await message.reply_text("❌ Please send a valid Zee5 link (e.g., https://www.zee5.com/...).")

# ഡൗൺലോഡ് പ്രോസസ്സ് ഹാൻഡ്‌ലർ
@app.on_callback_query(filters.regex("^dl\|"))
async def download_media(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    url = USER_URLS.get(user_id)

    if not url:
        await callback_query.message.edit_text("❌ Link expired. Please send the link again.")
        return

    status_msg = await callback_code_msg = await callback_query.message.edit_text("🎵 Extracting and converting to MP3 audio... Please wait...")
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': 'downloads/%(title)s.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'progress_hooks': [get_progress_hook(client, status_msg)],
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'no_warnings': True,
        'extractor_args': {'zee5': {'all_formats': True}},
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        }
    }

    if os.path.exists("cookies.txt"):
        ydl_opts['cookiefile'] = "cookies.txt"

    filename = None
    try:
        os.makedirs("downloads", exist_ok=True)
        def run_dl():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if not info:
                    raise Exception("Could not extract media info.")
                return ydl.prepare_filename(info)

        filename = await asyncio.to_thread(run_dl)
        if filename:
            filename = os.path.splitext(filename)[0] + ".mp3"

        if not filename or not os.path.exists(filename):
            raise Exception("Audio file could not be generated.")

        await status_msg.edit_text("📤 Uploading MP3 to Telegram...")

        await client.send_audio(
            chat_id=callback_query.message.chat.id,
            audio=filename,
            caption="🎵 Here is your Zee5 MP3 Audio!"
        )

        await status_msg.delete()
        
    except Exception as e:
        await status_msg.edit_text(f"❌ Download failed: {str(e)}")
    finally:
        if filename and os.path.exists(filename):
            try:
                os.remove(filename)
            except:
                pass

if __name__ == "__main__":
    print("Zee5 Audio Bot is running...")
    app.run()
