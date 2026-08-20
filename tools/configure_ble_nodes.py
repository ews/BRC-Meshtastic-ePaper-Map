#!/usr/bin/env python3
"""Audit and repair an allowlisted set of Meshtastic radios over BLE.

The desired channel URL, BLE PIN, and target inventory are loaded from a
git-ignored .env file. Audit is the default. Applying changes requires the
explicit --apply flag and an expected node ID for every BLE address.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import re
import subprocess
import sys
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from meshtastic.protobuf import apponly_pb2, channel_pb2, config_pb2
from tabulate import tabulate

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = ROOT / ".env"
CHANNEL_URL_ENV = "MESHTASTIC_CHANNEL_URL"
BLE_PIN_ENV = "MESHTASTIC_BLE_PIN"
BLE_TARGETS_ENV = "MESHTASTIC_BLE_TARGETS"
DEFAULT_BLE_PIN = "123456"
NODE_ID_RE = re.compile(r"^![0-9a-fA-F]{8}$")
BLE_ADDRESS_RE = re.compile(r"^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
RECOMMENDED_FIRMWARE_RE = re.compile(r"^2\.8(?:\.|$)")


class ConfigurationError(ValueError):
    """Raised when private configuration or inventory is invalid."""


class PairingError(RuntimeError):
    """Raised when BlueZ cannot pair with an allowlisted radio."""


@dataclass(frozen=True)
class BleTarget:
    """One explicitly allowed BLE address and its expected mesh identity."""

    address: str
    expected_node_id: str | None = None


@dataclass
class DesiredChannels:
    """Channel settings decoded from the private Meshtastic URL."""

    settings: list


@dataclass
class DeviceAudit:
    """Secret-free audit result for a single radio."""

    address: str
    node_id: str = "unknown"
    name: str = "unknown"
    firmware: str = "unknown"
    location: str = "unknown"
    differences: list[str] = field(default_factory=list)
    advisories: list[str] = field(default_factory=list)
    error: str | None = None
    changed: bool = False

    @property
    def result(self) -> str:
        if self.error:
            return "ERROR"
        if self.differences:
            return "MISMATCH"
        if self.advisories:
            return "OK (warning)"
        return "OK"


def parse_env_file(path: str | Path) -> dict[str, str]:
    """Parse the small KEY=VALUE subset needed here without exposing secrets.

    Inline ``#`` characters are deliberately preserved because Meshtastic
    channel URLs use a URL fragment containing the encrypted channel payload.
    """
    path = Path(path)
    if not path.exists():
        return {}

    values = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not key:
            raise ConfigurationError(f"{path}:{line_number}: expected KEY=VALUE")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def merged_environment(
    path: str | Path, environ: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Return .env values with the real process environment taking priority."""
    values = parse_env_file(path)
    environ = os.environ if environ is None else environ
    for key in (CHANNEL_URL_ENV, BLE_PIN_ENV, BLE_TARGETS_ENV):
        if key in environ:
            values[key] = environ[key]
    return values


def parse_targets(raw_targets: str | Iterable[str]) -> list[BleTarget]:
    """Parse comma-separated ADDRESS[=!nodeid] allowlist entries."""
    if isinstance(raw_targets, str):
        entries = raw_targets.split(",")
    else:
        entries = list(raw_targets)

    targets = []
    seen = set()
    for raw_entry in entries:
        entry = raw_entry.strip()
        if not entry:
            continue
        address, separator, node_id = entry.partition("=")
        address = address.strip().upper()
        node_id = node_id.strip().lower() if separator else ""
        if not BLE_ADDRESS_RE.fullmatch(address):
            raise ConfigurationError(f"invalid BLE address in target: {address!r}")
        if node_id and not NODE_ID_RE.fullmatch(node_id):
            raise ConfigurationError(
                f"invalid expected node ID for {address}: {node_id!r}"
            )
        if address in seen:
            raise ConfigurationError(f"duplicate BLE target: {address}")
        seen.add(address)
        targets.append(BleTarget(address, node_id or None))
    return targets


