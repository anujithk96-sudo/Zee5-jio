import logging
import os
import time
import asyncio
import yt_dlp
import cv2
from hachoir.metadata import extractMetadata
from hachoir.parser import createParser
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# Logging setup
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variables
API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# Dictionaries for storing user data
USER_URLS = {}
USER_THUMBNAILS = {}
USER_STATES = {}

# Event loop setup
try:
    loop = asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# Pyrogram Client initialization
app = Client(
    "jiohotstar_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# Function to get video duration
def get_video_duration(file_path):
    try:
        parser = createParser(file_path)
        if parser:
            metadata = extractMetadata(parser)
            if metadata and metadata.has("duration"):
                return int(metadata.get("duration").seconds)
    except Exception:
        pass
    return 0

# Function to generate automatic thumbnail
def generate_thumbnail(video_path):
    try:
        cap = cv2.VideoCapture(video_path)
        success, image = cap.read()
        thumb_path = "downloads/thumb.jpg"
        if success:
            cv2.imwrite(thumb_path, image)
            return thumb_path
    except Exception:
        pass
    return None

# Progress bar helper
def get_progress_bar(percentage):
    try:
        pct = float(percentage.replace('%', '').strip())
    except:
        pct = 0.0
    completed = int(pct // 10)
    remaining = 10 - completed
    return "█" * completed + "░" * remaining

def get_progress_hook(client, message, title="Downloading"):
    last_update_time = 0
    def progress_hook(d):
        nonlocal last_update_time
        if d['status'] == 'downloading':
            current_time = time.time()
            if current_time - last_update_time > 3:
                percentage = d.get('_percent_str', '0%').strip()
                speed = d.get('_speed_str', 'N/A').strip()
                eta = d.get('_eta_str', 'N/A').strip()
                bar = get_progress_bar(percentage)
                try:
                    asyncio.run_coroutine_threadsafe(
                        message.edit_text(
                            f"📥 {title}...\n\n"
                            f"[{bar}] {percentage}\n"
                            f"🚀 Speed: {speed}\n"
                            f"⏱️ ETA: {eta}"
                        ),
                        client.loop
                    )
                except Exception:
                    pass
                last_update_time = current_time
    return progress_hook

# User settings keyboard markup
def build_user_settings_keyboard(user_id):
    has_thumb = "Yes ✅" if user_id in USER_THUMBNAILS else "No ❌"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🖼️ Thumbnail Set: {has_thumb}", callback_data="set_thumb")],
        [InlineKeyboardButton("👀 View Thumbnail", callback_data="view_thumb")],
        [InlineKeyboardButton("🗑️ Remove Thumbnail", callback_data="remove_thumb")]
    ])

# /start command handler
@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    await message.reply_text(
        "👋 Hello! Welcome to JioHotstar Downloader Bot.\n\n"
        "Send any JioHotstar link with `-n custom_name` for renaming, and download as Audio or Video!",
        reply_markup=build_user_settings_keyboard(message.from_user.id)
    )

# /settings command handler
@app.on_message(filters.command("settings") & filters.private)
async def settings_command(client, message):
    await message.reply_text(
        "⚙️ **User Settings**\n\nManage your custom thumbnail here:",
        reply_markup=build_user_settings_keyboard(message.from_user.id)
    )

