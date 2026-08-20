"""Tests for safe Meshtastic BLE fleet configuration."""

import asyncio
import base64
import subprocess
from types import SimpleNamespace

import pytest
from meshtastic.protobuf import apponly_pb2, channel_pb2, config_pb2

from tools import configure_ble_nodes
from tools.configure_ble_nodes import (
    BLE_PIN_ENV,
    BLE_TARGETS_ENV,
    CHANNEL_URL_ENV,
    BleTarget,
    ConfigurationError,
    PairingCommandResult,
    _clean_bluetoothctl_output,
    _discover_meshtastic_devices,
    apply_channel_policy,
    audit_interface,
    channel_differences,
    configure_target,
    connect_ble,
    decode_channel_url,
    ensure_paired,
    parse_env_file,
    parse_targets,
    render_audits,
)


def _settings(name, key, precision):
    settings = channel_pb2.ChannelSettings()
    settings.name = name
    settings.psk = key
    settings.module_settings.position_precision = precision
    return settings


def _channel_url():
    channel_set = apponly_pb2.ChannelSet()
    channel_set.settings.extend(
        [
            _settings("Everyone", b"e" * 32, 0),
            _settings("Kaleido", b"k" * 32, 32),
        ]
    )
    payload = base64.urlsafe_b64encode(channel_set.SerializeToString())
    return "https://meshtastic.org/e/#" + payload.rstrip(b"=").decode("ascii")


def _channel(index, role, settings):
    channel = channel_pb2.Channel(index=index, role=role)
    channel.settings.CopyFrom(settings)
    return channel


class _LocalNode:
    def __init__(self, channels):
        self.channels = channels
        position = config_pb2.Config.PositionConfig(
            gps_mode=config_pb2.Config.PositionConfig.GpsMode.ENABLED
        )
        self.localConfig = SimpleNamespace(position=position)
        self.writes = []

    def writeChannel(self, index):
        self.writes.append(index)


class _Interface:
    def __init__(self, channels, node_num=0x12345678):
        self.localNode = _LocalNode(channels)
        self.myInfo = SimpleNamespace(my_node_num=node_num)
        self.nodesByNum = {
            node_num: {
                "user": {"longName": "Test Radio"},
                "position": {"latitude": 40.78, "longitude": -119.20},
            }
        }
        self.metadata = SimpleNamespace(firmware_version="2.8.0")
        self.close_count = 0

    def close(self):
        self.close_count += 1


def _matching_channels(desired):
    return [
        _channel(0, channel_pb2.Channel.Role.PRIMARY, desired.settings[0]),
        _channel(1, channel_pb2.Channel.Role.SECONDARY, desired.settings[1]),
    ]


def test_env_file_keeps_channel_url_fragment_and_private_values(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"{CHANNEL_URL_ENV}={_channel_url()}\n"
        f"{BLE_PIN_ENV}='123456'\n"
        f"{BLE_TARGETS_ENV}=AA:BB:CC:DD:EE:FF=!12345678\n",
        encoding="utf-8",
    )

    values = parse_env_file(env_file)

    assert values[CHANNEL_URL_ENV] == _channel_url()
    assert values[BLE_PIN_ENV] == "123456"
    assert values[BLE_TARGETS_ENV].endswith("=!12345678")


def test_decode_channel_url_requires_location_only_on_channel_one():
    desired = decode_channel_url(_channel_url())

    assert [settings.name for settings in desired.settings] == ["Everyone", "Kaleido"]
    assert desired.settings[0].module_settings.position_precision == 0
    assert desired.settings[1].module_settings.position_precision == 32

    channel_set = apponly_pb2.ChannelSet()
    channel_set.settings.extend(
        [_settings("Everyone", b"e" * 32, 32), _settings("Kaleido", b"k" * 32, 32)]
    )
    encoded = base64.urlsafe_b64encode(channel_set.SerializeToString()).decode()
    with pytest.raises(ConfigurationError, match="channel 0"):
        decode_channel_url(f"https://meshtastic.org/e/#{encoded}")


def test_target_allowlist_normalizes_and_rejects_unsafe_inventory():
    targets = parse_targets(
        "aa:bb:cc:dd:ee:ff=!ABCDEF12, 11:22:33:44:55:66=!12345678"
    )

    assert targets == [
        BleTarget("AA:BB:CC:DD:EE:FF", "!abcdef12"),
        BleTarget("11:22:33:44:55:66", "!12345678"),
    ]
    with pytest.raises(ConfigurationError, match="duplicate"):
        parse_targets("AA:BB:CC:DD:EE:FF,aa:bb:cc:dd:ee:ff")
    with pytest.raises(ConfigurationError, match="invalid BLE"):
        parse_targets("nearby-radio")


def test_channel_policy_repairs_two_slots_and_disables_other_location_sharing():
    desired = decode_channel_url(_channel_url())
    channels = _matching_channels(desired)
    channels[1].settings.module_settings.position_precision = 0
    channels.append(
        _channel(2, channel_pb2.Channel.Role.SECONDARY, _settings("Other", b"o", 16))
    )
    local_node = _LocalNode(channels)

    differences = channel_differences(channels, desired)
    changed = apply_channel_policy(local_node, desired)

    assert "channel 1 position precision is 0, expected 32" in differences
    assert any("channel 2" in item for item in differences)
    assert changed == [1, 2]
    assert local_node.writes == [1, 2]
    assert channel_differences(channels, desired) == []


