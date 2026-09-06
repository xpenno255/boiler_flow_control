"""Make the pure `core` package importable without Home Assistant."""
import sys
from pathlib import Path

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "boiler_flow_control"
if str(COMPONENT) not in sys.path:
    sys.path.insert(0, str(COMPONENT))
