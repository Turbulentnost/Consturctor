"""Сколько голосов в записи и где они говорят одновременно.

Диаризация группирует похожие голоса и даёт число. Разделение на два потока
включается только на кусках, где сразу двое. Имя берётся из asr-server/voices,
если образец голоса совпал. Иначе остаётся «голос N».
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

SAMPLE_RATE = 16000
WINDOW_SEC = 1.5
HOP_SEC = 0.75
# Ниже этого косинуса окно не присоединяется к уже услышанному голосу.
SAME_SPEAKER = 0.50
# Похожие центроиды после первого прохода — это один человек, а не новый голос.
MERGE_CENTROIDS = 0.48
MAX_SPEAKERS = 8
# Окно далеко от среднего голоса записи — похоже, что говорят двое сразу.
MIXED_SIM = 0.30
# Если два ближайших голоса почти одинаково похожи на окно, там говорят оба.
OVERLAP_MARGIN = 0.08
OVERLAP_MIN = 0.42
ENROLL_MIN = 0.62
MAX_TURN_SEC = 24.0


@dataclass
class Turn:
    start: float
    end: float
    speaker: str
    overlap: bool
    speakers: tuple[str, str] | None = None


def _norm(vector: np.ndarray) -> np.ndarray:
    scale = float(np.linalg.norm(vector))
    if scale < 1e-8:
        return vector.astype(np.float32)
    return (vector / scale).astype(np.float32)


def _resample(audio: np.ndarray, origin: int, target: int) -> np.ndarray:
    if origin == target or len(audio) == 0:
        return audio.astype(np.float32, copy=False)
    size = max(1, int(round(len(audio) * target / origin)))
    grid = np.linspace(0, len(audio) - 1, size)
    return np.interp(grid, np.arange(len(audio)), audio).astype(np.float32)


def cluster_hierarchical(embeddings: np.ndarray) -> tuple[list[int], bool]:
    """Число голосов — по самому большому разрыву в слиянии.

    Если разрыва нет, голоса с одного микрофона не различить: все окна остаются
    одним голосом, а одновременные куски ищутся отдельно.
    """
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import squareform

    matrix = np.stack([_norm(np.asarray(row, dtype=np.float32)) for row in embeddings])
    if len(matrix) < 4:
        return [0] * len(matrix), False
    similarity = np.clip(matrix @ matrix.T, -1.0, 1.0)
    distance = np.clip(1.0 - similarity, 0.0, 2.0)
    np.fill_diagonal(distance, 0.0)
    linked = linkage(squareform(distance, checks=False), method="average")
    tail = linked[-8:, 2] if len(linked) >= 8 else linked[:, 2]
    gaps = np.diff(tail)
    gap_at = int(np.argmax(gaps))
    if float(gaps[gap_at]) < 0.12:
        return [0] * len(matrix), False
    raw = fcluster(linked, t=float(tail[gap_at]) + 1e-4, criterion="distance")
    remap: dict[int, int] = {}
    labels: list[int] = []
    for item in raw:
        key = int(item)
        if key not in remap:
            remap[key] = 0 if len(remap) >= MAX_SPEAKERS else len(remap)
        labels.append(remap[key])
    return labels, len(set(labels)) > 1


def cluster_speakers(embeddings: np.ndarray, threshold: float = SAME_SPEAKER, limit: int = MAX_SPEAKERS) -> list[int]:
    """Онлайн-группировка уже нормированных векторов. Возвращает номер голоса на каждое окно."""
    labels: list[int] = []
    centroids: list[np.ndarray] = []
    counts: list[int] = []
    for raw in embeddings:
        vector = _norm(np.asarray(raw, dtype=np.float32))
        if not centroids:
            centroids.append(vector)
            counts.append(1)
            labels.append(0)
            continue
        scores = [float(np.dot(vector, item)) for item in centroids]
        best = int(np.argmax(scores))
        if scores[best] >= threshold or len(centroids) >= limit:
            counts[best] += 1
            centroids[best] = _norm(centroids[best] * (counts[best] - 1) + vector)
            labels.append(best)
            continue
        centroids.append(vector)
        counts.append(1)
        labels.append(len(centroids) - 1)
    return labels


def collapse_labels(embeddings: np.ndarray, labels: list[int], merge_at: float = MERGE_CENTROIDS) -> list[int]:
    labels = list(labels)
    while True:
        ids = sorted(set(labels))
        if len(ids) < 2:
            break
        centroids = {
            speaker: _norm(embeddings[[index for index, label in enumerate(labels) if label == speaker]].mean(axis=0))
            for speaker in ids
        }
        best: tuple[float, int, int] | None = None
        for left_at, left in enumerate(ids):
            for right in ids[left_at + 1 :]:
                score = float(np.dot(centroids[left], centroids[right]))
                if score >= merge_at and (best is None or score > best[0]):
                    best = (score, left, right)
        if best is None:
            break
        _score, left, right = best
        labels = [left if label == right else label for label in labels]
    remap: dict[int, int] = {}
    for label in labels:
        if label not in remap:
            remap[label] = len(remap)
    return [remap[label] for label in labels]


def overlap_pair(vector: np.ndarray, centroids: list[np.ndarray]) -> tuple[int, int] | None:
    if len(centroids) < 2:
        return None
    scores = [float(np.dot(_norm(vector), item)) for item in centroids]
    order = sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)
    first, second = order[0], order[1]
    if scores[first] < OVERLAP_MIN or scores[second] < OVERLAP_MIN:
        return None
    if scores[first] - scores[second] > OVERLAP_MARGIN:
        return None
    return first, second


def _speaker_name(index: int, enrolled: dict[int, str]) -> str:
    return enrolled.get(index) or f"голос {index + 1}"


def match_enrolled(centroids: list[np.ndarray], samples: list[tuple[str, np.ndarray]]) -> dict[int, str]:
    """Жадное сопоставление центроида с образцом. Один человек — один голос."""
    pairs: list[tuple[float, int, int]] = []
    for speaker, centroid in enumerate(centroids):
        for sample_index, (_name, sample) in enumerate(samples):
            score = float(np.dot(_norm(centroid), _norm(sample)))
            if score >= ENROLL_MIN:
                pairs.append((score, speaker, sample_index))
    pairs.sort(reverse=True)
    used_speakers: set[int] = set()
    used_samples: set[int] = set()
    found: dict[int, str] = {}
    for _score, speaker, sample_index in pairs:
        if speaker in used_speakers or sample_index in used_samples:
            continue
        used_speakers.add(speaker)
        used_samples.add(sample_index)
        found[speaker] = samples[sample_index][0]
    return found


def turns_from_windows(
    windows: list[tuple[float, float, int, tuple[int, int] | None]],
    names: dict[int, str],
) -> list[Turn]:
    """Окна (start, end, speaker, overlap_pair) склеиваются в куски для распознавания."""
    turns: list[Turn] = []
    current: Turn | None = None
    for start, end, speaker, pair in windows:
        if pair is not None:
            left, right = pair
            label = (_speaker_name(left, names), _speaker_name(right, names))
            if (
                current is not None
                and current.overlap
                and current.speakers == label
                and start - current.end < 0.3
                and end - current.start <= 8
            ):
                current.end = end
                continue
            if current is not None:
                turns.append(current)
                current = None
            current = Turn(start, end, label[0], True, label)
            continue
        name = _speaker_name(speaker, names)
        if (
            current is not None
            and not current.overlap
            and current.speaker == name
            and start - current.end < 0.45
            and end - current.start <= MAX_TURN_SEC
        ):
            current.end = end
            continue
        if current is not None:
            turns.append(current)
        current = Turn(start, end, name, False, None)
    if current is not None:
        turns.append(current)
    return [item for item in turns if item.end - item.start >= 0.4]


class VoiceSplitter:
    def __init__(self) -> None:
        self.device = "cuda:0"
        self.vad: Any = None
        self.get_timestamps: Any = None
        self.encoder: Any = None
        self.separator: Any = None
        self.ready = False

    def load(self, cache: Path) -> None:
        import torch

        cache.mkdir(parents=True, exist_ok=True)
        vad, utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            trust_repo=True,
        )
        self.vad = vad.to(self.device)
        self.get_timestamps = utils[0]
        from speechbrain.inference.speaker import EncoderClassifier
        from speechbrain.inference.separation import SepformerSeparation
        from speechbrain.utils.fetching import LocalStrategy

        copy = LocalStrategy.COPY
        self.encoder = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir=str(cache / "ecapa"),
            run_opts={"device": self.device},
            local_strategy=copy,
        )
        self.separator = SepformerSeparation.from_hparams(
            source="speechbrain/sepformer-wsj02mix",
            savedir=str(cache / "sepformer"),
            run_opts={"device": self.device},
            local_strategy=copy,
        )
        self.ready = True

    def _speech_mask(self, audio: np.ndarray) -> list[tuple[int, int]]:
        import torch

        wav = torch.tensor(audio, device=self.device)
        stamps = self.get_timestamps(wav, self.vad, sampling_rate=SAMPLE_RATE)
        return [(int(item["start"]), int(item["end"])) for item in stamps]

    def _embed_batch(self, chunks: list[np.ndarray]) -> np.ndarray:
        import torch

        wavs = torch.tensor(np.stack(chunks), device=self.device)
        with torch.inference_mode():
            encoded = self.encoder.encode_batch(wavs)
        vectors = encoded.detach().float().cpu().numpy().reshape(len(chunks), -1)
        return np.stack([_norm(item) for item in vectors])

    def _enrolled(self, voices: Path) -> list[tuple[str, np.ndarray]]:
        if not voices.is_dir():
            return []
        found: list[tuple[str, np.ndarray]] = []
        for path in sorted(voices.iterdir()):
            if path.suffix.lower() not in {".wav", ".mp3", ".m4a", ".flac", ".ogg"}:
                continue
            audio = _load_voice(path)
            if audio is None or len(audio) < SAMPLE_RATE:
                continue
            piece = audio[: SAMPLE_RATE * 8]
            if len(piece) < WINDOW_SEC * SAMPLE_RATE:
                continue
            vector = self._embed_batch([_fit(piece)])[0]
            found.append((path.stem.replace("_", " "), vector))
        return found

    def _centroids(self, embeddings: np.ndarray, labels: list[int]) -> list[np.ndarray]:
        count = max(labels) + 1 if labels else 0
        centroids: list[np.ndarray] = []
        for speaker in range(count):
            rows = embeddings[[index for index, label in enumerate(labels) if label == speaker]]
            centroids.append(_norm(rows.mean(axis=0)))
        return centroids

    def analyze(self, audio: np.ndarray, voices: Path) -> tuple[list[Turn], int, list[str]]:
        if not self.ready:
            raise RuntimeError("Модели голосов ещё не загружены")
        spans = self._speech_mask(audio)
        window = int(WINDOW_SEC * SAMPLE_RATE)
        hop = int(HOP_SEC * SAMPLE_RATE)
        slots: list[tuple[float, float, np.ndarray]] = []
        chunks: list[np.ndarray] = []
        for start, end in spans:
            cursor = start
            while cursor + window <= end:
                piece = audio[cursor : cursor + window]
                chunks.append(piece)
                slots.append((cursor / SAMPLE_RATE, (cursor + window) / SAMPLE_RATE, piece))
                cursor += hop
        if not chunks:
            return [Turn(0.0, len(audio) / SAMPLE_RATE, "голос 1", False)], 1, ["голос 1"]
        embeddings = self._embed_many(chunks)
        labels, separable = cluster_hierarchical(embeddings)
        centroids = self._centroids(embeddings, labels)
        enrolled = match_enrolled(centroids, self._enrolled(voices))
        center = _norm(embeddings.mean(axis=0))
        windows: list[tuple[float, float, int, tuple[int, int] | None]] = []
        for (start, end, _piece), vector, label in zip(slots, embeddings, labels):
            if separable:
                pair = overlap_pair(vector, centroids)
                if pair is not None and label not in pair:
                    pair = (label, pair[0] if pair[0] != label else pair[1])
            else:
                pair = (0, 1) if float(np.dot(vector, center)) < MIXED_SIM else None
            windows.append((start, end, label, pair))
        planned = turns_from_windows(windows, enrolled)
        names: list[str] = []
        for turn in planned:
            heard = turn.speakers if turn.overlap and turn.speakers else (turn.speaker,)
            for name in heard:
                if name not in names:
                    names.append(name)
        return planned, len(names), names

    def _embed_many(self, chunks: list[np.ndarray]) -> np.ndarray:
        rows: list[np.ndarray] = []
        batch = 32
        for offset in range(0, len(chunks), batch):
            rows.append(self._embed_batch(chunks[offset : offset + batch]))
        return np.concatenate(rows, axis=0)

    def separate(self, audio: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        import torch

        rate = int(getattr(self.separator.hparams, "sample_rate", 8000))
        mix = _resample(audio, SAMPLE_RATE, rate)
        tensor = torch.tensor(mix, device=self.device).unsqueeze(0)
        with torch.inference_mode():
            estimate = self.separator.separate_batch(tensor)
        array = estimate.detach().float().cpu().numpy()
        array = np.squeeze(array)
        if array.ndim == 1:
            array = np.stack([array, np.zeros_like(array)])
        if array.shape[0] > array.shape[-1]:
            array = array.T
        left = _resample(array[0], rate, SAMPLE_RATE)
        right = _resample(array[1] if array.shape[0] > 1 else array[0], rate, SAMPLE_RATE)
        return _fit_length(left, len(audio)), _fit_length(right, len(audio))


def _fit(audio: np.ndarray) -> np.ndarray:
    need = int(WINDOW_SEC * SAMPLE_RATE)
    if len(audio) >= need:
        return audio[:need]
    return np.pad(audio, (0, need - len(audio)))


def _fit_length(audio: np.ndarray, size: int) -> np.ndarray:
    if len(audio) == size:
        return audio
    if len(audio) > size:
        return audio[:size]
    return np.pad(audio, (0, size - len(audio)))


def _load_voice(path: Path) -> np.ndarray | None:
    try:
        import av
    except ImportError:
        return None
    try:
        container = av.open(str(path))
    except av.AVError:
        return None
    stream = next((item for item in container.streams if item.type == "audio"), None)
    if stream is None:
        container.close()
        return None
    resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
    chunks: list[np.ndarray] = []
    for frame in container.decode(stream):
        for item in resampler.resample(frame):
            chunks.append(item.to_ndarray().reshape(-1))
    container.close()
    if not chunks:
        return None
    return np.concatenate(chunks).astype(np.float32)
