"""Расшифровка аудио-вложений запуска (язык ru).

Если задан ASR_GPU_URL, файл уходит на серверный GPU-сервис asr-server
(whisper-large-v3 на видеокарте). Иначе — faster-whisper на CPU.
Модель и CUDA в установщики Constructor и Orchestrator не входят.

Инструмент audio.transcribe: file_id вложения запуска → текст и сегменты
с таймкодами. Модель кэшируется на процесс, читается из env WHISPER_MODEL.
Готовая расшифровка хранится на диске по хэшу файла: повторная загрузка той же
записи не распознаётся заново, в том числе после перезапуска backend.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

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

_SAMPLE_RATE = 16000
_CHUNK_SECONDS = 600
# ~10–12 минут речи и ~12 тыс. символов: часть целиком помещается в один ответ инструмента.
TRANSCRIPT_PART_SEGMENTS = 120
_SPAN_RE = re.compile(r"^\[([0-9:]+)[–-]([0-9:]+)\]")

_model: Any = None
_model_name = ""
_model_lock = threading.Lock()
_cache: dict[str, dict[str, Any]] = {}
_inflight: dict[str, threading.Event] = {}
_inflight_lock = threading.Lock()


DEFAULT_MODEL = "small"
DEFAULT_BEAM_SIZE = 5


def _wanted_model() -> str:
    return (os.environ.get("WHISPER_MODEL") or DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _asr_gpu_url() -> str:
    from app.config import settings

    return (settings.asr_gpu_url or "").strip().rstrip("/")


def _engine_tag() -> str:
    url = _asr_gpu_url()
    if not url:
        return f"{_wanted_model()}:beam{_beam_size()}"
    from app.config import settings

    model = (settings.asr_gpu_model or "openai/whisper-large-v3").strip()
    return f"gpu:{model}:voices"


def _beam_size() -> int:
    """Beam 5 by default for accuracy; WHISPER_BEAM_SIZE=1 is ~3x faster on CPU."""
    raw = (os.environ.get("WHISPER_BEAM_SIZE") or "").strip()
    try:
        return max(1, min(10, int(raw))) if raw else DEFAULT_BEAM_SIZE
    except ValueError:
        return DEFAULT_BEAM_SIZE


def _cpu_threads() -> int:
    """Leave a couple of cores so /health and the rest of the API stay responsive."""
    cores = os.cpu_count() or 2
    return max(1, cores - 2)


def _install_faster_whisper() -> None:
    """Desktop app starts backend with the machine's own Python, which may lack the audio stack
    (faster-whisper + PyAV decoder for wav/mp3/m4a); install it into that interpreter once."""
    import importlib
    import subprocess
    import sys

    command = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "faster-whisper>=1.0.0"]
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Не удалось установить faster-whisper на backend: {exc}") from exc
    if done.returncode != 0:
        tail = (done.stderr or done.stdout or "").strip().splitlines()[-3:]
        raise RuntimeError(
            "Не удалось установить faster-whisper на backend "
            f"({sys.executable} -m pip install faster-whisper): {' '.join(tail)[:400]}"
        )
    importlib.invalidate_caches()


def _get_model() -> Any:
    """Синглтон модели faster-whisper: первый вызов скачивает и загружает её."""
    global _model, _model_name
    wanted = _wanted_model()
    with _model_lock:
        if _model is not None and _model_name == wanted:
            return _model
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            _install_faster_whisper()
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError(
                    "faster-whisper установлен, но не импортируется на backend — перезапустите сервис"
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
    lines.extend(_transcript_line(row) for row in segments)
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return path


def _transcript_line(row: dict[str, Any]) -> str:
    speaker = str(row.get("speaker") or "").strip()
    who = f"{speaker}: " if speaker else ""
    return f"[{_clock(float(row['start']))}–{_clock(float(row['end']))}] {who}{row['text']}"


def transcript_parts(segment_count: int) -> int:
    return max(1, -(-int(segment_count) // TRANSCRIPT_PART_SEGMENTS))


def _segment_lines(text: str) -> tuple[list[str], list[str]]:
    lines = text.splitlines()
    head: list[str] = []
    body: list[str] = []
    for line in lines:
        if line.startswith("["):
            body.append(line)
        elif not body and line.strip():
            head.append(line)
    return head, body


def _line_span(line: str) -> tuple[str, str]:
    match = _SPAN_RE.match(line)
    return (match.group(1), match.group(2)) if match else ("", "")


def read_transcript(transcript_path: str, part: Any = None) -> dict[str, Any]:
    """Текст расшифровки по transcript_path из ответа audio.transcribe — только файлы этой папки.

    part (1…parts) — кусок по TRANSCRIPT_PART_SEGMENTS реплик: чтение агентом целиком
    обрезает середину длинной записи, а по частям он видит каждую реплику.
    """
    folder = _transcript_dir().resolve()
    try:
        path = Path(str(transcript_path or "").strip()).resolve()
    except (OSError, ValueError) as exc:
        raise RuntimeError("Непонятный путь к расшифровке") from exc
    if path.parent != folder or path.suffix.lower() != ".txt":
        raise RuntimeError("Это не файл расшифровки audio.transcribe")
    if not path.is_file():
        raise RuntimeError("Расшифровка не найдена — её удалили вместе с временными файлами сервера")
    text = path.read_text(encoding="utf-8")
    head, body = _segment_lines(text)
    parts = transcript_parts(len(body))
    result: dict[str, Any] = {
        "ok": True,
        "transcript_path": str(path),
        "segment_count": len(body),
        "parts": parts,
    }
    if part in (None, ""):
        return {**result, "text": text}
    try:
        index = int(part)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("part — номер части, целое число от 1") from exc
    if index < 1 or index > parts:
        raise RuntimeError(f"Части {index} нет: в расшифровке {parts} частей (part от 1 до {parts})")
    start = (index - 1) * TRANSCRIPT_PART_SEGMENTS
    chunk = body[start : start + TRANSCRIPT_PART_SEGMENTS]
    begin = _line_span(chunk[0])[0] if chunk else ""
    end = _line_span(chunk[-1])[1] if chunk else ""
    title = f"Часть {index} из {parts}, реплики {start + 1}–{start + len(chunk)} из {len(body)}, [{begin}–{end}]"
    return {
        **result,
        "part": index,
        "from": begin,
        "to": end,
        "next_part": index + 1 if index < parts else None,
        "text": "\n".join([*head, title, "", *chunk]),
        "note": (
            f"Прочитай следующую часть: part={index + 1}."
            if index < parts
            else "Это последняя часть: расшифровка прочитана целиком."
        ),
    }


def _disk_cache_path(cache_key: str) -> Path:
    name = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:24]
    return _transcript_dir() / f"{name}.json"


def _read_disk_cache(cache_key: str) -> dict[str, Any] | None:
    path = _disk_cache_path(cache_key)
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(result, dict) or not Path(str(result.get("transcript_path") or "")).is_file():
        return None
    return result


def _write_disk_cache(cache_key: str, result: dict[str, Any]) -> None:
    try:
        _disk_cache_path(cache_key).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


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
    return _with_parts(
        {
            "ok": True,
            "cached": cached,
            "filename": filename,
            "duration_sec": duration_sec,
            "segment_count": len(segments),
            "transcript_path": str(path),
            "preview": preview[:800],
            "diarization": (
                "nemotron" if any(str(row.get("speaker") or "").strip() for row in segments) else "none"
            ),
            "names_hint": prompt,
        }
    )


def _with_parts(result: dict[str, Any]) -> dict[str, Any]:
    """Число частей и подсказка чтения — и для расшифровок из кэша прежних версий."""
    parts = transcript_parts(int(result.get("segment_count") or 0))
    return {
        **result,
        "parts": parts,
        "note": (
            f"Полная расшифровка с таймкодами записана в transcript_path, {parts} частей. "
            "Цельный текст — audio.transcript без part. "
            f"По фрагментам — part=1, 2, … {parts} по порядку, "
            "не пропуская ни одной части: длинный текст в одном ответе обрезается посередине. "
            "Больше не вызывай audio.transcribe для того же вложения. "
            + (
                "У реплик есть метка говорящего (Голос N). ФИО ставь только если человек сам назвался."
                if result.get("diarization") == "nemotron"
                else "Меток говорящих нет: реплику подписывай ФИО только при обращении или самопредставлении, иначе «Участник N»."
            )
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
    cache_key = f"{digest}:{_engine_tag()}:{prompt}"
    with _inflight_lock:
        hit = _cache.get(cache_key)
        if hit is None or not Path(str(hit.get("transcript_path") or "")).is_file():
            hit = _read_disk_cache(cache_key)
            if hit is not None:
                _cache[cache_key] = hit
        waiter = _inflight.get(cache_key)
        owner = hit is None and waiter is None
        if owner:
            waiter = threading.Event()
            _inflight[cache_key] = waiter
    if hit is not None:
        return _claimed(_with_parts({**hit, "cached": True}), user_id, digest)
    if not owner:
        # A retry of the same file waits for the run already in progress
        # instead of starting a second transcription and starving the API.
        waiter.wait(timeout=7200)
        with _inflight_lock:
            cached = _cache.get(cache_key)
        if cached is not None:
            return _claimed(cached, user_id, digest)
        raise RuntimeError("Расшифровка этого файла уже шла и не завершилась. Повторите вызов.")

    try:
        segments, duration_sec, extra = _transcribe_bytes(
            raw, suffix=suffix, filename=filename, prompt=prompt
        )
        path = _write_transcript(filename, segments, duration_sec, digest)
        result = _short_result(
            filename=filename,
            duration_sec=duration_sec,
            segments=segments,
            path=path,
            cached=False,
            prompt=prompt,
        )
        saved = _persist_transcript(
            user_id=user_id,
            filename=filename,
            sha256=digest,
            duration_sec=duration_sec,
            transcript_path=str(path),
            segments=segments,
            embeddings=(extra or {}).get("speaker_embeddings"),
        )
        if saved:
            result["transcript_id"] = saved["transcript_id"]
            result["known_speakers"] = saved["known_speakers"]
            result["unknown_speakers"] = saved["unknown_speakers"]
        with _inflight_lock:
            _cache[cache_key] = result
        _write_disk_cache(cache_key, result)
        return result
    finally:
        waiter.set()
        with _inflight_lock:
            _inflight.pop(cache_key, None)


def _claimed(result: dict[str, Any], user_id: str, digest: str) -> dict[str, Any]:
    """Ответ из кэша с transcript_id этого пользователя: чужую запись audio.speakers не откроет."""
    from app.services.speaker_bank import claim_transcript

    transcript_id = str(result.get("transcript_id") or "")
    if not transcript_id:
        return result
    try:
        claimed = claim_transcript(transcript_id, user_id, digest)
    except Exception:
        logger.exception("Не удалось закрепить расшифровку %s за %s", transcript_id, user_id)
        return result
    if claimed is None:
        return result
    out = {
        **result,
        "transcript_id": claimed["transcript_id"],
        "known_speakers": claimed["known_speakers"],
        "unknown_speakers": claimed["unknown_speakers"],
    }
    if claimed["pristine"] and claimed["segments"]:
        # Прежние bind_speakers переписывали общий файл кэша — возвращаем ему метки «Голос N».
        try:
            path = _write_transcript(
                str(result.get("filename") or "audio"),
                claimed["segments"],
                float(result.get("duration_sec") or 0.0),
                digest,
            )
            out["transcript_path"] = str(path)
        except OSError:
            logger.warning("Не удалось обновить файл расшифровки %s", transcript_id)
    return out


def _persist_transcript(
    *,
    user_id: str,
    filename: str,
    sha256: str,
    duration_sec: float,
    transcript_path: str,
    segments: list[dict[str, Any]],
    embeddings: Any,
) -> dict[str, Any] | None:
    from app.db import session as db_session
    from app.services.speaker_bank import save_transcript

    full_text = "\n".join(_transcript_line(row) for row in segments)
    db = db_session.SessionLocal()
    try:
        return save_transcript(
            db,
            user_id=user_id,
            filename=filename,
            sha256=sha256,
            duration_sec=duration_sec,
            transcript_path=transcript_path,
            full_text=full_text,
            segments=segments,
            embeddings=embeddings if isinstance(embeddings, dict) else {},
        )
    finally:
        db.close()


def _decode(path: Path) -> Any:
    """Mono float32 samples at 16 kHz (PyAV inside faster-whisper: wav, mp3, m4a, …)."""
    from faster_whisper.audio import decode_audio

    return decode_audio(str(path), sampling_rate=_SAMPLE_RATE)


def segments_from_gpu_payload(
    payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], float, dict[str, Any]]:
    raw_rows = payload.get("segments")
    if not isinstance(raw_rows, list):
        raise RuntimeError("Сервис распознавания не вернул сегменты")
    segments: list[dict[str, Any]] = []
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        start = float(row.get("start") or 0.0)
        end = float(row.get("end") or start)
        item: dict[str, Any] = {"start": round(start, 2), "end": round(max(end, start), 2), "text": text}
        speaker = str(row.get("speaker") or "").strip()
        if speaker:
            item["speaker"] = speaker
        segments.append(item)
    duration = payload.get("duration_sec")
    if duration is None and segments:
        duration = segments[-1]["end"]
    embeddings = payload.get("speaker_embeddings")
    extra = {"speaker_embeddings": embeddings if isinstance(embeddings, dict) else {}}
    return segments, round(float(duration or 0.0), 2), extra


def _transcribe_via_gpu(
    raw: bytes, *, suffix: str, filename: str, prompt: str
) -> tuple[list[dict[str, Any]], float, dict[str, Any]]:
    import httpx

    from app.config import settings

    url = _asr_gpu_url()
    timeout = float(settings.asr_gpu_timeout_sec or 3600)
    try:
        response = httpx.post(
            f"{url}/transcribe",
            files={"file": (filename or f"audio{suffix}", raw, "application/octet-stream")},
            data={"prompt": prompt},
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"Сервис распознавания на видеокарте недоступен ({url}). Запустите asr-server\\run.bat"
        ) from exc
    if response.status_code >= 400:
        detail = ""
        try:
            body = response.json()
            detail = str(body.get("detail") or "") if isinstance(body, dict) else ""
        except ValueError:
            detail = (response.text or "")[:300]
        raise RuntimeError(detail or f"Сервис распознавания ответил {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("Сервис распознавания вернул не JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Сервис распознавания вернул пустой ответ")
    return segments_from_gpu_payload(payload)


def _transcribe_bytes(
    raw: bytes, *, suffix: str, filename: str, prompt: str
) -> tuple[list[dict[str, Any]], float, dict[str, Any]]:
    if _asr_gpu_url():
        return _transcribe_via_gpu(raw, suffix=suffix, filename=filename, prompt=prompt)
    model = _get_model()
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(raw)
            tmp_path = Path(tmp.name)
        # Not conditioning on previous text is faster and stops Whisper's repeat loops on long meetings.
        options: dict[str, Any] = {
            "language": "ru",
            "vad_filter": True,
            "beam_size": _beam_size(),
            "condition_on_previous_text": False,
        }
        if prompt:
            options["initial_prompt"] = prompt
        audio = _decode(tmp_path)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

    # Whisper builds the spectrogram of the whole input at once: an hour of audio needs ~0.5 GB
    # in one block and fails with MemoryError on a busy machine. Chunks keep it to ~80 MB.
    segments: list[dict[str, Any]] = []
    step = _CHUNK_SECONDS * _SAMPLE_RATE
    for begin in range(0, len(audio), step):
        offset = begin / _SAMPLE_RATE
        segments_iter, _info = model.transcribe(audio[begin : begin + step], **options)
        segments.extend(
            {
                "start": round(offset + float(segment.start or 0.0), 2),
                "end": round(offset + float(segment.end or 0.0), 2),
                "text": segment.text.strip(),
            }
            for segment in segments_iter
            if segment.text and segment.text.strip()
        )
    return segments, round(len(audio) / _SAMPLE_RATE, 2), {}
