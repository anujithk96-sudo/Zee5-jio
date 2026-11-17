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

USER_URLS = {}

# Pyrogram ക്라이언트 initialization
app = Client(
    "prime_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# പ്രോഗ്രസ് ബാർ ഹുക്ക്
def get_progress_hook(client, message, media_type="Video"):
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
                            f"📥 Downloading {media_type}...\n\n"
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

@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    await message.reply_text(
        "👋 Hello! Welcome to Prime Video Downloader Bot.\n\n"
        "Send any Amazon Prime Video link, and download it as MP3 Audio or MP4 Video using cookies.txt!"
    )

@app.on_message(filters.text & filters.private & ~filters.command("start"))
async def get_link(client, message):
    url = message.text.strip()
    user_id = message.from_user.id

    if "primevideo.com" in url or "amazon.com" in url:
        USER_URLS[user_id] = url
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🎵 Download MP3 Audio", callback_data="dl|audio|mp3"),
                InlineKeyboardButton("🎬 Download MP4 Video", callback_data="dl|video|mp4")
            ]
        ])
        await message.reply_text("📥 Prime Video link detected! Choose your format below:", reply_markup=keyboard)
    else:
        await message.reply_text("❌ Please send a valid Amazon Prime Video link.")

@app.on_callback_query(filters.regex(r"^dl\|"))
async def download_media(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    url = USER_URLS.get(user_id)

    if not url:
        await callback_query.message.edit_text("❌ Link expired. Please send the link again.")
        return

    cb_data = callback_query.data
    _, media_type, ext = cb_data.split("|")

    if media_type == "audio":
        status_msg = await callback_query.message.edit_text("🎵 Downloading and converting to MP3 audio... Please wait...")
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': 'downloads/%(title)s.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'progress_hooks': [get_progress_hook(client, status_msg, "Audio")],
            'nocheckcertificate': True,
            'ignoreerrors': False,
            'no_warnings': True,
        }
    else:
        status_msg = await callback_query.message.edit_text("🎬 Downloading MP4 video... Please wait...")
        ydl_opts = {
            'format': 'bestvideo+bestaudio/best',
            'outtmpl': 'downloads/%(title)s.%(ext)s',
            'merge_output_format': 'mp4',
            'progress_hooks': [get_progress_hook(client, status_msg, "Video")],
            'nocheckcertificate': True,
            'ignoreerrors': False,
            'no_warnings': True,
        }

    # cookies.txt ഫയൽ ഉപയോഗിക്കുന്നു
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
        if filename and media_type == "audio":
            filename = os.path.splitext(filename)[0] + ".mp3"
        elif filename and media_type == "video":
            filename = os.path.splitext(filename)[0] + ".mp4"

        if not filename or not os.path.exists(filename):
            raise Exception("Media file could not be generated.")

        await status_msg.edit_text(f"📤 Uploading {ext.upper()} to Telegram...")

        if media_type == "audio":
            await client.send_audio(
                chat_id=callback_query.message.chat.id,
                audio=filename,
                caption="🎵 Here is your Prime Video MP3 Audio!"
            )
        else:
            await client.send_video(
                chat_id=callback_query.message.chat.id,
                video=filename,
                caption="🎬 Here is your Prime Video MP4 Video!",
                supports_streaming=True
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
    print("Prime Video Bot is running...")
    app.run()
