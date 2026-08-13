"""Tests for Meshtastic connection selection."""

import mesh


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
