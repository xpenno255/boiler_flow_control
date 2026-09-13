"""Render the original vector mark. Optional dependency: cairosvg."""

from pathlib import Path

import cairosvg

ROOT = Path(__file__).resolve().parents[1]
for filename, size in (("icon.png", 256), ("icon@2x.png", 512)):
    cairosvg.svg2png(
        url=str(ROOT / "assets/icon.svg"),
        write_to=str(ROOT / "custom_components/boiler_flow_control/brand" / filename),
        output_width=size,
        output_height=size,
    )
