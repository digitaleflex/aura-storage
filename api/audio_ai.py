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
_asr_model = None
_asr_lock = __import__("threading").Lock()

CATEGORIES = [
    "meditation", "developpement_personnel", "formation", "business",
    "podcast", "litterature", "spiritualite", "musique",
    "sante_bien_etre", "histoire_societe", "autre",
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
    tags = fmt.get("tags") or {}
    # normalize tag keys to lowercase
    norm_tags = {}
    if isinstance(tags, dict):
        for k, v in tags.items():
            if isinstance(k, str) and isinstance(v, str) and v.strip():
                norm_tags[k.strip().lower()] = v.strip()[:300]
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
        "tags": {k: norm_tags[k] for k in ("title", "artist", "album", "genre", "album_artist", "comment", "date", "track") if k in norm_tags},
    }


def extract_sample(src: str, dst: str, *, max_seconds: int = 480, start_seconds: int = 0) -> bool:
    """Extract an audio sample as low-bitrate mono mp3 for AI analysis."""
    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-ss", str(max(0, int(start_seconds))),
        "-i", src,
        "-t", str(max_seconds), "-vn",
        "-ac", "1", "-ar", "22050", "-b:a", "64k",
        dst,
    ]
    r = _run(cmd, timeout=180)
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


import re as _re
import unicodedata as _ud

def _norm_text(s: str) -> str:
    s = _ud.normalize("NFKD", s or "")
    s = "".join(c for c in s if not _ud.combining(c))
    return _re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()

_DEFAULT_RULE_KEYWORDS: list[tuple[str, list[str]]] = [
    ("meditation", ["meditation", "mediter", "pleine conscience", "mindfulness", "respiration", "respirez", "relaxation", "detente", "sommeil guide", "body scan", "yoga nidra", "visualisation guidee", "hypnose", "sophrologie", "coherence cardiaque", "ancrage", "calme", "serenite", "anti stress", "lacher prise"]),
    ("developpement_personnel", ["developpement personnel", "confiance en soi", "estime de soi", "motivation", "habitude", "productivite", "coaching", "pnl", "intelligence emotionnelle", "reussite", "pensee positive", "mindset", "discipline", "procrastination", "communication", "assertivite", "leadership personnel", "guerison", "resilience"]),
    ("formation", ["formation", "cours", "lecon", "module", "apprendre", "tutoriel", "masterclass", "certification", "atelier", "seminaire", "conference", "didacticiel", "programme", "chapitre", "session", "niveau", "debutant", "avance"]),
    ("business", ["business", "entrepreneuriat", "marketing", "vente", "finance", "investissement", "management", "startup", "leadership", "strategie", "negociation", "e-commerce", "immobilier", "bourse", "crypto", "freelance", "copywriting"]),
    ("podcast", ["podcast", "episode", "ep ", "interview", "entretien", "chronique", "emission", "radio", "talk", "debat", "rediffusion"]),
    ("litterature", ["livre audio", "audiobook", "roman", "nouvelle", "conte", "poesie", "lecture", "chapitre", "tome", "volume", "narrateur", "fiction", "biographie", "autobiographie", "memoire"]),
    ("spiritualite", ["spiritualite", "priere", "eveil", "conscience", "mantra", "sagesse", "karma", "dharma", "energie", "chakras", "gratitude", "loi de l'attraction", "guidance", "ange", "oracle"]),
    ("musique", ["musique", "album", "single", "instrumental", "beat", "sonate", "playlist", "concert", "symphonie", "ambient", "lofi", "binaural"]),
    ("sante_bien_etre", ["sante", "bien etre", "nutrition", "sommeil", "fitness", "yoga", "respiration", "detox", "stress", "anxiete", "burnout", "guerison"]),
    ("histoire_societe", ["histoire", "societe", "philosophie", "politique", "economie", "culture", "documentaire", "biographie historique"]),
]

_RULES_FILE = Path(__file__).resolve().parent / "audio_rules.json"

def _load_rule_keywords() -> list[tuple[str, list[str]]]:
    try:
        if _RULES_FILE.exists():
            data = json.loads(_RULES_FILE.read_text(encoding="utf-8"))
            rules = data.get("categories") if isinstance(data, dict) else data
            if isinstance(rules, list):
                out = []
                for item in rules:
                    if isinstance(item, dict) and isinstance(item.get("category"), str) and isinstance(item.get("keywords"), list):
                        kws = [str(k).strip() for k in item["keywords"] if str(k).strip()]
                        if kws:
                            out.append((item["category"].strip().lower(), kws))
                if out:
                    return out
            log.warning("audio_rules.json invalid format, using built-in defaults: %s", _RULES_FILE)
    except Exception as e:
        log.warning("audio_rules.json load failed, using built-in defaults: %s", e)
    return list(_DEFAULT_RULE_KEYWORDS)

