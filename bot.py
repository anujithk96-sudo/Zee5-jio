import asyncio
import html
import logging
import os
import re
import subprocess
import time
import uuid
from datetime import datetime
from urllib.parse import urlparse

import yt_dlp
from dotenv import load_dotenv
from hachoir.metadata import extractMetadata
from hachoir.parser import createParser
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_IDS = (
    set(map(int, os.getenv("ALLOWED_USER_IDS", "").split(",")))
    if os.getenv("ALLOWED_USER_IDS")
    else set()
)

USER_URLS = {}
USER_THUMBNAILS = {}
USER_STATES = {}
USER_AVAILABLE_QUALITIES = {}
active_downloads = {}
CANCEL_REQUESTS = set()

PLATFORMS = {
    "global": ["netflix", "prime", "disney", "hbomax", "hulu", "apple", "peacock", "paramount"],
    "indian": ["jiocinema", "hotstar", "sonyliv", "zee5", "altbalaji", "erosnow", "manoramamax", "hoichoi"],
    "regional": ["aha", "mxplayer", "voot", "shemaroo", "sun_nxt", "yupp_tv", "stage"],
}
ALL_PLATFORMS = [p for group in PLATFORMS.values() for p in group]
QUALITIES = ["4K", "1080p", "720p", "480p"]

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


def clean_ansi(text_val) -> str:
    return ANSI_ESCAPE_RE.sub("", str(text_val or "")).strip()


def is_allowed(user_id: int) -> bool:
    return not ALLOWED_IDS or user_id in ALLOWED_IDS


def sanitize_filename(name_str: str) -> str:
    cleaned = re.sub(r'[\\/*?:"<>|]+', "_", str(name_str or "")).strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned[:120] or "OTT_Video"


def extract_serial_name_from_url(url: str) -> str:
    try:
        path = urlparse(url).path or ""
        parts = [p for p in path.split("/") if p]
        for idx, part in enumerate(parts):
            if part.lower() in ("shows", "tv-shows", "series", "details") and idx + 1 < len(parts):
                candidate = parts[idx + 1]
                if not re.fullmatch(r"[\d\-]+", candidate):
                    words = [w.capitalize() for w in re.split(r"[-_]+", candidate) if w and not w.isdigit()]
                    if words:
                        return "_".join(words)
        for part in reversed(parts):
            if len(part) > 4 and "-" in part and not re.fullmatch(r"[0-9a-zA-Z\-]{1,12}", part):
                words = [w.capitalize() for w in re.split(r"[-_]+", part) if w and not w.isdigit()]
                if words:
                    return "_".join(words)
    except Exception:
        pass
    return "OTT_Serial"


def build_auto_filename(info: dict, url: str, season: int, episode: int, quality: str, audio: str, ext: str, custom_name: str = None) -> str:
    ext = ext if ext.startswith(".") else f".{ext or 'mp4'}"
    ep_tag = f"S{int(season):02d}E{int(episode):02d}" if season and episode else ""

    if custom_name:
        base = sanitize_filename(custom_name)
        if ep_tag and ep_tag.lower() not in base.lower():
            return f"{base}_{ep_tag}_{quality}p_{audio.upper()}{ext}"
        return f"{base}_{quality}p_{audio.upper()}{ext}"

    raw_series = (
        info.get("series")
        or info.get("show")
        or info.get("playlist_title")
        or info.get("title")
        or extract_serial_name_from_url(url)
    )
    series_clean = sanitize_filename(raw_series)
    if ep_tag:
        return f"{series_clean}_{ep_tag}_{quality}p_{audio.upper()}{ext}"
    return f"{series_clean}_{quality}p_{audio.upper()}{ext}"


