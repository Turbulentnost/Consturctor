from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from app.vendors.aiagentback.tools.fs.paths import (
    canonicalize_path_str,
    ensure_under_allowed_roots,
    is_absolute_path,
    join_root_segments,
    name_similarity,
    normalize_path_str,
    parse_allowed_roots,
    path_under_root,
    split_segments,
    to_path,
)


@dataclass(frozen=True)
class PathCandidate:
    path: str
    score: float


@dataclass
class ResolveResult:
    match_type: str  # exact | fuzzy | ambiguous | not_found
    resolved_path: str | None = None
    score: float | None = None
    candidates: list[PathCandidate] = field(default_factory=list)
    ok: bool = False


def _listdir_names(directory: Path) -> list[str]:
    try:
        return [entry.name for entry in os.scandir(directory)]
    except OSError:
        return []


def _longest_existing_prefix(root: str, segments: list[str]) -> tuple[str, list[str]]:
    current = normalize_path_str(root)
    remaining = list(segments)
    while remaining:
        nxt = join_root_segments(current, [remaining[0]])
        if to_path(nxt).exists():
            current = nxt
            remaining.pop(0)
        else:
            break
    return current, remaining


def _score_segment_matches(query_segment: str, names: list[str]) -> list[tuple[str, float]]:
    scored = [(name, name_similarity(query_segment, name)) for name in names]
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored


def _walk_filename_candidates(
    start: Path,
    query: str,
    *,
    max_entries: int,
) -> list[PathCandidate]:
    found: list[PathCandidate] = []
    scanned = 0
    if not start.is_dir():
        return found
    for dirpath, _dirnames, filenames in os.walk(start):
        for filename in filenames:
            scanned += 1
            if scanned > max_entries:
                return found
            score = name_similarity(query, filename)
            if score <= 0:
                continue
            found.append(PathCandidate(path=str(Path(dirpath) / filename), score=score))
        if scanned > max_entries:
            break
    found.sort(key=lambda item: item.score, reverse=True)
    return found


def _relative_segments(path: str, root: str) -> list[str]:
    path_norm = canonicalize_path_str(path)
    root_norm = canonicalize_path_str(root).rstrip("\\")
    if path_key_equal(path_norm, root_norm):
        return []
    prefix = root_norm + "\\"
    if path_norm.casefold().startswith(prefix.casefold()):
        remainder = path_norm[len(root_norm) :].lstrip("\\")
        return [p for p in remainder.split("\\") if p]
    _prefix, segments = split_segments(path_norm)
    return segments


def path_key_equal(a: str, b: str) -> bool:
    return normalize_path_str(a).casefold() == normalize_path_str(b).casefold()


def _pick_result(
    ranked: list[PathCandidate],
    *,
    min_score: float,
    max_candidates: int,
) -> ResolveResult:
    if not ranked:
        return ResolveResult(match_type="not_found", ok=False, candidates=[])

    top = ranked[:max_candidates]
    best = top[0]
    near_best = [
        c
        for c in top
        if c.score >= min_score and abs(c.score - best.score) < 0.02
    ]
    second = top[1].score if len(top) > 1 else 0.0
    clear_winner = (
        best.score >= min_score
        and (best.score - second) >= 0.05
        and len(near_best) == 1
    )
    if clear_winner:
        match_type = "exact" if best.score >= 0.999 else "fuzzy"
        return ResolveResult(
            match_type=match_type,
            resolved_path=best.path,
            score=best.score,
            candidates=top,
            ok=True,
        )

    if best.score >= min_score:
        return ResolveResult(
            match_type="ambiguous",
            resolved_path=None,
            score=best.score,
            candidates=top,
            ok=False,
        )

    return ResolveResult(
        match_type="not_found",
        resolved_path=None,
        score=best.score,
        candidates=top,
        ok=False,
    )


