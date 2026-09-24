"""Расшифровка аудио-вложений запуска через faster-whisper (CPU, язык ru).

Инструмент audio.transcribe: file_id вложения запуска → текст и сегменты
с таймкодами. Модель кэшируется на процесс, читается из env WHISPER_MODEL.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

MAX_BYTES = 500 * 1024 * 1024
ALLOWED_EXTENSIONS = frozenset(
    {
        ".wav",
        ".mp3",
        ".m4a",
        ".aac",
        ".ogg",
        ".opus",
        ".flac",
        ".webm",
        ".mp4",
        ".mkv",
        ".wma",
        ".amr",
    }
)

_model: Any = None
_model_name = ""
_model_lock = threading.Lock()
_cache: dict[str, dict[str, Any]] = {}
_inflight: dict[str, threading.Event] = {}
_inflight_lock = threading.Lock()


def _wanted_model() -> str:
    return (os.environ.get("WHISPER_MODEL") or "small").strip() or "small"


def _cpu_threads() -> int:
    """Leave a couple of cores so /health and the rest of the API stay responsive."""
    cores = os.cpu_count() or 2
    return max(1, cores - 2)


def _get_model() -> Any:
    """Синглтон модели faster-whisper: первый вызов скачивает и загружает её."""
    global _model, _model_name
    wanted = _wanted_model()
    with _model_lock:
        if _model is not None and _model_name == wanted:
            return _model
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "Модуль faster-whisper не установлен на backend: "
                "установите faster-whisper (pip install faster-whisper) "
                "и перезапустите сервис."
            ) from exc
        _model = WhisperModel(
            wanted, device="cpu", compute_type="int8", cpu_threads=_cpu_threads()
        )
        _model_name = wanted
        return _model


def _names_prompt(names: list[str] | None, hint: str) -> str:
    cleaned = []
    seen: set[str] = set()
    for raw in names or []:
        text = " ".join(str(raw or "").split())
        if not text or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        cleaned.append(text)
    parts = []
    if cleaned:
        parts.append("Участники совещания: " + ", ".join(cleaned[:24]) + ".")
    extra = " ".join(str(hint or "").split())
    if extra:
        parts.append(extra)
    return " ".join(parts)[:400]


def _clock(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _transcript_dir() -> Path:
    folder = Path(tempfile.gettempdir()) / "constructor-transcripts"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _write_transcript(filename: str, segments: list[dict[str, Any]], duration_sec: float, digest: str) -> Path:
    stem = Path(filename).stem
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in stem)[:40] or "audio"
    path = _transcript_dir() / f"{digest[:12]}-{safe}.txt"
    lines = [
        f"Файл: {filename}",
        f"Длительность: {_clock(duration_sec)}",
        f"Сегментов: {len(segments)}",
        "",
    ]
    lines.extend(
        f"[{_clock(float(row['start']))}–{_clock(float(row['end']))}] {row['text']}"
        for row in segments
    )
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return path


def _short_result(
    *,
    filename: str,
    duration_sec: float,
    segments: list[dict[str, Any]],
    path: Path,
    cached: bool,
    prompt: str,
) -> dict[str, Any]:
    preview = "\n".join(str(row["text"]) for row in segments[:8]).strip()
    return {
        "ok": True,
        "cached": cached,
        "filename": filename,
        "duration_sec": duration_sec,
        "segment_count": len(segments),
        "transcript_path": str(path),
        "preview": preview[:800],
        "diarization": "none",
        "names_hint": prompt,
        "note": (
            "Полная расшифровка с таймкодами записана в transcript_path. "
            "Прочитай этот файл один раз и больше не вызывай audio.transcribe для того же вложения. "
            "Меток говорящих нет: реплику подписывай ФИО только при обращении или самопредставлении, иначе «Участник N»."
        ),
    }


def transcribe_run_attachment(
    file_id: str,
    user_id: str,
    names: list[str] | None = None,
    hint: str = "",
) -> dict[str, Any]:
    """Расшифровка аудио-вложения запуска по file_id.

    Доступ: файл должен принадлежать workflow этого пользователя.
    Возвращает segments (start/end/text — таймкоды обязательны),
    полный text, duration_sec и filename.
    """
    from app.db.session import SessionLocal
    from app.models.workflow import Workflow, WorkflowFile

    fid = (file_id or "").strip()
    if not fid:
        raise RuntimeError("Для audio.transcribe нужен file_id вложения запуска")
    if not (user_id or "").strip():
        raise RuntimeError("Нет пользователя сессии для audio.transcribe")

    db = SessionLocal()
    try:
        item = db.query(WorkflowFile).filter(WorkflowFile.id == fid).first()
        if item is None:
            raise RuntimeError(f"Файл {fid} не найден среди вложений")
        workflow = db.get(Workflow, item.workflow_id)
        if workflow is None or workflow.user_id != user_id:
            raise RuntimeError("Файл принадлежит агенту другого пользователя")
        filename = item.filename or "audio"
        raw = bytes(item.content or b"")
    finally:
        db.close()

    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ext.lstrip(".") for ext in ALLOWED_EXTENSIONS))
        raise RuntimeError(
            f"Формат {suffix or 'без расширения'} не принимается. Можно: {allowed}"
        )
    if not raw:
        raise RuntimeError(f"Файл {filename} пустой")
    if len(raw) > MAX_BYTES:
        raise RuntimeError("Файл больше 500 МБ")

    prompt = _names_prompt(names, hint)
    digest = hashlib.sha256(raw).hexdigest()
    cache_key = f"{digest}:{_wanted_model()}:{prompt}"
    with _inflight_lock:
        cached = _cache.get(cache_key)
        if cached is not None and Path(str(cached.get("transcript_path") or "")).is_file():
            return {**cached, "cached": True}
        waiter = _inflight.get(cache_key)
        if waiter is None:
            waiter = threading.Event()
            _inflight[cache_key] = waiter
            owner = True
        else:
            owner = False
    if not owner:
        # A retry of the same file waits for the run already in progress
        # instead of starting a second transcription and starving the API.
        waiter.wait(timeout=3600)
        with _inflight_lock:
            cached = _cache.get(cache_key)
        if cached is not None:
            return cached
        raise RuntimeError("Расшифровка этого файла уже шла и не завершилась. Повторите вызов.")

    try:
        segments, duration_sec = _transcribe_bytes(raw, suffix=suffix, filename=filename, prompt=prompt)
        path = _write_transcript(filename, segments, duration_sec, digest)
        result = _short_result(
            filename=filename,
            duration_sec=duration_sec,
            segments=segments,
            path=path,
            cached=False,
            prompt=prompt,
        )
        with _inflight_lock:
            _cache[cache_key] = result
        return result
    finally:
        waiter.set()
        with _inflight_lock:
            _inflight.pop(cache_key, None)


def _transcribe_bytes(
    raw: bytes, *, suffix: str, filename: str, prompt: str
) -> tuple[list[dict[str, Any]], float]:
    model = _get_model()
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(raw)
            tmp_path = Path(tmp.name)
        options: dict[str, Any] = {"language": "ru", "vad_filter": True, "beam_size": 5}
        if prompt:
            options["initial_prompt"] = prompt
        segments_iter, info = model.transcribe(str(tmp_path), **options)
        segments = [
            {
                "start": round(float(segment.start or 0.0), 2),
                "end": round(float(segment.end or 0.0), 2),
                "text": segment.text.strip(),
            }
            for segment in segments_iter
            if segment.text and segment.text.strip()
        ]
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

    return segments, round(float(getattr(info, "duration", 0.0) or 0.0), 2)