def _get_asr_model():
    global _asr_model
    if _asr_model is not None:
        return _asr_model
    with _asr_lock:
        if _asr_model is not None:
            return _asr_model
        from faster_whisper import WhisperModel
        _asr_model = WhisperModel(
            settings.asr_model,
            device=settings.asr_device,
            compute_type=settings.asr_compute_type,
        )
        log.info("ASR model loaded: %s (%s/%s)", settings.asr_model, settings.asr_device, settings.asr_compute_type)
        return _asr_model


def transcribe_excerpt(path: str, *, max_seconds: int = 480) -> dict[str, Any]:
    """Transcribe an audio excerpt locally with faster-whisper. Returns dict with text/lang/error."""
    if not settings.asr_enabled:
        return {"ok": False, "error": "asr_disabled"}
    try:
        model = _get_asr_model()
        # Decode via ffmpeg to avoid PyAV version incompatibilities.
        import numpy as np
        cmd = ["ffmpeg", "-v", "error", "-i", path, "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", "-f", "s16le", "-"]
        r = _run(cmd, timeout=max(120, max_seconds))
        if r.returncode != 0 or not r.stdout:
            raise RuntimeError("ffmpeg_decode_failed")
        audio = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0
        try:
            segments, info = model.transcribe(audio, beam_size=1, vad_filter=True)
        except Exception:
            segments, info = model.transcribe(audio, beam_size=1, vad_filter=False)
        parts = []
        total = 0.0
        for seg in segments:
            text = (seg.text or "").strip()
            if text:
                parts.append(text)
            total = max(total, float(getattr(seg, "end", 0) or 0))
            if total >= max_seconds:
                break
        text = " ".join(parts).strip()
        return {
            "ok": True,
            "text": text[:4000],
            "language": getattr(info, "language", None),
            "language_probability": getattr(info, "language_probability", None),
            "duration_s": total,
        }
    except Exception as e:
        log.warning("ASR failed: %s", e)
        return {"ok": False, "error": str(e)[:300]}


def classify_with_rules(*, metadata: dict[str, Any], quality: dict[str, Any]) -> dict[str, Any]:
    """Deterministic classification from metadata/tags/filename/quality. No external AI."""
    tags = (quality.get("tags") or {}) if isinstance(quality, dict) else {}
    sources = [
        ("genre", str(tags.get("genre") or ""), 4),
        ("title_album", " ".join([str(tags.get("title") or ""), str(tags.get("album") or "")]), 3),
        ("transcript", str(metadata.get("transcript_excerpt") or ""), 3),
        ("filename", str(metadata.get("display_name") or ""), 2),
        ("folder", str(metadata.get("folder_name") or ""), 2),
        ("comment_artist", " ".join([str(tags.get("comment") or ""), str(tags.get("artist") or "")]), 1),
    ]
    rule_keywords = _load_rule_keywords()
    scores: dict[str, float] = {c: 0.0 for c, _ in rule_keywords}
    evidence: dict[str, list[str]] = {c: [] for c, _ in rule_keywords}
    matched: dict[str, list[str]] = {c: [] for c, _ in rule_keywords}

    for src_name, raw, weight in sources:
        hay = _norm_text(raw)
        if not hay:
            continue
        for cat, kws in rule_keywords:
            for kw in kws:
                nkw = _norm_text(kw)
                if not nkw or nkw not in hay:
                    continue
                occ = 1
                if src_name == "transcript":
                    occ = min(hay.count(nkw), 3)  # cap frequency boost
                pts = weight * (2 if " " in nkw else 1) * occ
                scores[cat] += pts
                if kw not in matched[cat]:
                    matched[cat].append(kw)
                ev = f"{src_name}:{kw}(+{pts})"
                if ev not in evidence[cat]:
                    evidence[cat].append(ev)

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_cat, best_score = ranked[0] if ranked else ("autre", 0.0)
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    third = ranked[2] if len(ranked) > 2 else None

    reasons = []
    confidence = 0.20
    if best_score > 0:
        margin = best_score - second_score
        # Calibrated confidence: strength + margin, capped.
        confidence = 0.35 + min(best_score / 40.0, 0.40) + min(margin / 20.0, 0.20)
        confidence = max(0.0, min(0.95, confidence))
        reasons.append("top=" + ", ".join([f"{c}:{int(s)}" for c, s in ranked[:3] if s > 0]))
        reasons.append("signaux=" + "; ".join(evidence.get(best_cat, [])[:6]))
    else:
        best_cat = "autre"
        confidence = 0.20
        reasons.append("aucun signal mots-clés")

    duration = float((quality.get("duration_s") or 0) if isinstance(quality, dict) else 0)
    if duration >= 20 * 60:
        reasons.append(f"durée longue ({int(duration//60)} min)")
        if best_cat == "autre":
            confidence = max(confidence, 0.30)
    elif duration and duration < 180:
        reasons.append("durée courte (<3 min)")
        if best_cat in ("litterature", "formation", "histoire_societe"):
            confidence = min(confidence, 0.55)

    # Simple conflict guard: chapter/livre audio often means literature, but history keywords win.
    if best_cat == "litterature" and scores.get("histoire_societe", 0) >= best_score * 0.8 and scores.get("histoire_societe", 0) > 0:
        reasons.append("conflit litterature/histoire_societe: revue recommandée")
        confidence = min(confidence, 0.70)

    if confidence < 0.60:
        reasons.append("confiance<0.60: incertain")
    elif confidence < 0.80:
        reasons.append("confiance 0.60-0.79: revue")
    else:
        reasons.append("confiance>=0.80: suggestion forte")

    themes = matched.get(best_cat, [])[:5]
    folder = f"Audiobooks/{best_cat.replace('_', ' ').title().replace(' ', '-')}"
    return _normalize_result(
        {
            "categorie": best_cat,
            "themes": themes,
            "langue": str(tags.get("language") or "fr")[:8],
            "confiance": round(confidence, 2),
            "dossier_suggere": folder,
            "raison": "Règles déterministes: " + " | ".join(reasons),
            "transcription_courte": "",
        },
        provider="rules",
        model="rules-v2",
        quality=quality,
    )


