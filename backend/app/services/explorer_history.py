"""История изменений базы знаний в скрытом git-репозитории папки владельца.

Репозиторий создаётся вместе с первым файлом пользователя: «<папка>/.orchestrator-git».
Каждое содержимое в нём зашифровано ключом репозитория из Postgres, поэтому сам
репозиторий без системы бесполезен. Изменения каждого сотрудника идут в его
собственную ветку «user-<id>», ветка «main» — снимок папки на момент создания.

Git вызывается только plumbing-командами через временный индекс: рабочей копии
нет, и запись не мешает файлам пользователя.
"""

from __future__ import annotations

import ctypes
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from app.models.explorer import ExplorerHistoryRepo

log = logging.getLogger(__name__)

REPO_DIR = ".orchestrator-git"
BLOB_MAGIC = b"ORCHH1"
BASE_BRANCH = "main"
GIT_TIMEOUT_S = 120
_EMAIL_DOMAIN = "orchestrator.local"
_REF_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="explorer-history")
_git_missing_logged = False
_lock = threading.Lock()

# (путь в репозитории, путь на диске, ключ файла) — для снимка уже существующих файлов.
BaselineSource = tuple[str, Path, str]
Reader = Callable[[Path, str], bytes]


@dataclass
class Change:
    path: str
    # None — файл удалён; для удаления папки путь заканчивается на «/».
    data: bytes | None


class HistoryError(Exception):
    pass


def branch_for(user_id: str) -> str:
    slug = _REF_UNSAFE.sub("-", user_id or "").strip(".-") or "unknown"
    return f"user-{slug}"


def repo_path(owner_dir: Path) -> Path:
    return owner_dir / REPO_DIR


def _git_exe() -> str | None:
    global _git_missing_logged
    exe = shutil.which("git")
    if exe is None and not _git_missing_logged:
        _git_missing_logged = True
        log.warning("git не найден: история базы знаний не записывается")
    return exe


def _git(
    exe: str,
    repo: Path,
    *args: str,
    stdin: bytes | None = None,
    env: dict[str, str] | None = None,
) -> str:
    cmd = [
        exe,
        "-c",
        "safe.directory=*",
        "-c",
        "core.quotepath=off",
        "--literal-pathspecs",
        f"--git-dir={repo}",
        *args,
    ]
    result = subprocess.run(
        cmd,
        input=stdin,
        capture_output=True,
        timeout=GIT_TIMEOUT_S,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env or {})},
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        raise HistoryError(
            f"git {args[0]}: {result.stderr.decode('utf-8', 'replace').strip() or result.returncode}"
        )
    return result.stdout.decode("utf-8", "replace").strip()


def _hide(path: Path) -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x2)  # FILE_ATTRIBUTE_HIDDEN
    except Exception:  # noqa: BLE001
        pass


def _tip(exe: str, repo: Path, branch: str) -> str | None:
    try:
        return _git(exe, repo, "rev-parse", "--verify", "-q", f"refs/heads/{branch}^{{commit}}")
    except HistoryError:
        return None


def _identity(name: str, user_id: str) -> dict[str, str]:
    email = f"{branch_for(user_id)}@{_EMAIL_DOMAIN}"
    return {
        "GIT_AUTHOR_NAME": name or user_id or "Сотрудник",
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": "Orchestrator",
        "GIT_COMMITTER_EMAIL": f"system@{_EMAIL_DOMAIN}",
    }


def _commit(
    exe: str,
    repo: Path,
    key: str,
    branch: str,
    start_from: str,
    changes: list[Change],
    message: str,
    identity: dict[str, str],
) -> str:
    own_tip = _tip(exe, repo, branch)
    parent = own_tip or _tip(exe, repo, start_from)
    fernet = Fernet(key.encode("ascii"))
    fd, index_name = tempfile.mkstemp(prefix="orch-index-")
    os.close(fd)
    os.unlink(index_name)
    env = {**identity, "GIT_INDEX_FILE": index_name}
    try:
        if parent:
            _git(exe, repo, "read-tree", parent, env=env)
        lines: list[str] = []
        for change in changes:
            if change.data is None:
                listed = _git(exe, repo, "ls-files", "-z", "--", change.path, env=env)
                for path in filter(None, listed.split("\0")):
                    lines.append(f"0 {'0' * 40}\t{path}")
                continue
            blob = BLOB_MAGIC + fernet.encrypt(change.data)
            sha = _git(exe, repo, "hash-object", "-w", "--stdin", stdin=blob)
            lines.append(f"100644 {sha}\t{change.path}")
        if lines:
            _git(
                exe,
                repo,
                "update-index",
                "-z",
                "--index-info",
                stdin="".join(f"{line}\0" for line in lines).encode("utf-8"),
                env=env,
            )
        tree = _git(exe, repo, "write-tree", env=env)
        if parent and tree == _git(exe, repo, "rev-parse", f"{parent}^{{tree}}"):
            return parent
        args = ["commit-tree", tree, "-F", "-"]
        if parent:
            args[2:2] = ["-p", parent]
        sha = _git(exe, repo, *args, stdin=message.encode("utf-8"), env=env)
        _git(exe, repo, "update-ref", f"refs/heads/{branch}", sha, own_tip or "0" * 40)
        return sha
    finally:
        Path(index_name).unlink(missing_ok=True)
        Path(index_name + ".lock").unlink(missing_ok=True)