def test_identity_mismatch_is_reported_and_never_written():
    desired = decode_channel_url(_channel_url())
    interface = _Interface(_matching_channels(desired))
    interface.localNode.channels[1].settings.name = "Wrong"
    target = BleTarget("AA:BB:CC:DD:EE:FF", "!ffffffff")

    audit = configure_target(
        target,
        desired,
        apply=True,
        connect=lambda _address: interface,
        settle_seconds=0,
    )

    assert audit.result == "MISMATCH"
    assert "refusing changes" in audit.differences[0]
    assert interface.localNode.writes == []
    assert interface.close_count == 1


def test_apply_reconnects_and_verifies_without_printing_keys():
    desired = decode_channel_url(_channel_url())
    interface = _Interface(_matching_channels(desired))
    interface.localNode.channels[1].settings.name = "Wrong"
    target = BleTarget("AA:BB:CC:DD:EE:FF", "!12345678")

    audit = configure_target(
        target,
        desired,
        apply=True,
        connect=lambda _address: interface,
        settle_seconds=0,
    )
    rendered = render_audits([audit])

    assert audit.result == "OK"
    assert audit.changed is True
    assert interface.localNode.writes == [1]
    assert interface.close_count == 2
    assert "OK (changed)" in rendered
    assert "kkkk" not in rendered


def test_audit_reports_gps_state_without_changing_position_config():
    desired = decode_channel_url(_channel_url())
    interface = _Interface(_matching_channels(desired))
    before = interface.localNode.localConfig.position.SerializeToString()

    audit = audit_interface(
        interface,
        BleTarget("AA:BB:CC:DD:EE:FF", "!12345678"),
        desired,
    )

    assert audit.location == "ENABLED, fix available"
    assert audit.result == "OK"
    assert interface.localNode.localConfig.position.SerializeToString() == before


def test_audit_warns_about_non_recommended_burning_mesh_firmware():
    desired = decode_channel_url(_channel_url())
    interface = _Interface(_matching_channels(desired))
    interface.metadata.firmware_version = "2.7.11"

    audit = audit_interface(
        interface,
        BleTarget("AA:BB:CC:DD:EE:FF", "!12345678"),
        desired,
    )

    assert audit.result == "OK (warning)"
    assert "Burning Mesh 2.8.x" in audit.advisories[0]


def test_scan_keeps_results_when_bluez_says_discovery_already_stopped():
    class DiscoveryStoppedError(Exception):
        dbus_error = "org.bluez.Error.Failed"

    device = SimpleNamespace(name="Meshtastic_abcd", address="AA:BB:CC:DD:EE:FF")
    advertisement = SimpleNamespace(
        service_uuids=["6BA1B218-15A8-461F-9FA8-5DCAE273EAFD"]
    )

    class Scanner:
        def __init__(self, **_kwargs):
            self.discovered_devices_and_advertisement_data = {
                device.address: (device, advertisement)
            }

        async def start(self):
            pass

        async def stop(self):
            raise DiscoveryStoppedError(
                "[org.bluez.Error.Failed] No discovery started"
            )

    devices = asyncio.run(
        _discover_meshtastic_devices(timeout=0, scanner_factory=Scanner)
    )

    assert devices == [device]


def test_connect_replaces_meshtastic_internal_scan_then_restores_it():
    expected_device = SimpleNamespace(
        name="Meshtastic_abcd", address="AA:BB:CC:DD:EE:FF"
    )

    class Interface:
        @staticmethod
        def scan():
            return ["original scanner"]

        def __init__(self, address):
            self.address = address
            self.devices = self.scan()

    interface = connect_ble(
        expected_device.address,
        interface_class=Interface,
        scanner=lambda: [expected_device],
    )

    assert interface.devices == [expected_device]
    assert Interface.scan() == ["original scanner"]


def test_pairing_waits_for_confirmation_and_reports_progress(monkeypatch):
    paired_checks = iter([False, True])
    monkeypatch.setattr(
        configure_ble_nodes,
        "is_paired",
        lambda _address: next(paired_checks),
    )
    monkeypatch.setattr(configure_ble_nodes, "is_trusted", lambda _address: True)
    monkeypatch.setattr(
        configure_ble_nodes,
        "_run_pairing_command",
        lambda *_args: PairingCommandResult(
            returncode=0,
            output="[agent] Enter PIN code: Pairing successful",
            pin_requested=True,
        ),
    )
    monkeypatch.setattr(
        configure_ble_nodes,
        "_bluetoothctl",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, "", ""),
    )
    statuses = []

    ensure_paired("AA:BB:CC:DD:EE:FF", "123456", status=statuses.append)

    assert any("waiting for the fixed-PIN prompt" in item for item in statuses)
    assert any("pairing confirmed" in item for item in statuses)
    assert statuses[-1] == "paired and trusted"


def test_bluetooth_output_never_displays_the_pin():
    lines = _clean_bluetoothctl_output(
        "\x1b[0mEnter PIN code: 123456\r\nPairing successful",
        "123456",
    )

    assert all("123456" not in line for line in lines)
    assert any("<redacted>" in line for line in lines)