def _gemini_generate(payload: dict[str, Any], model: str) -> dict[str, Any]:
    api_key = settings.gemini_api_key
    if not api_key:
        raise RuntimeError("missing_gemini_api_key")
    last_err: Exception | None = None
    for attempt in range(3):
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=settings.ai_timeout_s) as r:
                body = json.loads(r.read().decode("utf-8", "replace"))
            parts = (((body.get("candidates") or [{}])[0]).get("content") or {}).get("parts") or []
            text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
            if not text:
                raise RuntimeError("empty_gemini_response")
            try:
                return json.loads(text)
            except Exception:
                # tolerate markdown-fenced JSON
                if "```" in text:
                    text = text.split("```", 2)[1]
                    if text.lstrip().startswith("json"):
                        text = text.lstrip()[4:]
                return json.loads(text.strip())
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (429, 503) and attempt < 2:
                import time as _time
                _time.sleep(2 * (attempt + 1))
                continue
            raise
        except Exception as e:
            last_err = e
            if attempt < 2:
                import time as _time
                _time.sleep(1)
                continue
            raise
    raise last_err or RuntimeError("gemini_failed")


def _gemini_upload_file(path: str, mime_type: str) -> str:
    """Upload a large audio sample via Gemini Files API; returns file URI."""
    api_key = settings.gemini_api_key
    if not api_key:
        raise RuntimeError("missing_gemini_api_key")
    data = Path(path).read_bytes()
    num_bytes = len(data)
    start_req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/upload/v1beta/files?key={api_key}",
        data=json.dumps({"file": {"display_name": Path(path).name}}).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(num_bytes),
            "X-Goog-Upload-Header-Content-Type": mime_type,
        },
        method="POST",
    )
    with urllib.request.urlopen(start_req, timeout=settings.ai_timeout_s) as r:
        upload_url = r.headers.get("x-goog-upload-url") or r.headers.get("X-Goog-Upload-URL")
    if not upload_url:
        raise RuntimeError("gemini_upload_missing_url")
    up_req = urllib.request.Request(
        upload_url,
        data=data,
        headers={
            "Content-Length": str(num_bytes),
            "X-Goog-Upload-Offset": "0",
            "X-Goog-Upload-Command": "upload, finalize",
        },
        method="POST",
    )
    with urllib.request.urlopen(up_req, timeout=max(settings.ai_timeout_s, 120)) as r:
        body = json.loads(r.read().decode("utf-8", "replace"))
    file_info = body.get("file") or body
    uri = file_info.get("uri")
    if not uri:
        raise RuntimeError("gemini_upload_missing_uri")
    # Wait briefly for file to become ACTIVE if needed
    name = file_info.get("name")
    if name:
        for _ in range(15):
            get_req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/{name}?key={api_key}",
                headers={"Content-Type": "application/json"},
                method="GET",
            )
            try:
                with urllib.request.urlopen(get_req, timeout=30) as gr:
                    info = json.loads(gr.read().decode("utf-8", "replace"))
                if info.get("state") == "ACTIVE":
                    break
            except Exception:
                pass
            import time as _time
            _time.sleep(1)
    return uri


