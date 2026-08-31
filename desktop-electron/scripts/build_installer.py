from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path


ELECTRON_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ELECTRON_ROOT.parent
DESKTOP_ROOT = REPO_ROOT / "desktop"
RUNTIME_ROOT = ELECTRON_ROOT / ".installer-runtime"
CACHE_ROOT = RUNTIME_ROOT / ".cache"

NODE_VERSION = os.environ.get("CONSTRUCTOR_INSTALLER_NODE_VERSION", "22.13.1")


def run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=str(cwd), env=env, check=True)


def tool(name: str, *, env: dict[str, str] | None = None) -> str:
    search_path = (env or os.environ).get("PATH")
    found = shutil.which(name, path=search_path)
    if found:
        return found
    if os.name == "nt":
        found = shutil.which(f"{name}.cmd", path=search_path)
        if found:
            return found
    return name


def build_env() -> dict[str, str]:
    env = dict(os.environ)
    raw_path = env.get("PATH") or env.get("Path") or ""
    blocked = (
        str(RUNTIME_ROOT / "node").lower(),
        str(ELECTRON_ROOT / "release").lower(),
    )
    parts = []
    for item in raw_path.split(os.pathsep):
        folded = item.lower()
        if any(folded.startswith(prefix) for prefix in blocked):
            continue
        parts.append(item)
    env["PATH"] = os.pathsep.join(parts)
    env["Path"] = env["PATH"]
    return env


def download(url: str, dest: Path) -> None:
    if dest.is_file():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"download {url}", flush=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    urllib.request.urlretrieve(url, tmp)
    tmp.replace(dest)


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def copy_tree_contents(src: Path, dest: Path) -> None:
    reset_dir(dest)
    for item in src.iterdir():
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def existing_backend_url(env_path: Path) -> str:
    if not env_path.is_file():
        return ""
    for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "BACKEND_URL":
            return value.strip().strip("\"'").rstrip("/")
    return ""


def detect_backend_url() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        host = sock.getsockname()[0]
        sock.close()
    except OSError:
        host = "127.0.0.1"
    return f"http://{host}:7812"


def set_env_key(env_path: Path, key: str, value: str) -> None:
    lines: list[str] = []
    found = False
    if env_path.is_file():
        lines = env_path.read_text(encoding="utf-8", errors="replace").splitlines()
    next_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in line:
            next_lines.append(line)
            continue
        left, _right = line.split("=", 1)
        if left.strip() == key:
            next_lines.append(f"{key}={value}")
            found = True
        else:
            next_lines.append(line)
    if not found:
        next_lines.append(f"{key}={value}")
    env_path.write_text("\n".join(next_lines).rstrip() + "\n", encoding="utf-8")


def prepare_env(backend_url: str) -> str:
    env_path = DESKTOP_ROOT / ".env"
    if not env_path.is_file():
        example = DESKTOP_ROOT / ".env.example"
        if example.is_file():
            shutil.copy2(example, env_path)
        else:
            env_path.write_text("", encoding="utf-8")

    chosen = backend_url.strip().rstrip("/")
    if not chosen:
        current = existing_backend_url(env_path)
        if current and "127.0.0.1" not in current and "localhost" not in current.lower():
            chosen = current
        else:
            chosen = detect_backend_url()
    set_env_key(env_path, "BACKEND_URL", chosen)
    print(f"backend url: {chosen}", flush=True)
    return chosen


def prepare_sdk_agent(skip_install: bool) -> None:
    sdk_root = DESKTOP_ROOT / "sdk-agent"
    if not (sdk_root / "package.json").is_file():
        raise RuntimeError(f"sdk-agent package.json not found: {sdk_root}")
    if not skip_install:
        run([tool("npm"), "install"], cwd=sdk_root)
    if not (sdk_root / "node_modules").is_dir():
        raise RuntimeError("desktop/sdk-agent/node_modules is missing")


