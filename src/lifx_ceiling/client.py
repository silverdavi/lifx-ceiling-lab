"""Standard-library-only LIFX LAN client for the Ceiling 8x8 matrix.

UDP port 56700, little-endian binary protocol. The packets used here:

- ``GetService`` (2) / ``StateService`` (3) — broadcast discovery
- ``Get64`` (707) / ``State64`` (711) — read the current zone map
- ``Set64`` (715) — write all 64 zones in one datagram
- ``GetPower`` (20) / ``StatePower`` (22), ``SetLightPower`` (117)

No cloud, no tokens: anything on the LAN can drive the fixture.

Device identity is configured, not hard-coded. Provide the fixture IP and
serial via ``config.yaml`` (see ``config.example.yaml``), environment
variables ``LIFX_IP`` / ``LIFX_SERIAL``, or let ``connect()`` broadcast and
take the first device that answers. Serials look like ``d073d5xxxxxx`` —
``d0:73:d5`` is the LIFX OUI, the last six hex digits are your unit.
"""

from __future__ import annotations

import colorsys
import json
import os
import random
import socket
import struct
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .transform import (
    DEFAULT_ROTATE,
    VALID_ROTATIONS,
    transform_zones,
    with_uplight_masked,
)

PORT = 56700
DEFAULT_STATE_FILE = Path(tempfile.gettempdir()) / "lifx-ceiling-original.json"
HSBK = tuple[int, int, int, int]

_MASKED = ("xxx.xxx.xxx.xxx", "d073d5xxxxxx", "")


# --------------------------------------------------------------------------
# HSBK color helpers
# --------------------------------------------------------------------------

def hue_u16(degrees: float) -> int:
    return int(round(0x10000 * degrees) / 360) % 0x10000


def unit_u16(value: float) -> int:
    return int(round(0xFFFF * max(0.0, min(1.0, value))))


def rgb_to_hsbk(red: int, green: int, blue: int, kelvin: int = 3500) -> HSBK:
    hue, saturation, brightness = colorsys.rgb_to_hsv(
        red / 255, green / 255, blue / 255
    )
    return (
        hue_u16(hue * 360),
        unit_u16(saturation),
        unit_u16(brightness),
        kelvin,
    )


def hex_to_hsbk(value: str, kelvin: int = 3500) -> HSBK:
    value = value.removeprefix("#")
    if len(value) != 6:
        raise ValueError(f"expected six-digit RGB hex color, got {value!r}")
    return rgb_to_hsbk(*bytes.fromhex(value), kelvin=kelvin)


def pack_colors(colors: Sequence[HSBK]) -> bytes:
    if len(colors) != 64:
        raise ValueError(f"Set64 requires 64 colors, got {len(colors)}")
    return b"".join(struct.pack("<HHHH", *color) for color in colors)


def unpack_colors(payload: bytes) -> list[HSBK]:
    if len(payload) != 512:
        raise ValueError(f"expected 512 color bytes, got {len(payload)}")
    return [
        struct.unpack_from("<HHHH", payload, offset)
        for offset in range(0, len(payload), 8)
    ]


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

def load_config(path: Path | None = None) -> dict[str, object]:
    """Read fixture/display settings from config.yaml, env vars, or defaults.

    The parser is deliberately tiny (two-level ``key: value`` YAML subset) so
    the core package stays dependency-free. Masked placeholder values from
    ``config.example.yaml`` are treated as unset. Environment variables
    ``LIFX_IP``, ``LIFX_SERIAL``, and ``LIFX_ROTATE`` override the file.
    """
    settings: dict[str, object] = {
        "ip": None,
        "port": PORT,
        "serial": None,
        "rotate": DEFAULT_ROTATE,
        "flip_h": False,
        "flip_v": False,
    }
    candidates = [path] if path else [
        Path(os.environ.get("LIFX_CONFIG", "config.yaml")),
        Path(__file__).resolve().parent.parent.parent / "config.yaml",
    ]
    for candidate in candidates:
        if candidate and candidate.is_file():
            for line in candidate.read_text().splitlines():
                stripped = line.split("#", 1)[0].strip()
                if ":" not in stripped:
                    continue
                key, _, raw = stripped.partition(":")
                key, raw = key.strip(), raw.strip().strip("'\"")
                if key in settings and raw not in _MASKED:
                    if key in ("port", "rotate"):
                        settings[key] = int(raw)
                    elif key in ("flip_h", "flip_v"):
                        settings[key] = raw.lower() in ("true", "yes", "1", "on")
                    else:
                        settings[key] = raw
            break
    if os.environ.get("LIFX_IP"):
        settings["ip"] = os.environ["LIFX_IP"]
    if os.environ.get("LIFX_SERIAL"):
        settings["serial"] = os.environ["LIFX_SERIAL"]
    if os.environ.get("LIFX_ROTATE"):
        settings["rotate"] = int(os.environ["LIFX_ROTATE"])
    return settings


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------

