"""Tests for two-controller PKI fleet administration."""

import stat
from types import SimpleNamespace

import pytest
from meshtastic.protobuf import config_pb2

from tools import manage_admin_keys
from tools.configure_ble_nodes import BleTarget, ConfigurationError
from tools.manage_admin_keys import (
    ADMIN_BLE_PUBLIC_KEY_ENV,
    ADMIN_USB_PUBLIC_KEY_ENV,
    admin_audit_from_interface,
    configure_admin_target,
    decode_public_key,
    desired_admin_keys,
    encode_public_key,
    normalize_node_id,
    plan_admin_keys,
    pull_admin_keys,
    update_env_file,
)

ADMIN_A = b"a" * 32
ADMIN_B = b"b" * 32


class _LocalNode:
    def __init__(self, *, public_key=b"p" * 32, admin_keys=()):
        security = config_pb2.Config.SecurityConfig(public_key=public_key)
        security.admin_key.extend(admin_keys)
        self.localConfig = SimpleNamespace(security=security)
        self.writes = []

    def writeConfig(self, name):
        self.writes.append(name)


class _Interface:
    def __init__(self, node_num, *, public_key=b"p" * 32, admin_keys=()):
        self.localNode = _LocalNode(public_key=public_key, admin_keys=admin_keys)
        self.myInfo = SimpleNamespace(my_node_num=node_num)
        self.nodesByNum = {
            node_num: {"user": {"longName": f"Node {node_num:08x}"}}
        }
        self.close_count = 0

    def close(self):
        self.close_count += 1


def test_public_key_encoding_round_trip_and_validation():
    encoded = encode_public_key(ADMIN_A)

    assert decode_public_key(encoded, "test key") == ADMIN_A
    with pytest.raises(ConfigurationError, match="32"):
        decode_public_key(encode_public_key(b"short"), "test key")


def test_desired_admin_keys_must_be_distinct():
    with pytest.raises(ConfigurationError, match="distinct"):
        desired_admin_keys(
            {
                ADMIN_BLE_PUBLIC_KEY_ENV: encode_public_key(ADMIN_A),
                ADMIN_USB_PUBLIC_KEY_ENV: encode_public_key(ADMIN_A),
            }
        )


def test_node_id_normalization_accepts_both_forms():
    assert normalize_node_id("2ECBBFA5", "node") == "!2ecbbfa5"
    assert normalize_node_id("!913c4e9d", "node") == "!913c4e9d"
    with pytest.raises(ConfigurationError, match="eight-digit"):
        normalize_node_id("not-a-node", "node")


def test_env_update_preserves_channel_fragment_and_uses_private_permissions(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "MESHTASTIC_CHANNEL_URL=https://meshtastic.org/e/#private-fragment\n"
        "MESHTASTIC_ADMIN_BLE_PUBLIC_KEY=old\n",
        encoding="utf-8",
    )

    update_env_file(env_file, {ADMIN_BLE_PUBLIC_KEY_ENV: "new"})

    content = env_file.read_text(encoding="utf-8")
    assert "#private-fragment" in content
    assert "MESHTASTIC_ADMIN_BLE_PUBLIC_KEY=new" in content
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600


def test_admin_key_plan_preserves_existing_key_and_enforces_three_slot_limit():
    local_node = _LocalNode(admin_keys=[b"existing".ljust(32, b"x")])

    combined, missing = plan_admin_keys(local_node, [ADMIN_A, ADMIN_B])

    assert combined == [b"existing".ljust(32, b"x"), ADMIN_A, ADMIN_B]
    assert missing == [ADMIN_A, ADMIN_B]

    full_node = _LocalNode(
        admin_keys=[b"1" * 32, b"2" * 32, b"3" * 32]
    )
    with pytest.raises(ConfigurationError, match="exceed"):
        plan_admin_keys(full_node, [ADMIN_A])


def test_admin_audit_checks_identity_and_warns_about_legacy_admin():
    interface = _Interface(0x2ECBBFA5, admin_keys=[ADMIN_A, ADMIN_B])
    interface.localNode.localConfig.security.admin_channel_enabled = True
    target = BleTarget("AA:BB:CC:DD:EE:FF", "!2ecbbfa5")

    audit = admin_audit_from_interface(interface, target, [ADMIN_A, ADMIN_B])

    assert audit.result == "OK (warning)"
    assert audit.current_count == 2
    assert "legacy insecure" in audit.advisories[0]


def test_admin_audit_refuses_an_identity_mismatch():
    interface = _Interface(0xFFFFFFFF, admin_keys=[ADMIN_A, ADMIN_B])
    target = BleTarget("AA:BB:CC:DD:EE:FF", "!2ecbbfa5")

    with pytest.raises(ConfigurationError, match="refusing changes"):
        admin_audit_from_interface(interface, target, [ADMIN_A, ADMIN_B])


def test_admin_enrollment_writes_reconnects_and_verifies():
    interface = _Interface(0x2ECBBFA5, admin_keys=[ADMIN_A])
    target = BleTarget("AA:BB:CC:DD:EE:FF", "!2ecbbfa5")
    statuses = []

    audit = configure_admin_target(
        target,
        [ADMIN_A, ADMIN_B],
        apply=True,
        connect=lambda _address: interface,
        settle_seconds=0,
        status=statuses.append,
    )

    assert audit.result == "OK"
    assert audit.changed is True
    assert interface.localNode.writes == ["security"]
    assert list(interface.localNode.localConfig.security.admin_key) == [
        ADMIN_A,
        ADMIN_B,
    ]
    assert interface.close_count == 2
    assert statuses[-1] == "read-back verification passed"


def test_pull_keys_verifies_both_radios_and_persists_public_keys(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "MESHTASTIC_BLE_PIN=123456\n"
        "MESHTASTIC_BLE_TARGETS="
        "AA:BB:CC:DD:EE:FF=!2ecbbfa5,11:22:33:44:55:66=!913c4e9d\n",
        encoding="utf-8",
    )
    ble_interface = _Interface(0x2ECBBFA5, public_key=ADMIN_A)
    usb_interface = _Interface(0x913C4E9D, public_key=ADMIN_B)
    monkeypatch.setattr(
        manage_admin_keys,
        "scan_devices",
        lambda: [SimpleNamespace(address="AA:BB:CC:DD:EE:FF")],
    )
    monkeypatch.setattr(manage_admin_keys, "ensure_paired", lambda *_args, **_kw: None)

    result = pull_admin_keys(
        env_file,
        ble_connect=lambda _address: ble_interface,
        serial_connect=lambda _device: usb_interface,
    )
    values = manage_admin_keys.parse_env_file(env_file)

    assert result == 0
    assert decode_public_key(values[ADMIN_BLE_PUBLIC_KEY_ENV], "BLE") == ADMIN_A
    assert decode_public_key(values[ADMIN_USB_PUBLIC_KEY_ENV], "USB") == ADMIN_B
    assert ble_interface.close_count == 1
    assert usb_interface.close_count == 1
