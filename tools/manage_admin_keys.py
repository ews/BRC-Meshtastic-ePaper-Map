#!/usr/bin/env python3
"""Collect two controller public keys and enroll them across the BLE fleet."""

from __future__ import annotations

import argparse
import base64
import os
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from tabulate import tabulate

try:
    from tools.configure_ble_nodes import (
        BLE_PIN_ENV,
        BLE_TARGETS_ENV,
        DEFAULT_BLE_PIN,
        DEFAULT_ENV_FILE,
        BleTarget,
        ConfigurationError,
        PairingError,
        close_interface,
        connect_ble,
        ensure_paired,
        key_fingerprint,
        local_identity,
        parse_env_file,
        parse_targets,
        scan_devices,
    )
except ModuleNotFoundError:  # Direct execution adds tools/, not its parent.
    from configure_ble_nodes import (
        BLE_PIN_ENV,
        BLE_TARGETS_ENV,
        DEFAULT_BLE_PIN,
        DEFAULT_ENV_FILE,
        BleTarget,
        ConfigurationError,
        PairingError,
        close_interface,
        connect_ble,
        ensure_paired,
        key_fingerprint,
        local_identity,
        parse_env_file,
        parse_targets,
        scan_devices,
    )

ADMIN_BLE_NODE_ID_ENV = "MESHTASTIC_ADMIN_BLE_NODE_ID"
ADMIN_USB_NODE_ID_ENV = "MESHTASTIC_ADMIN_USB_NODE_ID"
ADMIN_USB_DEVICE_ENV = "MESHTASTIC_ADMIN_USB_DEVICE"
ADMIN_BLE_PUBLIC_KEY_ENV = "MESHTASTIC_ADMIN_BLE_PUBLIC_KEY"
ADMIN_USB_PUBLIC_KEY_ENV = "MESHTASTIC_ADMIN_USB_PUBLIC_KEY"
DEFAULT_ADMIN_BLE_NODE_ID = "!2ecbbfa5"
DEFAULT_ADMIN_USB_NODE_ID = "!913c4e9d"
MAX_ADMIN_KEYS = 3
PUBLIC_KEY_LENGTH = 32
ADMIN_ENV_KEYS = (
    BLE_PIN_ENV,
    BLE_TARGETS_ENV,
    ADMIN_BLE_NODE_ID_ENV,
    ADMIN_USB_NODE_ID_ENV,
    ADMIN_USB_DEVICE_ENV,
    ADMIN_BLE_PUBLIC_KEY_ENV,
    ADMIN_USB_PUBLIC_KEY_ENV,
)


@dataclass
class AdminAudit:
    """One radio's secret-free administrator-key state."""

    address: str
    node_id: str = "unknown"
    name: str = "unknown"
    current_count: int = 0
    missing: list[str] = field(default_factory=list)
    advisories: list[str] = field(default_factory=list)
    changed: bool = False
    error: str | None = None

    @property
    def result(self) -> str:
        if self.error:
            return "ERROR"
        if self.missing:
            return "MISSING"
        if self.advisories:
            return "OK (warning)"
        return "OK"


def progress(message: str) -> None:
    """Print one immediately visible operation update."""
    print(f"[mesh-admin] {message}", flush=True)


def normalize_node_id(raw_node_id: str, label: str) -> str:
    """Normalize an eight-digit node number into Meshtastic's ! form."""
    node_id = raw_node_id.strip().lower()
    if not node_id.startswith("!"):
        node_id = f"!{node_id}"
    if len(node_id) != 9 or any(char not in "0123456789abcdef" for char in node_id[1:]):
        raise ConfigurationError(f"{label} must be an eight-digit Meshtastic node ID")
    return node_id