def parse_batch_spec(text: str):
    """
    Supports formats at end of message:
      /1-1      -> season 1, episodes [1]
      /1-1-5    -> season 1, episodes [1, 2, 3, 4, 5]
    Returns (season, episodes_list) or (None, [None]) for single link.
    """
    match = re.search(r"(?:^|\s)/(\d+)-(\d+)(?:-(\d+))?\s*$", text)
    if not match:
        return None, [None]
    season = int(match.group(1))
    start_ep = int(match.group(2))
    end_ep = int(match.group(3)) if match.group(3) else start_ep
    if end_ep < start_ep:
        start_ep, end_ep = end_ep, start_ep
    episodes = list(range(start_ep, end_ep + 1))
    return season, episodes


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
                    [
                        "ffmpeg",
                        "-y",
                        "-i",
                        thumb_path,
                        "-vf",
                        "scale=320:320:force_original_aspect_ratio=decrease",
                        "-q:v",
                        "5",
                        converted_thumb,
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                if os.path.exists(thumb_path):
                    os.remove(thumb_path)
                if result.returncode == 0 and os.path.exists(converted_thumb):
                    return converted_thumb
                elif os.path.exists(thumb_path):
                    return thumb_path
    except Exception as e:
        logger.error(f"Error downloading thumbnail: {e}")
    return None


def generate_thumbnail(video_path, user_id):
    os.makedirs("thumbnails", exist_ok=True)
    thumb_path = f"thumbnails/auto_{user_id}.jpg"
    try:
        cmd = [
            "ffmpeg",
            "-ss",
            "00:00:05",
            "-i",
            video_path,
            "-vframes",
            "1",
            "-q:v",
            "2",
            thumb_path,
            "-y",
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
            return thumb_path
    except Exception as e:
        logger.error(f"Error generating thumbnail: {e}")
    return None


def get_progress_bar(percentage):
    try:
        pct = float(clean_ansi(percentage).replace("%", "").strip())
    except Exception:
        pct = 0.0
    completed = max(0, min(10, int(pct // 10)))
    remaining = 10 - completed
    return "█" * completed + "░" * remaining


def get_progress_hook(client, message, user_id, title="Downloading"):
    last_update_time = 0

    def progress_hook(d):
        nonlocal last_update_time
        if user_id in CANCEL_REQUESTS:
            raise Exception("Task cancelled by user.")
        if d.get("status") == "downloading":
            current_time = time.time()
            if current_time - last_update_time > 3:
                percentage = clean_ansi(d.get("_percent_str", "0%"))
                speed = clean_ansi(d.get("_speed_str", "N/A"))
                eta = clean_ansi(d.get("_eta_str", "N/A"))
                bar = get_progress_bar(percentage)
                cancel_keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✖️ Cancel Task", callback_data=f"cancel_dl_{user_id}")]
                ])
                try:
                    asyncio.run_coroutine_threadsafe(
                        message.edit_text(
                            f"📥 {title}...\n\n"
                            f"[{bar}] {percentage}\n"
                            f"🚀 Speed: {speed}\n"
                            f"⏱️ ETA: {eta}",
                            reply_markup=cancel_keyboard,
                        ),
                        client.loop,
                    )
                except Exception:
                    pass
                last_update_time = current_time

    return progress_hook


def build_quality_keyboard(quality_choices):
    quality_rows = []
    for i in range(0, len(quality_choices), 2):
        row = [
            InlineKeyboardButton(f"📹 {h}p", callback_data=f"dl|video|{h}")
            for h in quality_choices[i : i + 2]
        ]
        quality_rows.append(row)
    return InlineKeyboardMarkup(quality_rows)


app = Client(
    "jiohotstar_bot",
    api_id=int(API_ID) if API_ID and API_ID.isdigit() else 0,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)


@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    if not is_allowed(message.from_user.id):
        await message.reply_text("⛔ You are not authorised to use this bot.")
        return

    text = (
        "🎬 OTT Allu Downloader Bot\n\n"
        "Send supported OTT links to check available media via Telegram.\n"
        "Batch format example: <url> /1-1 or <url> /1-1-5 (Season-StartEp-EndEp)\n\n"
        "Quick commands:\n"
        "/rip <platform> <url> — Start a download\n"
        "/status — View active downloads\n"
        "/platforms — List all supported platforms\n"
        "/help — Full help"
    )
    await message.reply_text(text)


@app.on_message(filters.command("help") & filters.private)
async def help_cmd(client, message):
    if not is_allowed(message.from_user.id):
        return

    text = (
        "📖 Full Command Reference\n\n"
        "Download:\n"
        "/rip <platform> <url> [quality]\n"
        "  platform → hotstar, jiocinema, sun_nxt, netflix, etc.\n"
        "  quality → 4K, 1080p, 720p, 480p\n\n"
        "Batch format:\n"
        "  <url> /1-1 (Season 1, Episode 1)\n"
        "  <url> /1-1-5 (Season 1, Episodes 1 to 5)\n\n"
        "Other commands:\n"
        "/status — Active downloads\n"
        "/cancel <job_id> — Cancel a download\n"
        "/platforms — All supported platforms"
    )
    await message.reply_text(text)


@app.on_message(filters.command("platforms") & filters.private)
async def platforms_cmd(client, message):
    if not is_allowed(message.from_user.id):
        return

    text = (
        "📡 Supported Platforms\n\n"
        "🌍 Global\n"
        f"{' · '.join(PLATFORMS['global'])}\n\n"
        "🇮🇳 Indian\n"
        f"{' · '.join(PLATFORMS['indian'])}\n\n"
        "🗺️ Regional\n"
        f"{' · '.join(PLATFORMS['regional'])}"
    )
    await message.reply_text(text)


@app.on_message(filters.command("rip") & filters.private)
async def rip_cmd(client, message):
    if not is_allowed(message.from_user.id):
        await message.reply_text("⛔ Not authorised.")
        return

    args = message.command[1:]
    if len(args) < 2:
        await message.reply_text(
            "❌ Usage: /rip <platform> <url> [quality]\n\n"
            "Example: /rip hotstar https://... 1080p"
        )
        return

    platform = args[0].lower()
    url = args[1]
    quality = (
        args[2].upper()
        if len(args) > 2 and args[2].upper() in QUALITIES
        else "1080p"
    )

    if platform not in ALL_PLATFORMS:
        await message.reply_text(
            f"❌ Unknown platform {platform}.\nUse /platforms to see all supported ones."
        )
        return

    job_id = str(uuid.uuid4())[:8]
    started = datetime.now().strftime("%H:%M:%S")
    status_msg = await message.reply_text(
        f"⬇️ Download started!\n\n"
        f"🆔 Job ID: {job_id}\n"
        f"📡 Platform: {platform}\n"
        f"🎯 Quality: {quality}\n"
        f"🕐 Started: {started}"
    )
    asyncio.create_task(
        run_rip_download(job_id, platform, url, quality, status_msg, message.from_user.id)
    )


async def run_rip_download(job_id, platform, url, quality, status_msg, user_id):
    script = f"scripts/{_platform_folder(platform)}/{platform}.py"
    cmd = ["python", script, "--url", url, "--quality", quality]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        active_downloads[job_id] = {"process": proc}
        _, stderr = await proc.communicate()

        if user_id in CANCEL_REQUESTS:
            await status_msg.edit_text("❌ Task Cancelled successfully!")
            return

        if proc.returncode == 0:
            await status_msg.edit_text(
                f"✅ Download complete!\n🆔 Job {job_id} finished successfully."
            )
        else:
            err = stderr.decode(errors="ignore")[-300:] if stderr else "Unknown error"
            await status_msg.edit_text(
                f"❌ Download failed!\n🆔 Job {job_id}\n\nError:\n{err}"
            )
    except Exception as e:
        await status_msg.edit_text(f"💥 Unexpected error in job {job_id}:\n{str(e)}")
    finally:
        active_downloads.pop(job_id, None)


def _platform_folder(platform: str) -> str:
    if platform in PLATFORMS["global"]:
        return "global"
    if platform in PLATFORMS["indian"]:
        return "indian"
    if platform in PLATFORMS["regional"]:
        return "regional"
    return "global"


@app.on_message(filters.command("status") & filters.private)
async def status_cmd(client, message):
    if not is_allowed(message.from_user.id):
        return

    if not active_downloads:
        await message.reply_text("📭 No active downloads right now.")
        return

    lines = ["📊 Active Downloads Status\n"]
    for jid in list(active_downloads.keys())[-10:]:
        lines.append(f"⬇️ Job ID: {jid} — Running")
    await message.reply_text("\n".join(lines))


@app.on_message(filters.command("cancel") & filters.private)
async def cancel_cmd(client, message):
    if not is_allowed(message.from_user.id):
        return

    args = message.command[1:]
    if not args:
        await message.reply_text("Usage: /cancel <job_id>")
        return

    job_id = args[0]
    if job_id not in active_downloads:
        await message.reply_text(f"❌ Job {job_id} not found.")
        return

    info = active_downloads[job_id]
    if info.get("process"):
        info["process"].terminate()
    await message.reply_text(f"🚫 Job {job_id} cancelled.")


@app.on_callback_query(filters.regex(r"^cancel_dl_"))
async def cancel_task_callback(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    target_user_id = int(callback_query.data.split("_")[2])
    if user_id == target_user_id:
        CANCEL_REQUESTS.add(target_user_id)
        await callback_query.answer("⚠️ Task cancellation requested...", show_alert=True)
    else:
        await callback_query.answer(
            "❌ You are not authorized to cancel this task!", show_alert=True
        )


@app.on_callback_query(filters.regex(r"^back_to_quality$"))
async def back_to_quality_callback(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    quality_choices = USER_AVAILABLE_QUALITIES.get(user_id)
    if not quality_choices:
        await callback_query.answer(
            "Quality list expired. Please send the link again.", show_alert=True
        )
        return
    await callback_query.message.edit_reply_markup(
        build_quality_keyboard(quality_choices)
    )
    await callback_query.answer()


@app.on_message(
    filters.private
    & ~filters.command(["start", "help", "platforms", "rip", "status", "cancel"])
)
async def handle_user_inputs(client, message):
    user_id = message.from_user.id
    if not is_allowed(user_id):
        return

    text = message.text.strip() if message.text else ""
    url_match = re.search(r"https?://[^\s]+", text)
    extracted_url = url_match.group(0) if url_match else text

    if any(
        p in extracted_url.lower()
        for p in ["hotstar.com", "jiocinema.com", "jiohotstar.com", "sunnxt.com", "zee5.com"]
    ):
        season, episodes = parse_batch_spec(text)
        text_without_batch = re.sub(r"(?:^|\s)/\d+-\d+(?:-\d+)?\s*$", "", text).strip()
        parts = text_without_batch.split("-n", 1)
        url = url_match.group(0) if url_match else parts[0].strip()
        custom_name = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None

        USER_URLS[user_id] = {
            "url": url,
            "custom_name": custom_name,
            "season": season,
            "episodes": episodes,
        }

        status_msg = await message.reply_text(
            "⏳ Fetching video info & original thumbnail... Please wait!"
        )
        configured_cookie_file = os.getenv("COOKIE_FILE", "cookies.txt")
        cookie_file_path = (
            configured_cookie_file
            if os.path.isfile(configured_cookie_file)
            else None
        )

        try:
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "noplaylist": True,
                "nocheckcertificate": True,
                "socket_timeout": 10,
                "retries": 1,
                "extractor_retries": 1,
                "fragment_retries": 1,
            }
            if cookie_file_path:
                ydl_opts["cookiefile"] = cookie_file_path

            def extract_info_fast():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    return ydl.extract_info(url, download=False)

            info_task = asyncio.create_task(asyncio.to_thread(extract_info_fast))
            done, _ = await asyncio.wait({info_task}, timeout=5)
            if not done:
                await status_msg.edit_text(
                    "⏳ Video details are taking longer than 5 seconds. "
                    "Still checking available, downloadable qualities..."
                )

            info = await asyncio.wait_for(info_task, timeout=40)
            USER_URLS[user_id]["info"] = info

            auto_name = build_auto_filename(
                info=info,
                url=url,
                season=season or 1,
                episode=episodes[0] or 1,
                quality="720",
                audio="ALL",
                ext=".mp4",
                custom_name=custom_name,
            )
            title = html.escape(
                str(info.get("series") or info.get("title") or auto_name)
            )
            formats = info.get("formats") or []

            if info.get("has_drm") or (
                formats and all(f.get("has_drm") for f in formats)
            ):
                await status_msg.edit_text(
                    "🔒 This video is marked as DRM-protected. Quality buttons cannot be generated."
                )
                return

            heights_set = set()
            for f in formats:
                if f.get("has_drm") or not f.get("format_id"):
                    continue
                if f.get("height"):
                    heights_set.add(int(f.get("height")))
                elif f.get("resolution") and "x" in str(f.get("resolution")):
                    try:
                        h_val = int(str(f.get("resolution")).split("x")[-1])
                        heights_set.add(h_val)
                    except ValueError:
                        pass

            if info.get("height"):
                try:
                    heights_set.add(int(info["height"]))
                except (TypeError, ValueError):
                    pass

            quality_choices = sorted(heights_set, reverse=True)
            if not quality_choices:
                quality_choices = [1080, 720, 480, 360]

            USER_AVAILABLE_QUALITIES[user_id] = quality_choices
            thumbnail_url = info.get("thumbnail")
            if not thumbnail_url and "thumbnails" in info:
                thumbnails = info.get("thumbnails", [])
                if thumbnails:
                    thumbnail_url = thumbnails[-1].get("url")

            yt_thumb_path = None
            if thumbnail_url:
                yt_thumb_path = await asyncio.to_thread(
                    download_youtube_thumbnail, thumbnail_url, user_id
                )
            if yt_thumb_path:
                USER_THUMBNAILS[f"yt_{user_id}"] = yt_thumb_path

            batch_info_line = ""
            if season and episodes and episodes[0] is not None:
                if len(episodes) > 1:
                    batch_info_line = f"\n📦 Batch: <b>S{season:02d} E{episodes[0]:02d}–E{episodes[-1]:02d}</b> ({len(episodes)} episodes)"
                else:
                    batch_info_line = f"\n🎬 Episode: <b>S{season:02d} E{episodes[0]:02d}</b>"

            keyboard = build_quality_keyboard(quality_choices)
            caption_text = (
                f"🎬 <b>{title}</b>{batch_info_line}\n\n"
                f"👇 <b>Select your preferred quality:</b>"
            )

            if thumbnail_url:
                try:
                    await message.reply_photo(
                        photo=thumbnail_url,
                        caption=caption_text,
                        reply_markup=keyboard,
                        parse_mode=ParseMode.HTML,
                    )
                    await status_msg.delete()
                    return
                except Exception:
                    pass

            await status_msg.edit_text(
                caption_text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logging.exception("Info extraction error: %s", e)
            reason = (
                "Metadata lookup timed out."
                if isinstance(e, asyncio.TimeoutError)
                else str(e)
            )
            await status_msg.edit_text(
                f"❌ Could not fetch video info.\n\nReason: <code>{html.escape(reason[:500])}</code>",
                parse_mode=ParseMode.HTML,
            )
    else:
        await message.reply_text(
            "❌ Please send a valid OTT link or use /rip command."
        )


@app.on_callback_query(filters.regex(r"^dl\|video\|"))
async def select_audio_languages(client, callback_query: CallbackQuery):
    data_parts = callback_query.data.split("|")
    quality = data_parts[2]

    user_id = callback_query.from_user.id
    user_data = USER_URLS.get(user_id)
    if not user_data:
        await callback_query.message.edit_text(
            "❌ Link expired. Please send the link again."
        )
        return

    if int(quality) not in USER_AVAILABLE_QUALITIES.get(user_id, []):
        await callback_query.answer(
            "This quality is not available for this link.", show_alert=True
        )
        return

    detected_langs = ["mal", "tam", "hin", "eng", "tel", "kan"]
    audio_buttons = []
    for lang in detected_langs:
        lang_name = lang.upper()
        audio_buttons.append([
            InlineKeyboardButton(
                f"🔊 {lang_name} Audio", callback_data=f"dl_final|{quality}|{lang}"
            )
        ])
    audio_buttons.append([
        InlineKeyboardButton(
            "🌐 Download All Audio (Multi-Audio)",
            callback_data=f"dl_final|{quality}|all",
        )
    ])
    audio_buttons.append([
        InlineKeyboardButton("🔙 Back to Quality", callback_data="back_to_quality")
    ])

    await callback_query.message.edit_reply_markup(
        reply_markup=InlineKeyboardMarkup(audio_buttons)
    )
    await callback_query.answer("Select audio language(s):")


@app.on_callback_query(filters.regex(r"^dl_final\|"))
async def download_final_media(client, callback_query: CallbackQuery):
    data_parts = callback_query.data.split("|")
    quality = data_parts[1]
    selected_audio = data_parts[2]

    user_id = callback_query.from_user.id
    user_data = USER_URLS.get(user_id)
    if not user_data:
        await callback_query.message.edit_text(
            "❌ Link expired. Please send the link again."
        )
        return

    url = user_data["url"]
    custom_name = user_data.get("custom_name")
    season = user_data.get("season")
    episodes = user_data.get("episodes") or [None]
    info_meta = user_data.get("info") or {}

    try:
        await callback_query.message.delete()
    except Exception:
        pass

    cancel_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✖️ Cancel Task", callback_data=f"cancel_dl_{user_id}")]
    ])
    status_msg = await client.send_message(
        chat_id=callback_query.message.chat.id,
        text=f"⏳ Initializing download for {quality}p (Audio: {selected_audio.upper()})... Please wait.",
        reply_markup=cancel_keyboard,
    )

    if selected_audio == "all":
        format_str = (
            f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best"
        )
    else:
        format_str = (
            f"bestvideo[height<={quality}]+bestaudio[language={selected_audio}]"
            f"/best[height<={quality}]/best"
        )

    configured_cookie_file = os.getenv("COOKIE_FILE", "cookies.txt")
    cookie_file_path = (
        configured_cookie_file if os.path.isfile(configured_cookie_file) else None
    )

    total_items = len(episodes)
    os.makedirs("downloads", exist_ok=True)

    try:
        for idx, ep_num in enumerate(episodes, start=1):
            if user_id in CANCEL_REQUESTS:
                raise Exception("Task cancelled by user.")

            batch_prefix = f"[{idx}/{total_items}] " if total_items > 1 else ""
            item_token = uuid.uuid4().hex[:8]
            temp_template = f"downloads/tmp_{user_id}_{item_token}.%(ext)s"

            ydl_opts = {
                "format": format_str,
                "outtmpl": temp_template,
                "noplaylist": True,
                "progress_hooks": [
                    get_progress_hook(
                        client,
                        status_msg,
                        user_id,
                        f"{batch_prefix}Downloading {quality}p Video",
                    )
                ],
            }
            if cookie_file_path:
                ydl_opts["cookiefile"] = cookie_file_path

            # If season/episode batch is specified, pass playlist_items if supported by extractor
            if ep_num is not None:
                ydl_opts["playlist_items"] = str(ep_num)

            filename = None
            thumb_path = None
            try:
                def run_download():
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        if user_id in CANCEL_REQUESTS:
                            raise Exception("Task cancelled by user.")
                        info = ydl.extract_info(url, download=True)
                        requested = info.get("requested_downloads") or []
                        if requested:
                            for item in requested:
                                candidate = item.get("filepath") or item.get("_filename")
                                if candidate and os.path.exists(candidate):
                                    return candidate, info
                        candidate = info.get("_filename") or ydl.prepare_filename(info)
                        if os.path.exists(candidate):
                            return candidate, info
                        stem = os.path.splitext(candidate)[0]
                        for ext in (".mp4", ".mkv", ".webm", ".mov"):
                            if os.path.exists(stem + ext):
                                return stem + ext, info
                        return candidate, info

                filename, dl_info = await asyncio.to_thread(run_download)
                if user_id in CANCEL_REQUESTS:
                    raise Exception("Task cancelled by user.")

                if filename and os.path.exists(filename):
                    dir_name, orig_filename = os.path.split(filename)
                    _, ext = os.path.splitext(orig_filename)
                    final_name = build_auto_filename(
                        info=dl_info or info_meta,
                        url=url,
                        season=season or 1,
                        episode=ep_num or 1,
                        quality=quality,
                        audio=selected_audio,
                        ext=ext,
                        custom_name=custom_name,
                    )
                    new_filename = os.path.join(dir_name, final_name)
                    if os.path.exists(new_filename):
                        os.remove(new_filename)
                    os.rename(filename, new_filename)
                    filename = new_filename

                    await status_msg.edit_text(
                        f"📤 {batch_prefix}Uploading to Telegram...",
                        reply_markup=cancel_keyboard,
                    )

                    if user_id in USER_THUMBNAILS and os.path.exists(USER_THUMBNAILS[user_id]):
                        thumb_path = USER_THUMBNAILS[user_id]
                    elif f"yt_{user_id}" in USER_THUMBNAILS and os.path.exists(
                        USER_THUMBNAILS[f"yt_{user_id}"]
                    ):
                        thumb_path = USER_THUMBNAILS[f"yt_{user_id}"]

                    if not thumb_path or not os.path.exists(thumb_path):
                        thumb_path = generate_thumbnail(filename, user_id)

                    file_name = os.path.basename(filename)
                    duration = get_video_duration(filename)
                    await client.send_video(
                        chat_id=callback_query.message.chat.id,
                        video=filename,
                        file_name=file_name,
                        duration=duration,
                        thumb=thumb_path,
                        caption=(
                            f"📹 {batch_prefix}<code>{html.escape(file_name)}</code>\n"
                            f"🎯 Quality: {quality}p | 🔊 Audio: {selected_audio.upper()}"
                        ),
                        parse_mode=ParseMode.HTML,
                    )
            finally:
                if filename and os.path.exists(filename):
                    try:
                        os.remove(filename)
                    except Exception:
                        pass
                if (
                    thumb_path
                    and "thumbnails/auto_" in thumb_path
                    and os.path.exists(thumb_path)
                ):
                    try:
                        os.remove(thumb_path)
                    except Exception:
                        pass

        if f"yt_{user_id}" in USER_THUMBNAILS:
            try:
                os.remove(USER_THUMBNAILS[f"yt_{user_id}"])
                del USER_THUMBNAILS[f"yt_{user_id}"]
            except Exception:
                pass
        await status_msg.delete()
    except Exception as e:
        if user_id in CANCEL_REQUESTS or "cancelled" in str(e).lower():
            await status_msg.edit_text("❌ Task Cancelled successfully!")
        else:
            await status_msg.edit_text(f"❌ Download failed: {str(e)}")
    finally:
        CANCEL_REQUESTS.discard(user_id)


if __name__ == "__main__":
    print("🤖 OTT Bot is running... Press Ctrl+C to stop.")
    app.run()
