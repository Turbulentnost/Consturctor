"""Расшифровка записи с несколькими голосами.

Сначала определяется, кто и когда говорит (в том числе одновременно),
затем каждый голос расшифровывается отдельно. В результате — текст по каждому
голосу и общий диалог.

Запуск:
    .\\.venv\\Scripts\\python.exe -u transcribe.py
    .\\.venv\\Scripts\\python.exe -u transcribe.py Meeting-12-1002.wav
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_external_models = Path(r"C:\Users\testii\Downloads\voicetotext\models")
if (_external_models / "hf" / "hub").is_dir():
    os.environ["HF_HOME"] = str(_external_models / "hf")
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(_external_models / "hf" / "hub")
else:
    os.environ.setdefault("HF_HOME", str(ROOT / "models" / "hf"))
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(ROOT / "models" / "hf" / "hub"))
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import numpy as np
import soundfile as sf
import torch
import torchaudio

DIAR_MODEL = "nvidia/Nemotron-3-Diarization"
ASR_MODEL = "openai/whisper-large-v3"
SEP_MODEL = "speechbrain/sepformer-whamr16k"
EMB_MODEL = "speechbrain/spkrec-ecapa-voxceleb"
SAMPLE_RATE = 16000


def model_dir(name: str) -> Path:
    external = _external_models / name
    if external.is_dir():
        return external
    folder = ROOT / "models" / name
    folder.mkdir(parents=True, exist_ok=True)
    return folder

LANG_RU = {
    "ru": "русский",
    "en": "английский",
    "uk": "украинский",
    "de": "немецкий",
    "fr": "французский",
    "es": "испанский",
    "it": "итальянский",
    "zh": "китайский",
    "pt": "португальский",
    "pl": "польский",
    "tr": "турецкий",
}


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def fmt_ts(sec: float) -> str:
    sec = max(0.0, float(sec))
    hours = int(sec // 3600)
    minutes = int((sec % 3600) // 60)
    seconds = sec % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"


def fmt_dur(sec: float) -> str:
    sec = max(0, int(round(sec)))
    hours, rem = divmod(sec, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours} ч {minutes} мин {seconds} с"
    if minutes:
        return f"{minutes} мин {seconds} с"
    return f"{seconds} с"


def speaker_name(index: int) -> str:
    return f"Голос {index}"


def speakers_label(indexes: list[int] | tuple[int, ...]) -> str:
    names = [speaker_name(i) for i in indexes]
    if len(names) == 1:
        return names[0]
    return " + ".join(names)


def clean_text(text: str) -> str:
    text = " ".join((text or "").split())
    for mark in (",", ".", "?", "!", ":", ";", "…", "»"):
        text = text.replace(" " + mark, mark)
    text = text.replace("( ", "(").replace(" )", ")")
    text = text.replace("« ", "«")
    return text.strip()


def rms(values: np.ndarray) -> float:
    if values is None or len(values) == 0:
        return 0.0
    array = np.asarray(values, dtype=np.float64).reshape(-1)
    return float(np.sqrt(np.mean(np.square(array))))


def cosine(left: np.ndarray, right: np.ndarray) -> float:
    left = np.asarray(left, dtype=np.float64).reshape(-1)
    right = np.asarray(right, dtype=np.float64).reshape(-1)
    if left.shape != right.shape:
        size = min(left.size, right.size)
        left = left[:size]
        right = right[:size]
    denom = float(np.linalg.norm(left) * np.linalg.norm(right)) + 1e-8
    return float(np.dot(left, right) / denom)


def nvidia_smi_mem() -> tuple[int, int]:
    output = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    used_text, total_text = [part.strip() for part in output.strip().splitlines()[0].split(",")]
    return int(used_text) * 1024**2, int(total_text) * 1024**2


_gpu_capped = False


def cap_gpu(limit: float) -> tuple[float, int, int, int]:
    global _gpu_capped
    if not torch.cuda.is_available():
        raise RuntimeError("PyTorch не видит видеокарту. Нужна сборка CUDA, а не CPU.")
    used, total = nvidia_smi_mem()
    budget = int(limit * total - used)
    if budget < 3 * 1024**3 and not _gpu_capped:
        raise RuntimeError(
            "В пределах лимита "
            f"{limit:.0%} свободно меньше 3 ГБ. Сейчас занято {used / 1024**3:.1f} ГБ "
            f"из {total / 1024**3:.1f} ГБ."
        )
    fraction = min(limit, max(budget, 0) / total) if total else limit
    if not _gpu_capped:
        torch.cuda.set_per_process_memory_fraction(max(0.05, fraction), 0)
        _gpu_capped = True
    return fraction, max(budget, 0), total, used


def load_audio(path: Path, max_seconds: float) -> tuple[np.ndarray, int]:
    data, source_rate = sf.read(str(path), dtype="float32", always_2d=True)
    audio = data.mean(axis=1).astype(np.float32)
    if source_rate != SAMPLE_RATE:
        print(f"Привожу частоту {source_rate} Гц к {SAMPLE_RATE} Гц", flush=True)
        wave = torch.from_numpy(np.ascontiguousarray(audio)).unsqueeze(0)
        with torch.inference_mode():
            wave = torchaudio.functional.resample(wave, source_rate, SAMPLE_RATE)
        audio = wave.squeeze(0).contiguous().numpy().astype(np.float32)
    audio = np.clip(audio, -1.0, 1.0)
    if max_seconds and max_seconds > 0:
        audio = audio[: int(max_seconds * SAMPLE_RATE)]
    if len(audio) < SAMPLE_RATE:
        raise RuntimeError("В файле меньше секунды звука.")
    return audio, SAMPLE_RATE


def heartbeat(stop: threading.Event, started: float, message: str) -> None:
    while not stop.wait(20):
        print(f"  {message}, прошло {time.time() - started:.0f} с", flush=True)


class Heartbeat:
    def __init__(self, message: str) -> None:
        self.message = message
        self.stop = threading.Event()
        self.thread = threading.Thread(
            target=heartbeat,
            args=(self.stop, time.time(), message),
            daemon=True,
        )

    def __enter__(self) -> "Heartbeat":
        self.thread.start()
        return self

    def __exit__(self, *_) -> None:
        self.stop.set()
        self.thread.join(timeout=1)


def is_oom(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "out of memory" in text or "cuda" in text and "memory" in text


def as_speaker_id(value) -> int:
    if isinstance(value, str):
        digits = re.findall(r"\d+", value)
        if not digits:
            raise ValueError(f"непонятный идентификатор голоса: {value}")
        return int(digits[-1])
    return int(value)


def normalize_segment(segment) -> dict:
    if isinstance(segment, dict):
        start = segment.get("Start", segment.get("start"))
        end = segment.get("End", segment.get("end"))
        speaker = segment.get("Speaker", segment.get("speaker", segment.get("label")))
    elif isinstance(segment, (list, tuple)) and len(segment) >= 3:
        start, end, speaker = segment[0], segment[1], segment[2]
    else:
        raise TypeError(f"непонятный сегмент диаризации: {segment!r}")
    return {"start": float(start), "end": float(end), "speaker": as_speaker_id(speaker)}


def parse_diar_output(parsed) -> list:
    if parsed is None:
        return []
    if isinstance(parsed, dict):
        return [parsed]
    if not isinstance(parsed, (list, tuple)) or not parsed:
        return []
    first = parsed[0]
    if isinstance(first, dict):
        return list(parsed)
    if isinstance(first, (list, tuple)):
        if first and isinstance(first[0], dict):
            return list(first)
        if len(first) >= 3 and not isinstance(first[0], (list, tuple, dict)):
            return list(parsed)
    return []


def merge_same_speaker(segments: list[dict], gap: float) -> list[dict]:
    ordered = sorted(segments, key=lambda item: (item["speaker"], item["start"], item["end"]))
    merged: list[dict] = []
    for segment in ordered:
        if (
            merged
            and merged[-1]["speaker"] == segment["speaker"]
            and segment["start"] - merged[-1]["end"] <= gap
        ):
            merged[-1]["end"] = max(merged[-1]["end"], segment["end"])
        else:
            merged.append(dict(segment))
    merged.sort(key=lambda item: (item["start"], item["speaker"]))
    return merged


def polish_segments(raw: list, duration: float) -> list[dict]:
    cleaned = []
    for segment in raw:
        try:
            item = normalize_segment(segment)
        except (TypeError, ValueError, KeyError):
            continue
        item["start"] = min(duration, max(0.0, item["start"]))
        item["end"] = min(duration, max(0.0, item["end"]))
        if item["end"] - item["start"] >= 0.2:
            cleaned.append(item)
    cleaned = merge_same_speaker(cleaned, gap=0.25)

    def keep(min_total: float) -> list[dict]:
        totals: dict[int, float] = {}
        first: dict[int, float] = {}
        for segment in cleaned:
            speaker = segment["speaker"]
            totals[speaker] = totals.get(speaker, 0.0) + (segment["end"] - segment["start"])
            first[speaker] = min(first.get(speaker, duration), segment["start"])
        order = [speaker for speaker, total in totals.items() if total >= min_total]
        order.sort(key=lambda speaker: first[speaker])
        remap = {old: index + 1 for index, old in enumerate(order)}
        result = []
        for segment in cleaned:
            if segment["speaker"] not in remap:
                continue
            result.append({**segment, "speaker": remap[segment["speaker"]]})
        result.sort(key=lambda item: (item["start"], item["speaker"]))
        return result

    polished = keep(3.0)
    if not polished:
        polished = keep(1.5)
    return polished


def segments_from_logits(logits: torch.Tensor, hop: float = 0.01) -> list[dict]:
    probs = torch.sigmoid(logits.float().cpu())
    if probs.ndim == 3:
        probs = probs[0]
    array = probs.numpy()
    segments = []
    frames, speakers = array.shape
    for speaker in range(speakers):
        active = array[:, speaker] >= 0.5
        if not np.any(active):
            continue
        index = 0
        while index < frames:
            if not active[index]:
                index += 1
                continue
            end = index + 1
            while end < frames and active[end]:
                end += 1
            segments.append(
                {
                    "start": max(0.0, index * hop),
                    "end": end * hop,
                    "speaker": speaker,
                }
            )
            index = end
    return segments


def offline_logits(model, processor, audio: np.ndarray, sr: int) -> torch.Tensor:
    inputs = processor(audio, sampling_rate=sr)
    inputs = inputs.to(model.device, dtype=model.dtype)
    with torch.inference_mode():
        logits = model(**inputs).logits
    mask = inputs.attention_mask.cpu() if getattr(inputs, "attention_mask", None) is not None else None
    logits = logits.float().cpu()
    del inputs
    return logits, mask


def streaming_logits(model, processor, audio: np.ndarray, sr: int) -> torch.Tensor:
    processor.set_streaming_mode("low_latency")
    chunks = []

    def generate():
        total = len(audio)
        first_n = min(total, int(processor.num_samples_first_audio_chunk))
        yield processor(
            audio[:first_n],
            sampling_rate=sr,
            is_streaming=True,
            is_first_audio_chunk=True,
            is_last_audio_chunk=first_n >= total,
        )
        if first_n >= total:
            return
        mel_frame = processor.num_mel_frames_per_step
        start = int(processor.audio_chunk_start(mel_frame))
        while start < total:
            end = start + int(processor.num_samples_per_audio_chunk)
            last = end >= total
            piece = audio[start:] if last else audio[start:end]
            if len(piece) == 0:
                break
            yield processor(
                piece,
                sampling_rate=sr,
                is_streaming=True,
                is_first_audio_chunk=False,
                is_last_audio_chunk=last,
            )
            if last:
                break
            mel_frame += processor.num_mel_frames_per_step
            start = int(processor.audio_chunk_start(mel_frame))

    speaker_cache = None
    step = 0
    started = time.time()
    with torch.inference_mode():
        for inputs in generate():
            inputs = inputs.to(model.device, dtype=model.dtype)
            outputs = model(**inputs, speaker_cache=speaker_cache)
            chunks.append(outputs.logits.float().cpu())
            speaker_cache = outputs.speaker_cache
            step += 1
            if step % 100 == 0:
                print(
                    f"  диаризация по частям: шаг {step}, прошло {time.time() - started:.0f} с",
                    flush=True,
                )
            del inputs, outputs
    if not chunks:
        raise RuntimeError("диаризация не вернула ни одного фрагмента")
    return torch.cat(chunks, dim=1), None


def logits_to_segments(processor, logits: torch.Tensor, mask, duration: float) -> list[dict]:
    parsed = None
    try:
        if mask is None:
            parsed = processor.extract_speaker_dict(logits)
        else:
            parsed = processor.extract_speaker_dict(logits, mask)
    except Exception as exc:
        print(f"  разбор меток модели не удался ({exc}), беру порог по вероятности", flush=True)
    raw = parse_diar_output(parsed)
    if not raw:
        raw = segments_from_logits(logits)
    return polish_segments(raw, duration)


def diarize(audio: np.ndarray, sr: int, device: str) -> list[dict]:
    import transformers
    from packaging.version import Version

    version = transformers.__version__.split("+")[0]
    if Version(version) < Version("5.18.0"):
        raise RuntimeError(f"Нужен transformers >= 5.18.0, сейчас {transformers.__version__}.")
    from transformers import AutoModelForAudioFrameClassification, AutoProcessor

    print("Загружаю модель разделения голосов", flush=True)
    processor = AutoProcessor.from_pretrained(DIAR_MODEL)
    try:
        model = AutoModelForAudioFrameClassification.from_pretrained(
            DIAR_MODEL,
            dtype=torch.bfloat16,
            low_cpu_mem_usage=True,
        )
    except TypeError:
        model = AutoModelForAudioFrameClassification.from_pretrained(
            DIAR_MODEL,
            torch_dtype=torch.bfloat16,
            low_cpu_mem_usage=True,
        )
    model.to(device)
    model.eval()
    duration = len(audio) / sr
    print("Ищу голоса в записи", flush=True)
    try:
        with Heartbeat("ищу голоса"):
            logits, mask = offline_logits(model, processor, audio, sr)
    except Exception as exc:
        torch.cuda.empty_cache()
        if is_oom(exc):
            print("Весь файл сразу не поместился в лимит памяти. Считаю голоса по частям.", flush=True)
        else:
            print(f"Целиком посчитать голоса не вышло ({exc}). Считаю по частям.", flush=True)
        logits, mask = streaming_logits(model, processor, audio, sr)
    segments = logits_to_segments(processor, logits, mask, duration)
    del model, processor, logits, mask
    gc.collect()
    torch.cuda.empty_cache()
    return segments


def slice_audio(audio: np.ndarray, sr: int, start: float, end: float) -> np.ndarray:
    left = max(0, int(round(start * sr)))
    right = min(len(audio), int(round(end * sr)))
    if right <= left:
        return np.zeros(0, dtype=np.float32)
    return np.ascontiguousarray(audio[left:right])


def build_timeline(segments: list[dict], duration: float) -> list[dict]:
    bounds = {0.0, round(duration, 3)}
    for segment in segments:
        bounds.add(round(max(0.0, min(duration, segment["start"])), 3))
        bounds.add(round(max(0.0, min(duration, segment["end"])), 3))
    points = sorted(bounds)
    pieces = []
    for start, end in zip(points, points[1:]):
        if end - start < 0.02:
            continue
        midpoint = (start + end) / 2
        speakers = tuple(
            sorted(
                {
                    segment["speaker"]
                    for segment in segments
                    if segment["start"] <= midpoint < segment["end"]
                }
            )
        )
        pieces.append({"start": start, "end": end, "speakers": speakers})
    merged: list[dict] = []
    for piece in pieces:
        if not merged:
            merged.append(piece)
            continue
        previous = merged[-1]
        short = piece["end"] - piece["start"] < 0.15
        if short:
            previous["end"] = piece["end"]
            previous["speakers"] = tuple(sorted(set(previous["speakers"]) | set(piece["speakers"])))
        elif previous["speakers"] == piece["speakers"]:
            previous["end"] = piece["end"]
        else:
            merged.append(piece)
    return [
        piece
        for piece in merged
        if piece["speakers"] and piece["end"] - piece["start"] >= 0.2
    ]


def take_up_to(pieces: list[np.ndarray], sr: int, seconds: float) -> np.ndarray:
    remaining = int(seconds * sr)
    chunks = []
    for piece in sorted(pieces, key=len, reverse=True):
        if remaining <= 0:
            break
        part = piece[:remaining]
        if len(part) == 0:
            continue
        chunks.append(part)
        remaining -= len(part)
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks)


def fit_length(values: np.ndarray, size: int) -> np.ndarray:
    array = np.asarray(values, dtype=np.float32).reshape(-1)
    if len(array) == size:
        return array
    if len(array) > size:
        return array[:size].copy()
    if len(array) == 0:
        return np.zeros(size, dtype=np.float32)
    return np.pad(array, (0, size - len(array)))


def as_two_sources(estimated, size: int) -> tuple[np.ndarray, np.ndarray] | None:
    if isinstance(estimated, (list, tuple)):
        if len(estimated) >= 2 and torch.is_tensor(estimated[0]) and torch.is_tensor(estimated[1]):
            first = estimated[0].detach().float().cpu().numpy()
            second = estimated[1].detach().float().cpu().numpy()
            return fit_length(first, size), fit_length(second, size)
        estimated = estimated[0]
    array = estimated.detach().float().cpu().numpy() if torch.is_tensor(estimated) else np.asarray(estimated)
    array = np.squeeze(array)
    if array.ndim != 2:
        return None
    if array.shape[0] == 2:
        return fit_length(array[0], size), fit_length(array[1], size)
    if array.shape[1] == 2:
        return fit_length(array[:, 0], size), fit_length(array[:, 1], size)
    return None


def separate_two(separator, mix: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    if len(mix) < int(0.3 * SAMPLE_RATE) or rms(mix) < 1e-4:
        return None
    tensor = torch.tensor(np.ascontiguousarray(mix), dtype=torch.float32).unsqueeze(0)
    with torch.inference_mode():
        if hasattr(separator, "separate_batch"):
            estimated = separator.separate_batch(tensor)
        else:
            estimated = separator(tensor)
    sources = as_two_sources(estimated, len(mix))
    if sources is None:
        return None
    first, second = sources
    first_rms, second_rms = rms(first), rms(second)
    if max(first_rms, second_rms) < 1e-4:
        return None
    if min(first_rms, second_rms) < 0.08 * max(first_rms, second_rms):
        return None
    if cosine(first, second) > 0.98:
        return None
    return first, second


def embed(encoder, wav: np.ndarray) -> np.ndarray | None:
    wav = np.asarray(wav, dtype=np.float32).reshape(-1)
    if len(wav) < int(0.5 * SAMPLE_RATE):
        return None
    wav = wav[: 20 * SAMPLE_RATE]
    tensor = torch.tensor(np.ascontiguousarray(wav), dtype=torch.float32).unsqueeze(0)
    with torch.inference_mode():
        try:
            vector = encoder.encode_batch(tensor)
        except Exception:
            vector = encoder.encode_batch(tensor.unsqueeze(-1))
    array = vector.detach().float().cpu().numpy().reshape(-1)
    norm = float(np.linalg.norm(array))
    if norm < 1e-8:
        return None
    return array / norm


def assign_sources(encoder, enroll: dict, first: np.ndarray, second: np.ndarray, speakers: tuple[int, int]):
    left, right = speakers
    left_enroll, right_enroll = enroll.get(left), enroll.get(right)
    if left_enroll is None or right_enroll is None:
        return None
    first_sig = embed(encoder, first)
    second_sig = embed(encoder, second)
    if first_sig is None or second_sig is None:
        return None
    direct = cosine(first_sig, left_enroll) + cosine(second_sig, right_enroll)
    swapped = cosine(first_sig, right_enroll) + cosine(second_sig, left_enroll)
    if max(direct, swapped) < 0.25:
        return None
    if direct >= swapped:
        return {left: first, right: second}
    return {left: second, right: first}


def peak_norm(values: np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype=np.float32)
    if len(array) == 0:
        return array
    peak = float(np.max(np.abs(array)))
    if peak < 1e-4:
        return array
    if peak > 0.9:
        return array * (0.9 / peak)
    if peak < 0.05:
        return array * (0.2 / peak)
    return array


def _speechbrain_factory(device: str):
    try:
        from speechbrain.inference.separation import SepformerSeparation
        from speechbrain.inference.speaker import EncoderClassifier
    except ImportError:
        from speechbrain.pretrained import EncoderClassifier, SepformerSeparation
    from speechbrain.utils.fetching import LocalStrategy

    def hparams(factory, source: str, savedir: Path):
        return factory.from_hparams(
            source=source,
            savedir=str(savedir),
            run_opts={"device": device},
            local_strategy=LocalStrategy.COPY,
        )

    return hparams, SepformerSeparation, EncoderClassifier


def load_encoder(device: str):
    try:
        hparams, _separator_cls, encoder_cls = _speechbrain_factory(device)
        print("Снимаю отпечаток голоса", flush=True)
        return hparams(encoder_cls, EMB_MODEL, model_dir("ecapa"))
    except Exception as exc:
        print(f"Отпечаток голоса снять не удалось ({exc}).", flush=True)
        return None


def load_separator(device: str):
    try:
        hparams, separator_cls, _encoder_cls = _speechbrain_factory(device)
        print("Загружаю модель разделения одновременной речи", flush=True)
        return hparams(separator_cls, SEP_MODEL, model_dir("sepformer-whamr16k"))
    except Exception as exc:
        print(f"Разделить одновременную речь моделью не удалось ({exc}).", flush=True)
        print("Такие места останутся общей репликой обоих голосов.", flush=True)
        return None


def clip_of(start: float, end: float, audio: np.ndarray, speakers: tuple[int, ...], overlap: bool) -> dict:
    return {
        "start": start,
        "end": end,
        "audio": peak_norm(audio),
        "speakers": speakers,
        "overlap": overlap,
    }


def build_clips(audio: np.ndarray, sr: int, segments: list[dict], device: str):
    duration = len(audio) / sr
    timeline = build_timeline(segments, duration)
    exclusive: dict[int, list[np.ndarray]] = {}
    for piece in timeline:
        if len(piece["speakers"]) == 1:
            speaker = piece["speakers"][0]
            exclusive.setdefault(speaker, []).append(slice_audio(audio, sr, piece["start"], piece["end"]))

    has_pair = any(len(piece["speakers"]) == 2 and piece["end"] - piece["start"] >= 0.6 for piece in timeline)
    encoder = load_encoder(device)
    separator = load_separator(device) if has_pair else None

    enroll = {}
    embeddings: dict[str, list[float]] = {}
    if encoder is not None:
        for speaker, pieces in exclusive.items():
            sample = take_up_to(pieces, sr, 20.0)
            vector = embed(encoder, sample)
            if vector is None:
                continue
            enroll[speaker] = vector
            embeddings[speaker_name(speaker)] = [round(float(item), 5) for item in vector.reshape(-1)]

    tracks: dict[int, list[dict]] = {}
    shared: list[dict] = []
    overlap_sec = 0.0
    separated_sec = 0.0

    for piece in timeline:
        speakers = piece["speakers"]
        start, end = piece["start"], piece["end"]
        if len(speakers) >= 2:
            overlap_sec += end - start
        if len(speakers) == 1:
            tracks.setdefault(speakers[0], []).append(
                clip_of(start, end, slice_audio(audio, sr, start, end), speakers, False)
            )
            continue
        if len(speakers) != 2 or separator is None or end - start < 0.6:
            shared.append(clip_of(start, end, slice_audio(audio, sr, start, end), speakers, True))
            continue
        cursor = start
        while cursor < end - 0.05:
            chunk_end = min(end, cursor + 10.0)
            mix = slice_audio(audio, sr, cursor, chunk_end)
            sources = None
            try:
                sources = separate_two(separator, mix)
            except Exception as exc:
                print(f"  фрагмент {fmt_ts(cursor)} не разделился ({exc})", flush=True)
            assigned = None
            if sources is not None and encoder is not None:
                try:
                    assigned = assign_sources(encoder, enroll, sources[0], sources[1], speakers)
                except Exception as exc:
                    print(f"  не удалось сопоставить голоса {fmt_ts(cursor)} ({exc})", flush=True)
            if assigned is None:
                shared.append(clip_of(cursor, chunk_end, mix, speakers, True))
            else:
                separated_sec += chunk_end - cursor
                for speaker, wave in assigned.items():
                    tracks.setdefault(speaker, []).append(
                        clip_of(cursor, chunk_end, wave, (speaker,), True)
                    )
            cursor = chunk_end

    del separator, encoder
    gc.collect()
    torch.cuda.empty_cache()
    for speaker in tracks:
        tracks[speaker].sort(key=lambda item: item["start"])
    shared.sort(key=lambda item: item["start"])
    return tracks, shared, overlap_sec, separated_sec, embeddings


def build_track(clips: list[dict], sr: int, gap_sec: float = 0.3) -> tuple[np.ndarray, list[dict]]:
    gap_n = int(gap_sec * sr)
    pieces: list[np.ndarray] = []
    mapping = []
    cursor = 0.0
    for index, clip in enumerate(clips):
        wave = np.asarray(clip["audio"], dtype=np.float32).reshape(-1)
        if len(wave) == 0:
            continue
        if index > 0 and pieces:
            pieces.append(np.zeros(gap_n, dtype=np.float32))
            cursor += gap_sec
        duration = len(wave) / sr
        pieces.append(wave)
        mapping.append(
            {
                "track_start": cursor,
                "track_end": cursor + duration,
                "orig_start": float(clip["start"]),
                "orig_end": float(clip["end"]),
                "speakers": tuple(clip["speakers"]),
                "overlap": bool(clip["overlap"]),
            }
        )
        cursor += duration
    if not pieces:
        return np.zeros(0, dtype=np.float32), []
    return np.concatenate(pieces), mapping


def locate(mapping: list[dict], moment: float) -> dict | None:
    for piece in mapping:
        if piece["track_start"] - 0.05 <= moment <= piece["track_end"] + 0.05:
            return piece
    return None


def map_point(piece: dict, moment: float) -> float:
    rel = min(max(moment, piece["track_start"]), piece["track_end"]) - piece["track_start"]
    scale = (piece["orig_end"] - piece["orig_start"]) / max(1e-6, piece["track_end"] - piece["track_start"])
    return piece["orig_start"] + rel * scale


def load_asr(device: str):
    from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor

    print("Загружаю модель расшифровки", flush=True)
    processor = AutoProcessor.from_pretrained(ASR_MODEL)
    try:
        model = AutoModelForSpeechSeq2Seq.from_pretrained(
            ASR_MODEL,
            dtype=torch.float16,
            low_cpu_mem_usage=True,
            use_safetensors=True,
        )
    except TypeError:
        model = AutoModelForSpeechSeq2Seq.from_pretrained(
            ASR_MODEL,
            torch_dtype=torch.float16,
            low_cpu_mem_usage=True,
            use_safetensors=True,
        )
    model.to(device)
    model.eval()
    return model, processor


def detect_language(model, processor, sample: np.ndarray, device: str) -> str | None:
    if len(sample) < SAMPLE_RATE:
        return None
    features = processor.feature_extractor(
        sample[: 30 * SAMPLE_RATE],
        sampling_rate=SAMPLE_RATE,
        return_tensors="pt",
    ).input_features
    features = features.to(device=device, dtype=next(model.parameters()).dtype)
    model.generation_config.forced_decoder_ids = None
    model.generation_config.language = None
    start = torch.tensor([[model.config.decoder_start_token_id]], device=device)
    with torch.inference_mode():
        tokens = model.generate(features, decoder_input_ids=start, max_new_tokens=6, num_beams=1, do_sample=False)
    decoded = processor.tokenizer.decode(tokens[0], skip_special_tokens=False)
    print(f"Определение языка: {decoded}", flush=True)
    skip = {
        "startoftranscript",
        "transcribe",
        "translate",
        "notimestamps",
        "nospeech",
        "startoflm",
        "endoftext",
    }
    for code in re.findall(r"<\|([a-z]{2,3})\|>", decoded):
        if code not in skip:
            return code
    return None


def is_hallucination(text: str) -> bool:
    normalized = text.lower().strip(" .…!?,;:-—")
    blocked = {
        "продолжение следует",
        "субтитры создавал dimatorzok",
        "субтитры сделал dimatorzok",
        "субтитры подогнал dimatorzok",
        "спасибо за просмотр",
        "подписывайтесь на канал",
        "thanks for watching",
        "thank you for watching",
    }
    return normalized in blocked or normalized.startswith("субтитры ")


def overlapping_piece(mapping: list[dict], start: float, end: float) -> dict | None:
    best = None
    best_overlap = 0.0
    for piece in mapping:
        overlap = min(end, piece["track_end"]) - max(start, piece["track_start"])
        if overlap > best_overlap:
            best_overlap = overlap
            best = piece
    if best is None or best_overlap <= 0.05:
        return None
    return best


def transcribe_clips(model, processor, clips: list[dict], sr: int, language: str | None) -> list[dict]:
    track, mapping = build_track(clips, sr)
    if len(track) < int(0.25 * sr):
        return []
    inputs = processor(
        track,
        sampling_rate=sr,
        return_tensors="pt",
        truncation=False,
        return_attention_mask=True,
    )
    dtype = next(model.parameters()).dtype
    features = inputs.input_features.to(device=model.device, dtype=dtype)
    attention = inputs.attention_mask.to(device=model.device)
    generate_kwargs = {
        "input_features": features,
        "attention_mask": attention,
        "return_timestamps": True,
        "return_segments": True,
        "task": "transcribe",
    }
    if language:
        generate_kwargs["language"] = language
    last_print = time.time()

    def monitor(progress):
        nonlocal last_print
        try:
            now = time.time()
            if now - last_print < 20:
                return
            last_print = now
            index = int(torch.argmax(progress[:, 1]))
            done = int(progress[index, 0])
            total = max(1, int(progress[index, 1]))
            print(f"    {min(100, round(100 * done / total))}% дорожки", flush=True)
        except Exception:
            return

    with torch.inference_mode():
        generated = model.generate(**generate_kwargs, monitor_progress=monitor)
    segments = generated["segments"][0] if generated["segments"] and isinstance(generated["segments"][0], list) else generated["segments"]
    words = []
    for segment in segments:
        tokens = segment["tokens"]
        token_ids = tokens.tolist() if torch.is_tensor(tokens) else list(tokens)
        text = clean_text(processor.tokenizer.decode(token_ids, skip_special_tokens=True))
        if not text or is_hallucination(text) or not re.search(r"\w", text, flags=re.UNICODE):
            continue
        track_start = float(segment["start"])
        track_end = float(segment["end"])
        piece = overlapping_piece(mapping, track_start, track_end)
        if piece is None:
            continue
        start = map_point(piece, track_start)
        end = map_point(piece, track_end)
        if end < start:
            end = start + 0.2
        words.append(
            {
                "start": start,
                "end": max(end, start + 0.01),
                "text": text,
                "speakers": list(piece["speakers"]),
                "overlap": bool(piece["overlap"]),
            }
        )
    del features, attention, generated
    return words


def group_words(words: list[dict], max_gap: float = 1.2) -> list[dict]:
    ordered = sorted(words, key=lambda item: (item["start"], tuple(item["speakers"])))
    grouped = []
    current = None
    for word in ordered:
        key = (tuple(word["speakers"]), bool(word["overlap"]))
        if current and current["key"] == key and word["start"] - current["end"] <= max_gap:
            if word["text"].lower() != current["text"].lower():
                current["text"] = clean_text(current["text"] + " " + word["text"])
            current["end"] = max(current["end"], word["end"])
        else:
            if current:
                grouped.append(current)
            current = {
                "key": key,
                "speakers": list(word["speakers"]),
                "overlap": bool(word["overlap"]),
                "start": float(word["start"]),
                "end": float(word["end"]),
                "text": word["text"],
            }
    if current:
        grouped.append(current)
    for item in grouped:
        item.pop("key", None)
    return [item for item in grouped if item["text"]]


def speech_stats(segments: list[dict]) -> list[dict]:
    totals: dict[int, float] = {}
    first: dict[int, float] = {}
    for segment in segments:
        speaker = segment["speaker"]
        totals[speaker] = totals.get(speaker, 0.0) + (segment["end"] - segment["start"])
        first[speaker] = min(first.get(speaker, 1e9), segment["start"])
    rows = []
    for speaker in sorted(totals):
        rows.append(
            {
                "id": speaker,
                "label": speaker_name(speaker),
                "first_sec": round(first[speaker], 3),
                "speech_sec": round(totals[speaker], 3),
            }
        )
    return rows


def format_utterance(item: dict, with_speaker: bool) -> str:
    mark = ""
    if item["overlap"] or len(item["speakers"]) > 1:
        mark = " (одновременно)"
    if with_speaker:
        who = speakers_label(item["speakers"])
        return f"[{fmt_ts(item['start'])}] {who}{mark}: {item['text']}"
    if mark:
        return f"[{fmt_ts(item['start'])}]{mark}: {item['text']}"
    return f"[{fmt_ts(item['start'])}] {item['text']}"


def write_outputs(
    out_dir: Path,
    audio_path: Path,
    duration: float,
    language: str | None,
    segments: list[dict],
    utterances: list[dict],
    overlap_sec: float,
    separated_sec: float,
    gpu_fraction: float,
    speaker_embeddings: dict | None = None,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = speech_stats(segments)
    lang_code = language or "auto"
    lang_name = LANG_RU.get(lang_code, lang_code)
    header = [
        f"Файл: {audio_path.name}",
        f"Длительность: {fmt_dur(duration)}",
        f"Язык: {lang_name}",
        f"Голосов: {len(stats)}",
        f"Одновременная речь: {fmt_dur(overlap_sec)}",
        f"Из неё удалось разложить по голосам: {fmt_dur(separated_sec)}",
        f"Потолок загрузки видеокарты: 90%",
        "",
    ]
    for row in stats:
        header.append(
            f"{row['label']} — речь {fmt_dur(row['speech_sec'])}, впервые в {fmt_ts(row['first_sec'])}"
        )
    header.extend(["", "—" * 60, ""])
    full_lines = [format_utterance(item, with_speaker=True) for item in utterances]
    full_text = "\n".join(header + full_lines) + "\n"
    (out_dir / "общий_текст.txt").write_text(full_text, encoding="utf-8-sig")

    per_speaker = {}
    for row in stats:
        own = [item for item in utterances if row["id"] in item["speakers"]]
        lines = [
            row["label"],
            f"Речь: {fmt_dur(row['speech_sec'])}",
            "",
        ]
        lines.extend(format_utterance(item, with_speaker=False) for item in own)
        text = "\n".join(lines).rstrip() + "\n"
        per_speaker[row["label"]] = "\n".join(format_utterance(item, with_speaker=False) for item in own)
        (out_dir / f"голос_{row['id']}.txt").write_text(text, encoding="utf-8-sig")

    payload = {
        "audio": str(audio_path),
        "duration_sec": round(duration, 3),
        "language": lang_code,
        "gpu_memory_fraction": round(gpu_fraction, 4),
        "overlap_sec": round(overlap_sec, 3),
        "separated_overlap_sec": round(separated_sec, 3),
        "speakers": stats,
        "segments": segments,
        "utterances": utterances,
        "full_text": "\n".join(full_lines),
        "per_speaker_text": per_speaker,
        "speaker_embeddings": speaker_embeddings or {},
    }
    (out_dir / "результат.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload


def first_speech(audio: np.ndarray, sr: int, segments: list[dict]) -> np.ndarray:
    if not segments:
        return audio[: 30 * sr]
    start = min(segment["start"] for segment in segments)
    left = int(start * sr)
    return audio[left : left + 30 * sr]


def print_voices(segments: list[dict], overlap_sec: float) -> None:
    stats = speech_stats(segments)
    print(f"Найдено голосов: {len(stats)}", flush=True)
    for row in stats:
        print(
            f"  {row['label']}: речь {fmt_dur(row['speech_sec'])}, впервые в {fmt_ts(row['first_sec'])}",
            flush=True,
        )
    print(f"Одновременная речь: {fmt_dur(overlap_sec)}", flush=True)


def transcribe_jobs(model, processor, jobs: list[tuple[str, list[dict]]], language: str | None):
    words = []
    for title, clips in jobs:
        spoken = sum(clip["end"] - clip["start"] for clip in clips)
        print(f"Расшифровка: {title} ({fmt_dur(spoken)})", flush=True)
        words.extend(transcribe_clips(model, processor, clips, SAMPLE_RATE, language))
        torch.cuda.empty_cache()
    return group_words(words)


def recognize(
    audio_path: Path,
    *,
    language: str = "auto",
    gpu_fraction: float = 0.9,
    max_seconds: float = 0.0,
    output: Path | None = None,
) -> dict:
    """Полный прогон: голоса, фрагменты, общий текст и текст по каждому голосу."""
    configure_stdio()
    if not audio_path.is_file():
        raise FileNotFoundError(f"Нет файла: {audio_path}")
    fraction, budget, total, used = cap_gpu(gpu_fraction)
    print(f"Видеокарта: {torch.cuda.get_device_name(0)}", flush=True)
    print(
        f"Уже занято {used / 1024**3:.1f} ГБ из {total / 1024**3:.1f} ГБ. "
        f"Этот процесс возьмёт не больше {budget / 1024**3:.1f} ГБ.",
        flush=True,
    )
    audio, sr = load_audio(audio_path, max_seconds)
    duration = len(audio) / sr
    device = "cuda:0"
    segments = diarize(audio, sr, device)
    if not segments:
        raise RuntimeError("Голоса в записи не найдены.")
    rough_overlap = 0.0
    timeline = build_timeline(segments, duration)
    for piece in timeline:
        if len(piece["speakers"]) >= 2:
            rough_overlap += piece["end"] - piece["start"]
    print_voices(segments, rough_overlap)
    tracks, shared, overlap_sec, separated_sec, embeddings = build_clips(audio, sr, segments, device)
    model, processor = load_asr(device)
    if language == "auto":
        chosen = detect_language(model, processor, first_speech(audio, sr, segments), device)
    else:
        chosen = language
    jobs = []
    for speaker in sorted(tracks):
        if tracks[speaker]:
            jobs.append((speaker_name(speaker), tracks[speaker]))
    if shared:
        jobs.append(("одновременная речь", shared))
    utterances = transcribe_jobs(model, processor, jobs, chosen)
    del model, processor
    gc.collect()
    torch.cuda.empty_cache()
    out_dir = output if output is not None else ROOT / "output" / audio_path.stem
    return write_outputs(
        out_dir,
        audio_path,
        duration,
        chosen,
        segments,
        utterances,
        overlap_sec,
        separated_sec,
        fraction,
        embeddings,
    )


def main() -> int:
    configure_stdio()
    parser = argparse.ArgumentParser(description="Расшифровка аудио с разделением голосов")
    parser.add_argument("audio", nargs="?", default=str(ROOT / "Meeting-12-1002.wav"))
    parser.add_argument("--output", default="")
    parser.add_argument("--language", default="auto", help="Код языка, например ru, или auto")
    parser.add_argument("--gpu-fraction", type=float, default=0.9)
    parser.add_argument("--max-seconds", type=float, default=0.0)
    args = parser.parse_args()

    audio_path = Path(args.audio)
    if not audio_path.is_file():
        raise SystemExit(f"Нет файла: {audio_path}")
    if not 0.1 <= args.gpu_fraction <= 0.9:
        raise SystemExit("Доля видеокарты должна быть от 0.1 до 0.9")
    out_dir = Path(args.output) if args.output else None
    payload = recognize(
        audio_path,
        language=args.language,
        gpu_fraction=args.gpu_fraction,
        max_seconds=args.max_seconds,
        output=out_dir,
    )
    print(f"Готово. Реплик: {len(payload.get('utterances') or [])}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Остановлено", flush=True)
        raise SystemExit(130)
