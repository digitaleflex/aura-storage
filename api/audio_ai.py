"""Audio analysis + AI classification for the P1 bac à sable.

Pipeline per object:
1) Technical quality via ffprobe (deterministic).
2) Gemini (primary) analyzes a short audio sample + metadata and returns JSON.
3) Claude fallback (secondary) classifies from metadata when Gemini fails.

No automatic move/publish is performed; callers persist suggestions only.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .config import settings

log = logging.getLogger("uvicorn.error")

CATEGORIES = [
    "meditation", "developpement_personnel", "formation", "business",
    "podcast", "litterature", "spiritualite", "musique", "autre",
]


def _run(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)


def probe_quality(path: str) -> dict[str, Any]:
    """Return deterministic technical metadata from ffprobe."""
    cmd = [
        "ffprobe", "-v", "error", "-show_format", "-show_streams",
        "-of", "json", path,
    ]
    r = _run(cmd, timeout=45)
    if r.returncode != 0:
        return {"ok": False, "error": (r.stderr or b"").decode("utf-8", "replace")[-300]}
    try:
        data = json.loads(r.stdout.decode("utf-8", "replace") or "{}")
    except Exception:
        return {"ok": False, "error": "invalid_ffprobe_json"}
    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    audio = next((s for s in streams if s.get("codec_type") == "audio"), streams[0] if streams else {})
    duration = None
    try:
        duration = float(fmt.get("duration") or audio.get("duration") or 0) or None
    except Exception:
        duration = None
    bitrate = None
    try:
        bitrate = int(float(fmt.get("bit_rate") or 0)) or None
    except Exception:
        bitrate = None
    sample_rate = None
    try:
        sample_rate = int(float(audio.get("sample_rate") or 0)) or None
    except Exception:
        sample_rate = None
    channels = audio.get("channels")
    codec = audio.get("codec_name") or fmt.get("format_name")
    size = None
    try:
        size = int(float(fmt.get("size") or 0)) or None
    except Exception:
        size = None
    # Simple heuristic score: presence + reasonable bitrate/sample rate.
    score = 50
    if duration and duration > 1:
        score += 15
    if bitrate and bitrate >= 64000:
        score += 10
    if sample_rate and sample_rate >= 22050:
        score += 10
    if channels and channels >= 1:
        score += 5
    if codec:
        score += 10
    score = max(0, min(100, score))
    return {
        "ok": True,
        "duration_s": round(duration, 2) if duration else None,
        "format": fmt.get("format_name"),
        "codec": codec,
        "bit_rate": bitrate,
        "sample_rate_hz": sample_rate,
        "channels": channels,
        "size_bytes": size,
        "technical_score": score,
    }


def extract_sample(src: str, dst: str, *, max_seconds: int = 90) -> bool:
    """Extract first max_seconds as mp3 for AI analysis."""
    cmd = [
        "ffmpeg", "-v", "error", "-y", "-i", src,
        "-t", str(max_seconds), "-vn",
        "-ac", "1", "-ar", "22050", "-b:a", "64k",
        dst,
    ]
    r = _run(cmd, timeout=120)
    return r.returncode == 0 and Path(dst).exists() and Path(dst).stat().st_size > 1024


def _normalize_result(raw: dict[str, Any], *, provider: str, model: str, quality: dict[str, Any]) -> dict[str, Any]:
    cat = str(raw.get("categorie") or raw.get("category") or "autre").strip().lower()
    if cat not in CATEGORIES:
        cat = "autre"
    themes = raw.get("themes") or raw.get("suggested_themes") or []
    if isinstance(themes, str):
        themes = [t.strip().lower() for t in themes.split(",") if t.strip()]
    if not isinstance(themes, list):
        themes = []
    themes = [str(t).strip().lower().replace(" ", "-")[:32] for t in themes if str(t).strip()][:5]
    conf = raw.get("confiance", raw.get("confidence", 0))
    try:
        conf = float(conf)
    except Exception:
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    lang = str(raw.get("langue") or raw.get("language") or "fr").strip().lower()[:8]
    folder = str(raw.get("dossier_suggere") or raw.get("suggested_folder") or f"Audiobooks/{cat}").strip()[:200]
    reason = str(raw.get("raison") or raw.get("reason") or "").strip()[:500]
    excerpt = str(raw.get("transcription_courte") or raw.get("transcript_excerpt") or "").strip()[:1000]
    status = "needs_review"
    if conf >= settings.ai_confidence_threshold:
        status = "needs_review"  # MVP: always review before apply
    return {
        "provider": provider,
        "model": model,
        "status": status,
        "confidence": conf,
        "suggested_category": cat,
        "suggested_themes": themes,
        "suggested_language": lang,
        "suggested_folder": folder,
        "transcript_excerpt": excerpt,
        "reason": reason,
        "quality": quality,
        "raw": raw,
    }


def _gemini_generate(payload: dict[str, Any], model: str) -> dict[str, Any]:
    api_key = settings.gemini_api_key
    if not api_key:
        raise RuntimeError("missing_gemini_api_key")
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=settings.ai_timeout_s) as r:
        body = json.loads(r.read().decode("utf-8", "replace"))
    parts = (((body.get("candidates") or [{}])[0]).get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
    if not text:
        raise RuntimeError("empty_gemini_response")
    return json.loads(text)


def classify_with_gemini(*, sample_path: str, mime_type: str, metadata: dict[str, Any], quality: dict[str, Any]) -> dict[str, Any]:
    audio_bytes = Path(sample_path).read_bytes()
    prompt = (
        "Analyse ce livre audio (extrait). Réponds UNIQUEMENT en JSON valide avec ce schéma: "
        '{"transcription_courte":"1-2 phrases","langue":"fr","categorie":"meditation|developpement_personnel|formation|business|podcast|litterature|spiritualite|musique|autre",'
        '"themes":["..."],"confiance":0.0,"dossier_suggere":"Audiobooks/<Categorie>/<Sous-dossier>",'
        '"raison":"courte justification"}. '
        "Ne fais pas de transcription complète; donne seulement un court extrait représentatif."
    )
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt + "\n\nMétadonnées:\n" + json.dumps(metadata, ensure_ascii=False)[:3000]},
                {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(audio_bytes).decode()}},
            ]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 700,
            "responseMimeType": "application/json",
        },
    }
    raw = _gemini_generate(payload, settings.gemini_model)
    return _normalize_result(raw, provider="gemini", model=settings.gemini_model, quality=quality)


def _claude_generate(prompt: str) -> dict[str, Any]:
    api_key = settings.anthropic_api_key
    if not api_key:
        raise RuntimeError("missing_anthropic_api_key")
    payload = {
        "model": settings.anthropic_model,
        "max_tokens": 700,
        "temperature": 0.1,
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=settings.ai_timeout_s) as r:
        body = json.loads(r.read().decode("utf-8", "replace"))
    parts = body.get("content") or []
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
    if not text:
        raise RuntimeError("empty_claude_response")
    # Claude may wrap JSON in fences; be tolerant.
    if "```" in text:
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def classify_with_claude(*, metadata: dict[str, Any], quality: dict[str, Any], reason_prefix: str = "") -> dict[str, Any]:
    prompt = (
        "Classifie ce livre audio à partir des métadonnées (pas d'audio). "
        "Réponds UNIQUEMENT en JSON valide avec ce schéma: "
        '{"transcription_courte":"","langue":"fr","categorie":"meditation|developpement_personnel|formation|business|podcast|litterature|spiritualite|musique|autre",'
        '"themes":["..."],"confiance":0.0,"dossier_suggere":"Audiobooks/<Categorie>/<Sous-dossier>","raison":"courte justification"}.\n\n'
        f"Contexte: {reason_prefix}\nMétadonnées:\n{json.dumps(metadata, ensure_ascii=False)[:4000]}\nQualité:\n{json.dumps(quality, ensure_ascii=False)[:2000]}"
    )
    raw = _claude_generate(prompt)
    return _normalize_result(raw, provider="claude", model=settings.anthropic_model, quality=quality)


def analyze_audio_file(path: str, *, metadata: dict[str, Any]) -> dict[str, Any]:
    quality = probe_quality(path)
    sample_path = path
    sample_mime = metadata.get("content_type") or "audio/mpeg"
    tmp_sample = None
    try:
        size = Path(path).stat().st_size
        duration = (quality.get("duration_s") or 0) if isinstance(quality, dict) else 0
        # For large or long files, analyze a short sample only.
        if size > 15 * 1024 * 1024 or duration > 600:
            fd, tmp_sample = tempfile.mkstemp(prefix="aura-class-", suffix=".mp3")
            os.close(fd)
            if extract_sample(path, tmp_sample, max_seconds=90):
                sample_path = tmp_sample
                sample_mime = "audio/mpeg"
        errors = []
        if settings.ai_primary_provider == "gemini" and settings.gemini_api_key:
            try:
                return classify_with_gemini(sample_path=sample_path, mime_type=sample_mime, metadata=metadata, quality=quality)
            except Exception as e:
                errors.append(f"gemini:{type(e).__name__}")
                log.warning("audio_ai gemini failed: %s", e)
        if settings.ai_fallback_provider == "claude" and settings.anthropic_api_key:
            try:
                return classify_with_claude(metadata=metadata, quality=quality, reason_prefix="; ".join(errors))
            except Exception as e:
                errors.append(f"claude:{type(e).__name__}")
                log.warning("audio_ai claude failed: %s", e)
        # Last resort: deterministic metadata-only classification.
        name = str(metadata.get("display_name") or "").lower()
        cat = "autre"
        if "medit" in name:
            cat = "meditation"
        elif "podcast" in name:
            cat = "podcast"
        elif "formation" in name or "cours" in name:
            cat = "formation"
        return _normalize_result(
            {"categorie": cat, "confiance": 0.35, "raison": "fallback metadata-only; " + "; ".join(errors)},
            provider="heuristic", model="none", quality=quality,
        )
    finally:
        if tmp_sample and os.path.exists(tmp_sample):
            try:
                os.remove(tmp_sample)
            except Exception:
                pass
