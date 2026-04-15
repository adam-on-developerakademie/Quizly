import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from django.conf import settings
import whisper
from yt_dlp import YoutubeDL


class AudioDownloadError(Exception):
    pass


class TranscriptionError(Exception):
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
            # yt-dlp exposes the post-processed file path in different keys
            # depending on version; try each location in order of reliability.
            final_filepath = None
            requested_downloads = info.get("requested_downloads") or []
            if requested_downloads and isinstance(requested_downloads[0], dict):
                final_filepath = requested_downloads[0].get("filepath")

            if not final_filepath:
                final_filepath = info.get("filepath")

            if not final_filepath:
                # Last resort: reconstruct the expected path from the download template.
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


def _build_audio_clip(audio_path, max_seconds):
    if max_seconds <= 0:
        return audio_path, False

    ffmpeg_location = _resolve_ffmpeg_location()
    if not ffmpeg_location:
        return audio_path, False

    ffmpeg_exe = Path(ffmpeg_location) / "ffmpeg.exe"
    if not ffmpeg_exe.exists():
        ffmpeg_exe = Path(ffmpeg_location) / "ffmpeg"
        if not ffmpeg_exe.exists():
            return audio_path, False

    # Unique prefix avoids name collisions when multiple clips are created concurrently.
    clip_name = f"clip_{uuid4().hex}_{audio_path.name}"
    clip_path = audio_path.parent / clip_name

    # -y: overwrite output without prompting;
    # -t: stop writing after max_seconds;
    # -vn: drop any video stream;
    # -acodec copy: copy the audio stream without re-encoding (fast, lossless).
    command = [
        str(ffmpeg_exe),
        "-y",
        "-i",
        str(audio_path),
        "-t",
        str(max_seconds),
        "-vn",
        "-acodec",
        "copy",
        str(clip_path),
    ]

    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        if clip_path.exists():
            clip_path.unlink(missing_ok=True)
        # Clipping failed — fall back to transcribing the full audio file.
        return audio_path, False

    return clip_path, True


# Cache up to two loaded models to avoid reloading on every request
# (the configured model plus one potential fallback / temporary switch).
@lru_cache(maxsize=2)
def _load_model(model_name):
    return whisper.load_model(model_name)


def transcribe_audio_file(audio_file_name, max_seconds=0):
    audio_path = Path(settings.BASE_DIR) / "media" / audio_file_name
    if not audio_path.exists():
        raise TranscriptionError(f"Audio file not found: {audio_file_name}")

    model_name = os.getenv("WHISPER_MODEL", "base")
    transcription_input_path, is_temporary = _build_audio_clip(
        audio_path,
        max_seconds,
    )

    try:
        model = _load_model(model_name)
        # fp16=False: half-precision inference requires a GPU.
        # CPU inference must use fp32 to avoid errors on most hardware.
        result = model.transcribe(str(transcription_input_path), fp16=False)
    except Exception as exc:
        raise TranscriptionError(
            f"Could not transcribe audio: {exc}"
        ) from exc
    finally:
        if is_temporary and transcription_input_path.exists():
            transcription_input_path.unlink(missing_ok=True)

    segments = [
        {
            "id": segment.get("id"),
            "start": segment.get("start"),
            "end": segment.get("end"),
            "text": segment.get("text", "").strip(),
        }
        for segment in result.get("segments", [])
    ]

    return {
        "text": (result.get("text") or "").strip(),
        "language": result.get("language") or "",
        "segments": segments,
        "model": model_name,
    }
