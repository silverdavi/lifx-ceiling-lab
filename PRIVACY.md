# Privacy and masking policy

This repository is a public extract of a private home-automation project. Any
value that identifies a specific device, network, or household is **masked
structurally**: the shape of the value is preserved so you can see what a real
one looks like, but the identifying digits are replaced with `x`.

## Masking conventions

| Kind of value | Real shape | Published as | Note |
| --- | --- | --- | --- |
| Device serial / MAC | `d073d5` + 6 hex digits | `d073d5xxxxxx` | `d0:73:d5` is the LIFX OUI, kept so you recognise it in a packet capture |
| LAN IP address | dotted quad | `xxx.xxx.xxx.xxx` | your fixture's address goes in `config.yaml` |
| Hostnames | — | omitted | nothing here needs one |

## What is intentionally not in this repository

- Real serial numbers, IP addresses, or network names.
- Photographs that identify a household (the calibration `ideal*.png` images
  are synthetic renders of the patterns, not photos).
- Any cloud tokens, API keys, or account identifiers. The LAN protocol used
  here needs none.

## Your own data

`config.yaml` (git-ignored; copy from `config.example.yaml`) is where your
fixture's IP and serial live. `scripts/check_secrets.py` runs over tracked
files and fails if a full `d073d5`-prefixed serial or a private-looking
dotted-quad IP sneaks into a commit — run it before publishing forks.
