"""Simgeleri üretir (installer/*.ico). Yalnızca simge değiştirilecekse çalıştırılır:

    pip install pillow
    python installer/make-icons.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
S = 1024  # çizim boyutu; küçük boyutlar bundan küçültülür


def base(background: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((32, 32, S - 32, S - 32), radius=210, fill=background)
    return image, draw


def monitor(draw: ImageDraw.ImageDraw, colour: str, screen: str) -> None:
    """Ayaklı bir ekran: çerçeve, iç yüzey, ayak."""
    draw.rounded_rectangle((190, 250, 834, 680), radius=56, fill=colour)
    draw.rounded_rectangle((250, 310, 774, 620), radius=24, fill=screen)
    draw.rectangle((462, 680, 562, 770), fill=colour)
    draw.rounded_rectangle((350, 760, 674, 820), radius=30, fill=colour)


def system_icon() -> Image.Image:
    """Sınav İzleme Sistemi: siyah zemin, beyaz ekran, canlı yayın noktası."""
    image, draw = base("#0b0b0c")
    monitor(draw, "#ffffff", "#0b0b0c")
    # ekranın içinde dört küçük kutu: izlenen ekranlar
    for row in range(2):
        for column in range(2):
            x = 292 + column * 228
            y = 346 + row * 128
            draw.rounded_rectangle((x, y, x + 196, y + 104), radius=16, fill="#3a3a40")
    draw.ellipse((690, 150, 870, 330), fill="#0b0b0c")
    draw.ellipse((716, 176, 844, 304), fill="#2fbf71")
    return image


def agent_icon() -> Image.Image:
    """Sınav Ajanı: mavi zemin, beyaz ekran, ortada onay işareti."""
    image, draw = base("#1f6feb")
    monitor(draw, "#ffffff", "#1f6feb")
    draw.line((392, 470, 480, 552, 640, 384), fill="#ffffff", width=58, joint="curve")
    for x, y in ((392, 470), (640, 384)):
        draw.ellipse((x - 29, y - 29, x + 29, y + 29), fill="#ffffff")
    return image


def save(image: Image.Image, path: Path, sizes: list[int]) -> None:
    frames = [image.resize((size, size), Image.LANCZOS) for size in sizes]
    frames[-1].save(path, format="ICO", sizes=[(size, size) for size in sizes],
                    append_images=frames[:-1], bitmap_format="bmp")


if __name__ == "__main__":
    save(system_icon(), HERE / "sinav-izleme.ico", SIZES)
    save(agent_icon(), HERE / "sinav-ajan.ico", SIZES)
    # panel penceresinin görev çubuğundaki simgesi
    save(system_icon(), HERE.parent / "server" / "static" / "favicon.ico", [16, 32, 48, 64])