class CeilingClient:
    def __init__(
        self,
        ip: str,
        *,
        serial: str | None = None,
        port: int = PORT,
        timeout: float = 2.0,
        rotate: int = DEFAULT_ROTATE,
        flip_h: bool = False,
        flip_v: bool = False,
    ) -> None:
        if rotate not in VALID_ROTATIONS:
            raise ValueError(f"rotate must be one of {VALID_ROTATIONS}, got {rotate}")
        self.ip = ip
        self.port = port
        self.serial = serial.lower() if serial else None
        self.timeout = timeout
        self.rotate = rotate
        self.flip_h = flip_h
        self.flip_v = flip_v
        self.source = random.randrange(2, 2**32)
        self.sequence = 0
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(("0.0.0.0", 0))

    @property
    def target(self) -> bytes:
        if self.serial is None:
            return b"\x00" * 8  # tagged/broadcast target; we address by IP
        return bytes.fromhex(self.serial) + b"\x00\x00"

    def close(self) -> None:
        self.socket.close()

    def __enter__(self) -> "CeilingClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _header(
        self,
        packet_type: int,
        payload_size: int = 0,
        *,
        tagged: bool = False,
        response_required: bool = False,
        acknowledgement_required: bool = False,
        target: bytes | None = None,
    ) -> bytes:
        self.sequence = (self.sequence + 1) & 0xFF
        tagged = tagged or self.serial is None
        flags = 1024 | (1 << 12) | ((1 if tagged else 0) << 13)
        response_flags = (
            (1 if response_required else 0)
            | ((1 if acknowledgement_required else 0) << 1)
        )
        return (
            struct.pack("<HHI", 36 + payload_size, flags, self.source)
            + (self.target if target is None else target)
            + b"\x00" * 6
            + struct.pack("<BB", response_flags, self.sequence)
            + struct.pack("<QHH", 0, packet_type, 0)
        )

    def _send(self, packet_type: int, payload: bytes = b"") -> None:
        packet = self._header(packet_type, len(payload)) + payload
        self.socket.sendto(packet, (self.ip, self.port))

    def _request(
        self,
        packet_type: int,
        expected_type: int,
        payload: bytes = b"",
    ) -> bytes:
        packet = (
            self._header(
                packet_type,
                len(payload),
                response_required=True,
            )
            + payload
        )
        self.socket.sendto(packet, (self.ip, self.port))
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            self.socket.settimeout(max(0.01, deadline - time.monotonic()))
            try:
                data, _ = self.socket.recvfrom(4096)
            except socket.timeout:
                break
            if len(data) < 36:
                continue
            if self.serial is not None and data[8:14].hex() != self.serial:
                continue
            if struct.unpack_from("<I", data, 4)[0] != self.source:
                continue
            if struct.unpack_from("<H", data, 32)[0] == expected_type:
                if self.serial is None:
                    self.serial = data[8:14].hex()  # learn who answered
                return data[36:]
        who = self.serial or "device"
        raise TimeoutError(f"no packet {expected_type} from {who} at {self.ip}")

    def get64(self) -> list[HSBK]:
        payload = struct.pack("<BBBBBB", 0, 1, 0, 0, 0, 8)
        state = self._request(707, 711, payload)
        if len(state) < 517:
            raise ValueError(f"short State64 payload: {len(state)} bytes")
        return unpack_colors(state[5:517])

    def set64(
        self,
        colors: Sequence[HSBK],
        duration_ms: int = 0,
        *,
        mask_uplight: bool = True,
        rotate: int | None = None,
        flip_h: bool | None = None,
        flip_v: bool | None = None,
    ) -> None:
        mapped = transform_zones(
            colors,
            rotate=self.rotate if rotate is None else rotate,
            flip_h=self.flip_h if flip_h is None else flip_h,
            flip_v=self.flip_v if flip_v is None else flip_v,
        )
        effective_colors = with_uplight_masked(mapped) if mask_uplight else mapped
        payload = (
            struct.pack("<BBBBBBI", 0, 1, 0, 0, 0, 8, duration_ms)
            + pack_colors(effective_colors)
        )
        self._send(715, payload)

    def get_power(self) -> int:
        payload = self._request(20, 22)
        if len(payload) < 2:
            raise ValueError(f"short StatePower payload: {len(payload)} bytes")
        return struct.unpack_from("<H", payload)[0]

    def set_light_power(self, level: int, duration_ms: int = 0) -> None:
        if not 0 <= level <= 0xFFFF:
            raise ValueError("power level must be between 0 and 65535")
        self._send(117, struct.pack("<HI", level, duration_ms))

    def save_state(
        self, path: Path = DEFAULT_STATE_FILE, *, overwrite: bool = False
    ) -> bool:
        """Snapshot power + zone map so playback can be undone. Idempotent."""
        if path.exists() and not overwrite:
            return False
        state = {
            "serial": self.serial,
            "savedAt": datetime.now(timezone.utc).isoformat(),
            "power": self.get_power(),
            "colors": [list(color) for color in self.get64()],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(state, separators=(",", ":")) + "\n")
        os.replace(temporary, path)
        return True

    def restore_state(self, path: Path = DEFAULT_STATE_FILE) -> None:
        state = json.loads(path.read_text())
        raw_colors = state["colors"]
        if isinstance(raw_colors, str):
            colors = unpack_colors(bytes.fromhex(raw_colors))
        else:
            colors = [tuple(int(value) for value in color) for color in raw_colors]
        self.set64(
            colors,
            mask_uplight=False,
            rotate=0,
            flip_h=False,
            flip_v=False,
        )
        self.set_light_power(int(state["power"]), duration_ms=150)


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------

