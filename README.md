# Quizly Backend Setup Guide (Windows, VS Code)

This guide explains how to set up everything required for the current backend features:

- Django + DRF API
- Cookie-based JWT authentication
- Quiz creation from YouTube links
- Audio download and MP3 conversion via yt-dlp + FFmpeg
- Media file serving in local development

## 1. Prerequisites

Install these tools first:

1. Python 3.11+ (3.14 also works in this project)
2. Git
3. FFmpeg (already available for you at `C:/ffmpeg`)
4. VS Code

## 2. Recommended VS Code Extensions (Plugins)

Install these extensions in VS Code:

1. `ms-python.python` (Python)
2. `ms-python.vscode-pylance` (Pylance)
3. `batisteo.vscode-django` (Django support)
4. `humao.rest-client` (optional, API testing from editor)
5. `eamodio.gitlens` (optional, Git productivity)

Optional but useful VS Code setting:

- Enable `python.terminal.useEnvFile` so terminal sessions can read variables from `.env` automatically.

## 3. Open Project

From a terminal:

```powershell
cd C:\backend\projekte\Quizly\BACKEND\Quizly
code .
```

## 4. Create and Activate .venv

If `.venv` does not exist yet:

```powershell
python -m venv .venv
```

Activate:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks scripts:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## 5. Install Python Dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If `yt-dlp` is missing, install explicitly:

```powershell
pip install yt-dlp
```

## 6. Configure .env

Create `.env` in the project root (same folder as `manage.py`).

Use this baseline:

```dotenv
SECRET_KEY=replace-with-your-secret
DEBUG=False
JWT_COOKIE_SECURE=False
ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_ENGINE=django.db.backends.sqlite3
DATABASE_NAME=db.sqlite3
LANGUAGE_CODE=en-us
TIME_ZONE=UTC
STATIC_URL=static/
MEDIA_URL=/media/
MEDIA_ROOT=media
SERVE_MEDIA=True
CSRF_TRUSTED_ORIGINS=http://127.0.0.1:5500,http://localhost:5500
CORS_ALLOWED_ORIGINS=http://127.0.0.1:5500,http://localhost:5500
CORS_ALLOW_CREDENTIALS=True
FFMPEG_LOCATION=C:/ffmpeg
```

Important notes:

1. `FFMPEG_LOCATION` should point to FFmpeg root or bin folder.
2. This backend resolves both `C:/ffmpeg` and `C:/ffmpeg/bin` automatically.
3. After changing `.env`, restart the Django server.

## 7. Database Setup

Run migrations:

```powershell
python manage.py migrate
```

(Optional) Create admin user:

```powershell
python manage.py createsuperuser
```

## 8. Run the Server

```powershell
python manage.py runserver
```

API base URL:

- `http://127.0.0.1:8000/api/`

## 9. Current Main Endpoints

1. `POST /api/register/`
2. `POST /api/login/`
3. `POST /api/token/refresh/`
4. `GET /api/hello/`
5. `POST /api/logout/`
6. `POST /api/quizzes/`

## 10. How /api/quizzes/ Works

Request (authenticated):

```json
{
  "url": "https://www.youtube.com/watch?v=OS_SlyzL4eo"
}
```

Supported YouTube formats include:

1. `youtube.com/watch?v=...`
2. `youtube.com/shorts/...`
3. `youtube.com/embed/...`
4. `youtu.be/...`

The backend normalizes them to canonical watch format internally.

On success it:

1. Downloads best audio with yt-dlp
2. Converts to MP3 using FFmpeg
3. Stores file under `media/quiz_audio/`
4. Saves file mapping and YouTube metadata in DB
5. Returns the quiz payload with generated question list

## 11. Postman Requirements

For authenticated endpoints (`/api/hello/`, `/api/logout/`, `/api/quizzes/`):

1. Login first via `POST /api/login/`
2. Reuse same cookie jar/session
3. Set body type to JSON (not text)
4. Use `Content-Type: application/json`

If you send `text/plain`, DRF returns:

- `415 Unsupported Media Type`

## 12. FFmpeg / yt-dlp Troubleshooting

If quiz creation fails with an FFmpeg message:

1. Verify files exist:
   - `C:/ffmpeg/bin/ffmpeg.exe`
   - `C:/ffmpeg/bin/ffprobe.exe`
2. Set `.env` value:
   - `FFMPEG_LOCATION=C:/ffmpeg/bin`
3. Restart server

Quick runtime check:

```powershell
python manage.py shell -c "from quiz_app.api.services import _resolve_ffmpeg_location; print(_resolve_ffmpeg_location())"
```

Expected output should be a valid folder path.

## 13. Run Tests

Auth tests:

```powershell
python manage.py test auth_app
```

Quiz tests:

```powershell
python manage.py test quiz_app
```

All current tests:

```powershell
python manage.py test quiz_app auth_app
```

## 14. Git Hygiene for Downloaded Media

Downloaded audio files should not be committed.

Make sure `.gitignore` includes:

```gitignore
media/
quiz_cookies.txt
```

If media files were already tracked, remove from git index (keep local files):

```powershell
git rm -r --cached media
```

## 15. Common Restart Rule

Restart backend whenever you change:

1. `.env`
2. Installed packages
3. Django settings

This avoids stale config/runtime behavior.
