import os
from functools import lru_cache
from pathlib import Path
import subprocess
from uuid import uuid4

from django.conf import settings
import whisper

from .services import _resolve_ffmpeg_location


class TranscriptionError(Exception):
    pass


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
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        if clip_path.exists():
            clip_path.unlink(missing_ok=True)
        return audio_path, False

    return clip_path, True


@lru_cache(maxsize=2)
def _load_model(model_name):
    return whisper.load_model(model_name)


def transcribe_audio_file(audio_file_name, max_seconds=0):
    audio_path = Path(settings.BASE_DIR) / "media" / audio_file_name
    if not audio_path.exists():
        raise TranscriptionError(f"Audio file not found: {audio_file_name}")

    model_name = os.getenv("WHISPER_MODEL", "base")
    transcription_input_path, is_temporary = _build_audio_clip(audio_path, max_seconds)

    try:
        model = _load_model(model_name)
        result = model.transcribe(str(transcription_input_path), fp16=False)
    except Exception as exc:
        raise TranscriptionError(f"Could not transcribe audio: {exc}") from exc
    finally:
        if is_temporary and transcription_input_path.exists():
            transcription_input_path.unlink(missing_ok=True)

    segments = []
    for segment in result.get("segments", []):
        segments.append(
            {
                "id": segment.get("id"),
                "start": segment.get("start"),
                "end": segment.get("end"),
                "text": segment.get("text", "").strip(),
            }
        )

    return {
        "text": (result.get("text") or "").strip(),
        "language": result.get("language") or "",
        "segments": segments,
        "model": model_name,
    }