def load_environment(
    path: str | Path,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Load the private file, allowing explicit process overrides."""
    values = parse_env_file(path)
    environ = os.environ if environ is None else environ
    for key in ADMIN_ENV_KEYS:
        if key in environ:
            values[key] = environ[key]
    return values


def encode_public_key(key: bytes) -> str:
    """Encode a public key using the Meshtastic CLI's accepted representation."""
    return "base64:" + base64.b64encode(bytes(key)).decode("ascii")


def decode_public_key(value: str, label: str) -> bytes:
    """Decode and validate one stored Curve25519 public key."""
    if not value.startswith("base64:"):
        raise ConfigurationError(f"{label} must start with base64:")
    try:
        key = base64.b64decode(value[7:], validate=True)
    except ValueError as exc:
        raise ConfigurationError(f"{label} is not valid base64") from exc
    if len(key) != PUBLIC_KEY_LENGTH:
        raise ConfigurationError(
            f"{label} decoded to {len(key)} bytes; expected {PUBLIC_KEY_LENGTH}"
        )
    return key


def desired_admin_keys(environment: Mapping[str, str]) -> tuple[bytes, bytes]:
    """Return the two distinct public keys previously collected into .env."""
    first = decode_public_key(
        environment.get(ADMIN_BLE_PUBLIC_KEY_ENV, ""),
        ADMIN_BLE_PUBLIC_KEY_ENV,
    )
    second = decode_public_key(
        environment.get(ADMIN_USB_PUBLIC_KEY_ENV, ""),
        ADMIN_USB_PUBLIC_KEY_ENV,
    )
    if first == second:
        raise ConfigurationError("the BLE and USB administrator keys must be distinct")
    return first, second


def update_env_file(path: str | Path, updates: Mapping[str, str]) -> None:
    """Atomically update selected values without exposing or rewriting other keys."""
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(updates)
    updated_lines = []
    for line in lines:
        stripped = line.strip()
        candidate = (
            stripped[7:].lstrip() if stripped.startswith("export ") else stripped
        )
        key, separator, _value = candidate.partition("=")
        key = key.strip()
        if separator and key in remaining:
            updated_lines.append(f"{key}={remaining.pop(key)}")
        else:
            updated_lines.append(line)
    if updated_lines and updated_lines[-1]:
        updated_lines.append("")
    updated_lines.extend(f"{key}={value}" for key, value in remaining.items())

    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("\n".join(updated_lines) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


def target_for_node_id(targets: Sequence[BleTarget], node_id: str) -> BleTarget:
    """Find the single allowlisted BLE address for an expected node ID."""
    matches = [target for target in targets if target.expected_node_id == node_id]
    if len(matches) != 1:
        raise ConfigurationError(
            f"{node_id} must appear exactly once with its node ID in {BLE_TARGETS_ENV}"
        )
    return matches[0]


def public_key_from_interface(
    interface, expected_node_id: str
) -> tuple[str, str, bytes]:
    """Verify local identity and return its public key."""
    node_id, name = local_identity(interface)
    if node_id.lower() != expected_node_id:
        raise ConfigurationError(
            f"connected to {node_id}, expected {expected_node_id}; refusing key capture"
        )
    key = bytes(interface.localNode.localConfig.security.public_key)
    if len(key) != PUBLIC_KEY_LENGTH:
        raise ConfigurationError(
            f"{node_id} public key is {len(key)} bytes; expected {PUBLIC_KEY_LENGTH}"
        )
    return node_id, name, key


def connect_serial(device: str | None):
    """Connect to the Pi's USB administrator radio."""
    from meshtastic.serial_interface import SerialInterface

    return SerialInterface(devPath=device or None, noNodes=True, timeout=60)


def pull_admin_keys(
    env_file: str | Path,
    *,
    serial_device: str | None = None,
    skip_pairing: bool = False,
    ble_connect: Callable[[str], object] = connect_ble,
    serial_connect: Callable[[str | None], object] = connect_serial,
) -> int:
    """Capture both verified controller public keys and save them atomically."""
    environment = load_environment(env_file)
    targets = parse_targets(environment.get(BLE_TARGETS_ENV, ""))
    ble_node_id = normalize_node_id(
        environment.get(ADMIN_BLE_NODE_ID_ENV, DEFAULT_ADMIN_BLE_NODE_ID),
        ADMIN_BLE_NODE_ID_ENV,
    )
    usb_node_id = normalize_node_id(
        environment.get(ADMIN_USB_NODE_ID_ENV, DEFAULT_ADMIN_USB_NODE_ID),
        ADMIN_USB_NODE_ID_ENV,
    )
    if ble_node_id == usb_node_id:
        raise ConfigurationError("the two administrator node IDs must be different")
    ble_target = target_for_node_id(targets, ble_node_id)
    pin = environment.get(BLE_PIN_ENV, DEFAULT_BLE_PIN)
    selected_serial = serial_device or environment.get(ADMIN_USB_DEVICE_ENV) or None

    progress(f"scanning for BLE administrator {ble_node_id} (10s)")
    discovered = {device.address.upper() for device in scan_devices()}
    if ble_target.address not in discovered:
        raise ConfigurationError(
            f"BLE administrator {ble_node_id} ({ble_target.address}) was not discovered"
        )
    if not skip_pairing:
        ensure_paired(
            ble_target.address,
            pin,
            status=lambda message: progress(f"BLE administrator: {message}"),
        )

    ble_interface = None
    try:
        progress(f"connecting to BLE administrator {ble_node_id}")
        ble_interface = ble_connect(ble_target.address)
        actual_ble_id, ble_name, ble_key = public_key_from_interface(
            ble_interface, ble_node_id
        )
        progress(
            f"verified {actual_ble_id} ({ble_name}); key fingerprint "
            f"{key_fingerprint(ble_key)}"
        )
    finally:
        close_interface(ble_interface)

    usb_interface = None
    try:
        device_label = selected_serial or "auto-detected USB serial"
        progress(f"connecting to USB administrator {usb_node_id} via {device_label}")
        usb_interface = serial_connect(selected_serial)
        actual_usb_id, usb_name, usb_key = public_key_from_interface(
            usb_interface, usb_node_id
        )
        progress(
            f"verified {actual_usb_id} ({usb_name}); key fingerprint "
            f"{key_fingerprint(usb_key)}"
        )
    except Exception as exc:
        raise ConfigurationError(
            f"USB administrator connection failed: {exc}. Stop "
            "brc-meshtastic-map.service before pulling keys"
        ) from exc
    finally:
        close_interface(usb_interface)

    if ble_key == usb_key:
        raise ConfigurationError(
            "both administrator radios have the same key; independent keys are required"
        )
    update_env_file(
        env_file,
        {
            ADMIN_BLE_NODE_ID_ENV: ble_node_id,
            ADMIN_USB_NODE_ID_ENV: usb_node_id,
            ADMIN_USB_DEVICE_ENV: selected_serial or "",
            ADMIN_BLE_PUBLIC_KEY_ENV: encode_public_key(ble_key),
            ADMIN_USB_PUBLIC_KEY_ENV: encode_public_key(usb_key),
        },
    )
    progress(f"stored both verified public keys in {env_file} with mode 0600")
    return 0


def current_admin_keys(local_node) -> list[bytes]:
    """Return nonempty, unique administrator public keys in slot order."""
    keys = []
    for raw_key in local_node.localConfig.security.admin_key:
        key = bytes(raw_key)
        if key and len(key) != PUBLIC_KEY_LENGTH:
            raise ConfigurationError(
                f"radio contains an invalid {len(key)}-byte administrator key"
            )
        if key and key not in keys:
            keys.append(key)
    return keys


def plan_admin_keys(
    local_node, desired: Sequence[bytes]
) -> tuple[list[bytes], list[bytes]]:
    """Preserve existing keys, add desired keys, and refuse to exceed three slots."""
    current = current_admin_keys(local_node)
    missing = [key for key in desired if key not in current]
    combined = [*current, *missing]
    if len(combined) > MAX_ADMIN_KEYS:
        raise ConfigurationError(
            f"radio already has {len(current)} different admin key(s); adding "
            f"{len(missing)} would exceed the {MAX_ADMIN_KEYS}-key limit"
        )
    return combined, missing


def admin_audit_from_interface(
    interface,
    target: BleTarget,
    desired: Sequence[bytes],
) -> AdminAudit:
    """Verify identity and inspect administrator keys without writing."""
    node_id, name = local_identity(interface)
    if not target.expected_node_id:
        raise ConfigurationError("fleet admin audit requires an expected node ID")
    if node_id.lower() != target.expected_node_id:
        raise ConfigurationError(
            f"connected to {node_id}, expected {target.expected_node_id}; "
            "refusing changes"
        )
    current = current_admin_keys(interface.localNode)
    _combined, missing = plan_admin_keys(interface.localNode, desired)
    advisories = []
    if interface.localNode.localConfig.security.admin_channel_enabled:
        advisories.append("legacy insecure admin channel is enabled")
    return AdminAudit(
        address=target.address,
        node_id=node_id,
        name=name,
        current_count=len(current),
        missing=[key_fingerprint(key) for key in missing],
        advisories=advisories,
    )


def configure_admin_target(
    target: BleTarget,
    desired: Sequence[bytes],
    *,
    apply: bool,
    connect: Callable[[str], object] = connect_ble,
    settle_seconds: float = 5,
    status: Callable[[str], None] | None = None,
) -> AdminAudit:
    """Audit or enroll two keys, reconnect, and verify persistent state."""
    interface = None
    try:
        if status:
            status("connecting and downloading security configuration")
        interface = connect(target.address)
        audit = admin_audit_from_interface(interface, target, desired)
        if status:
            status(f"connected as {audit.node_id} ({audit.name})")
        if not audit.missing:
            if status:
                status("both administrator keys are already present")
            return audit
        if not apply:
            if status:
                status(f"audit found {len(audit.missing)} missing administrator key(s)")
            return audit

        combined, _missing = plan_admin_keys(interface.localNode, desired)
        if status:
            status(
                f"writing security config with {len(combined)} administrator key(s)"
            )
        interface.localNode.localConfig.security.admin_key[:] = combined
        interface.localNode.writeConfig("security")
        audit.changed = True
    except Exception as exc:  # noqa: BLE001 - isolate one radio's library failure
        if status:
            status(f"failed: {exc}")
        return AdminAudit(address=target.address, error=str(exc))
    finally:
        close_interface(interface)

    if status:
        status(f"waiting {settle_seconds:g}s before read-back")
    if settle_seconds:
        time.sleep(settle_seconds)
    interface = None
    try:
        if status:
            status("reconnecting to verify administrator keys")
        interface = connect(target.address)
        verified = admin_audit_from_interface(interface, target, desired)
        verified.changed = True
        if verified.missing:
            verified.error = "administrator keys failed read-back verification"
            if status:
                status("read-back verification failed")
        elif status:
            status("read-back verification passed")
        return verified
    except Exception as exc:  # noqa: BLE001 - report failed read-back per radio
        if status:
            status(f"verification reconnect failed: {exc}")
        return AdminAudit(
            address=target.address,
            changed=True,
            error=f"could not reconnect for verification: {exc}",
        )
    finally:
        close_interface(interface)


def render_admin_audits(audits: Sequence[AdminAudit]) -> str:
    """Render fleet administrator-key state without printing public keys."""
    rows = [
        (
            audit.address,
            audit.node_id,
            audit.name,
            audit.current_count,
            len(audit.missing),
            f"{audit.result} (changed)" if audit.changed else audit.result,
        )
        for audit in audits
    ]
    output = [
        tabulate(
            rows,
            headers=(
                "BLE address",
                "Node",
                "Name",
                "Admin keys",
                "Missing",
                "Result",
            ),
            tablefmt="simple",
            disable_numparse=True,
        )
    ]
    for audit in audits:
        details = [f"missing key fingerprint: {value}" for value in audit.missing]
        details.extend(f"warning: {value}" for value in audit.advisories)
        if audit.error:
            details.append(f"error: {audit.error}")
        if details:
            output.append(f"\n{audit.address} ({audit.node_id}):")
            output.extend(f"  - {detail}" for detail in details)
    return "\n".join(output)


def audit_or_enroll_fleet(
    env_file: str | Path,
    *,
    apply: bool,
    skip_pairing: bool = False,
) -> int:
    """Audit or enroll the two stored keys on every allowlisted BLE radio."""
    environment = load_environment(env_file)
    desired = desired_admin_keys(environment)
    targets = parse_targets(environment.get(BLE_TARGETS_ENV, ""))
    if not targets:
        raise ConfigurationError(f"no fleet targets configured in {BLE_TARGETS_ENV}")
    missing_id_targets = [
        target.address for target in targets if not target.expected_node_id
    ]
    if missing_id_targets:
        raise ConfigurationError(
            "every fleet target needs an expected node ID before admin enrollment: "
            + ", ".join(missing_id_targets)
        )
    pin = environment.get(BLE_PIN_ENV, DEFAULT_BLE_PIN)

    mode = "ENROLL AND VERIFY" if apply else "audit only"
    progress(f"mode: {mode}")
    progress("scanning for allowlisted radios (10s)")
    discovered = {device.address.upper(): device for device in scan_devices()}
    progress(f"discovered {len(discovered)} Meshtastic radio(s)")

    audits = []
    for index, target in enumerate(targets, start=1):
        prefix = f"[{index}/{len(targets)}] {target.address}"

        def target_status(message, *, _prefix=prefix):
            progress(f"{_prefix}: {message}")

        target_status("starting")
        if target.address not in discovered:
            target_status("not found in the scan; skipping")
            audits.append(
                AdminAudit(
                    address=target.address,
                    node_id=target.expected_node_id or "unknown",
                    error="not found in this BLE scan",
                )
            )
            continue
        if not skip_pairing:
            try:
                ensure_paired(target.address, pin, status=target_status)
            except (ConfigurationError, PairingError) as exc:
                target_status(f"pairing failed: {exc}")
                audits.append(
                    AdminAudit(
                        address=target.address,
                        node_id=target.expected_node_id or "unknown",
                        error=str(exc),
                    )
                )
                continue
        audits.append(
            configure_admin_target(
                target,
                desired,
                apply=apply,
                status=target_status,
            )
        )

    print(render_admin_audits(audits))
    if any(audit.error for audit in audits):
        return 1
    if any(audit.missing for audit in audits):
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the key-management command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument("--skip-pairing", action="store_true")
    parser.add_argument("--serial-device")
    parser.add_argument("action", choices=("pull", "audit", "enroll"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Collect, audit, or enroll administrator keys."""
    args = build_parser().parse_args(argv)
    try:
        if args.action == "pull":
            return pull_admin_keys(
                args.env_file,
                serial_device=args.serial_device,
                skip_pairing=args.skip_pairing,
            )
        return audit_or_enroll_fleet(
            args.env_file,
            apply=args.action == "enroll",
            skip_pairing=args.skip_pairing,
        )
    except ConfigurationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - hardware/backend error boundary
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