def _init_repo(
    exe: str,
    repo: Path,
    key: str,
    owner_name: str,
    owner_user_id: str,
    baseline: list[BaselineSource],
    reader: Reader,
) -> None:
    if not (repo / "HEAD").exists():
        repo.mkdir(parents=True, exist_ok=True)
        _git(exe, repo, "init", "--bare", "-q", f"--initial-branch={BASE_BRANCH}")
        _git(exe, repo, "config", "gc.auto", "0")
        _hide(repo)
    if _tip(exe, repo, BASE_BRANCH):
        return
    changes: list[Change] = []
    for path, disk_path, file_key in baseline:
        try:
            changes.append(Change(path, reader(disk_path, file_key)))
        except Exception as exc:  # noqa: BLE001
            log.warning("история: не удалось прочитать %s для снимка: %s", disk_path, exc)
    _commit(
        exe,
        repo,
        key,
        BASE_BRANCH,
        BASE_BRANCH,
        changes,
        "Создана история папки",
        _identity(owner_name, owner_user_id),
    )


def _write(
    owner_dir: Path,
    key: str,
    owner_name: str,
    owner_user_id: str,
    baseline: list[BaselineSource],
    reader: Reader,
    actor_id: str,
    actor_name: str,
    changes: list[Change],
    message: str,
) -> None:
    exe = _git_exe()
    if exe is None:
        return
    repo = repo_path(owner_dir)
    try:
        with _lock:
            _init_repo(exe, repo, key, owner_name, owner_user_id, baseline, reader)
            _commit(
                exe,
                repo,
                key,
                branch_for(actor_id),
                BASE_BRANCH,
                changes,
                message,
                _identity(actor_name, actor_id),
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("история базы знаний не записана (%s): %s", owner_dir, exc)


def _repo_key(
    db: Session, owner_folder: str, owner_user_id: str
) -> tuple[str, bool]:
    row = db.get(ExplorerHistoryRepo, owner_folder)
    if row is not None:
        return row.key, False
    row = ExplorerHistoryRepo(
        owner_folder=owner_folder,
        owner_user_id=owner_user_id,
        key=Fernet.generate_key().decode("ascii"),
    )
    db.add(row)
    db.commit()
    return row.key, True


def record(
    db: Session,
    *,
    owner_dir: Path,
    owner_folder: str,
    owner_user_id: str,
    owner_name: str,
    actor_id: str,
    actor_name: str,
    changes: list[Change],
    message: str,
    baseline: Callable[[], list[BaselineSource]],
    reader: Reader,
) -> Future | None:
    """Ставит коммит в очередь. Ошибки истории не мешают работе с файлами."""
    try:
        key, created = _repo_key(db, owner_folder, owner_user_id)
        sources = baseline() if created or not (repo_path(owner_dir) / "HEAD").exists() else []
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.warning("история базы знаний: нет ключа репозитория %s: %s", owner_folder, exc)
        return None
    return _executor.submit(
        _write,
        owner_dir,
        key,
        owner_name,
        owner_user_id,
        sources,
        reader,
        actor_id,
        actor_name,
        changes,
        message,
    )


def drain() -> None:
    """Дожидается всех поставленных коммитов."""
    _executor.submit(lambda: None).result()


@dataclass
class Version:
    sha: str
    at: int
    author: str
    branch_note: str
    data: bytes


def versions(owner_dir: Path, key: str, path: str, limit: int = 2) -> list[Version]:
    """Последние версии файла во всех ветках, новые первыми. Удаления пропускаются."""
    exe = _git_exe()
    repo = repo_path(owner_dir)
    if exe is None or not (repo / "HEAD").exists():
        return []
    try:
        log = _git(
            exe,
            repo,
            "log",
            "--all",
            "--date-order",
            f"-n{max(1, limit) * 3}",
            "--format=%H%x09%ct%x09%an%x09%ae",
            "--",
            path,
        )
    except HistoryError:
        return []
    found: list[Version] = []
    for line in filter(None, log.splitlines()):
        sha, at, author, email = (line.split("\t") + ["", "", "", ""])[:4]
        try:
            data = read_blob(exe, repo, key, sha, path)
        except Exception:  # noqa: BLE001 — в этом коммите файл удалён
            continue
        found.append(Version(sha, int(at or 0), author, email.split("@")[0], data))
        if len(found) >= limit:
            break
    return found


def recent_log(owner_dir: Path, since_ts: int, limit: int = 20) -> list[str]:
    """Что менялось в папке с момента since_ts: «время · автор · сообщение · файлы»."""
    exe = _git_exe()
    repo = repo_path(owner_dir)
    if exe is None or not (repo / "HEAD").exists():
        return []
    try:
        log = _git(
            exe,
            repo,
            "log",
            "--all",
            "--date-order",
            f"--since={since_ts}",
            f"-n{limit}",
            "--name-only",
            "--format=@@%ct%x09%an%x09%s",
        )
    except HistoryError:
        return []
    from datetime import datetime, timezone

    rows: list[str] = []
    for block in log.split("@@"):
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        at, author, subject = (lines[0].split("\t") + ["", "", ""])[:3]
        when = datetime.fromtimestamp(int(at or 0), tz=timezone.utc).isoformat(timespec="minutes")
        rows.append(f"{when} · {author} · {subject} · {', '.join(lines[1:6])}")
    return rows


def read_blob(exe: str, repo: Path, key: str, rev: str, path: str) -> bytes:
    """Расшифрованное содержимое файла в указанной версии."""
    result = subprocess.run(
        [exe, "-c", "safe.directory=*", f"--git-dir={repo}", "cat-file", "blob", f"{rev}:{path}"],
        capture_output=True,
        timeout=GIT_TIMEOUT_S,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        raise HistoryError(result.stderr.decode("utf-8", "replace").strip())
    blob = result.stdout
    if not blob.startswith(BLOB_MAGIC):
        raise HistoryError("Неизвестный формат версии")
    return Fernet(key.encode("ascii")).decrypt(blob[len(BLOB_MAGIC) :])
