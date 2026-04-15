"""Services for downloading audio and transcribing it with Whisper."""

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
    """Raised when YouTube audio download or conversion fails."""

    pass


class TranscriptionError(Exception):
    """Raised when audio transcription cannot be completed."""

    pass


def _resolve_ffmpeg_location():
    """Return a usable ffmpeg location or None when auto-detection should be used.

    If the FFMPEG_LOCATION environment variable is set, the configured path
    is validated by searching for both ffmpeg and ffprobe binaries before
    returning it. If the variable is unset, or no valid binaries are found,
    None is returned so yt-dlp can auto-detect ffmpeg from PATH.
    """
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
    """Download and convert a YouTube video's audio track to MP3.

    A metadata-only first pass is performed to obtain the video ID so that
    any stale files from a previous download of the same video can be removed
    before the actual download begins.

    After downloading, the final MP3 path is resolved by inspecting the
    yt-dlp info dict in three locations in order of reliability:
    ``requested_downloads[0]["filepath"]``, ``info["filepath"]``, and
    finally by reconstructing the expected path from the download template.
    """
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
    """Delete a downloaded audio file from the media directory.

    Does nothing when ``audio_file_name`` is empty or None, or when the
    resolved path does not exist or is not a regular file.
    """
    if not audio_file_name:
        return

    audio_path = Path(settings.BASE_DIR) / "media" / audio_file_name
    if audio_path.exists() and audio_path.is_file():
        audio_path.unlink(missing_ok=True)


def _build_audio_clip(audio_path, max_seconds):
    """Create a temporary clipped audio file when a time limit is configured.

    A UUID-prefixed filename is used to avoid name collisions when multiple
    clips are created concurrently. The FFmpeg command is built with:

    - ``-y``: overwrite the output file without prompting
    - ``-t``: stop writing after ``max_seconds`` seconds
    - ``-vn``: drop any video stream present in the source file
    - ``-acodec copy``: copy audio without re-encoding (fast, lossless)

    When FFmpeg is unavailable or clipping fails, the original audio path is
    returned unchanged so the caller can still attempt full-file transcription.
    Returns a tuple of ``(path, is_temporary)``.
    """
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

    clip_name = f"clip_{uuid4().hex}_{audio_path.name}"
    clip_path = audio_path.parent / clip_name

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
        return audio_path, False

    return clip_path, True


@lru_cache(maxsize=2)
def _load_model(model_name):
    """Load and cache a Whisper model by name.

    At most two models are kept in memory at once, covering the configured
    model and one potential fallback or temporary switch without reloading
    on every request.
    """
    return whisper.load_model(model_name)


def transcribe_audio_file(audio_file_name, max_seconds=0):
    """Transcribe an audio file and return normalized transcript payload data.

    When ``max_seconds`` is positive, a temporary clipped file is created
    and transcribed instead of the full track; the clip is deleted once
    transcription finishes.

    ``fp16=False`` is always passed to Whisper because half-precision
    inference requires a GPU. On standard CPU hardware, fp32 must be used
    to avoid numerical errors.
    """
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