def classify_with_gemini(*, sample_path: str, mime_type: str, metadata: dict[str, Any], quality: dict[str, Any]) -> dict[str, Any]:
    prompt = (
        "Analyse ce livre audio (extrait). Réponds UNIQUEMENT en JSON valide avec ce schéma: "
        '{"transcription_courte":"1-2 phrases","langue":"fr","categorie":"meditation|developpement_personnel|formation|business|podcast|litterature|spiritualite|musique|sante_bien_etre|histoire_societe|autre",'
        '"themes":["..."],"confiance":0.0,"dossier_suggere":"Audiobooks/<Categorie>/<Sous-dossier>",'
        '"raison":"courte justification"}. '
        "Ne fais pas de transcription complète; donne seulement un court extrait représentatif."
    )
    size = Path(sample_path).stat().st_size
    if size > 20 * 1024 * 1024:
        file_uri = _gemini_upload_file(sample_path, mime_type)
        audio_part = {"file_data": {"mime_type": mime_type, "file_uri": file_uri}}
    else:
        audio_bytes = Path(sample_path).read_bytes()
        audio_part = {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(audio_bytes).decode()}}
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt + "\n\nMétadonnées:\n" + json.dumps(metadata, ensure_ascii=False)[:3000]},
                audio_part,
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
        '{"transcription_courte":"","langue":"fr","categorie":"meditation|developpement_personnel|formation|business|podcast|litterature|spiritualite|musique|sante_bien_etre|histoire_societe|autre",'
        '"themes":["..."],"confiance":0.0,"dossier_suggere":"Audiobooks/<Categorie>/<Sous-dossier>","raison":"courte justification"}.\n\n'
        f"Contexte: {reason_prefix}\nMétadonnées:\n{json.dumps(metadata, ensure_ascii=False)[:4000]}\nQualité:\n{json.dumps(quality, ensure_ascii=False)[:2000]}"
    )
    raw = _claude_generate(prompt)
    return _normalize_result(raw, provider="claude", model=settings.anthropic_model, quality=quality)


def classify_with_openrouter(*, sample_path: str, mime_type: str, metadata: dict[str, Any], quality: dict[str, Any]) -> dict[str, Any]:
    api_key = settings.openrouter_api_key
    if not api_key:
        raise RuntimeError("missing_openrouter_api_key")
    audio_bytes = Path(sample_path).read_bytes()
    fmt = "mp3"
    if "wav" in mime_type: fmt = "wav"
    elif "ogg" in mime_type: fmt = "ogg"
    elif "flac" in mime_type: fmt = "flac"
    elif "m4a" in mime_type or "mp4" in mime_type: fmt = "m4a"
    prompt = (
        "Analyse ce livre audio (extrait). Réponds UNIQUEMENT en JSON valide avec ce schéma: "
        '{"transcription_courte":"1-2 phrases","langue":"fr","categorie":"meditation|developpement_personnel|formation|business|podcast|litterature|spiritualite|musique|sante_bien_etre|histoire_societe|autre",'
        '"themes":["..."],"confiance":0.0,"dossier_suggere":"Audiobooks/<Categorie>/<Sous-dossier>",'
        '"raison":"courte justification"}. '
        "Ne fais pas de transcription complète; donne seulement un court extrait représentatif."
    )
    payload = {
        "model": settings.openrouter_model,
        "temperature": 0.1,
        "max_tokens": 700,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt + "\n\nMétadonnées:\n" + json.dumps(metadata, ensure_ascii=False)[:3000]},
                {"type": "input_audio", "input_audio": {"data": base64.b64encode(audio_bytes).decode(), "format": fmt}},
            ],
        }],
    }
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://aura.local",
            "X-Title": "AURA Audio Classification",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=settings.ai_timeout_s) as r:
            body = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"openrouter_http_{e.code}:{detail}") from e
    choices = body.get("choices") or []
    msg = (choices[0].get("message") if choices else {}) or {}
    text = msg.get("content") or ""
    if isinstance(text, list):
        text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
    text = str(text).strip()
    if "```" in text:
        text = text.split("```", 2)[1]
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
        text = text.strip()
    raw = json.loads(text)
    return _normalize_result(raw, provider="openrouter", model=settings.openrouter_model, quality=quality)


