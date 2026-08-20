"""Tests for Meshtastic connection selection."""

import logging

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


def test_ignored_position_logs_each_sender_identity_once(caplog):
    cache = mesh.ChannelPositionCache(1)
    interface = type(
        "Interface",
        (),
        {
            "nodes": {
                "!channel0a": {
                    "user": {
                        "longName": "Pete",
                        "shortName": "PETE",
                        "hwModel": "T_ECHO",
                    }
                },
                "!channel0b": {
                    "user": {
                        "longName": "KaleidoTie",
                        "shortName": "TIE",
                        "hwModel": "T_DECK",
                    }
                },
            }
        },
    )()
    position = {"latitude": 40.783247, "longitude": -119.207884}

    with caplog.at_level(logging.INFO):
        for node_id in ("!channel0a", "!channel0a", "!channel0b"):
            cache.receive(
                {
                    "channel": 0,
                    "fromId": node_id,
                    "decoded": {"position": position},
                },
                interface,
            )

    ignored = [
        record.getMessage()
        for record in caplog.records
        if "ignoring channel 0 position" in record.getMessage()
    ]
    assert len(ignored) == 2
    assert any(
        "node_id=!channel0a name='Pete' short='PETE' hardware=T_ECHO" in message
        for message in ignored
    )
    assert any(
        "node_id=!channel0b name='KaleidoTie' short='TIE' hardware=T_DECK"
        in message
        for message in ignored
    )


def test_received_position_logs_sender_identity_and_coordinates(caplog):
    cache = mesh.ChannelPositionCache(1)
    interface = type(
        "Interface",
        (),
        {
            "nodes": {
                "!1e447ab7": {
                    "user": {
                        "longName": "Zack // Mad Hatter",
                        "shortName": "zack",
                        "hwModel": "T_BEAM",
                    }
                }
            }
        },
    )()

    with caplog.at_level(logging.INFO):
        cache.receive(
            {
                "channel": 1,
                "fromId": "!1e447ab7",
                "decoded": {
                    "position": {
                        "latitude": 37.924532,
                        "longitude": -122.526900,
                    }
                },
            },
            interface,
        )

    message = next(
        record.getMessage()
        for record in caplog.records
        if "received channel 1 position" in record.getMessage()
    )
    assert "node_id=!1e447ab7" in message
    assert "name='Zack // Mad Hatter'" in message
    assert "short='zack' hardware=T_BEAM" in message
    assert "latitude=37.924532 longitude=-122.526900" in message


def test_far_position_warning_identifies_device_and_is_not_duplicated(caplog):
    mesh._last_warned_far_positions.clear()
    nodes = [
        (
            "!7a848c3e",
            {
                "user": {
                    "longName": "Meshtastic 9454",
                    "shortName": "9454",
                    "hwModel": "HELTEC_V3",
                },
                "position": {
                    "latitude": 37.924348,
                    "longitude": -122.526990,
                },
            },
        )
    ]

    with caplog.at_level(logging.WARNING):
        mesh.add_bm_coordinates(nodes)
        mesh.add_bm_coordinates(nodes)

    warnings = [
        record.getMessage()
        for record in caplog.records
        if "far from BRC center" in record.getMessage()
    ]
    assert warnings == [
        "position for node_id=!7a848c3e name='Meshtastic 9454' short='9454' "
        "hardware=HELTEC_V3 is far from BRC center: latitude=37.924348 "
        "longitude=-122.526990 center=(40.783247, -119.207884)"
    ]


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
        {"nodes": {"!1e447ab7": {"user": {"longName": "Zack", "shortName": "zack"}}}},
    )()

    records = cache.snapshot(interface)
    burners = mesh.add_bm_coordinates(records)

    assert cache.count() == 1
    assert list(burners) == ["Zack"]
    assert burners["Zack"]["coordinates"]["time"] == 123
    assert cache.web_nodes(interface) == [
        {
            "node_id": "!1e447ab7",
            "name": "Zack",
            "short_name": "zack",
            "brc_address": "12:00+The Man",
            "position_time": 123,
        }
    ]


def test_position_cache_restores_all_last_known_nodes_and_keeps_newest():
    cache = mesh.ChannelPositionCache(1)
    records = []
    for index in range(8):
        node_id = f"!0000000{index}"
        records.append(
            (
                node_id,
                {
                    "user": {"longName": f"Node {index}"},
                    "position": {
                        "latitude": 40.783247 + index * 0.00001,
                        "longitude": -119.207884,
                        "time": 100 + index,
                    },
                },
            )
        )

    assert cache.restore(records) == 8
    assert cache.count() == 8

    cache.receive(
        {
            "channel": 1,
            "fromId": "!00000000",
            "decoded": {
                "position": {
                    "latitude": 40.79,
                    "longitude": -119.20,
                    "time": 200,
                }
            },
        }
    )
    assert cache.restore([records[0]]) == 0
    positions = dict(cache.snapshot())
    assert positions["!00000000"]["position"]["time"] == 200
    assert positions["!00000000"]["user"]["longName"] == "Node 0"
