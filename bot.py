import logging
import os
import time
import asyncio
import yt_dlp
import shutil
import html
import subprocess
from hachoir.metadata import extractMetadata
from hachoir.parser import createParser
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# ലോഗിങ് സെറ്റ് ചെയ്യുക
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# എൻവയോൺമെന്റ് വേരിയബിളുകൾ
API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# വലിയ URL-കളും യൂസർ ഡാറ്റകളും സേവ് ചെയ്തു വെക്കാനുള്ള ഡിക്ഷണറികൾ
USER_URLS = {}
USER_THUMBNAILS = {}
USER_STATES = {}

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

# വീഡിയോയുടെ ഡ്യൂറേഷൻ (Duration) കണ്ടുപിടിക്കാൻ
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

# ഒറിജിനൽ തംബ്‌നെയിൽ ലിങ്കിൽ നിന്ന് ഡൗൺലോഡ് ചെയ്ത് ലോക്കൽ ഫയലാക്കാൻ
def download_youtube_thumbnail(thumbnail_url, user_id):
    os.makedirs("thumbnails", exist_ok=True)
    thumb_path = f"thumbnails/yt_{user_id}.jpg"
    try:
        import requests
        response = requests.get(thumbnail_url, timeout=10)
        if response.status_code == 200:
            with open(thumb_path, "wb") as f:
                f.write(response.content)
            if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
                converted_thumb = f"thumbnails/thumb_{user_id}.jpg"
                result = subprocess.run(
                    ["ffmpeg", "-y", "-i", thumb_path, "-vf",
                     "scale=320:320:force_original_aspect_ratio=decrease",
                     "-q:v", "5", converted_thumb],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                if os.path.exists(thumb_path):
                    os.remove(thumb_path)
                if result.returncode == 0 and os.path.exists(converted_thumb):
                    return converted_thumb
                elif os.path.exists(thumb_path):
                    return thumb_path
    except Exception as e:
        logger.error(f"Error downloading YouTube/Hotstar thumbnail: {e}")
    return None

# ഒറിജിനൽ തംബ്‌നെയിൽ കിട്ടിയില്ലെങ്കിൽ വീഡിയോയിൽ നിന്ന് 5-ാം സെക്കൻഡിൽ ഫോട്ടോ എടുക്കാൻ
def generate_thumbnail(video_path, user_id):
    os.makedirs("thumbnails", exist_ok=True)
    thumb_path = f"thumbnails/auto_{user_id}.jpg"
    try:
        cmd = [
            "ffmpeg", "-ss", "00:00:05", "-i", video_path,
            "-vframes", "1", "-q:v", "2", thumb_path, "-y"
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
            return thumb_path
    except Exception as e:
        logger.error(f"Error generating thumbnail: {e}")
    return None

# പ്രോഗ്രസ് ബാർ (ബ്ലാക്ക് ബോക്സ് രീതിയിൽ നിറയുന്നത്) ഉണ്ടാക്കാൻ
def get_progress_bar(percentage):
    try:
        pct = float(percentage.replace('%', '').strip())
    except:
        pct = 0.0
    completed = int(pct // 10)
    remaining = 10 - completed
    return "█" * completed + "░" * remaining

# ലൈവ് പ്രോഗ്രസ് ബാർ ഹുക്ക് (ഡൗൺലോഡ് & അപ്‌ലോഡ് സമയത്ത് കാണിക്കാൻ)
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

# യൂസർ സെറ്റിംഗ്സ് കീബോർഡ് (തംബ്‌നെയിൽ മാനേജ്‌മെന്റ് ഓപ്ഷനുകൾ)
def build_user_settings_keyboard(user_id):
    has_thumb = "Yes ✅" if user_id in USER_THUMBNAILS else "No ❌"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🖼️ Thumbnail Set: {has_thumb}", callback_data="set_thumb")],
        [InlineKeyboardButton("👀 View Thumbnail", callback_data="view_thumb")],
        [InlineKeyboardButton("🗑️ Remove Thumbnail", callback_data="remove_thumb")]
    ])

# /start കമാൻഡ്
@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    await message.reply_text(
        "👋 Hello! Welcome to JioHotstar Downloader Bot.\n\n"
        "Send any JioHotstar link with `-n custom_name` for renaming, and download as Audio or Video!",
        reply_markup=build_user_settings_keyboard(message.from_user.id)
    )

# /settings കമാൻഡ് (തംബ്‌നെയിൽ സെറ്റപ്പുകൾക്കായി)
@app.on_message(filters.command("settings") & filters.private)
async def settings_command(client, message):
    await message.reply_text(
        "⚙️ **User Settings**\n\nManage your custom thumbnail here:",
        reply_markup=build_user_settings_keyboard(message.from_user.id)
    )

# സെറ്റിംഗ്സ് ബട്ടൺ കോൾബാക്കുകൾ
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

# ഫോട്ടോയോ ലിങ്കോ ഇൻപുട്ട് എടുക്കുന്ന ഹാൻഡ്‌ലർ
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
    if "hotstar.com" in text or "jiocinema.com" in text or "jiohotstar.com" in text:
        parts = text.split("-n")
        url = parts[0].strip()
        custom_name = parts[1].strip() if len(parts) > 1 else None

        USER_URLS[user_id] = {"url": url, "custom_name": custom_name}
        
        status_msg = await message.reply_text(
            "⏳ **Fetching JioHotstar video info & original thumbnail... Please wait!**"
        )

        cookie_file_path = "cookies.txt" if os.path.exists("cookies.txt") else None

        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
                'noplaylist': True,
                'cookiefile': cookie_file_path,
                'nocheckcertificate': True
            }

            def extract_info_fast():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    return ydl.extract_info(url, download=False)

            info = await asyncio.to_thread(extract_info_fast)
            title = info.get('title', 'JioHotstar Video')
            thumbnail_url = info.get('thumbnail')
            if not thumbnail_url and 'thumbnails' in info:
                thumbnails = info.get('thumbnails', [])
                if thumbnails:
                    thumbnail_url = thumbnails[-1].get('url')

            # ഒറിജിനൽ തംബ്‌നെയിൽ മുൻകൂട്ടി ഡൗൺലോഡ് ചെയ്ത് സേവ് ചെയ്തു വെക്കുന്നു
            yt_thumb_path = None
            if thumbnail_url:
                yt_thumb_path = await asyncio.to_thread(download_youtube_thumbnail, thumbnail_url, user_id)
            if yt_thumb_path:
                USER_THUMBNAILS[f"yt_{user_id}"] = yt_thumb_path

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

            caption_text = (
                f"🎬 <b>{title}</b>\n\n"
                "👇 <b>Select your preferred quality:</b>"
            )

            if thumbnail_url:
                try:
                    await message.reply_photo(
                        photo=thumbnail_url,
                        caption=caption_text,
                        reply_markup=keyboard
                    )
                    await status_msg.delete()
                    return
                except Exception:
                    pass

            await status_msg.edit_text(
                caption_text,
                reply_markup=keyboard
            )

        except Exception as e:
            logging.exception("JioHotstar info extraction error: %s", e)
            await status_msg.edit_text(
                "❌ Could not fetch JioHotstar video info.\n\n"
                f"<b>Reason:</b> <code>{html.escape(str(e)[:500])}</code>",
                parse_mode="html",
            )
    else:
        if not state:
            await message.reply_text("❌ Please send a valid JioHotstar link with `-n custom_name` or use `/settings`.")