def _resolve_under_root(
    root: str,
    segments: list[str],
    *,
    query: str | None,
    min_score: float,
    max_candidates: int,
    max_entries: int,
) -> ResolveResult:
    root_norm = normalize_path_str(root)
    root_path = to_path(root_norm)
    # UNC server roots like \\host are not real filesystem nodes; shares live at
    # \\host\share. Only bail out when there is nothing to descend into.
    if not root_path.exists() and not segments and not query:
        return ResolveResult(match_type="not_found", ok=False)

    if not segments and not query:
        if not root_path.exists():
            return ResolveResult(match_type="not_found", ok=False)
        return ResolveResult(
            match_type="exact",
            resolved_path=root_norm,
            score=1.0,
            candidates=[PathCandidate(path=root_norm, score=1.0)],
            ok=True,
        )

    current, remaining = _longest_existing_prefix(root_norm, segments)

    if not remaining and not query:
        if to_path(current).exists():
            return ResolveResult(
                match_type="exact",
                resolved_path=current,
                score=1.0,
                candidates=[PathCandidate(path=current, score=1.0)],
                ok=True,
            )

    cursor = current
    matched_segments = 0
    for index, segment in enumerate(remaining):
        names = _listdir_names(to_path(cursor))
        if not names:
            break
        scored = _score_segment_matches(segment, names)
        if not scored:
            break
        best_name, best_score = scored[0]
        is_last = index == len(remaining) - 1

        if best_score < min_score:
            # Directory names often differ only by a space after the number
            # ("22. Name" in a reply vs "22.Name" on the share).
            soft_hits = [
                (name, score)
                for name, score in scored
                if score >= max(0.55, min_score - 0.2)
            ]
            if soft_hits:
                best_name, best_score = soft_hits[0]
            else:
                walk_hits = _walk_filename_candidates(
                    to_path(cursor),
                    segment,
                    max_entries=max_entries,
                )
                filtered = [c for c in walk_hits if path_under_root(c.path, root_norm)]
                return _pick_result(
                    filtered,
                    min_score=min_score,
                    max_candidates=max_candidates,
                )

        close = [
            name
            for name, score in scored
            if score >= min(best_score, min_score) and (best_score - score) < 0.05
        ]
        if len(close) > 1 and not is_last:
            candidates = [
                PathCandidate(path=join_root_segments(cursor, [name]), score=score)
                for name, score in scored[:max_candidates]
                if score >= max(0.55, min_score - 0.2)
            ]
            return ResolveResult(
                match_type="ambiguous",
                candidates=candidates,
                score=best_score,
                ok=False,
            )

        cursor = join_root_segments(cursor, [best_name])
        matched_segments += 1

    # Segments already matched as directories/files must not be re-searched as a
    # filename inside the resolved cursor (e.g. "22. Служба" ≈ "22.Служба").
    unmatched = remaining[matched_segments:]
    search_name = (query or (unmatched[-1] if unmatched else "")).strip()
    cursor_path = to_path(cursor)

    if cursor_path.is_file() and not query:
        return ResolveResult(
            match_type="fuzzy" if matched_segments else "exact",
            resolved_path=normalize_path_str(str(cursor_path)),
            score=1.0,
            candidates=[PathCandidate(path=normalize_path_str(str(cursor_path)), score=1.0)],
            ok=True,
        )

    if search_name and (query or unmatched):
        local_names = _listdir_names(cursor_path) if cursor_path.is_dir() else []
        local_hits = [
            PathCandidate(path=join_root_segments(cursor, [name]), score=score)
            for name, score in _score_segment_matches(search_name, local_names)
            if score > 0
        ]
        if local_hits and local_hits[0].score >= min_score:
            return _pick_result(
                local_hits,
                min_score=min_score,
                max_candidates=max_candidates,
            )

        walk_root = cursor_path if cursor_path.is_dir() else cursor_path.parent
        walk_hits = _walk_filename_candidates(
            walk_root,
            search_name,
            max_entries=max_entries,
        )
        filtered = [c for c in walk_hits if path_under_root(c.path, root_norm)]
        return _pick_result(
            filtered,
            min_score=min_score,
            max_candidates=max_candidates,
        )

    if cursor_path.exists():
        resolved = normalize_path_str(str(cursor_path))
        match_type = "exact" if matched_segments == 0 and not remaining else "fuzzy"
        return ResolveResult(
            match_type=match_type,
            resolved_path=resolved,
            score=1.0 if match_type == "exact" else max(min_score, 0.9),
            candidates=[PathCandidate(path=resolved, score=1.0)],
            ok=True,
        )

    return ResolveResult(match_type="not_found", ok=False)


def resolve_path(
    path: str,
    *,
    allowed_roots: list[str] | tuple[str, ...] | str | None,
    query: str | None = None,
    min_score: float = 0.72,
    max_candidates: int = 8,
    max_entries: int = 5000,
) -> ResolveResult:
    """Находит путь внутри allowlist: exact / fuzzy / ambiguous / not_found."""
    roots = parse_allowed_roots(allowed_roots)
    if not roots:
        raise ValueError("Не заданы разрешённые корни FS_ALLOWED_ROOTS")

    raw = canonicalize_path_str(path or "") if (path or "").strip() else ""
    query_name = (query or "").strip() or None

    if raw and is_absolute_path(raw):
        matched_root = next((root for root in roots if path_under_root(raw, root)), None)
        if matched_root is None:
            _prefix, segments = split_segments(raw)
            best: ResolveResult | None = None
            for root in roots:
                result = _resolve_under_root(
                    root,
                    segments,
                    query=query_name,
                    min_score=min_score,
                    max_candidates=max_candidates,
                    max_entries=max_entries,
                )
                if result.ok:
                    return result
                if best is None or (result.score or 0) > (best.score or 0):
                    best = result
            if best and best.candidates:
                return best
            raise ValueError(
                f"Путь вне разрешённых корней: {raw}. "
                f"Разрешено: {', '.join(roots)}"
            )

        if to_path(raw).exists() and not query_name:
            safe = ensure_under_allowed_roots(raw, roots)
            return ResolveResult(
                match_type="exact",
                resolved_path=safe,
                score=1.0,
                candidates=[PathCandidate(path=safe, score=1.0)],
                ok=True,
            )

        rel_segments = _relative_segments(raw, matched_root)
        return _resolve_under_root(
            matched_root,
            rel_segments,
            query=query_name,
            min_score=min_score,
            max_candidates=max_candidates,
            max_entries=max_entries,
        )

    segments = split_segments(raw)[1] if raw else []
    combined: list[PathCandidate] = []
    exact_hits: list[ResolveResult] = []

    for root in roots:
        result = _resolve_under_root(
            root,
            segments,
            query=query_name,
            min_score=min_score,
            max_candidates=max_candidates,
            max_entries=max_entries,
        )
        if result.ok and result.resolved_path:
            exact_hits.append(result)
        combined.extend(result.candidates)

    if len(exact_hits) == 1:
        return exact_hits[0]
    if len(exact_hits) > 1:
        return ResolveResult(
            match_type="ambiguous",
            candidates=[
                PathCandidate(path=item.resolved_path or "", score=item.score or 1.0)
                for item in exact_hits
                if item.resolved_path
            ][:max_candidates],
            score=1.0,
            ok=False,
        )

    seen: set[str] = set()
    unique: list[PathCandidate] = []
    combined.sort(key=lambda item: item.score, reverse=True)
    for item in combined:
        key = item.path.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) >= max_candidates:
            break

    return _pick_result(unique, min_score=min_score, max_candidates=max_candidates)
