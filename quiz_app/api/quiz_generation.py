import json
import os
import re


def _get_max_response_chars() -> int:
    raw = os.getenv("GOOGLE_GENAI_MAX_RESPONSE_CHARS", "60000").strip()
    try:
        value = int(raw)
    except Exception:
        return 60000
    if value <= 0:
        return 60000
    return value


def _build_fallback_quiz(topic_hint: str, description_hint: str, reason: str = "") -> dict:
    if reason == "no_credits":
        options = ["Retry later", "Add credits", "Use another key", "Disable AI mode"]
        questions = []
        for i in range(1, 11):
            questions.append(
                {
                    "question_title": f"AI generation unavailable (no credits) - item {i}.",
                    "question_options": options,
                    "answer": "Add credits",
                }
            )

        return {
            "title": "AI credits unavailable",
            "description": "No AI credits available. Add billing/quota to enable AI-based quiz generation.",
            "questions": questions,
        }

    topic = (topic_hint or "the video").strip()
    description = (description_hint or "Auto-generated quiz based on transcript.").strip()
    if len(description) > 150:
        description = description[:150].rstrip()

    questions = []
    for i in range(1, 11):
        options = [f"Option {i}A", f"Option {i}B", f"Option {i}C", f"Option {i}D"]
        questions.append(
            {
                "question_title": f"Question {i}: What key point appears in {topic}?",
                "question_options": options,
                "answer": options[0],
            }
        )

    return {
        "title": f"Quiz: {topic}"[:120].strip(),
        "description": description,
        "questions": questions,
    }


def _sanitize_quiz_payload(payload: object, topic_hint: str, description_hint: str) -> tuple[dict, bool]:
    fallback = _build_fallback_quiz(topic_hint, description_hint)

    if not isinstance(payload, dict):
        return fallback, True

    quiz_title = str(payload.get("title", "")).strip() or fallback["title"]
    description = str(payload.get("description", "")).strip() or fallback["description"]
    if len(description) > 150:
        description = description[:150].rstrip()

    raw_questions = payload.get("questions")
    if not isinstance(raw_questions, list):
        return fallback, True

    cleaned: list[dict] = []
    for item in raw_questions:
        if not isinstance(item, dict):
            continue

        question_title = str(item.get("question_title", "")).strip()
        options = item.get("question_options")
        answer = str(item.get("answer", "")).strip()

        if not question_title or not isinstance(options, list) or len(options) != 4:
            continue

        normalized_options = [str(opt).strip() for opt in options]
        if any(not opt for opt in normalized_options) or len(set(normalized_options)) != 4:
            continue

        # The declared answer must be one of the offered options.
        if answer not in normalized_options:
            continue

        cleaned.append(
            {
                "question_title": question_title,
                "question_options": normalized_options,
                "answer": answer,
            }
        )

    if len(cleaned) < 10:
        # We always need exactly 10 valid questions; return the safe fallback
        # if the model did not deliver enough usable items.
        return fallback, True

    return (
        {
            "title": quiz_title,
            "description": description,
            "questions": cleaned[:10],
        },
        False,
    )


def _strip_markdown_fences(text: str) -> str:
    # AI models often wrap JSON output in markdown code fences (```json … ```).
    # Extract the inner content when that pattern is present.
    stripped = (text or "").strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", stripped, flags=re.IGNORECASE | re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()
    return stripped


def _parse_model_json(text: str) -> object:
    cleaned = _strip_markdown_fences(text)
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    # Standard json.loads failed — scan the text character by character for
    # the first valid JSON object or array embedded in the response.
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(cleaned):
        if ch not in "{[":
            continue
        try:
            obj, _ = decoder.raw_decode(cleaned[idx:])
            return obj
        except Exception:
            continue

    raise ValueError("No valid JSON payload found in model response")


def _limit_model_response_text(text: str) -> str:
    max_chars = _get_max_response_chars()
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