# ഡൗൺലോഡ് പ്രോസസ്സ് ഹാൻഡ്‌ലർ
@app.on_callback_query(filters.regex("^dl\|"))
async def download_media(client, callback_query: CallbackQuery):
    data_parts = callback_query.data.split("|")
    media_type = data_parts[1] # video അല്ലെങ്കിൽ audio
    quality = data_parts[2]
    
    user_id = callback_query.from_user.id
    user_data = USER_URLS.get(user_id)

    if not user_data:
        await callback_query.message.edit_text("❌ Link expired. Please send the link again.")
        return

    url = user_data["url"]
    custom_name = user_data["custom_name"]

    try:
        await callback_query.message.delete()
    except Exception:
        pass

    status_msg = await client.send_message(
        chat_id=callback_query.message.chat.id,
        text=f"⏳ Initializing download for `{quality}`... Please wait."
    )

    if media_type == "audio":
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
        ydl_opts = {
            'format': f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best',
            'outtmpl': 'downloads/%(title)s.%(ext)s',
            'progress_hooks': [get_progress_hook(client, status_msg, f"Downloading {quality}p Video")],
        }

    # cookies.txt ഫയൽ ഉണ്ടെങ്കിൽ ഉപയോഗിക്കുന്നു
    if os.path.exists("cookies.txt"):
        ydl_opts['cookiefile'] = "cookies.txt"

    thumb_path = None
    filename = None
    try:
        os.makedirs("downloads", exist_ok=True)
        def run_download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                fname = ydl.prepare_filename(info)
                if media_type == "audio":
                    fname = os.path.splitext(fname)[0] + ".mp3"
                return fname

        filename = await asyncio.to_thread(run_download)

        # -n വഴി നൽകിയ കസ്റ്റം പേര് അനുസരിച്ച് ഫയൽ റീനെയിം ചെയ്യൽ
        if filename and os.path.exists(filename):
            dir_name, orig_filename = os.path.split(filename)
            _, ext = os.path.splitext(orig_filename)
            
            if custom_name:
                new_filename = os.path.join(dir_name, f"{custom_name}{ext}")
                if os.path.exists(new_filename):
                    os.remove(new_filename)
                os.rename(filename, new_filename)
                filename = new_filename

        await status_msg.edit_text("📤 Uploading to Telegram...")

        # തംബ്‌നെയിൽ തെരഞ്ഞെടുക്കുന്ന ക്രമം:
        # 1. യൂസർ സെറ്റ് ചെയ്ത കസ്റ്റം തംബ്‌നെയിൽ
        if user_id in USER_THUMBNAILS and os.path.exists(USER_THUMBNAILS[user_id]):
            thumb_path = USER_THUMBNAILS[user_id]
        
        # 2. ലിങ്ക് ഫെച്ച് ചെയ്തപ്പോൾ കിട്ടിയ ഒറിജിനൽ തംബ്‌നെയിൽ
        elif f"yt_{user_id}" in USER_THUMBNAILS and os.path.exists(USER_THUMBNAILS[f"yt_{user_id}"]):
            thumb_path = USER_THUMBNAILS[f"yt_{user_id}"]
            
        # 3. ഇവയെല്ലാം ഇല്ലെങ്കിൽ ഡൗൺലോഡ് ചെയ്ത വീഡിയോയുടെ ഉള്ളിൽ നിന്ന് 5-ാം സെക്കൻഡിൽ ഓട്ടോ തംബ്‌നെയിൽ ജനറേറ്റ് ചെയ്യും
        if not thumb_path or not os.path.exists(thumb_path):
            thumb_path = generate_thumbnail(filename, user_id)

        if media_type == "audio":
            await client.send_audio(
                chat_id=callback_query.message.chat.id,
                audio=filename,
                thumb=thumb_path,
                caption="🎵 Here is your JioHotstar MP3 Audio!"
            )
        else:
            file_name = os.path.basename(filename)
            duration = get_video_duration(filename)

            await client.send_video(
                chat_id=callback_query.message.chat.id,
                video=filename,
                file_name=file_name,
                duration=duration,
                thumb=thumb_path,
                caption=f"📹 Here is your JioHotstar Video ({quality}p)!"
            )

        await status_msg.delete()
        
        # ഫയൽ ക്ലീനപ്പ്
        if filename and os.path.exists(filename):
            os.remove(filename)
        if thumb_path and "thumbnails/auto_" in thumb_path and os.path.exists(thumb_path):
            os.remove(thumb_path)
        if f"yt_{user_id}" in USER_THUMBNAILS:
            try:
                os.remove(USER_THUMBNAILS[f"yt_{user_id}"])
                del USER_THUMBNAILS[f"yt_{user_id}"]
            except:
                pass

    except Exception as e:
        await status_msg.edit_text(f"❌ Download failed: {str(e)}")
        if filename and os.path.exists(filename):
            os.remove(filename)

if __name__ == "__main__":
    print("Bot is running...")
    app.run()