def decode_channel_url(url: str) -> DesiredChannels:
    """Decode and validate the desired channel 0/channel 1 policy."""
    if not url or "#" not in url:
        raise ConfigurationError(
            f"{CHANNEL_URL_ENV} must contain a Meshtastic channel URL"
        )
    payload = url.rsplit("#", 1)[1].strip()
    payload += "=" * ((4 - len(payload) % 4) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload)
        channel_set = apponly_pb2.ChannelSet()
        channel_set.ParseFromString(decoded)
    except Exception as exc:
        raise ConfigurationError(
            f"{CHANNEL_URL_ENV} is not a valid Meshtastic channel URL"
        ) from exc

    if len(channel_set.settings) < 2:
        raise ConfigurationError("channel URL must contain channel 0 and channel 1")
    desired = []
    for source in channel_set.settings[:2]:
        copied = channel_pb2.ChannelSettings()
        copied.CopyFrom(source)
        desired.append(copied)

    if desired[0].module_settings.position_precision != 0:
        raise ConfigurationError("channel 0 must have location sharing disabled")
    if desired[1].module_settings.position_precision == 0:
        raise ConfigurationError("channel 1 must have location sharing enabled")
    if not desired[0].name or not desired[1].name:
        raise ConfigurationError("channel 0 and channel 1 must both have names")
    if not desired[0].psk or not desired[1].psk:
        raise ConfigurationError("channel 0 and channel 1 must both be encrypted")
    return DesiredChannels(desired)


def key_fingerprint(key: bytes) -> str:
    """Return a non-secret identifier suitable for comparisons and logs."""
    return hashlib.sha256(bytes(key)).hexdigest()[:12]


def channel_differences(channels: Sequence, desired: DesiredChannels) -> list[str]:
    """Return secret-free differences from the desired location policy."""
    differences = []
    expected_roles = (
        channel_pb2.Channel.Role.PRIMARY,
        channel_pb2.Channel.Role.SECONDARY,
    )
    for index, expected_settings in enumerate(desired.settings):
        if index >= len(channels):
            differences.append(f"channel {index} is missing")
            continue
        actual = channels[index]
        if actual.role != expected_roles[index]:
            actual_role = channel_pb2.Channel.Role.Name(actual.role)
            expected_role = channel_pb2.Channel.Role.Name(expected_roles[index])
            differences.append(
                f"channel {index} role is {actual_role}, expected {expected_role}"
            )
        if actual.settings.name != expected_settings.name:
            differences.append(
                f"channel {index} name is {actual.settings.name!r}, "
                f"expected {expected_settings.name!r}"
            )
        if bytes(actual.settings.psk) != bytes(expected_settings.psk):
            differences.append(
                f"channel {index} key fingerprint is "
                f"{key_fingerprint(actual.settings.psk)}, expected "
                f"{key_fingerprint(expected_settings.psk)}"
            )
        actual_precision = actual.settings.module_settings.position_precision
        expected_precision = expected_settings.module_settings.position_precision
        if actual_precision != expected_precision:
            differences.append(
                f"channel {index} position precision is {actual_precision}, "
                f"expected {expected_precision}"
            )
        if (
            actual.settings.module_settings.is_muted
            != expected_settings.module_settings.is_muted
        ):
            differences.append(
                f"channel {index} muted setting differs from the channel URL"
            )
        if actual.settings.uplink_enabled != expected_settings.uplink_enabled:
            differences.append(
                f"channel {index} MQTT uplink setting differs from the channel URL"
            )
        if actual.settings.downlink_enabled != expected_settings.downlink_enabled:
            differences.append(
                f"channel {index} MQTT downlink setting differs from the channel URL"
            )

    for index, channel in enumerate(channels[2:], start=2):
        if (
            channel.role != channel_pb2.Channel.Role.DISABLED
            and channel.settings.module_settings.position_precision != 0
        ):
            differences.append(
                f"channel {index} also has location sharing enabled; "
                "expected only channel 1"
            )
    return differences


