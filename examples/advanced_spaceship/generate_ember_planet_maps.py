"""Generate seamless, reproducible PBR maps for the second story location.

The copper gas giant has turbulent latitudinal bands and two storm systems.
Its maps are equirectangular and wrap cleanly at the longitude seam.
"""

from pathlib import Path

import numpy as np
from PIL import Image


OUT = Path(__file__).resolve().parent / "textures"
W, H = 2048, 1024
y, x = np.mgrid[0:H, 0:W].astype(np.float32)
lon = x / W * (2 * np.pi)
lat = (y / (H - 1) - .5) * np.pi


def wrapped_storm(center_lon, center_lat, radius_lon, radius_lat, twist):
    dx = np.angle(np.exp(1j * (lon - center_lon))) / radius_lon
    dy = (lat - center_lat) / radius_lat
    r2 = dx * dx + dy * dy
    influence = np.exp(-r2 * 2.4)
    angle = np.arctan2(dy, dx) + twist * influence
    return influence, angle


storm_a, angle_a = wrapped_storm(1.2, -.27, .32, .19, 4.5)
storm_b, angle_b = wrapped_storm(4.7, .35, .21, .15, -3.8)
latitude = lat + .15 * np.sin(5 * lon + 7 * lat) * np.cos(lat) ** 2
latitude += .08 * np.sin(11 * lon - 18 * lat) * np.cos(lat) ** 3
latitude += .10 * storm_a * np.sin(angle_a * 2)
latitude -= .07 * storm_b * np.sin(angle_b * 3)
bands = .5 + .29 * np.sin(53 * latitude + 1.8 * np.sin(3 * lon))
bands += .12 * np.sin(123 * latitude + 4 * np.sin(8 * lon + lat))
bands += .045 * np.sin(247 * latitude - 11 * lon)
bands = np.clip(bands, 0, 1)
storms = .70 * storm_a * (.5 + .5 * np.cos(angle_a * 7))
storms += .52 * storm_b * (.5 + .5 * np.cos(angle_b * 6))
polar = np.clip((np.abs(lat) - 1.12) * 2.7, 0, 1)
color = np.stack((.16 + .76 * bands + .27 * storms,
                  .035 + .39 * bands + .16 * storms,
                  .025 + .20 * bands + .08 * storms), axis=-1)
color = color * (1 - polar[..., None] * .48)

height = .55 * bands + .45 * (storm_a + storm_b)
dx = np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)
dy = np.roll(height, -1, axis=0) - np.roll(height, 1, axis=0)
nx, ny = -dx * 2.6, -dy * 2.6
length = np.sqrt(nx * nx + ny * ny + 1)
normal = np.stack((nx / length * .5 + .5, ny / length * .5 + .5,
                   1 / length * .5 + .5), axis=-1)
orm = np.stack((np.clip(.87 + .13 * bands, 0, 1),
                np.clip(.74 - .13 * bands, 0, 1),
                np.zeros_like(bands)), axis=-1)

OUT.mkdir(exist_ok=True)
for name, data in (("ember_albedo.png", color),
                   ("ember_normal.png", normal),
                   ("ember_orm.png", orm)):
    Image.fromarray(np.uint8(np.clip(data, 0, 1) * 255), "RGB").save(OUT / name,
                                                                  optimize=True)
    print(name, (OUT / name).stat().st_size)
