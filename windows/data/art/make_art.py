"""Draw Aethel's artwork: the dusk hero on Home and the logo mark.

Aethel is named after the aether, the bright upper air; the art is that sky
at dusk over layered ridges. Everything is generated here (no stock images),
deterministically, as SVG, then rendered to PNG with GdkPixbuf so GTK can
load it on every platform without an SVG loader.

    python3 data/art/make_art.py
"""

import math
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 2400, 900


def ridge(seed: int, base: float, amplitude: float, roughness: float, peaks: int) -> str:
    """A mountain ridge as a closed SVG path along the bottom edge."""
    rng = random.Random(seed)
    phase = [rng.uniform(0, math.tau) for _ in range(4)]
    points = []
    steps = 160
    for i in range(steps + 1):
        x = W * i / steps
        t = i / steps
        y = base
        y -= amplitude * (0.55 + 0.45 * math.sin(t * math.pi * peaks / 2 + phase[0]))
        y -= amplitude * 0.35 * math.sin(t * math.pi * peaks * 1.7 + phase[1])
        y -= amplitude * 0.18 * math.sin(t * math.pi * peaks * 4.3 + phase[2])
        y += rng.uniform(-roughness, roughness)
        points.append(f"{x:.1f},{y:.1f}")
    return f"M0,{H} L" + " L".join(points) + f" L{W},{H} Z"


def stars(seed: int, count: int) -> str:
    rng = random.Random(seed)
    out = []
    for _ in range(count):
        x, y = rng.uniform(0, W), rng.uniform(0, H * 0.42)
        r = rng.choice((0.9, 1.1, 1.4, 1.8))
        o = rng.uniform(0.25, 0.85) * (1 - y / (H * 0.5))
        out.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r}" fill="#fff6e8" opacity="{o:.2f}"/>')
    return "\n  ".join(out)


def hero_svg() -> str:
    sun_x, sun_y = W * 0.68, H * 0.70
    layers = [
        # (seed, base y, amplitude, roughness, peaks, colour)
        (11, H * 0.74, 150, 4, 3, "#5a2b3f"),
        (23, H * 0.80, 170, 5, 4, "#3d1f33"),
        (37, H * 0.88, 150, 5, 5, "#271627"),
        (51, H * 0.97, 130, 4, 6, "#170d18"),
    ]
    ridges = "\n  ".join(
        f'<path d="{ridge(seed, base, amp, rough, peaks)}" fill="{colour}"/>'
        for seed, base, amp, rough, peaks, colour in layers
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
  <defs>
    <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#0c0a17"/>
      <stop offset="0.35" stop-color="#211531"/>
      <stop offset="0.58" stop-color="#5b2541"/>
      <stop offset="0.74" stop-color="#c2533a"/>
      <stop offset="0.86" stop-color="#f08a3c"/>
    </linearGradient>
    <radialGradient id="sun" cx="{sun_x}" cy="{sun_y}" r="{H * 0.75}" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#ffd59a" stop-opacity="0.95"/>
      <stop offset="0.12" stop-color="#ffa057" stop-opacity="0.75"/>
      <stop offset="0.4" stop-color="#e2683a" stop-opacity="0.25"/>
      <stop offset="1" stop-color="#e2683a" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="haze" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#f3a35c" stop-opacity="0"/>
      <stop offset="1" stop-color="#f3a35c" stop-opacity="0.18"/>
    </linearGradient>
    <linearGradient id="read" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#0c0a12" stop-opacity="0.55"/>
      <stop offset="0.6" stop-color="#0c0a12" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <rect width="{W}" height="{H}" fill="url(#sky)"/>
  {stars(7, 140)}
  <rect width="{W}" height="{H}" fill="url(#sun)"/>
  <circle cx="{sun_x}" cy="{sun_y}" r="46" fill="#ffe2b5" opacity="0.95"/>
  <rect y="{H * 0.55}" width="{W}" height="{H * 0.25}" fill="url(#haze)"/>
  {ridges}
  <rect width="{W}" height="{H}" fill="url(#read)"/>
</svg>
"""


def mark_svg(size: int = 256) -> str:
    """The logo: the sun setting behind a ridge, in a rounded square."""
    s = size
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{s}" height="{s}" viewBox="0 0 64 64">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#2a1834"/>
      <stop offset="1" stop-color="#5e2740"/>
    </linearGradient>
    <linearGradient id="sun" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#ffd59a"/>
      <stop offset="1" stop-color="#f2762e"/>
    </linearGradient>
  </defs>
  <rect width="64" height="64" rx="16" fill="url(#bg)"/>
  <circle cx="34" cy="38" r="15" fill="url(#sun)"/>
  <path d="M0,46 L14,34 L22,40 L33,28 L45,41 L52,36 L64,45 L64,64 L0,64 Z" fill="#170d18"/>
</svg>
"""


def render(svg: str, name: str, width: int, height: int) -> None:
    import gi

    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf

    svg_path = os.path.join(HERE, f"{name}.svg")
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(svg)
    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(svg_path, width, height, False)
    pixbuf.savev(os.path.join(HERE, f"{name}.png"), "png", [], [])


if __name__ == "__main__":
    render(hero_svg(), "hero-dusk", W, H)
    render(mark_svg(), "mark", 256, 256)
    print("Wrote hero-dusk.png and mark.png")
