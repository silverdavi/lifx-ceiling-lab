# LIFX Ceiling — LAN protocol notes

What we learned driving a LIFX Ceiling (round, US, product id 176, firmware
4.2) over the LAN protocol. Cloud HTTP is a different API
([LIFX HTTP API](https://api.developer.lifx.com/)); everything here is
**LAN UDP only**. Official protocol docs:
[lan.developer.lifx.com](https://lan.developer.lifx.com/docs/introduction).

Serials in examples are structurally masked (`d073d5xxxxxx`): `d0:73:d5` is
the LIFX OUI, the last six hex digits identify your unit.

## The fixture

| | |
|---|---|
| Product | LIFX Ceiling US (round), product id **176** |
| Serial / MAC | `d073d5xxxxxx` (`d073d5` = LIFX OUI) |
| Matrix | **8×8**, 64 HSBK zones, one tile in the chain |
| Layout | zones **0–62** downlight, zone **63** uplight ring |
| Firmware tested | **4.2** (host + wifi) |

Same class of device, for comparison:

| Product id | Model | Zones |
|---|---|---|
| 176 / 177 | Ceiling US / Intl | 8×8 (64), uplight = 63 |
| 201 / 202 | Ceiling Capsule 26×13 US / Intl | 16×8 (128), uplight = 127 |

Firmware 4.2 means: broadcast discovery, not mDNS (`_lifx._udp` needs
≥ 4.110). The **Sky** firmware effect is documented as ≥ 4.4 — Morph / Flame
work. `CopyFrameBuffer` (716) is for 128-zone Capsule transitions; a 64-zone
unit does not need it.

### What this device answers

| Capability | Ceiling 176 |
|---|---|
| On / off (`SetPower` 21, `SetLightPower` 117) | yes |
| Whole-fixture color (`SetColor` 102) | yes — paints **all** 64 zones the same |
| Per-zone pixel map (`Set64` 715 / `Get64` 707) | yes — 8×8, width=8 |
| Independent uplight vs downlight | yes — last zone vs the rest |
| Waveforms (`SetWaveform` 103) | yes — whole fixture as one color |
| Firmware effects (`SetTileEffect` 719) | Morph / Flame; Sky unproven on 4.2 |
| Linear multizone (`SetColorZones` 501, extended 511) | **no** (wrong product class) |
| Infrared / HEV | **no** |

## Packet shape

LIFX devices speak a packed **little-endian binary** protocol over **UDP/IPv4
port 56700**. Every datagram is a **36-byte header** plus an optional payload.

1. **Frame** (8 bytes) — `size` (uint16), then a packed uint16: protocol
   **1024** (12 bits), `addressable` (1, always true), `tagged` (1), `origin`
   (2 bits, 0), then `source` (uint32). `source` 0 and 1 are reserved; pick
   something else and match it on replies.
2. **Frame address** (16 bytes) — `target` (8 bytes: 6-byte serial + two
   zeros), 6 reserved, then `res_required` / `ack_required` (1 bit each) + 6
   reserved bits, then `sequence` (uint8, wrap 0–255).
3. **Protocol header** (12 bytes) — 8 reserved, `pkt_type` (uint16), 2
   reserved.
4. **Payload** — type-specific.

`tagged=1` and `target=0` = broadcast (discovery). `tagged=0` and `target` =
serial for unicast.

Get messages reply with State even if `res_required=0`. After a Set, a State
reply (if any) is often the **pre-change** snapshot — prefer ack + a later
Get. **`Set64` (715) has no State response** even with `res_required=1`; use
ack or `Get64`.

## Discovery

UDP broadcast `GetService` (2) to `255.255.255.255:56700` with `tagged=1`.
Devices reply `StateService` (3) from their IP; then unicast with `target` =
serial bytes (`d0 73 d5 xx xx xx 00 00`). See
`src/lifx_ceiling/client.py::discover`.

## Color: HSBK

Each zone is Hue, Saturation, Brightness, Kelvin
([docs](https://lan.developer.lifx.com/docs/representing-color-with-hsbk)):

- Hue 0–360° → uint16: `int(round(0x10000 * hue) / 360) % 0x10000`
- Saturation / brightness 0–1 → `int(round(0xFFFF * x))`
- Kelvin is the plain kelvin number (typically 1500–9000); ignored at full
  saturation.

## Pixel map: `Get64` / `Set64`

The Ceiling is a **matrix** device; same messages as Tile
([tile control](https://lan.developer.lifx.com/docs/tile-control)).

**Get64 (707)** payload (6 bytes): `tile_index`, `length`, reserved, `x`,
`y`, `width` — for this fixture `0, 1, 0, 0, 0, 8`. Reply **State64 (711)**:
tile index + rect + 64 × HSBK (512 color bytes). Index `i` is row-major:
`y = i // 8`, `x = i % 8`.

**Set64 (715)** payload: `tile_index`, `length`, `fb_index` (0 = visible),
`x`, `y`, `width` (8), `duration` ms (uint32), then 64 colors. No State
reply.

### Zone 63 is the uplight

Zone 63 is **not** the bottom-right downlight pixel. It controls the
up-facing ring, so treating all 64 protocol zones as a visible square leaks
that pixel onto the ceiling and changes the room wash. This client masks zone
63 to brightness 0 on every normal `Set64`; pass `--include-uplight` only
when a design deliberately controls the ring. State restoration bypasses the
mask because it must reproduce the saved fixture exactly.

### Orientation

On our installed disc, the physical top was the **bottom** of the Set64
index grid — a portrait sent in protocol order appeared upside down, fixed
with a 180° clockwise remap. Mounting varies per install: push a
recognisable static frame with `--rotate 0`, look up, and put the winning
rotation in `config.yaml`.

## No on-device animation storage

A custom animation **cannot** be uploaded once and left looping on the
fixture. The LAN protocol has no frame-buffer upload: `Set64` writes the
*current* map and returns. The only thing the device runs autonomously is a
firmware effect (`SetTileEffect` 719) — Morph / Flame / Sky driven by a
palette of at most 16 HSBK colors, with motion generated in firmware. There
is no way to express a scripted 900-frame sequence as a palette.

So any authored animation needs a LAN host streaming `Set64` at the frame
rate. The cost is small — 20 packets/s, well under the rate that makes LIFX
devices drop packets — but the host must stay up (see
`systemd/lifx-firefly.service.example`). LIFX cautions against flooding:
avoid tight loops with no frame delay, especially alongside discovery or
state polling.

The official LIFX app cannot host this either: its public HTTP API can list
and activate existing scenes but has **no create-scene endpoint**, and
neither scenes nor the API accept a multi-frame matrix animation. When you
want the app to control the fixture, stop streaming and power it off once
("release") so the two senders never interleave.

## Message reference used here

| Packet | Type | Notes |
|---|---|---|
| GetService / StateService | 2 / 3 | discovery |
| GetPower / StatePower | 20 / 22 | 0 off, 65535 on |
| SetColor | 102 | washes all zones |
| SetLightPower | 117 | power with fade duration |
| GetDeviceChain / StateDeviceChain | 701 / 702 | tile layout |
| Get64 / State64 | 707 / 711 | read pixel map |
| Set64 | 715 | write pixel map |
| GetTileEffect / SetTileEffect / StateTileEffect | 718 / 719 / 720 | Morph, Flame, Sky |

Full catalogs: [querying](https://lan.developer.lifx.com/docs/querying-the-device-for-data),
[changing](https://lan.developer.lifx.com/docs/changing-a-device),
[information messages](https://lan.developer.lifx.com/docs/information-messages).
Usage is bound by the [LIFX Developer Terms](https://www.lifx.com/pages/developer-terms-of-use).
