"""Tests for Meshtastic connection selection."""

import mesh
import pytest


def test_serial_connection_is_used_when_initialized(monkeypatch):
    serial = type("Serial", (), {"nodes": {}})()
    monkeypatch.setattr(
        mesh.meshtastic.serial_interface, "SerialInterface", lambda: serial
    )

    assert mesh.connect_serial() is serial


def test_tcp_localhost_is_used_when_serial_is_uninitialized(monkeypatch):
    serial = object()
    tcp = type("TCP", (), {"nodes": {}})()
    hosts = []
    monkeypatch.setattr(
        mesh.meshtastic.serial_interface, "SerialInterface", lambda: serial
    )
    monkeypatch.setattr(
        mesh.meshtastic.tcp_interface,
        "TCPInterface",
        lambda host: hosts.append(host) or tcp,
    )

    assert mesh.connect_serial() is tcp
    assert hosts == ["localhost"]


def test_meshtastic_position_field_is_converted_to_burner():
    nodes = [
        (
            "!1e447ab7",
            {
                "user": {"longName": "Zack"},
                "position": {
                    "latitudeI": 407832470,
                    "longitudeI": -1192078840,
                    "time": 123,
                },
            },
        )
    ]

    burners = mesh.add_bm_coordinates(nodes)

    assert burners["Zack"]["node_id"] == "!1e447ab7"
    assert burners["Zack"]["coordinates"]["latitude"] == pytest.approx(40.783247)
    assert burners["Zack"]["coordinates"]["longitude"] == pytest.approx(-119.207884)


def test_channel_position_cache_accepts_only_configured_channel():
    cache = mesh.ChannelPositionCache(1)
    position = {"latitude": 40.783247, "longitude": -119.207884, "time": 123}

    cache.receive(
        {"channel": 0, "fromId": "!channel0", "decoded": {"position": position}}
    )
    cache.receive(
        {"channel": 2, "fromId": "!channel2", "decoded": {"position": position}}
    )

    assert cache.count() == 0


def test_channel_position_cache_snapshots_channel_one_sender_with_node_name():
    cache = mesh.ChannelPositionCache(1)
    cache.receive(
        {
            "channel": 1,
            "from": 0x1E447AB7,
            "decoded": {
                "position": {
                    "latitudeI": 407832470,
                    "longitudeI": -1192078840,
                    "time": 123,
                }
            },
        }
    )
    interface = type(
        "Interface",
        (),
        {
            "nodes": {
                "!1e447ab7": {"user": {"longName": "Zack", "shortName": "zack"}}
            }
        },
    )()

    records = cache.snapshot(interface)
    burners = mesh.add_bm_coordinates(records)

    assert cache.count() == 1
    assert list(burners) == ["Zack"]
    assert burners["Zack"]["coordinates"]["time"] == 123