def apply_channel_policy(local_node, desired: DesiredChannels) -> list[int]:
    """Write only mismatched channel slots and return their indexes."""
    channels = local_node.channels
    if channels is None or len(channels) < 2:
        raise RuntimeError("radio did not provide channel 0 and channel 1")

    changed = []
    expected_roles = (
        channel_pb2.Channel.Role.PRIMARY,
        channel_pb2.Channel.Role.SECONDARY,
    )
    for index, expected_settings in enumerate(desired.settings):
        channel = channels[index]
        expected = channel_pb2.Channel()
        expected.index = index
        expected.role = expected_roles[index]
        expected.settings.CopyFrom(expected_settings)
        if channel.SerializeToString() != expected.SerializeToString():
            channel.CopyFrom(expected)
            local_node.writeChannel(index)
            changed.append(index)

    for index, channel in enumerate(channels[2:], start=2):
        if (
            channel.role != channel_pb2.Channel.Role.DISABLED
            and channel.settings.module_settings.position_precision != 0
        ):
            channel.settings.module_settings.position_precision = 0
            local_node.writeChannel(index)
            changed.append(index)
    return changed


def local_identity(interface) -> tuple[str, str]:
    """Return the connected radio's node ID and human-readable name."""
    node_num = int(interface.myInfo.my_node_num)
    node_id = f"!{node_num:08x}"
    node = (getattr(interface, "nodesByNum", {}) or {}).get(node_num, {})
    user = node.get("user", {})
    name = user.get("longName") or user.get("shortName") or node_id
    return node_id, name


def location_status(interface) -> tuple[str, list[str]]:
    """Summarize GPS/fixed-position state without changing source settings."""
    position_config = interface.localNode.localConfig.position
    try:
        gps_mode = config_pb2.Config.PositionConfig.GpsMode.Name(
            position_config.gps_mode
        )
    except ValueError:
        gps_mode = str(position_config.gps_mode)

    node_num = int(interface.myInfo.my_node_num)
    node = (getattr(interface, "nodesByNum", {}) or {}).get(node_num, {})
    position = node.get("position", {})
    latitude = position.get("latitude")
    longitude = position.get("longitude")
    if latitude is None and position.get("latitudeI") is not None:
        latitude = position["latitudeI"] * 1e-7
    if longitude is None and position.get("longitudeI") is not None:
        longitude = position["longitudeI"] * 1e-7
    has_position = latitude is not None and longitude is not None

    if position_config.fixed_position:
        return "fixed position", []
    if has_position:
        return f"{gps_mode}, fix available", []
    if gps_mode == "ENABLED":
        return "GPS enabled, no fix", ["GPS has no current position fix"]
    if gps_mode == "NOT_PRESENT":
        return "phone location required", [
            "radio has no GPS; verify the phone app is providing background location"
        ]
    return f"GPS {gps_mode.lower()}, no fix", [
        "radio has no usable GPS/fixed/phone-provided position"
    ]


def audit_interface(
    interface, target: BleTarget, desired: DesiredChannels
) -> DeviceAudit:
    """Audit a connected interface without exposing any channel key."""
    node_id, name = local_identity(interface)
    metadata = getattr(interface, "metadata", None)
    firmware = getattr(metadata, "firmware_version", None) or "unknown"
    location, advisories = location_status(interface)
    if firmware == "unknown":
        advisories.append("firmware version unavailable; Burning Mesh 2.8.x required")
    elif not RECOMMENDED_FIRMWARE_RE.match(firmware):
        advisories.append(
            f"firmware {firmware} is not the recommended Burning Mesh 2.8.x"
        )
    differences = channel_differences(interface.localNode.channels or [], desired)
    if target.expected_node_id and node_id.lower() != target.expected_node_id:
        differences.insert(
            0,
            f"identity is {node_id}, expected {target.expected_node_id}; "
            "refusing changes",
        )
    return DeviceAudit(
        address=target.address,
        node_id=node_id,
        name=name,
        firmware=firmware,
        location=location,
        differences=differences,
        advisories=advisories,
    )


