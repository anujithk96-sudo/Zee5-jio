import logging
import os
import time
import asyncio
import re
import requests
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

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

app = Client(
    "zee5_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

def get_progress_hook(client, message, media_type="Audio"):
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
        "👋 Hello! Welcome to Zee5 Downloader Bot.\n\n"
        "Send any Zee5 link (including onelink.me links), and download it as MP3 Audio or MP4 Video!"
    )

@app.on_message(filters.text & filters.private & ~filters.command("start"))
async def get_link(client, message):
    w = message.text.strip()
    user_id = message.from_user.id

    if "zee5.com" in w or "onelink.me" in w:
        status_msg = await message.reply_text("⏳ Processing Zee5 link & extracting stream info...")
        try:
            if "onelink.me" in w:
                session = requests.Session()
                response = session.get(w, headers=headers, allow_redirects=True, timeout=10)
                w = response.url

            req1 = requests.get("https://useraction.zee5.com/tokennd").json()
            rgx = re.findall(r"([0-9]?\w+)", w)[-3:]
            li = {"url": "zee5vodnd.akamaized.net", "token": "https://gwapi.zee5.com/content/details/"}
            req2 = requests.get("https://useraction.zee5.com/token/platform_tokens.php?platform_name=web_app").json()["token"]
            headers["X-Access-Token"] = req2
            req3 = requests.get("https://useraction.zee5.com/token").json()

            if "movies" in w:
                r1 = requests.get(li["token"] + "-".join(rgx), headers=headers, params={"translation": "en", "country": "IN"}).json()
                g1 = (r1["hls"][0].replace("drm", "hls") + req1["video_token"])
                url = "https://" + li["url"] + g1
            elif "tvshows" in w or "originals" in w:
                r2 = requests.get(li["token"] + "-".join(rgx), headers=headers, params={"translation": "en", "country": "IN"}).json()
                g2 = (r2["hls"][0].replace("drm", "hls"))
                if "netst" in g2:
                    url = g2 + req3["video_token"]
                else:
                    url = "https://" + li["url"] + g2 + req1["video_token"]
            else:
                r2 = requests.get(li["token"] + "-".join(rgx), headers=headers, params={"translation": "en", "country": "IN"}).json()
                g2 = (r2["hls"][0].replace("drm", "hls"))
                url = "https://" + li["url"] + g2 + req1["video_token"]

            USER_URLS[user_id] = url
            
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🎵 Download MP3 Audio", callback_data="dl|audio|mp3"),
                    InlineKeyboardButton("🎬 Download MP4 Video", callback_data="dl|video|mp4")
                ]
            ])
            await status_msg.edit_text("📥 Zee5 link successfully processed! Choose your format below:", reply_markup=keyboard)

        except Exception as e:
            logger.error(f"Zee5 extraction error: {e}")
            await status_msg.edit_text("❌ There's some issue resolving this link. Make sure it points to a valid Zee5 media page 😕")
    else:
        await message.reply_text("❌ Please send a valid Zee5 link (or onelink.me link).")

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
            'http_headers': headers
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
            'http_headers': headers
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
                caption="🎵 Here is your Zee5 MP3 Audio!"
            )
        else:
            await client.send_video(
                chat_id=callback_query.message.chat.id,
                video=filename,
                caption="🎬 Here is your Zee5 MP4 Video!",
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
    print("Zee5 Bot is running...")
    app.run()
