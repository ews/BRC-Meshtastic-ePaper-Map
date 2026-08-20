"""Tests for the cron-safe daily Meshtastic weather sender."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from tools import send_daily_weather as weather


class FakeInterface:
    def __init__(self, response=None):
        self.localNode = SimpleNamespace(nodeNum=1234)
        self.response = response
        self.call = None
        self.closed = False

    def sendText(self, message, **kwargs):
        self.call = (message, kwargs)
        if self.response is not None:
            kwargs["onResponse"](self.response)
        return SimpleNamespace(id=9876)

    def close(self):
        self.closed = True


def _args(state_file):
    return weather.build_parser().parse_args(
        ["--state-file", str(state_file), "--ack-timeout", "0.01"]
    )


def test_send_waits_for_implicit_broadcast_ack(monkeypatch):
    interface = FakeInterface(
        {
            "from": 1234,
            "decoded": {"routing": {"errorReason": "NONE"}},
        }
    )
    monkeypatch.setattr(
        weather,
        "open_serial_interface",
        lambda device, timeout: interface,
    )

    packet_id, ack_type = weather.send_and_wait(
        "forecast",
        device=None,
        connection_timeout=1,
        ack_timeout=0.01,
    )

    assert (packet_id, ack_type) == (9876, "implicit_ack")
    message, kwargs = interface.call
    assert message == "forecast"
    assert kwargs["destinationId"] == weather.BROADCAST_ADDR
    assert kwargs["channelIndex"] == 0
    assert kwargs["wantAck"] is True
    assert interface.closed is True


def test_success_is_recorded_and_second_run_says_already_sent(
    tmp_path, monkeypatch, capsys
):
    state_file = tmp_path / "weather-state.json"
    args = _args(state_file)
    now = datetime(2026, 8, 18, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(weather, "fetch_forecast", lambda url, timeout: "forecast")
    monkeypatch.setattr(
        weather,
        "send_and_wait",
        lambda *args, **kwargs: (55, "implicit_ack"),
    )

    assert weather.run(args, now=now) == 0
    first_output = capsys.readouterr().out
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert "sent and acknowledged" in first_output
    assert state["sent_dates"]["2026-08-18"]["packet_id"] == 55
    assert state["sent_dates"]["2026-08-18"]["ack"] == "implicit_ack"

    monkeypatch.setattr(
        weather,
        "fetch_forecast",
        lambda *args, **kwargs: pytest.fail("already-sent run fetched the URL"),
    )
    monkeypatch.setattr(
        weather,
        "send_and_wait",
        lambda *args, **kwargs: pytest.fail("already-sent run touched the radio"),
    )
    assert weather.run(args, now=now) == 0
    assert capsys.readouterr().out == "already sent\n"


def test_timeout_does_not_mark_day_complete(tmp_path, monkeypatch):
    interface = FakeInterface(response=None)
    monkeypatch.setattr(
        weather,
        "open_serial_interface",
        lambda device, timeout: interface,
    )

    with pytest.raises(weather.DeliveryError, match="no mesh acknowledgment"):
        weather.send_and_wait(
            "forecast",
            device=None,
            connection_timeout=1,
            ack_timeout=0.001,
        )

    assert interface.closed is True


def test_nak_does_not_count_as_delivery(monkeypatch):
    interface = FakeInterface(
        {
            "from": 1234,
            "decoded": {"routing": {"errorReason": "MAX_RETRANSMIT"}},
        }
    )
    monkeypatch.setattr(
        weather,
        "open_serial_interface",
        lambda device, timeout: interface,
    )

    with pytest.raises(weather.DeliveryError, match="MAX_RETRANSMIT"):
        weather.send_and_wait(
            "forecast",
            device=None,
            connection_timeout=1,
            ack_timeout=0.01,
        )


def test_failed_send_leaves_day_available_for_next_cron_run(tmp_path, monkeypatch):
    state_file = tmp_path / "weather-state.json"
    args = _args(state_file)
    now = datetime(2026, 8, 18, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(weather, "fetch_forecast", lambda url, timeout: "forecast")

    def fail_send(*args, **kwargs):
        raise weather.DeliveryError("no acknowledgment")

    monkeypatch.setattr(weather, "send_and_wait", fail_send)
    with pytest.raises(weather.DeliveryError):
        weather.run(args, now=now)
    assert not state_file.exists()


def test_invalid_state_fails_closed_without_sending(tmp_path, monkeypatch):
    state_file = tmp_path / "weather-state.json"
    state_file.write_text("not-json", encoding="utf-8")
    args = _args(state_file)
    monkeypatch.setattr(
        weather,
        "fetch_forecast",
        lambda *args, **kwargs: pytest.fail("invalid state fetched the URL"),
    )

    with pytest.raises(RuntimeError, match="cannot read state file"):
        weather.run(
            args,
            now=datetime(2026, 8, 18, 12, tzinfo=timezone.utc),
        )


@pytest.mark.parametrize(
    "content", [b"", b" \n", b"x" * (weather.MAX_MESSAGE_BYTES + 1)]
)
def test_invalid_forecast_content_is_rejected(monkeypatch, content):
    response = SimpleNamespace(
        content=content,
        raise_for_status=lambda: None,
    )
    monkeypatch.setattr(weather.requests, "get", lambda *args, **kwargs: response)

    with pytest.raises(ValueError):
        weather.fetch_forecast(weather.DEFAULT_URL, timeout=1)