def _bluetoothctl(
    *arguments: str,
    input_text: str | None = None,
    timeout: float = 35,
) -> subprocess.CompletedProcess:
    """Run bluetoothctl without ever echoing stdin or captured PIN data."""
    try:
        return subprocess.run(
            ["bluetoothctl", *arguments],
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise PairingError("bluetoothctl is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise PairingError("bluetoothctl pairing timed out") from exc


def is_paired(address: str) -> bool:
    """Return whether BlueZ already has a bond for this address."""
    result = _bluetoothctl("info", address, timeout=10)
    output = f"{result.stdout}\n{result.stderr}".lower()
    return "paired: yes" in output


def ensure_paired(address: str, pin: str, timeout: int = 35) -> None:
    """Pair and trust one previously discovered BLE device using a fixed PIN."""
    if is_paired(address):
        return
    if not pin.isdigit() or not 1 <= len(pin) <= 6 or int(pin) > 999999:
        raise ConfigurationError(f"{BLE_PIN_ENV} must be a 1-6 digit passkey")

    result = _bluetoothctl(
        "--agent",
        "KeyboardOnly",
        "--timeout",
        str(timeout),
        "pair",
        address,
        input_text=f"{pin}\n",
        timeout=timeout + 5,
    )
    output = f"{result.stdout}\n{result.stderr}"
    lowered = output.lower()
    if result.returncode != 0 or "failed to pair" in lowered:
        raise PairingError(
            "pairing failed; confirm the radio is awake, disconnected from its phone, "
            "and configured for the expected fixed PIN"
        )
    if "pairing successful" not in lowered and not is_paired(address):
        raise PairingError("BlueZ did not confirm that pairing succeeded")

    trusted = _bluetoothctl("trust", address, timeout=10)
    if trusted.returncode != 0:
        raise PairingError("paired successfully but BlueZ could not trust the device")


def scan_devices():
    """Return nearby Meshtastic BLE peripherals."""
    from meshtastic.ble_interface import BLEInterface

    return BLEInterface.scan()


def connect_ble(address: str):
    """Connect to one allowlisted Meshtastic BLE peripheral."""
    from meshtastic.ble_interface import BLEInterface

    return BLEInterface(address)


def close_interface(interface) -> None:
    """Close an interface, preserving the original operation's exception."""
    if interface is not None:
        interface.close()


def configure_target(
    target: BleTarget,
    desired: DesiredChannels,
    *,
    apply: bool,
    connect: Callable[[str], object] = connect_ble,
    settle_seconds: float = 2.0,
) -> DeviceAudit:
    """Audit one target and optionally repair and verify its channel policy."""
    interface = None
    try:
        interface = connect(target.address)
        audit = audit_interface(interface, target, desired)
        identity_mismatch = bool(
            target.expected_node_id
            and audit.node_id.lower() != target.expected_node_id
        )
        if not apply or not audit.differences or identity_mismatch:
            return audit

        changed_indexes = apply_channel_policy(interface.localNode, desired)
        audit.changed = bool(changed_indexes)
    except Exception as exc:  # noqa: BLE001 - isolate one radio's library failure
        return DeviceAudit(address=target.address, error=str(exc))
    finally:
        close_interface(interface)

    if settle_seconds:
        time.sleep(settle_seconds)
    interface = None
    try:
        interface = connect(target.address)
        verified = audit_interface(interface, target, desired)
        verified.changed = audit.changed
        if verified.differences:
            verified.error = "channel changes did not pass read-back verification"
        return verified
    except Exception as exc:  # noqa: BLE001 - report failed read-back per radio
        return DeviceAudit(
            address=target.address,
            changed=audit.changed,
            error=f"could not reconnect for verification: {exc}",
        )
    finally:
        close_interface(interface)


def render_scan(devices: Sequence) -> str:
    """Render discovered device names and addresses for inventory creation."""
    rows = sorted(
        (
            (getattr(device, "name", None) or "unknown", device.address)
            for device in devices
        ),
        key=lambda row: row[0].lower(),
    )
    if not rows:
        return "No Meshtastic BLE devices found."
    return tabulate(rows, headers=("BLE name", "BLE address"), tablefmt="simple")


def render_audits(audits: Sequence[DeviceAudit]) -> str:
    """Render a compact summary plus per-device diagnostic details."""
    rows = [
        (
            audit.address,
            audit.node_id,
            audit.name,
            audit.firmware,
            audit.location,
            f"{audit.result} (changed)" if audit.changed else audit.result,
        )
        for audit in audits
    ]
    output = [
        tabulate(
            rows,
            headers=("BLE address", "Node", "Name", "Firmware", "Location", "Result"),
            tablefmt="simple",
            disable_numparse=True,
        )
    ]
    for audit in audits:
        details = []
        details.extend(f"mismatch: {item}" for item in audit.differences)
        details.extend(f"warning: {item}" for item in audit.advisories)
        if audit.error:
            details.append(f"error: {audit.error}")
        if details:
            output.append(f"\n{audit.address} ({audit.node_id}):")
            output.extend(f"  - {detail}" for detail in details)
    return "\n".join(output)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--scan", action="store_true", help="list nearby radios only")
    mode.add_argument(
        "--apply",
        action="store_true",
        help="repair mismatched allowlisted radios and verify by reconnecting",
    )
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        metavar="ADDRESS=!NODEID",
        help="override/add an explicit target (repeatable)",
    )
    parser.add_argument(
        "--skip-pairing",
        action="store_true",
        help="require devices to have already been paired by BlueZ",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run scan, audit, or explicit apply mode."""
    args = build_parser().parse_args(argv)
    if args.scan:
        try:
            devices = scan_devices()
        except Exception as exc:  # noqa: BLE001 - BLE backend error boundary
            print(f"error: BLE scan failed: {exc}", file=sys.stderr)
            return 1
        print(render_scan(devices))
        return 0

    try:
        environment = merged_environment(args.env_file)
        desired = decode_channel_url(environment.get(CHANNEL_URL_ENV, ""))
        raw_targets = args.target or environment.get(BLE_TARGETS_ENV, "")
        targets = parse_targets(raw_targets)
        if not targets:
            raise ConfigurationError(
                f"no BLE targets configured; set {BLE_TARGETS_ENV} in {args.env_file}"
            )
        if args.apply and any(not target.expected_node_id for target in targets):
            raise ConfigurationError(
                "--apply requires an expected !nodeid for every BLE target"
            )
        pin = environment.get(BLE_PIN_ENV, DEFAULT_BLE_PIN)
    except ConfigurationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    desired_names = ", ".join(
        f"{index}:{settings.name} location="
        f"{settings.module_settings.position_precision}"
        for index, settings in enumerate(desired.settings)
    )
    print(f"Desired policy: {desired_names}")
    print("Mode: APPLY AND VERIFY" if args.apply else "Mode: audit only")

    try:
        discovered = scan_devices()
    except Exception as exc:  # noqa: BLE001 - BLE backend error boundary
        print(f"error: BLE scan failed: {exc}", file=sys.stderr)
        return 1
    discovered_addresses = {device.address.upper() for device in discovered}

    audits = []
    for target in targets:
        if target.address not in discovered_addresses:
            audits.append(
                DeviceAudit(
                    address=target.address,
                    node_id=target.expected_node_id or "unknown",
                    error="not found in this BLE scan",
                )
            )
            continue
        if not args.skip_pairing:
            try:
                ensure_paired(target.address, pin)
            except (ConfigurationError, PairingError) as exc:
                audits.append(
                    DeviceAudit(
                        address=target.address,
                        node_id=target.expected_node_id or "unknown",
                        error=str(exc),
                    )
                )
                continue
        audits.append(configure_target(target, desired, apply=args.apply))

    print(render_audits(audits))
    if any(audit.error for audit in audits):
        return 1
    if any(audit.differences for audit in audits):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
