from pathlib import Path

from PIL import Image


frontend = Path(__file__).resolve().parent.parent
source = frontend / "src" / "assets" / "sandrone-icon.png"
target = frontend / "desktop" / "app.ico"

with Image.open(source) as image:
    image.crop((360, 0, 710, 350)).save(
        target,
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (256, 256)],
    )
