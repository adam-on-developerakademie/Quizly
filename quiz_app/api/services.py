import os
import shutil
from pathlib import Path

from django.conf import settings
from yt_dlp import YoutubeDL


class AudioDownloadError(Exception):
    pass


def _resolve_ffmpeg_location():
    # If explicitly configured, validate and return a usable ffmpeg location.
    # If not configured, return None so yt_dlp can auto-detect from PATH.
    configured = os.getenv("FFMPEG_LOCATION")
    if not configured:
        return None

    configured_path = Path(configured)
    candidates = [configured_path, configured_path / "bin"]

    for candidate in candidates:
        if not candidate.exists():
            continue

        if candidate.is_file():
            return str(candidate)

        ffmpeg_binary = shutil.which("ffmpeg", path=str(candidate))
        ffprobe_binary = shutil.which("ffprobe", path=str(candidate))
        if ffmpeg_binary and ffprobe_binary:
            return str(candidate)

    return None


def download_youtube_audio(video_url):
    media_root = Path(settings.BASE_DIR) / "media"
    download_dir = media_root / "quiz_audio"
    download_dir.mkdir(parents=True, exist_ok=True)
    tmp_filename = str(download_dir / "%(id)s.%(ext)s")
    ffmpeg_location = _resolve_ffmpeg_location()

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": tmp_filename,
        "quiet": True,
        "noplaylist": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        "overwrites": True,
    }

    if ffmpeg_location:
        ydl_opts["ffmpeg_location"] = ffmpeg_location

    try:
        # First pass: get metadata and proactively remove stale files for same video id.
        with YoutubeDL({**ydl_opts, "skip_download": True}) as ydl:
            meta = ydl.extract_info(video_url, download=False)
            video_id = meta.get("id", "")

        if video_id:
            for existing_file in download_dir.glob(f"{video_id}*"):
                if existing_file.is_file():
                    existing_file.unlink(missing_ok=True)

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            final_filepath = None
            requested_downloads = info.get("requested_downloads") or []
            if requested_downloads and isinstance(requested_downloads[0], dict):
                final_filepath = requested_downloads[0].get("filepath")

            if not final_filepath:
                final_filepath = info.get("filepath")

            if not final_filepath:
                prepared = Path(ydl.prepare_filename(info))
                final_filepath = str(prepared.with_suffix(".mp3"))

            downloaded_path = Path(final_filepath)

            if not downloaded_path.exists():
                fallback_match = sorted(download_dir.glob(f"{info.get('id', '')}*.mp3"))
                if fallback_match:
                    downloaded_path = fallback_match[0]
    except Exception as exc:
        exc_message = str(exc)
        if "ffprobe and ffmpeg not found" in exc_message.lower() or "postprocessing: ffprobe and ffmpeg not found" in exc_message.lower():
            raise AudioDownloadError(
                "FFmpeg/FFprobe wurden nicht gefunden. Installiere ffmpeg und stelle sicher, dass ffmpeg und ffprobe im PATH sind oder setze FFMPEG_LOCATION."
            ) from exc
        raise AudioDownloadError(f"Could not download YouTube audio: {exc}") from exc

    return {
        "video_id": info.get("id", ""),
        "title": info.get("title") or "Quiz from YouTube Video",
        "description": info.get("description") or "",
        "channel": info.get("uploader") or info.get("channel") or "",
        "duration_seconds": info.get("duration"),
        "webpage_url": info.get("webpage_url") or video_url,
        "audio_file_name": f"quiz_audio/{downloaded_path.name}",
        "audio_filename": downloaded_path.name,
        "audio_filesize_bytes": downloaded_path.stat().st_size if downloaded_path.exists() else None,
    }


def delete_downloaded_audio(audio_file_name):
    if not audio_file_name:
        return

    audio_path = Path(settings.BASE_DIR) / "media" / audio_file_name
    if audio_path.exists() and audio_path.is_file():
        audio_path.unlink(missing_ok=True)