def discover(
    *,
    serial: str | None = None,
    timeout: float = 1.5,
    broadcast: str = "255.255.255.255",
) -> tuple[str, int, str] | None:
    """Broadcast GetService; return ``(ip, port, serial)`` of the match.

    With ``serial=None`` the first LIFX device to answer wins — fine for a
    one-fixture network, otherwise pin the serial in config.yaml.
    """
    source = random.randrange(2, 2**32)
    flags = 1024 | (1 << 12) | (1 << 13)
    packet = (
        struct.pack("<HHI", 36, flags, source)
        + b"\x00" * 14
        + struct.pack("<BB", 1, 0)
        + struct.pack("<QHH", 0, 2, 0)
    )
    expected_target = bytes.fromhex(serial.lower()) if serial else None
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("0.0.0.0", 0))
        sock.sendto(packet, (broadcast, PORT))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            sock.settimeout(max(0.01, deadline - time.monotonic()))
            try:
                data, address = sock.recvfrom(4096)
            except socket.timeout:
                break
            if len(data) < 41:
                continue
            if expected_target is not None and data[8:14] != expected_target:
                continue
            if struct.unpack_from("<I", data, 4)[0] != source:
                continue
            if struct.unpack_from("<H", data, 32)[0] != 3:
                continue
            service, port = struct.unpack_from("<BI", data, 36)
            if service == 1:
                return address[0], port, data[8:14].hex()
    return None


def connect(
    *,
    ip: str | None = None,
    serial: str | None = None,
    discovery_timeout: float = 1.5,
    rotate: int | None = None,
    flip_h: bool | None = None,
    flip_v: bool | None = None,
) -> CeilingClient:
    """Connect using explicit arguments, config.yaml/env settings, or discovery."""
    config = load_config()
    ip = ip or config["ip"]  # type: ignore[assignment]
    serial = serial or config["serial"]  # type: ignore[assignment]
    rotate = config["rotate"] if rotate is None else rotate  # type: ignore[assignment]
    flip_h = config["flip_h"] if flip_h is None else flip_h  # type: ignore[assignment]
    flip_v = config["flip_v"] if flip_v is None else flip_v  # type: ignore[assignment]
    if ip is not None:
        return CeilingClient(
            ip,
            serial=serial,
            port=int(config["port"]),  # type: ignore[arg-type]
            rotate=rotate,
            flip_h=flip_h,
            flip_v=flip_v,
        )
    found = discover(serial=serial, timeout=discovery_timeout)
    if found is None:
        raise TimeoutError(
            "no LIFX device answered discovery; set fixture.ip in config.yaml "
            "or pass --ip"
        )
    discovered_ip, port, discovered_serial = found
    return CeilingClient(
        discovered_ip,
        serial=discovered_serial,
        port=port,
        rotate=rotate,
        flip_h=flip_h,
        flip_v=flip_v,
    )