# Settings callback query handler
@app.on_callback_query(filters.regex("^(set_thumb|view_thumb|remove_thumb)$"))
async def settings_callback(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data

    if data == "set_thumb":
        USER_STATES[user_id] = "waiting_for_thumb"
        await callback_query.message.reply_text("📸 Please send the photo you want to set as custom thumbnail.")
    elif data == "view_thumb":
        if user_id in USER_THUMBNAILS and os.path.exists(USER_THUMBNAILS[user_id]):
            await client.send_photo(chat_id=user_id, photo=USER_THUMBNAILS[user_id], caption="🖼️ Your current custom thumbnail.")
        else:
            await callback_query.answer("❌ No custom thumbnail set yet!", show_alert=True)
    elif data == "remove_thumb":
        if user_id in USER_THUMBNAILS:
            if os.path.exists(USER_THUMBNAILS[user_id]):
                os.remove(USER_THUMBNAILS[user_id])
            del USER_THUMBNAILS[user_id]
            await callback_query.answer("🗑️ Custom thumbnail removed successfully!", show_alert=True)
        else:
            await callback_query.answer("❌ No custom thumbnail to remove!", show_alert=True)
        await callback_query.message.edit_reply_markup(reply_markup=build_user_settings_keyboard(user_id))
    await callback_query.answer()

# Input message handler for links and photos
@app.on_message(filters.private & ~filters.command(["start", "settings"]))
async def handle_user_inputs(client, message):
    user_id = message.from_user.id
    state = USER_STATES.get(user_id)

    if state == "waiting_for_thumb" and message.photo:
        os.makedirs("thumbnails", exist_ok=True)
        thumb_path = f"thumbnails/{user_id}.jpg"
        await message.download(file_name=thumb_path)
        USER_THUMBNAILS[user_id] = thumb_path
        USER_STATES[user_id] = None
        await message.reply_text("✅ Custom thumbnail saved successfully!", reply_markup=build_user_settings_keyboard(user_id))
        return

    text = message.text.strip() if message.text else ""
    if "hotstar.com" in text:
        parts = text.split("-n")
        url = parts[0].strip()
        custom_name = parts[1].strip() if len(parts) > 1 else None

        USER_URLS[user_id] = {"url": url, "custom_name": custom_name}
        
        # എല്ലാ ക്വാളിറ്റികളും MP3 ഓപ്ഷനും ഉൾപ്പെടുത്തിയ കീബോർഡ്
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎵 Extract MP3 Audio", callback_data="dl|audio|mp3")],
            [
                InlineKeyboardButton("📹 144p", callback_data="dl|video|144"),
                InlineKeyboardButton("📹 240p", callback_data="dl|video|240")
            ],
            [
                InlineKeyboardButton("📹 360p", callback_data="dl|video|360"),
                InlineKeyboardButton("📹 480p", callback_data="dl|video|480")
            ],
            [
                InlineKeyboardButton("📹 576p", callback_data="dl|video|576"),
                InlineKeyboardButton("📹 720p", callback_data="dl|video|720")
            ],
            [
                InlineKeyboardButton("📹 1080p", callback_data="dl|video|1080")
            ]
        ])
        await message.reply_text("📥 JioHotstar link detected! Please select your required format:", reply_markup=keyboard)
    else:
        if not state:
            await message.reply_text("❌ Please send a valid JioHotstar link with `-n custom_name` or use `/settings`.")

# Download process callback handler
@app.on_callback_query(filters.regex("^dl\|"))
async def download_media(client, callback_query: CallbackQuery):
    data_parts = callback_query.data.split("|")
    media_type = data_parts[1] 
    quality = data_parts[2]
    
    user_id = callback_query.from_user.id
    user_data = USER_URLS.get(user_id)

    if not user_data:
        await callback_query.message.edit_text("❌ Link expired. Please send the link again.")
        return

    url = user_data["url"]
    custom_name = user_data["custom_name"]

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
            'progress_hooks': [get_progress_hook(client, status_msg, "Downloading Audio")],
        }
    else:
        status_msg = await callback_query.message.edit_text(f"📥 Downloading {quality}p video... Please wait...")
        ydl_opts = {
            'format': f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best',
            'outtmpl': 'downloads/%(title)s.%(ext)s',
            'progress_hooks': [get_progress_hook(client, status_msg, f"Downloading {quality}p Video")],
        }

    if os.path.exists("cookies.txt"):
        ydl_opts['cookiefile'] = "cookies.txt"

    thumb_path = None
    try:
        os.makedirs("downloads", exist_ok=True)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            if media_type == "audio":
                filename = os.path.splitext(filename)[0] + ".mp3"

        dir_name, orig_filename = os.path.split(filename)
        name_part, ext = os.path.splitext(orig_filename)
        
        if custom_name:
            new_filename = os.path.join(dir_name, f"{custom_name}{ext}")
            os.rename(filename, new_filename)
            filename = new_filename

        await status_msg.edit_text("📤 Uploading to Telegram...")

        if media_type == "audio":
            await client.send_audio(
                chat_id=callback_query.message.chat.id,
                audio=filename,
                caption="🎵 Here is your JioHotstar MP3 Audio!"
            )
        else:
            file_name = os.path.basename(filename)
            duration = get_video_duration(filename)
            
            if user_id in USER_THUMBNAILS and os.path.exists(USER_THUMBNAILS[user_id]):
                thumb_path = USER_THUMBNAILS[user_id]
            else:
                thumb_path = generate_thumbnail(filename)

            await client.send_video(
                chat_id=callback_query.message.chat.id,
                video=filename,
                file_name=file_name,
                duration=duration,
                thumb=thumb_path,
                caption=f"📹 Here is your JioHotstar Video ({quality}p)!"
            )

        await status_msg.delete()
        
        if os.path.exists(filename):
            os.remove(filename)
        if thumb_path and thumb_path.startswith("downloads/") and os.path.exists(thumb_path):
            os.remove(thumb_path)

    except Exception as e:
        await status_msg.edit_text(f"❌ Download failed: {str(e)}")
        if thumb_path and thumb_path.startswith("downloads/") and os.path.exists(thumb_path):
            os.remove(thumb_path)

if __name__ == "__main__":
    print("Bot is running...")
    app.run()
