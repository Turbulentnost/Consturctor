"""Светлый PNG-фон чата из SVG (цвета UI Constructor).

Варианты:
  lines   — тонкие непересекающиеся линии
  grid    — клетка + один крупный SVG-агент; преломление по форме стекла (Снелл)
  repeat  — повторяющиеся SVG (маскот / скрепка)
  all     — все три файла

Запуск из desktop/:
  py -3.13 scripts/generate_chat_bg.py
  py -3.13 scripts/generate_chat_bg.py --style grid --seed 11
  py -3.13 scripts/generate_chat_bg.py --svg-dir app/chat/assets/svg
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SVG_DIR = ROOT / "app" / "chat" / "assets" / "svg"
DEFAULT_OUT_DIR = ROOT / "app" / "chat" / "assets" / "bg"

# Constructor theme (desktop/app/ui/theme.py)
BG = QColor("#FAFCFB")
WASH = QColor("#EAF7F3")
SIDEBAR_TOP = QColor("#08745F")
SIDEBAR_MID = QColor("#06483D")
MINT = QColor("#62E0BE")
WHITE = QColor("#F7FBFA")


def _app() -> QGuiApplication:
    existing = QGuiApplication.instance()
    if existing is not None:
        return existing  # type: ignore[return-value]
    return QGuiApplication(sys.argv)


def _load_svgs(folder: Path) -> list[tuple[str, QSvgRenderer]]:
    items: list[tuple[str, QSvgRenderer]] = []
    if not folder.is_dir():
        return items
    for path in sorted(folder.glob("*.svg")):
        if path.stem.endswith("_volume") or path.stem.endswith("_glass"):
            continue
        renderer = QSvgRenderer(str(path))
        if renderer.isValid():
            items.append((path.stem, renderer))
    return items


def _load_named_svg(folder: Path, name: str) -> QSvgRenderer | None:
    path = folder / name
    if not path.is_file():
        return None
    renderer = QSvgRenderer(str(path))
    return renderer if renderer.isValid() else None


def _paint_svg(painter: QPainter, renderer: QSvgRenderer, rect: QRectF, opacity: float) -> None:
    painter.save()
    painter.setOpacity(max(0.0, min(1.0, opacity)))
    renderer.render(painter, rect)
    painter.restore()


def _base_canvas(width: int, height: int) -> QImage:
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(BG)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(0, 0, width * 0.15, height)
    wash = QColor(WASH)
    wash.setAlpha(140)
    clear = QColor(BG)
    clear.setAlpha(0)
    gradient.setColorAt(0.0, wash)
    gradient.setColorAt(0.45, clear)
    gradient.setColorAt(1.0, wash)
    painter.fillRect(0, 0, width, height, gradient)
    painter.end()
    return image


def _segment_distance(a1: QPointF, a2: QPointF, b1: QPointF, b2: QPointF) -> float:
    def _dot(u: QPointF, v: QPointF) -> float:
        return u.x() * v.x() + u.y() * v.y()

    def _sub(u: QPointF, v: QPointF) -> QPointF:
        return QPointF(u.x() - v.x(), u.y() - v.y())

    d1 = _sub(a2, a1)
    d2 = _sub(b2, b1)
    r = _sub(a1, b1)
    a = _dot(d1, d1)
    e = _dot(d2, d2)
    f = _dot(d2, r)
    eps = 1e-8
    if a <= eps and e <= eps:
        return math.hypot(r.x(), r.y())
    if a <= eps:
        t = max(0.0, min(1.0, f / e))
        p = QPointF(b1.x() + d2.x() * t, b1.y() + d2.y() * t)
        return math.hypot(a1.x() - p.x(), a1.y() - p.y())
    c = _dot(d1, r)
    if e <= eps:
        t = max(0.0, min(1.0, -c / a))
        p = QPointF(a1.x() + d1.x() * t, a1.y() + d1.y() * t)
        return math.hypot(p.x() - b1.x(), p.y() - b1.y())
    b = _dot(d1, d2)
    denom = a * e - b * b
    s = 0.0 if abs(denom) < eps else max(0.0, min(1.0, (b * f - c * e) / denom))
    t = (b * s + f) / e
    if t < 0:
        t = 0
        s = max(0.0, min(1.0, -c / a))
    elif t > 1:
        t = 1
        s = max(0.0, min(1.0, (b - c) / a))
    p = QPointF(a1.x() + d1.x() * s, a1.y() + d1.y() * s)
    q = QPointF(b1.x() + d2.x() * t, b1.y() + d2.y() * t)
    return math.hypot(p.x() - q.x(), p.y() - q.y())


def draw_lines(image: QImage, rng: random.Random) -> None:
    w, h = image.width(), image.height()
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    segments: list[tuple[QPointF, QPointF]] = []
    gap = 22.0
    attempts = 0
    target = max(28, int((w * h) / 52000))
    while len(segments) < target and attempts < target * 80:
        attempts += 1
        length = rng.uniform(90, 280)
        angle = rng.choice(
            (
                rng.uniform(-0.35, 0.35),
                rng.uniform(math.pi * 0.45, math.pi * 0.55),
                rng.uniform(0.7, 1.1),
                rng.uniform(-1.1, -0.7),
            )
        )
        x1 = rng.uniform(-40, w + 40)
        y1 = rng.uniform(-40, h + 40)
        x2 = x1 + math.cos(angle) * length
        y2 = y1 + math.sin(angle) * length
        a1, a2 = QPointF(x1, y1), QPointF(x2, y2)
        if any(_segment_distance(a1, a2, b1, b2) < gap for b1, b2 in segments):
            continue
        segments.append((a1, a2))

    palette = [SIDEBAR_TOP, MINT, SIDEBAR_MID]
    for a1, a2 in segments:
        color = QColor(rng.choice(palette))
        color.setAlpha(rng.randint(150, 210))
        pen = QPen(color, rng.uniform(1.8, 2.6), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(a1, a2)
    painter.end()


_N_GLASS = 1.52
_N_AIR = 1.0


def _raster_svg(renderer: QSvgRenderer, width: int, height: int) -> QImage:
    pic = QImage(max(1, width), max(1, height), QImage.Format.Format_ARGB32)
    pic.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pic)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, width, height))
    painter.end()
    return pic


def _alpha_grid(pic: QImage) -> list[list[float]]:
    w, h = pic.width(), pic.height()
    rows: list[list[float]] = []
    for y in range(h):
        line = []
        for x in range(w):
            line.append(QColor.fromRgba(pic.pixel(x, y)).alpha() / 255.0)
        rows.append(line)
    return rows


def _distance_inside(alpha: list[list[float]], threshold: float = 0.12) -> list[list[float]]:
    h = len(alpha)
    w = len(alpha[0]) if h else 0
    inf = 1.0e6
    dist = [[0.0 if cell < threshold else inf for cell in row] for row in alpha]
    diag = math.sqrt(2.0)
    for y in range(h):
        for x in range(w):
            best = dist[y][x]
            if y:
                best = min(best, dist[y - 1][x] + 1.0)
                if x:
                    best = min(best, dist[y - 1][x - 1] + diag)
                if x + 1 < w:
                    best = min(best, dist[y - 1][x + 1] + diag)
            if x:
                best = min(best, dist[y][x - 1] + 1.0)
            dist[y][x] = best
    for y in range(h - 1, -1, -1):
        for x in range(w - 1, -1, -1):
            best = dist[y][x]
            if y + 1 < h:
                best = min(best, dist[y + 1][x] + 1.0)
                if x:
                    best = min(best, dist[y + 1][x - 1] + diag)
                if x + 1 < w:
                    best = min(best, dist[y + 1][x + 1] + diag)
            if x + 1 < w:
                best = min(best, dist[y][x + 1] + 1.0)
            dist[y][x] = best
    return dist


def _height_from_sdf(dist: list[list[float]], thickness: float, bevel: float) -> list[list[float]]:
    bevel = max(1.0, bevel)
    height: list[list[float]] = []
    for row in dist:
        out = []
        for d in row:
            if d <= 0.0:
                out.append(0.0)
                continue
            # выпуклое стекло по силуэту: толще к медиальной оси, 0 на контуре
            t = min(1.0, d / bevel)
            out.append(thickness * math.sqrt(max(0.0, 1.0 - (1.0 - t) ** 2)))
        height.append(out)
    return height


def _refract_vec(ix: float, iy: float, iz: float, nx: float, ny: float, nz: float, eta: float):
    cosi = nx * ix + ny * iy + nz * iz
    k = 1.0 - eta * eta * (1.0 - cosi * cosi)
    if k < 0.0:
        return None
    scale = eta * cosi + math.sqrt(k)
    return (eta * ix - scale * nx, eta * iy - scale * ny, eta * iz - scale * nz)


def _sample_pixel(image: QImage, fx: float, fy: float) -> int:
    w, h = image.width(), image.height()
    x0 = int(math.floor(fx))
    y0 = int(math.floor(fy))
    tx = fx - x0
    ty = fy - y0
    x0 = max(0, min(w - 1, x0))
    y0 = max(0, min(h - 1, y0))
    x1 = max(0, min(w - 1, x0 + 1))
    y1 = max(0, min(h - 1, y0 + 1))
    c00 = QColor.fromRgba(image.pixel(x0, y0))
    c10 = QColor.fromRgba(image.pixel(x1, y0))
    c01 = QColor.fromRgba(image.pixel(x0, y1))
    c11 = QColor.fromRgba(image.pixel(x1, y1))

    def mix(a: QColor, b: QColor, t: float) -> tuple[float, float, float, float]:
        return (
            a.red() + (b.red() - a.red()) * t,
            a.green() + (b.green() - a.green()) * t,
            a.blue() + (b.blue() - a.blue()) * t,
            a.alpha() + (b.alpha() - a.alpha()) * t,
        )

    top = mix(c00, c10, tx)
    bot = mix(c01, c11, tx)
    r = top[0] + (bot[0] - top[0]) * ty
    g = top[1] + (bot[1] - top[1]) * ty
    b = top[2] + (bot[2] - top[2]) * ty
    a = top[3] + (bot[3] - top[3]) * ty
    return QColor(int(r), int(g), int(b), int(a)).rgba()


def _refract_through_svg(
    dest: QImage,
    source: QImage,
    volume: QSvgRenderer,
    icon: QRectF,
    *,
    ior: float = _N_GLASS,
) -> None:
    box = icon.toAlignedRect().intersected(source.rect())
    if box.width() < 8 or box.height() < 8:
        return
    mask = _raster_svg(volume, box.width(), box.height())
    alpha = _alpha_grid(mask)
    dist = _distance_inside(alpha)
    thickness = min(box.width(), box.height()) * 0.28
    bevel = min(box.width(), box.height()) * 0.38
    height = _height_from_sdf(dist, thickness, bevel)
    mh, mw = len(height), len(height[0]) if height else 0
    eta_in = _N_AIR / ior
    eta_out = ior / _N_AIR
    ox, oy = box.x(), box.y()
    for ly in range(mh):
        for lx in range(mw):
            if height[ly][lx] <= 0.05:
                continue
            hx = 0.0
            hy = 0.0
            if 0 < lx < mw - 1:
                hx = (height[ly][lx + 1] - height[ly][lx - 1]) * 0.5
            if 0 < ly < mh - 1:
                hy = (height[ly + 1][lx] - height[ly - 1][lx]) * 0.5
            inv = 1.0 / math.sqrt(hx * hx + hy * hy + 1.0)
            nx, ny, nz = -hx * inv, -hy * inv, inv
            entered = _refract_vec(0.0, 0.0, -1.0, nx, ny, nz, eta_in)
            if entered is None:
                continue
            tx, ty, tz = entered
            if abs(tz) < 1e-4:
                continue
            travel = height[ly][lx] / abs(tz)
            bx = lx + 0.5 + tx * travel
            by = ly + 0.5 + ty * travel
            exited = _refract_vec(tx, ty, tz, 0.0, 0.0, -1.0, eta_out)
            if exited is None:
                sx, sy = ox + bx, oy + by
            else:
                ex, ey, ez = exited
                air = 36.0 / max(abs(ez), 1e-4)
                sx = ox + bx + ex * air
                sy = oy + by + ey * air
            dest.setPixel(ox + lx, oy + ly, _sample_pixel(source, sx, sy))


def draw_grid(image: QImage, svgs: list[tuple[str, QSvgRenderer]], rng: random.Random) -> None:
    w, h = image.width(), image.height()
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    step = 36
    line = QColor(SIDEBAR_TOP)
    line.setAlpha(78)
    painter.setPen(QPen(line, 1.35))
    for x in range(0, w + step, step):
        painter.drawLine(x, 0, x, h)
    for y in range(0, h + step, step):
        painter.drawLine(0, y, w, y)
    accent = QColor(MINT)
    accent.setAlpha(110)
    painter.setPen(QPen(accent, 1.55))
    for x in range(0, w + step * 4, step * 4):
        painter.drawLine(x, 0, x, h)
    for y in range(0, h + step * 4, step * 4):
        painter.drawLine(0, y, w, y)
    painter.end()

    svg_dir = Path(getattr(draw_grid, "svg_dir", DEFAULT_SVG_DIR))
    mascot = next((item for item in svgs if item[0] == "mascot"), svgs[0])
    volume = _load_named_svg(svg_dir, "mascot_volume.svg") or mascot[1]
    glass = _load_named_svg(svg_dir, "mascot_glass.svg")
    size = min(w, h) * 0.82
    icon = QRectF((w - size) / 2.0, (h - size) / 2.0 - h * 0.03, size, size)
    snapshot = image.copy()
    _refract_through_svg(image, snapshot, volume, icon)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    _paint_svg(painter, glass or mascot[1], icon, 0.88)
    painter.end()
    _ = rng


def draw_repeat(image: QImage, svgs: list[tuple[str, QSvgRenderer]], rng: random.Random) -> None:
    if not svgs:
        return
    w, h = image.width(), image.height()
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    cell = 118
    stamps = svgs
    row = 0
    y = 28
    while y < h:
        x = 22 + (cell * 0.42 if row % 2 else 0)
        col = 0
        while x < w:
            name, renderer = stamps[(row + col) % len(stamps)]
            size = 36 if name == "paperclip" else 52
            painter.save()
            painter.translate(x + size / 2, y + size / 2)
            painter.rotate(rng.choice((-10, -5, 0, 5, 10)))
            rect = QRectF(-size / 2, -size / 2, size, size)
            _paint_svg(painter, renderer, rect, 1.0)
            painter.restore()
            x += cell
            col += 1
        y += cell * 0.86
        row += 1
    painter.end()


def render_style(
    style: str,
    width: int,
    height: int,
    svgs: list[tuple[str, QSvgRenderer]],
    rng: random.Random,
) -> QImage:
    image = _base_canvas(width, height)
    if style == "lines":
        draw_lines(image, rng)
    elif style == "grid":
        draw_grid.svg_dir = getattr(render_style, "svg_dir", DEFAULT_SVG_DIR)
        draw_grid(image, svgs, rng)
    elif style == "repeat":
        draw_repeat(image, svgs, rng)
    else:
        raise ValueError(f"Неизвестный стиль: {style}")
    return image


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PNG-фон чата Constructor из SVG")
    parser.add_argument("--style", choices=("lines", "grid", "repeat", "all"), default="all")
    parser.add_argument("--width", type=int, default=1200)
    parser.add_argument("--height", type=int, default=1800)
    parser.add_argument("--seed", type=int, default=24)
    parser.add_argument("--svg-dir", type=Path, default=DEFAULT_SVG_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    _app()
    svgs = _load_svgs(args.svg_dir)
    if not svgs:
        print(f"Нет SVG в {args.svg_dir}", file=sys.stderr)
        return 1
    args.out_dir.mkdir(parents=True, exist_ok=True)
    styles = ("lines", "grid", "repeat") if args.style == "all" else (args.style,)
    style_seed = {"lines": 0, "grid": 17, "repeat": 41}
    for style in styles:
        rng = random.Random(args.seed + style_seed[style])
        render_style.svg_dir = args.svg_dir
        image = render_style(style, args.width, args.height, svgs, rng)
        dest = args.out_dir / f"chat_bg_{style}.png"
        if not image.save(str(dest), "PNG"):
            print(f"Не удалось сохранить {dest}", file=sys.stderr)
            return 1
        print(dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