def analyze_audio_file(path: str, *, metadata: dict[str, Any]) -> dict[str, Any]:
    quality = probe_quality(path)
    sample_path = path
    sample_mime = metadata.get("content_type") or "audio/mpeg"
    tmp_sample = None
    try:
        size = Path(path).stat().st_size
        duration = float((quality.get("duration_s") or 0) if isinstance(quality, dict) else 0)
        # For large or long files, analyze a representative 8-min sample (5-10 min requested).
        if size > 20 * 1024 * 1024 or duration > 600:
            fd, tmp_sample = tempfile.mkstemp(prefix="aura-class-", suffix=".mp3")
            os.close(fd)
            start = min(30, int(duration * 0.05)) if duration > 60 else 0
            max_s = 480 if duration > 600 else 180
            if extract_sample(path, tmp_sample, max_seconds=max_s, start_seconds=start):
                sample_path = tmp_sample
                sample_mime = "audio/mpeg"
        # 1b) Optional local ASR on excerpt (no external API).
        asr = {"ok": False, "error": "asr_disabled"}
        if settings.asr_enabled:
            asr = transcribe_excerpt(sample_path, max_seconds=480)
            if asr.get("ok") and asr.get("text"):
                metadata = {**metadata, "transcript_excerpt": asr.get("text", "")}
                if asr.get("language") and not metadata.get("language"):
                    metadata["language"] = asr.get("language")
        quality = {**quality, "asr": {"ok": asr.get("ok"), "language": asr.get("language"), "chars": len(asr.get("text") or ""), "error": asr.get("error")}}

        # 1) Deterministic rules first (no external AI, fast, explainable).
        rules = classify_with_rules(metadata=metadata, quality=quality)
        rules_conf = float(rules.get("confidence") or 0)
        primary = str(settings.ai_primary_provider or "rules").strip().lower()
        fallback = str(settings.ai_fallback_provider or "none").strip().lower()
        ai_enabled = primary not in ("rules", "none", "off", "disabled")

        if not ai_enabled or rules_conf >= settings.ai_confidence_threshold:
            rules["reason"] = (rules.get("reason") or "") + ("; IA ignorée (confiance règles suffisante)" if rules_conf >= settings.ai_confidence_threshold and ai_enabled else "; mode règles")
            return rules

        # 2) AI enrichment when rules are uncertain.
        errors = []
        transient = False

        def _try_provider(name: str):
            nonlocal transient
            try:
                if name == "gemini" and settings.gemini_api_key:
                    return classify_with_gemini(sample_path=sample_path, mime_type=sample_mime, metadata=metadata, quality=quality)
                if name == "openrouter" and settings.openrouter_api_key:
                    return classify_with_openrouter(sample_path=sample_path, mime_type=sample_mime, metadata=metadata, quality=quality)
                if name == "claude" and settings.anthropic_api_key:
                    return classify_with_claude(metadata=metadata, quality=quality, reason_prefix="; ".join(errors))
            except Exception as e:
                errors.append(f"{name}:{type(e).__name__}")
                msg = str(e)
                if isinstance(e, urllib.error.HTTPError) and e.code in (429, 503):
                    transient = True
                if "429" in msg or "503" in msg:
                    transient = True
                log.warning("audio_ai %s failed: %s", name, e)
            return None

        for name in [primary, fallback]:
            if name in ("rules", "none", "off", "disabled", ""):
                continue
            res = _try_provider(name)
            if res is not None:
                return res
        # If providers failed due to transient rate limits, let worker requeue.
        if transient and not any(x.startswith("claude:") and "429" not in x and "503" not in x for x in errors):
            raise RuntimeError("transient_ai_failure: " + "; ".join(errors))
        # AI unavailable/failed: return deterministic rules.
        rules["reason"] = (rules.get("reason") or "") + ("; fallback règles: " + "; ".join(errors) if errors else "; fallback règles")
        return rules
    finally:
        if tmp_sample and os.path.exists(tmp_sample):
            try:
                os.remove(tmp_sample)
            except Exception:
                pass
