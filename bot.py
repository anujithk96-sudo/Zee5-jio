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
                            f"📥 ഡൗൺലോഡ് പുരോഗമിക്കുന്നു...\n\n"
                            f"📊 ശതമാനം: {percentage}\n"
                            f"🚀 വേഗത: {speed}\n"
                            f"⏱️ ബാക്കി സമയം: {eta}"
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
        "👋 സ്വാഗതം!\n\n"
        "ഞാൻ ഒരു Media Downloader Bot ആണ്. "
        "നിങ്ങൾക്ക് ആവശ്യമുള്ള ജിയോ ഹോസ്റ്റാർ ലിങ്ക് ഇവിടെ അയച്ചു തന്നാൽ, MP3 ഓഡിയോ ആയോ വീഡിയോ ആയോ ഡൗൺലോഡ് ചെയ്ത് തരുന്നതാണ്."
    )

# ലിങ്ക് പരിശോധിക്കുന്ന ഹാൻഡ്‌ലർ (Hotstar അല്ലെങ്കിൽ പൊതുവായ ലിങ്കുകൾ തിരിച്ചറിയാൻ)
@app.on_message(filters.text & filters.private & ~filters.command("start"))
async def get_link(client, message):
    url = message.text.strip()

    # ഏത് ഹോസ്റ്റാർ / ഒടിടി ലിങ്ക് ആണെങ്കിലും പെട്ടെന്ന് തിരിച്ചറിയാൻ
    if "hotstar.com" in url or "jiocinema" in url or "http" in url:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🎵 Extract MP3 Audio (Recommended)", callback_data=f"dl|audio|mp3|{url}")
            ],
            [
                InlineKeyboardButton("📹 720p Video", callback_data=f"dl|video|720|{url}"),
                InlineKeyboardButton("📹 480p Video", callback_data=f"dl|video|480|{url}")
            ]
        ])
        await message.reply_text("📥 ആവശ്യമായ ഫോർമാറ്റ് തിരഞ്ഞെടുക്കുക:", reply_markup=keyboard)
    else:
        await message.reply_text("ദയവായി ശരിയായ ജിയോ ഹോസ്റ്റാർ ലിങ്ക് അയക്കുക.")

# ഡൗൺലോഡ് പ്രോസസ്സ് ഹാൻഡ്‌ലർ
@app.on_callback_query(filters.regex("^dl\|"))
async def download_media(client, callback_query: CallbackQuery):
    data_parts = callback_query.data.split("|")
    media_type = data_parts[1] # video അല്ലെങ്കിൽ audio
    quality = data_parts[2]
    url = data_parts[3]

    if media_type == "audio":
        status_msg = await callback_query.message.edit_text("🎵 MP3 ഓഡിയോ എക്സ്ട്രാക്റ്റ് ചെയ്യുന്നു... ദയവായി കാത്തിരിക്കുക...")
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
        status_msg = await callback_query.message.edit_text(f" തിരഞ്ഞെടുക്കപ്പെട്ട ക്വാളിറ്റി: {quality}p. ഡൗൺലോഡ് ആരംഭിക്കുന്നു...")
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

        await status_msg.edit_text(" ഫയൽ അപ്‌ലോഡ് ചെയ്യുന്നു...")

        if media_type == "audio":
            await client.send_audio(
                chat_id=callback_query.message.chat.id,
                audio=filename,
                caption="🎵 ഇവിടെ നിങ്ങളുടെ MP3 ഓഡിയോ!"
            )
        else:
            await client.send_video(
                chat_id=callback_query.message.chat.id,
                video=filename,
                caption=f"📹 ഇവിടെ നിങ്ങളുടെ വീഡിയോ ({quality}p)!"
            )

        await status_msg.delete()
        
        # ഫയൽ ക്ലീനപ്പ്
        if os.path.exists(filename):
            os.remove(filename)

    except Exception as e:
        await status_msg.edit_text(f"❌ ഡൗൺലോഡ് ചെയ്യുന്നതിൽ പരാജയപ്പെട്ടു: {str(e)}")

if __name__ == "__main__":
    print("ബോട്ട് റൺ ആകുന്നു...")
    app.run()
