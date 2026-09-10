"""lifx_ceiling — LAN control for the LIFX Ceiling 8x8 matrix.

The core client is standard library only. See README.md for the frame file
schema, calibration workflow, and examples.
"""

from .client import (
    HSBK,
    PORT,
    CeilingClient,
    connect,
    discover,
    discover_all,
    hex_to_hsbk,
    hue_u16,
    load_config,
    pack_colors,
    rgb_to_hsbk,
    unit_u16,
    unpack_colors,
)
from .frames import load_frames, load_named_frame, save_frames
from .transform import (
    DEFAULT_ROTATE,
    UPLIGHT_INDEX,
    VALID_ROTATIONS,
    transform_zones,
    with_uplight_masked,
)

__all__ = [
    "HSBK",
    "PORT",
    "CeilingClient",
    "connect",
    "discover",
    "discover_all",
    "hex_to_hsbk",
    "hue_u16",
    "load_config",
    "pack_colors",
    "rgb_to_hsbk",
    "unit_u16",
    "unpack_colors",
    "load_frames",
    "load_named_frame",
    "save_frames",
    "DEFAULT_ROTATE",
    "UPLIGHT_INDEX",
    "VALID_ROTATIONS",
    "transform_zones",
    "with_uplight_masked",
]
