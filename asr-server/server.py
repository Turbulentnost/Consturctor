"""Распознавание речи на видеокарте сервера.

Слушает только localhost. В установщики Constructor и Orchestrator не входит:
модели и CUDA живут рядом, основной backend только отправляет сюда файл.

Пайплайн тот же, что в voicetotext: Nemotron находит голоса, SepFormer
разводит одновременную речь, Whisper пишет текст по каждому голосу.
"""

from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path
from typing import Any

import torch
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from engine import ASR_MODEL, DIAR_MODEL, EMB_MODEL, SEP_MODEL, recognize, speakers_label

HOST = os.environ.get("ASR_HOST", "127.0.0.1")
PORT = int(os.environ.get("ASR_PORT", "7820"))
MAX_BYTES = 500 * 1024 * 1024

_gpu_name = ""
_ready = False
_lock = threading.RLock()

app = FastAPI(title="Constructor ASR", docs_url=None, redoc_url=None)


def load_model() -> None:
    global _gpu_name, _ready
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA недоступна: распознавание запускается только на видеокарте сервера")
    _gpu_name = torch.cuda.get_device_name(0)
    _ready = True


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in payload.get("utterances") or []:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        speakers = [int(speaker) for speaker in (item.get("speakers") or [])]
        who = speakers_label(speakers) if speakers else ""
        if item.get("overlap") or len(speakers) > 1:
            who = f"{who} (одновременно)".strip()
        start = float(item.get("start") or 0.0)
        end = float(item.get("end") or start)
        rows.append(
            {
                "start": round(start, 2),
                "end": round(max(end, start), 2),
                "text": text,
                "speaker": who,
            }
        )
    rows.sort(key=lambda item: (item["start"], item["speaker"]))
    return rows


def transcribe(path: Path, prompt: str) -> dict[str, Any]:
    if not _ready:
        raise RuntimeError("Сервис ещё не готов")
    hint = " ".join((prompt or "").split())[:240]
    with _lock:
        with tempfile.TemporaryDirectory(prefix="asr-") as folder:
            payload = recognize(path, language="auto", output=Path(folder))
    speakers = payload.get("speakers") or []
    labels = [str(row.get("label") or "") for row in speakers if isinstance(row, dict)]
    return {
        "ok": True,
        "language": payload.get("language") or "auto",
        "model": ASR_MODEL,
        "diarization_model": DIAR_MODEL,
        "separation_model": SEP_MODEL,
        "embedding_model": EMB_MODEL,
        "device": "cuda",
        "gpu": _gpu_name,
        "duration_sec": payload.get("duration_sec"),
        "speaker_count": len(speakers),
        "speakers": labels,
        "voices_separable": len(speakers) > 1,
        "overlap_sec": payload.get("overlap_sec"),
        "segments": _rows(payload),
        "full_text": payload.get("full_text") or "",
        "per_speaker_text": payload.get("per_speaker_text") or {},
        "speaker_embeddings": payload.get("speaker_embeddings") or {},
        "names_hint": hint,
    }


@app.on_event("startup")
def _startup() -> None:
    load_model()


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": _ready,
        "device": "cuda",
        "gpu": _gpu_name,
        "model": ASR_MODEL,
        "diarization_model": DIAR_MODEL,
        "separation_model": SEP_MODEL,
        "embedding_model": EMB_MODEL,
        "diarization": _ready,
    }


@app.post("/transcribe")
async def transcribe_upload(
    file: UploadFile = File(...),
    prompt: str = Form(""),
) -> dict[str, Any]:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Пустой файл")
    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="Файл больше 500 МБ")
    suffix = Path(file.filename or "audio.wav").suffix.lower() or ".wav"
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(raw)
            tmp_path = Path(tmp.name)
        return transcribe(tmp_path, prompt)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host=HOST, port=PORT, reload=False)