def generate_quiz_from_transcript(transcript_text: str, topic_hint: str, description_hint: str) -> dict:
    api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    model_name = os.getenv("GOOGLE_GENAI_MODEL", "gemini-2.0-flash")
    fallback_model_name = os.getenv("GOOGLE_GENAI_FALLBACK_MODEL", "models/gemini-2.5-flash-lite").strip()
    fallback = _build_fallback_quiz(topic_hint, description_hint)

    def _is_quota_error(exc: Exception) -> bool:
        message = str(exc).upper()
        return "RESOURCE_EXHAUSTED" in message or "QUOTA EXCEEDED" in message or "NO CREDITS" in message

    def _is_model_not_found_error(exc: Exception) -> bool:
        message = str(exc).upper()
        return "NOT_FOUND" in message or "IS NOT FOUND" in message or "NOT SUPPORTED FOR GENERATECONTENT" in message

    def _with_meta(
        quiz_payload: dict,
        raw_text: str = "",
        raw_json: object = None,
        status: str = "",
        error_message: str = "",
        model_used: str = "",
    ) -> dict:
        payload = dict(quiz_payload)
        payload["raw_response_text"] = raw_text
        payload["raw_response_json"] = raw_json if isinstance(raw_json, (dict, list)) else {}
        payload["ai_model"] = model_used or model_name
        payload["ai_status"] = status
        payload["ai_error_message"] = error_message
        return payload

    if not api_key or not transcript_text.strip():
        return _with_meta(
            fallback,
            status="missing_input",
            error_message="Missing API key or transcript text.",
        )

    try:
        from google import genai
    except Exception:
        return _with_meta(
            fallback,
            status="sdk_error",
            error_message="google-genai SDK import failed.",
        )

    # Limit transcript length to stay within the model's context window and
    # reduce token cost; 12 000 characters cover roughly 15 minutes of speech.
    truncated_transcript = transcript_text[:12000]
    prompt = (
        "Based on the following transcript, generate a quiz in valid JSON format.\n\n"
        "The quiz must follow this exact structure:\n\n"
        "{\n"
        '  "title": "Create a concise quiz title based on the topic of the transcript.",\n'
        '  "description": "Summarize the transcript in no more than 150 characters. Do not include any quiz questions or answers.",\n'
        '  "questions": [\n'
        "    {\n"
        '      "question_title": "The question goes here.",\n'
        '      "question_options": ["Option A", "Option B", "Option C", "Option D"],\n'
        '      "answer": "The correct answer from the above options"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Requirements:\n"
        "- Each question must have exactly 4 distinct answer options.\n"
        "- Only one correct answer is allowed per question, and it must be present in 'question_options'.\n"
        "- The output must be valid JSON and parsable as-is (e.g., using Python's json.loads).\n"
        "- Do not include explanations, comments, or any text outside the JSON.\n"
        "- Return exactly 10 questions.\n\n"
        f"Transcript:\n{truncated_transcript}"
    )

    try:
        client = genai.Client(api_key=api_key)
        # Try the primary model first; if it is unavailable (NOT_FOUND), advance
        # to the fallback model. Any other error (quota, network …) is re-raised.
        models_to_try = [model_name]
        if fallback_model_name and fallback_model_name not in models_to_try:
            models_to_try.append(fallback_model_name)

        response = None
        model_used = model_name
        last_model_error: Exception | None = None
        used_model_fallback = False

        for candidate_model in models_to_try:
            try:
                response = client.models.generate_content(model=candidate_model, contents=prompt)
                model_used = candidate_model
                used_model_fallback = candidate_model != model_name
                break
            except Exception as exc:
                last_model_error = exc
                if _is_model_not_found_error(exc):
                    continue
                raise

        if response is None:
            raise last_model_error or RuntimeError("No model produced a response")

        raw_text = response.text or ""
        limited_text = _limit_model_response_text(raw_text)
        parsed = _parse_model_json(limited_text)
        sanitized, used_fallback = _sanitize_quiz_payload(parsed, topic_hint, description_hint)
        if used_fallback:
            return _with_meta(
                sanitized,
                raw_text=raw_text,
                raw_json=parsed,
                status="invalid_payload",
                error_message="AI response did not match required quiz JSON schema.",
                model_used=model_used,
            )
        status = "ok_with_model_fallback" if used_model_fallback else "ok"
        error_message = "Configured model was unavailable. Fallback model was used." if used_model_fallback else ""
        return _with_meta(
            sanitized,
            raw_text=raw_text,
            raw_json=parsed,
            status=status,
            error_message=error_message,
            model_used=model_used,
        )
    except Exception as exc:
        if _is_quota_error(exc):
            return _with_meta(
                _build_fallback_quiz(topic_hint, description_hint, reason="no_credits"),
                status="no_credits",
                error_message=str(exc),
            )
        return _with_meta(
            fallback,
            status="request_error",
            error_message=str(exc),
        )
