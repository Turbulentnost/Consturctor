from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from uuid import uuid4

from app.api_client import (
    FunctionActor,
    MatchEvidence,
    RegulationFragment,
    RegulationParseResult,
    RoleFunction,
    RoleMatch,
    RoleMatchResult,
)
from app.config import DESKTOP_ROOT, REPO_ROOT, _env_value


def jwt_secret() -> str:
    env = os.getenv("JWT_SECRET", "").strip()
    if env:
        return env
    for path in (
        DESKTOP_ROOT / ".env",
        REPO_ROOT / "backend" / ".env",
        DESKTOP_ROOT.parent / "backend" / ".env",
    ):
        value = _env_value(path, "JWT_SECRET")
        if value:
            return value
    return "change-me"


def mint_local_access_token(
    user_id: str,
    fio: str,
    department: str = "",
    position: str = "",
    *,
    secret: str = "",
    expire_minutes: int = 480,
) -> str:
    key = (secret or jwt_secret()).strip()
    if not key or not user_id:
        return ""
    now = int(time.time())
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode("utf-8"))
    payload = _b64url(
        json.dumps(
            {
                "sub": user_id,
                "fio": fio,
                "department": department,
                "position": position,
                "sid": str(uuid4()),
                "iat": now,
                "exp": now + max(60, expire_minutes) * 60,
            },
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    )
    signing = f"{header}.{payload}".encode("utf-8")
    signature = _b64url(hmac.new(key.encode("utf-8"), signing, hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


def parse_local_regulation(path: str) -> RegulationParseResult:
    file_path = Path(path)
    text = _read_document(file_path)
    paragraphs = [part.strip() for part in text.splitlines() if part.strip()]
    if not paragraphs:
        paragraphs = [f"Документ {file_path.name} загружен локально."]
    fragments = [
        RegulationFragment(
            fragment_id=f"local-f{index}",
            page=1,
            section="Документ",
            kind="text",
            text=paragraph[:4000],
            table=None,
            ocr_confidence=1.0,
            section_path=["Документ"],
            block_type="paragraph",
        )
        for index, paragraph in enumerate(paragraphs[:80], start=1)
    ]
    return RegulationParseResult(
        regulation_id=f"local-{uuid4().hex[:12]}",
        file_name=file_path.name,
        page_count=1,
        table_count=0,
        section_count=1,
        recognition_quality=1.0,
        is_scan=False,
        sections=["Документ"],
        fragments=fragments,
    )


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def local_role_match(
    regulation: RegulationParseResult,
    position: str,
    department: str,
) -> RoleMatchResult:
    matches: list[RoleMatch] = []
    functions: list[RoleFunction] = []
    actor = FunctionActor(text=position, canonical_position=position, source_block_id="")
    for index, fragment in enumerate(regulation.fragments[:24], start=1):
        function = RoleFunction(
            function_id=f"local-fn{index}",
            target_block_id=fragment.fragment_id,
            is_function=True,
            title=(fragment.text[:80] or f"Блок {index}").strip(),
            actor=actor,
            action="выполняет",
            object=fragment.section or "регламент",
            recipient="",
            conditions=[],
            dependencies=[],
            evidence=[MatchEvidence(fragment_id=fragment.fragment_id, quote=fragment.text[:240])],
            proof_chain=[],
            explanation="Локальный разбор без сервера: блок взят из загруженного документа.",
            confidence=0.9,
            duplicate_group="",
            requires_confirmation=False,
        )
        functions.append(function)
        matches.append(
            RoleMatch(
                match_id=f"local-m{index}",
                fragment_id=fragment.fragment_id,
                relation="direct",
                match_types=["position"],
                confidence=0.9,
                model_confidence=0.9,
                explanation=function.explanation,
                requires_confirmation=False,
                status="accepted",
                fragment=fragment,
                signals=[],
                function=function,
            )
        )
    return RoleMatchResult(
        run_id=f"local-run-{uuid4().hex[:8]}",
        regulation_id=regulation.regulation_id,
        canonical_title=position,
        department=department,
        matches=matches,
        functions=functions,
        audit={"source": "local"},
    )


def _read_document(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".markdown"}:
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".docx":
        try:
            import docx
        except ImportError:
            return ""
        document = docx.Document(str(path))
        return "\n".join(para.text for para in document.paragraphs)
    return ""