def node_version(node_exe: Path) -> tuple[int, int, int]:
    try:
        result = subprocess.run(
            [str(node_exe), "--version"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except Exception:
        return (0, 0, 0)
    if result.returncode != 0:
        return (0, 0, 0)
    raw = (result.stdout or "").strip().lstrip("v")
    parts = []
    for item in raw.split(".")[:3]:
        try:
            parts.append(int(item))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return (parts[0], parts[1], parts[2])


def node_is_supported(node_exe: Path) -> bool:
    major, minor, _patch = node_version(node_exe)
    return major > 22 or (major == 22 and minor >= 13)


def local_node_root() -> Path | None:
    override = os.environ.get("CONSTRUCTOR_INSTALLER_NODE_SOURCE", "").strip()
    if override:
        root = Path(override)
        candidate = root / "node.exe"
        return root if candidate.is_file() and node_is_supported(candidate) else None
    found = shutil.which("node", path=build_env().get("PATH"))
    if not found:
        return None
    root = Path(found).resolve().parent
    candidate = root / "node.exe"
    return root if candidate.is_file() and node_is_supported(candidate) else None


def prepare_node(skip: bool, *, download_node: bool = False) -> None:
    node_dir = RUNTIME_ROOT / "node"
    if skip and (node_dir / "node.exe").is_file():
        return
    if not download_node:
        source = local_node_root()
        if source is not None:
            copy_tree_contents(source, node_dir)
            if not (node_dir / "node.exe").is_file():
                raise RuntimeError("local node copy did not produce node.exe")
            print(f"bundled local node: {source}", flush=True)
            return
    archive = CACHE_ROOT / f"node-v{NODE_VERSION}-win-x64.zip"
    download(
        f"https://nodejs.org/dist/v{NODE_VERSION}/node-v{NODE_VERSION}-win-x64.zip",
        archive,
    )
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(tmp)
        extracted = tmp / f"node-v{NODE_VERSION}-win-x64"
        copy_tree_contents(extracted, node_dir)
    if not (node_dir / "node.exe").is_file():
        raise RuntimeError("bundled node.exe was not prepared")


def filtered_requirements() -> Path:
    src = DESKTOP_ROOT / "requirements.txt"
    if not src.is_file():
        raise RuntimeError(f"requirements.txt not found: {src}")
    skip_prefixes = ("PySide6", "pyinstaller", "winotify")
    lines: list[str] = []
    for raw in src.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if any(stripped.lower().startswith(prefix.lower()) for prefix in skip_prefixes):
            continue
        if stripped:
            lines.append(stripped)
    target = RUNTIME_ROOT / "requirements-electron-sidecar.txt"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def enable_embedded_python_site(python_dir: Path) -> None:
    for pth in python_dir.glob("python*._pth"):
        text = pth.read_text(encoding="utf-8", errors="replace")
        text = text.replace("#import site", "import site")
        pth.write_text(text, encoding="utf-8")


def prepare_python(skip: bool) -> None:
    python_dir = RUNTIME_ROOT / "python"
    python_exe = python_dir / "python.exe"
    if skip and python_exe.is_file():
        return
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    archive = CACHE_ROOT / f"python-{version}-embed-amd64.zip"
    download(
        f"https://www.python.org/ftp/python/{version}/python-{version}-embed-amd64.zip",
        archive,
    )
    reset_dir(python_dir)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(python_dir)
    enable_embedded_python_site(python_dir)
    get_pip = CACHE_ROOT / "get-pip.py"
    download("https://bootstrap.pypa.io/get-pip.py", get_pip)
    run([str(python_exe), str(get_pip), "--no-warn-script-location"], cwd=python_dir)
    req = filtered_requirements()
    run([str(python_exe), "-m", "pip", "install", "-r", str(req)], cwd=python_dir)
    postinstall = python_dir / "Scripts" / "pywin32_postinstall.py"
    if postinstall.is_file():
        try:
            run([str(python_exe), str(postinstall), "-install"], cwd=python_dir)
        except subprocess.CalledProcessError:
            print("pywin32 postinstall failed; continuing", flush=True)


def prepare_playwright(skip: bool) -> None:
    target = RUNTIME_ROOT / "ms-playwright"
    if skip:
        target.mkdir(parents=True, exist_ok=True)
        return
    source = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")) if os.environ.get("PLAYWRIGHT_BROWSERS_PATH") else None
    if source is None:
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            source = Path(local) / "ms-playwright"
    if source and source.is_dir():
        copy_tree_contents(source, target)
        return
    target.mkdir(parents=True, exist_ok=True)
    print("playwright browser cache not found; packaged browser tools may need system browsers", flush=True)


def read_package_version() -> str:
    package_path = ELECTRON_ROOT / "package.json"
    if not package_path.is_file():
        raise RuntimeError(f"package.json not found: {package_path}")
    data = json.loads(package_path.read_text(encoding="utf-8"))
    version = str(data.get("version") or "").strip()
    if not version:
        raise RuntimeError("package.json does not contain a version")
    return version


def github_repo_slug() -> str:
    override = os.environ.get("UPDATE_GITHUB_REPO", "").strip()
    if "/" in override:
        return override
    owner = os.environ.get("UPDATE_GITHUB_OWNER", "").strip()
    repo = override or os.environ.get("GITHUB_REPOSITORY", "").strip()
    if owner and repo and "/" not in repo:
        return f"{owner}/{repo}"
    if repo.count("/") == 1:
        return repo
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        result = None
    remote = (result.stdout if result else "").strip()
    marker = "github.com"
    if marker in remote.lower():
        tail = remote.split(marker, 1)[1]
        tail = tail.lstrip(":/")
        if tail.endswith(".git"):
            tail = tail[:-4]
        parts = [item for item in tail.replace("\\", "/").split("/") if item]
        if len(parts) >= 2:
            return f"{parts[0]}/{parts[1]}"
    return "Turbulentnost/Consturctor"


def installer_artifacts() -> list[Path]:
    release_dir = ELECTRON_ROOT / "release"
    names = (
        "Constructor-Setup.exe",
        "latest.yml",
        "Constructor-Setup.exe.blockmap",
    )
    found = [release_dir / name for name in names if (release_dir / name).is_file()]
    setup = release_dir / "Constructor-Setup.exe"
    if not setup.is_file():
        raise RuntimeError(f"installer not found: {setup}")
    return found


def publish_github_release() -> None:
    gh = tool("gh")
    if not shutil.which(gh) and not shutil.which("gh.exe"):
        raise RuntimeError("GitHub CLI (gh) is not on PATH")
    version = read_package_version()
    tag = f"v{version}"
    repo = github_repo_slug()
    files = installer_artifacts()
    print(f"publishing {tag} to {repo}", flush=True)
    env = build_env()
    view = subprocess.run(
        [gh, "release", "view", tag, "--repo", repo],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    paths = [str(path) for path in files]
    if view.returncode == 0:
        run([gh, "release", "upload", tag, *paths, "--repo", repo, "--clobber"], cwd=REPO_ROOT, env=env)
        print(f"updated existing GitHub release {tag}", flush=True)
        return
    run(
        [
            gh,
            "release",
            "create",
            tag,
            *paths,
            "--repo",
            repo,
            "--title",
            f"Constructor {version}",
            "--generate-notes",
        ],
        cwd=REPO_ROOT,
        env=env,
    )
    print(f"created GitHub release {tag}", flush=True)


def build_electron(dir_only: bool) -> None:
    env = build_env()
    run([tool("npm", env=env), "run", "build"], cwd=ELECTRON_ROOT, env=env)
    cmd = [tool("npx", env=env), "electron-builder", "--publish", "never"]
    if dir_only:
        cmd.append("--dir")
    run(cmd, cwd=ELECTRON_ROOT, env=env)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Constructor Electron installer")
    parser.add_argument("--backend-url", default="", help="Backend URL to write into desktop/.env")
    parser.add_argument("--dir", action="store_true", help="Build unpacked directory instead of NSIS setup")
    parser.add_argument("--skip-python", action="store_true", help="Reuse prepared embedded Python")
    parser.add_argument("--skip-node", action="store_true", help="Reuse prepared portable Node.js")
    parser.add_argument("--download-node", action="store_true", help="Use nodejs.org zip instead of local Node")
    parser.add_argument("--skip-sdk-install", action="store_true", help="Do not run npm install in desktop/sdk-agent")
    parser.add_argument("--skip-browsers", action="store_true", help="Do not copy Playwright browser cache")
    parser.add_argument("--publish", action="store_true", help="Upload the built installer to GitHub Releases")
    parser.add_argument(
        "--publish-only",
        action="store_true",
        help="Publish an already built Constructor-Setup.exe without rebuilding",
    )
    args = parser.parse_args(argv)

    if args.publish_only:
        publish_github_release()
        return 0

    prepare_env(args.backend_url)
    prepare_sdk_agent(args.skip_sdk_install)
    prepare_node(args.skip_node, download_node=args.download_node)
    prepare_python(args.skip_python)
    prepare_playwright(args.skip_browsers)
    build_electron(args.dir)
    if args.publish:
        if args.dir:
            raise RuntimeError("refusing to publish a directory build; omit --dir")
        publish_github_release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
