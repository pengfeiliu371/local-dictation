"""Create the Windows app icon used by the shortcut and packaged executable."""

from pathlib import Path

from PIL import Image, ImageDraw


output = Path(__file__).with_name("local-dictation.ico")
sizes = (16, 24, 32, 48, 64, 128, 256)
images = []
for size in sizes:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = max(1, round(size * 0.06))
    draw.ellipse((margin, margin, size - margin, size - margin), fill="#2F80ED")
    white = "#FFFFFF"
    draw.rounded_rectangle(
        (round(size * 0.42), round(size * 0.23), round(size * 0.58), round(size * 0.60)),
        radius=round(size * 0.08),
        fill=white,
    )
    draw.arc(
        (round(size * 0.31), round(size * 0.36), round(size * 0.69), round(size * 0.72)),
        0,
        180,
        fill=white,
        width=max(1, round(size * 0.07)),
    )
    draw.line(
        (round(size * 0.50), round(size * 0.68), round(size * 0.50), round(size * 0.78)),
        fill=white,
        width=max(1, round(size * 0.07)),
    )
    draw.line(
        (round(size * 0.38), round(size * 0.78), round(size * 0.62), round(size * 0.78)),
        fill=white,
        width=max(1, round(size * 0.07)),
    )
    images.append(image)

images[-1].save(output, format="ICO", append_images=images[:-1], sizes=[(size, size) for size in sizes])
print(output)
