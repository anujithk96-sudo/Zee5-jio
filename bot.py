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
    "jiohotstar_bot",
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
                            f"📥 Downloading...\n\n"
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

# /start കമാൻഡ് (ഇംഗ്ലീഷിലുള്ള വെൽക്കം മെസ്സേജ്)
@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    await message.reply_text(
        "👋 Hello! Welcome to JioHotstar Downloader Bot.\n\n"
        "Send any JioHotstar link, and you can download it as MP3 Audio or Video!"
    )

# https ലിങ്കുകൾ ഉൾപ്പെടെയുള്ള ഹോസ്റ്റാർ ലിങ്കുകൾ ഓട്ടോമാറ്റിക്കായി തിരിച്ചറിയുന്ന ഹാൻഡ്‌ലർ
@app.on_message(filters.text & filters.private & ~filters.command("start"))
async def get_link(client, message):
    url = message.text.strip()
    user_id = message.from_user.id

    # ലിങ്കിൽ hotstar.com ഉണ്ടോ എന്ന് പരിശോധിക്കുന്നു
    if "hotstar.com" in url:
        USER_URLS[user_id] = url
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🎵 Extract MP3 Audio (Recommended)", callback_data="dl|audio|mp3")
            ],
            [
                InlineKeyboardButton("📹 720p Video", callback_data="dl|video|720"),
                InlineKeyboardButton("📹 480p Video", callback_data="dl|video|480")
            ]
        ])
        await message.reply_text("📥 JioHotstar link detected! Please select your required format:", reply_markup=keyboard)
    else:
        await message.reply_text("❌ Please send a valid JioHotstar link.")

# ഡൗൺലോഡ് പ്രോസസ്സ് ഹാൻഡ്‌ലർ
@app.on_callback_query(filters.regex("^dl\|"))
async def download_media(client, callback_query: CallbackQuery):
    data_parts = callback_query.data.split("|")
    media_type = data_parts[1] # video അല്ലെങ്കിൽ audio
    quality = data_parts[2]
    
    user_id = callback_query.from_user.id
    url = USER_URLS.get(user_id)

    if not url:
        await callback_query.message.edit_text("❌ Link expired. Please send the link again.")
        return

    if media_type == "audio":
        status_msg = await callback_query.message.edit_text("🎵 Extracting MP3 audio... Please wait...")
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': 'downloads/%(title)s.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'progress_hooks': [get_progress_hook(client, status_msg)],
        }
    else:
        status_msg = await callback_query.message.edit_text(f"📥 Downloading {quality}p video... Please wait...")
        ydl_opts = {
            'format': f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best',
            'outtmpl': 'downloads/%(title)s.%(ext)s',
            'progress_hooks': [get_progress_hook(client, status_msg)],
        }

    # cookies.txt ഫയൽ ഉണ്ടെങ്കിൽ ഉപയോഗിക്കുന്നു
    if os.path.exists("cookies.txt"):
        ydl_opts['cookiefile'] = "cookies.txt"

    try:
        os.makedirs("downloads", exist_ok=True)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            if media_type == "audio":
                filename = os.path.splitext(filename)[0] + ".mp3"

        await status_msg.edit_text("📤 Uploading to Telegram...")

        if media_type == "audio":
            await client.send_audio(
                chat_id=callback_query.message.chat.id,
                audio=filename,
                caption="🎵 Here is your JioHotstar MP3 Audio!"
            )
        else:
            await client.send_video(
                chat_id=callback_query.message.chat.id,
                video=filename,
                caption=f"📹 Here is your JioHotstar Video ({quality}p)!"
            )

        await status_msg.delete()
        
        # ഫയൽ ക്ലീനപ്പ്
        if os.path.exists(filename):
            os.remove(filename)

    except Exception as e:
        await status_msg.edit_text(f"❌ Download failed: {str(e)}")

if __name__ == "__main__":
    print("Bot is running...")
    app.run()
