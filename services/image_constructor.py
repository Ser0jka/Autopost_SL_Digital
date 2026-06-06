import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

BASE_DIR = Path(__file__).resolve().parent.parent
ICONS_DIR = BASE_DIR / "data" / "icons"
FONT_DIR = BASE_DIR / "data" / "font"
LOGO_PATH = BASE_DIR / "data" / "Waynut.png"
IMAGE_DIR = BASE_DIR / "data" / "images"

WIDTH = 1080
HEIGHT = 1080
ORANGE = (255, 151, 31)
GRAPHITE = (35, 35, 35)


@dataclass
class ConstructorPlan:
    icon: str
    title: str
    subtitle: str


def list_constructor_icons() -> list[str]:
    if not ICONS_DIR.exists():
        return []
    return sorted(path.stem for path in ICONS_DIR.glob("*.png"))


def build_constructor_image(post_id: str, plan: ConstructorPlan) -> str:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    image = _gradient_background(WIDTH, HEIGHT)
    draw = ImageDraw.Draw(image)

    _draw_soft_waves(image)
    _draw_text_block(draw, plan.title, plan.subtitle)
    _paste_logo(image)
    _paste_icon_scene(image, plan.icon)

    out_path = IMAGE_DIR / f"{post_id}_constructor.png"
    image.save(out_path, "PNG", optimize=True)
    return str(out_path)


def _gradient_background(width: int, height: int) -> Image.Image:
    top = (255, 252, 244)
    mid = (255, 235, 188)
    bottom = (255, 168, 65)
    img = Image.new("RGBA", (width, height), top)
    pixels = img.load()
    for y in range(height):
        t = y / max(1, height - 1)
        if t < 0.55:
            local = t / 0.55
            color = _mix(top, mid, local)
        else:
            local = (t - 0.55) / 0.45
            color = _mix(mid, bottom, local)
        for x in range(width):
            pixels[x, y] = (*color, 255)
    return img


def _draw_soft_waves(image: Image.Image) -> None:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for idx, alpha in enumerate((26, 18, 14)):
        y = 720 + idx * 54
        points = []
        for x in range(-100, WIDTH + 101, 30):
            wave = math.sin((x / 150) + idx) * 30
            points.append((x, y + wave))
        points += [(WIDTH + 100, HEIGHT + 100), (-100, HEIGHT + 100)]
        draw.polygon(points, fill=(255, 255, 255, alpha))
    image.alpha_composite(overlay.filter(ImageFilter.GaussianBlur(18)))


def _draw_text_block(draw: ImageDraw.ImageDraw, title: str, subtitle: str) -> None:
    x = 76
    y = 82
    max_width = 720
    text_bottom_limit = 430
    title_font = _fit_font(draw, title, "VelaSans-ExtraBold.ttf", 86, 58, max_width, max_lines=2)
    subtitle_font = _fit_font(draw, subtitle, "VelaSans-Regular.ttf", 44, 34, max_width, max_lines=2)

    title_lines = _wrap_text(draw, title, title_font, max_width, max_lines=2)
    for line in title_lines:
        draw.text((x, y), line, font=title_font, fill=ORANGE)
        y += int(title_font.size * 1.08)

    y += 28
    subtitle_lines = _wrap_text(draw, subtitle, subtitle_font, max_width, max_lines=2)
    for line in subtitle_lines:
        if y + subtitle_font.size > text_bottom_limit:
            break
        draw.text((x, y), line, font=subtitle_font, fill=GRAPHITE)
        y += int(subtitle_font.size * 1.12)


def _paste_logo(image: Image.Image) -> None:
    if not LOGO_PATH.exists():
        draw = ImageDraw.Draw(image)
        draw.text((870, 72), "Waynut", font=_font("VelaSans-Bold.ttf", 34), fill=(20, 20, 20))
        return
    logo = Image.open(LOGO_PATH).convert("RGBA")
    target_w = 132
    ratio = target_w / logo.width
    logo = logo.resize((target_w, int(logo.height * ratio)), Image.LANCZOS)
    image.alpha_composite(logo, (WIDTH - target_w - 72, 72))


def _paste_icon_scene(image: Image.Image, icon_name: str) -> None:
    icon_path = ICONS_DIR / f"{icon_name}.png"
    if not icon_path.exists():
        icons = list_constructor_icons()
        icon_path = ICONS_DIR / f"{icons[0]}.png" if icons else None
    if not icon_path or not icon_path.exists():
        return

    icon = Image.open(icon_path).convert("RGBA")
    icon_zone_top = 470
    icon_zone_bottom = 1010
    max_w, max_h = 660, icon_zone_bottom - icon_zone_top
    scale = min(max_w / icon.width, max_h / icon.height)
    icon = icon.resize((int(icon.width * scale), int(icon.height * scale)), Image.LANCZOS)

    x = (WIDTH - icon.width) // 2
    y = icon_zone_top + ((icon_zone_bottom - icon_zone_top) - icon.height) // 2
    image.alpha_composite(icon, (x, y))


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    path = FONT_DIR / name
    if path.exists():
        return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default(size=size)


def _fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_name: str,
    max_size: int,
    min_size: int,
    max_width: int,
    max_lines: int,
) -> ImageFont.FreeTypeFont:
    for size in range(max_size, min_size - 1, -2):
        font = _font(font_name, size)
        lines = _wrap_text(draw, text, font, max_width, max_lines=max_lines)
        if all(draw.textbbox((0, 0), line, font=font)[2] <= max_width for line in lines):
            return font
    return _font(font_name, min_size)


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    max_lines: int,
) -> list[str]:
    words = (text or "").strip().split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    if len(lines) == max_lines and len(" ".join(words)) > len(" ".join(lines)):
        lines[-1] = lines[-1].rstrip(".,:;") + "..."
    return lines or ["IT без хаоса"]


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
