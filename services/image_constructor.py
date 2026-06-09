from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

BASE_DIR = Path(__file__).resolve().parent.parent
BACKGROUND_DIR = BASE_DIR / "data" / "background"
FONT_DIR = BASE_DIR / "data" / "font"
IMAGE_DIR = BASE_DIR / "data" / "images"

WIDTH = 1080
HEIGHT = 1080
WHITE = (255, 255, 255)
SOFT_WHITE = (222, 224, 224)
MUTED_WHITE = (190, 194, 194)
ACCENT = (255, 151, 31)


@dataclass
class ConstructorPlan:
    icon: str
    title: str
    subtitle: str
    details: list[str] = field(default_factory=list)


def list_constructor_icons() -> list[str]:
    if not BACKGROUND_DIR.exists():
        return []
    return sorted(path.stem for path in BACKGROUND_DIR.glob("*.png"))


def build_constructor_image(post_id: str, plan: ConstructorPlan) -> str:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    image = _background_image(plan.icon)

    _draw_readability_layer(image)
    _draw_text_block(image, plan.title, plan.subtitle)
    _draw_details_block(image, plan.details)

    out_path = IMAGE_DIR / f"{post_id}_constructor.png"
    image.save(out_path, "PNG", optimize=True)
    return str(out_path)


def _background_image(background_name: str) -> Image.Image:
    path = BACKGROUND_DIR / f"{background_name}.png"
    if not path.exists():
        backgrounds = list_constructor_icons()
        path = BACKGROUND_DIR / f"{backgrounds[0]}.png" if backgrounds else None
    if not path or not path.exists():
        return Image.new("RGBA", (WIDTH, HEIGHT), (14, 14, 14, 255))

    source = Image.open(path).convert("RGBA")
    scale = max(WIDTH / source.width, HEIGHT / source.height)
    resized = source.resize((int(source.width * scale), int(source.height * scale)), Image.LANCZOS)
    left = (resized.width - WIDTH) // 2
    top = (resized.height - HEIGHT) // 2
    return resized.crop((left, top, left + WIDTH, top + HEIGHT))


def _draw_readability_layer(image: Image.Image) -> None:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rectangle((0, 0, WIDTH, HEIGHT), fill=(0, 0, 0, 24))
    draw.rectangle((0, 0, WIDTH, 410), fill=(0, 0, 0, 64))
    draw.rectangle((0, 740, WIDTH, HEIGHT), fill=(0, 0, 0, 46))
    draw.ellipse((-260, -260, 1020, 520), fill=(0, 0, 0, 86))
    image.alpha_composite(overlay.filter(ImageFilter.GaussianBlur(42)))


def _draw_text_block(image: Image.Image, title: str, subtitle: str) -> None:
    draw = ImageDraw.Draw(image)
    x = 76
    y = 86
    max_width = 860
    text_bottom_limit = 392
    title_font = _fit_font(draw, title, "Unbounded-Bold.ttf", 68, 40, max_width, max_lines=2)
    subtitle_font = _fit_font(draw, subtitle, "Gilroy-Light_0.ttf", 38, 28, max_width, max_lines=2)

    title_lines = _wrap_text(draw, title, title_font, max_width, max_lines=2)
    for line in title_lines:
        _draw_clean_text(image, (x, y), line, title_font, WHITE)
        y += int(title_font.size * 1.12)

    y += 24
    subtitle_lines = _wrap_text(draw, subtitle, subtitle_font, max_width, max_lines=2)
    for line in subtitle_lines:
        if y + subtitle_font.size > text_bottom_limit:
            break
        _draw_clean_text(image, (x, y), line, subtitle_font, SOFT_WHITE)
        y += int(subtitle_font.size * 1.24)


def _draw_details_block(image: Image.Image, details: list[str]) -> None:
    details = [item.strip() for item in details if item and item.strip()][:3]
    if not details:
        return

    draw = ImageDraw.Draw(image)
    panel_x = 56
    panel_y = 782
    content_x = 76
    label_y = 804
    bullet_x = content_x + 5
    text_x = content_x + 30
    list_y = 856
    max_width = 820
    label_font = _font("Gilroy-Semibold_0.ttf", 26)
    text_font = _fit_font(draw, " ".join(details), "Gilroy-Light_0.ttf", 31, 24, max_width - 42, max_lines=3)
    line_gap = int(text_font.size * 1.38)
    block_h = 72 + line_gap * len(details)
    block_w = 880

    panel = Image.new("RGBA", image.size, (0, 0, 0, 0))
    panel_draw = ImageDraw.Draw(panel)
    panel_draw.rounded_rectangle(
        (panel_x, panel_y, panel_x + block_w, panel_y + block_h),
        radius=22,
        fill=(0, 0, 0, 112),
    )
    image.alpha_composite(panel)

    _draw_clean_text(image, (content_x, label_y), "В фокусе", label_font, MUTED_WHITE)

    y = list_y
    for detail in details:
        lines = _wrap_text(draw, detail, text_font, max_width - 42, max_lines=1)
        if not lines:
            continue
        line = lines[0]
        bbox = draw.textbbox((text_x, y), line, font=text_font)
        center_y = (bbox[1] + bbox[3]) // 2
        radius = 5
        draw.ellipse(
            (bullet_x - radius, center_y - radius, bullet_x + radius, center_y + radius),
            fill=ACCENT,
        )
        _draw_clean_text(image, (text_x, y), line, text_font, SOFT_WHITE)
        y += line_gap


def _draw_clean_text(
    image: Image.Image,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
) -> None:
    draw = ImageDraw.Draw(image)
    x, y = xy
    draw.text((x + 1, y + 1), text, font=font, fill=(0, 0, 0, 64))
    draw.text((x, y), text, font=font, fill=fill)


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
    original = " ".join(words)
    rendered = " ".join(lines)
    if len(lines) == max_lines and len(original) > len(rendered):
        while words and len(" ".join(words)) > len(rendered):
            words.pop()
        return _wrap_text(draw, " ".join(words).rstrip(".,:;"), font, max_width, max_lines)
    return lines or ["IT без хаоса"]


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
