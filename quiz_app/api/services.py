import os
import shutil
from pathlib import Path

from django.conf import settings
from yt_dlp import YoutubeDL


class AudioDownloadError(Exception):
    pass


def _resolve_ffmpeg_location():
    configured = os.getenv("FFMPEG_LOCATION", "C:/ffmpeg")
    candidates = [
        Path(configured),
        Path(configured) / "bin",
    ]

    ffmpeg_from_path = shutil.which("ffmpeg")
    if ffmpeg_from_path:
        candidates.append(Path(ffmpeg_from_path).parent)

    for candidate in candidates:
        if not candidate:
            continue
        ffmpeg_exe = candidate / "ffmpeg.exe"
        ffprobe_exe = candidate / "ffprobe.exe"
        if ffmpeg_exe.exists() and ffprobe_exe.exists():
            return str(candidate)

    return None


def download_youtube_audio(video_url):
    media_root = Path(settings.BASE_DIR) / "media"
    download_dir = media_root / "quiz_audio"
    download_dir.mkdir(parents=True, exist_ok=True)
    tmp_filename = str(download_dir / "%(id)s.%(ext)s")
    ffmpeg_location = _resolve_ffmpeg_location()

    if not ffmpeg_location:
        raise AudioDownloadError(
            "FFmpeg/FFprobe not found. Set FFMPEG_LOCATION to the folder containing ffmpeg.exe and ffprobe.exe (e.g. C:/ffmpeg/bin)."
        )

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
