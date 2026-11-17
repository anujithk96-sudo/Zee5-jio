
import logging
import os
import time
import asyncio
import yt_dlp

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

USER_URLS = {}

os.makedirs("downloads", exist_ok=True)

app = Client(
    "zee5_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)


def get_progress_hook(client, message, media_type):
    last_update = 0

    def progress_hook(d):
        nonlocal last_update

        if d["status"] == "downloading":
            now = time.time()

            if now - last_update >= 3:
                percentage = d.get("_percent_str", "0%").strip()
                speed = d.get("_speed_str", "N/A").strip()
                eta = d.get("_eta_str", "N/A").strip()

                text = (
                    f"📥 Downloading {media_type}...\n\n"
                    f"📊 Progress: {percentage}\n"
                    f"🚀 Speed: {speed}\n"
                    f"⏱ ETA: {eta}"
                )

                asyncio.run_coroutine_threadsafe(
                    message.edit_text(text),
                    client.loop
                )

                last_update = now

    return progress_hook


@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    await message.reply_text(
        "👋 Welcome to Zee5 Media Downloader!\n\n"
        "Send a supported media link to continue."
    )


@app.on_message(filters.text & filters.private & ~filters.command("start"))
async def get_link(client, message):
    url = message.text.strip()
    user_id = message.from_user.id

    if "zee5.com" not in url:
        await message.reply_text("❌ Please send a valid Zee5 link.")
        return

    USER_URLS[user_id] = url

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🎵 Download MP3",
                callback_data="dl|mp3"
            ),
            InlineKeyboardButton(
                "🎬 Download MP4",
                callback_data="dl|mp4"
            )
        ]
    ])

    await message.reply_text(
        "✅ Link detected!\n\nSelect your download format:",
        reply_markup=keyboard
    )


@app.on_callback_query(filters.regex(r"^dl\|(mp3|mp4)$"))
async def download_media(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    url = USER_URLS.get(user_id)

    if not url:
        await callback_query.answer("Link expired. Send again.", show_alert=True)
        return

    media_type = callback_query.data.split("|")[1]

    await callback_query.answer()

    status_msg = await callback_query.message.edit_text(
        f"⏳ Preparing {media_type.upper()} download..."
    )

    filename = None

    try:
        ydl_opts = {
            "outtmpl": "downloads/%(title)s.%(ext)s",
            "noplaylist": True,
            "nocheckcertificate": True,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [
                get_progress_hook(client, status_msg, media_type.upper())
            ],
        }

        if os.path.exists("cookies.txt"):
            ydl_opts["cookiefile"] = "cookies.txt"

        if media_type == "mp3":
            ydl_opts.update({
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            })
        else:
            ydl_opts.update({
                "format": "best[ext=mp4]/best",
            })

        def run_download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)

                if not info:
                    raise Exception("Media information unavailable.")

                path = ydl.prepare_filename(info)

                if media_type == "mp3":
                    path = os.path.splitext(path)[0] + ".mp3"

                return path, info

        filename, info = await asyncio.to_thread(run_download)

        if not os.path.exists(filename):
            raise Exception("Downloaded file not found.")

        await status_msg.edit_text("📤 Uploading to Telegram...")

        if media_type == "mp3":
            await client.send_audio(
                chat_id=callback_query.message.chat.id,
                audio=filename,
                title=info.get("title", "Audio"),
                caption="🎵 Zee5 MP3 Audio"
            )
        else:
            await client.send_video(
                chat_id=callback_query.message.chat.id,
                video=filename,
                caption="🎬 Zee5 MP4 Video",
                supports_streaming=True
            )

        await status_msg.delete()

    except Exception as e:
        logger.exception("Download failed")
        await status_msg.edit_text(
            f"❌ Download failed:\n{str(e)}"
        )

    finally:
        if filename and os.path.exists(filename):
            try:
                os.remove(filename)
            except OSError:
                pass


if __name__ == "__main__":
    print("Zee5 MP3 & MP4 Bot is running...")
    app.run()
