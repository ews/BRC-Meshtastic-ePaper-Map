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
        self.call: tuple | None = None
        self.calls = []
        self.closed = False

    def sendText(self, message, **kwargs):
        self.call = (message, kwargs)
        self.calls.append(self.call)
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


def test_existing_map_interface_is_reused_without_being_closed():
    interface = FakeInterface(
        {
            "from": 1234,
            "decoded": {"routing": {"errorReason": "NONE"}},
        }
    )

    result = weather.send_with_interface(interface, "forecast", ack_timeout=0.01)

    assert result == (9876, "implicit_ack")
    assert interface.closed is False


def test_success_is_recorded_and_second_run_says_already_sent(
    tmp_path, monkeypatch, capsys
):
    state_file = tmp_path / "weather-state.json"
    args = _args(state_file)
    now = datetime(2026, 8, 18, 17, tzinfo=timezone.utc)
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


def test_failed_send_waits_until_next_hour_before_retry(tmp_path, monkeypatch):
    state_file = tmp_path / "weather-state.json"
    monkeypatch.setattr(weather, "fetch_forecast", lambda url, timeout: "forecast")
    attempts = []

    def fail_send(message):
        attempts.append(message)
        raise weather.DeliveryError("no acknowledgment")

    with pytest.raises(weather.DeliveryError):
        weather.attempt_daily_weather(
            fail_send,
            state_file=state_file,
            now=datetime(2026, 8, 18, 16, tzinfo=timezone.utc),
        )

    same_hour = weather.attempt_daily_weather(
        fail_send,
        state_file=state_file,
        now=datetime(2026, 8, 18, 16, 30, tzinfo=timezone.utc),
    )
    assert same_hour.status == "already_attempted"
    assert attempts == ["forecast"]

    with pytest.raises(weather.DeliveryError):
        weather.attempt_daily_weather(
            fail_send,
            state_file=state_file,
            now=datetime(2026, 8, 18, 17, tzinfo=timezone.utc),
        )
    assert attempts == ["forecast", "forecast"]
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["last_attempt"]["slot"] == "2026-08-18T10"
    assert state["sent_dates"] == {}


def test_scheduler_starts_new_delivery_day_at_9_am_pacific(tmp_path, monkeypatch):
    state_file = tmp_path / "weather-state.json"
    interface = FakeInterface(
        {
            "from": 1234,
            "decoded": {"routing": {"errorReason": "NONE"}},
        }
    )
    scheduler = weather.WeatherAlertScheduler(
        interface,
        state_file=state_file,
        ack_timeout=0.01,
    )
    fetches = []

    def fetch(url, timeout):
        fetches.append((url, timeout))
        return "forecast"

    monkeypatch.setattr(weather, "fetch_forecast", fetch)

    before = scheduler.maybe_send(
        now=datetime(2026, 8, 19, 15, 59, tzinfo=timezone.utc)
    )
    sent = scheduler.maybe_send(now=datetime(2026, 8, 19, 16, 0, tzinfo=timezone.utc))
    same_hour = scheduler.maybe_send(
        now=datetime(2026, 8, 19, 16, 30, tzinfo=timezone.utc)
    )
    after_success = scheduler.maybe_send(
        now=datetime(2026, 8, 19, 17, 0, tzinfo=timezone.utc)
    )

    assert before.status == "before_start"
    assert sent.status == "sent"
    assert same_hour.status == "not_due"
    assert after_success.status == "already_sent"
    assert len(fetches) == 1
    assert len(interface.calls) == 1
    assert interface.closed is False


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
            now=datetime(2026, 8, 18, 17, tzinfo=timezone.utc),
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


def test_fetch_mesh_status_validates_and_normalizes_json(monkeypatch):
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {
            "state": " b62 ",
            "conditionsState": " abc123 ",
            "conditions": " BRC 95F ",
            "alerts": [" High wind ", " Dust "],
        },
    )
    monkeypatch.setattr(weather.requests, "get", lambda *args, **kwargs: response)

    assert weather.fetch_mesh_status(
        "https://example.test/mesh", 1
    ) == weather.MeshStatus(
        state="b62",
        conditionsState="abc123",
        conditions="BRC 95F",
        alerts=("High wind", "Dust"),
    )


def test_fetch_mesh_status_requires_conditions_state(monkeypatch):
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {
            "state": "b62",
            "conditions": "BRC 95F",
            "alerts": [],
        },
    )
    monkeypatch.setattr(weather.requests, "get", lambda *args, **kwargs: response)

    with pytest.raises(ValueError, match="conditionsState"):
        weather.fetch_mesh_status("https://example.test/mesh", 1)


def test_live_conditions_are_sent_once_after_ack(tmp_path, monkeypatch):
    state_file = tmp_path / "weather-state.json"
    status = weather.MeshStatus(
        state="b62",
        conditionsState="cond-1",
        conditions="BRC 95F wind SSW5g11mph",
        alerts=(),
    )
    monkeypatch.setattr(weather, "fetch_mesh_status", lambda url, timeout: status)
    messages = []

    def send(message):
        messages.append(message)
        return 101, "implicit_ack"

    first = weather.attempt_mesh_alert(
        send,
        state_file=state_file,
        now=datetime(2026, 8, 20, 16, tzinfo=timezone.utc),
    )
    second = weather.attempt_mesh_alert(
        send,
        state_file=state_file,
        now=datetime(2026, 8, 20, 17, tzinfo=timezone.utc),
    )

    assert first.status == "sent"
    assert first.kind == "conditions"
    assert second.status == "already_sent"
    assert messages == ["CONDITIONS: BRC 95F wind SSW5g11mph"]


def test_conditions_broadcast_when_conditions_state_changes(tmp_path, monkeypatch):
    state_file = tmp_path / "weather-state.json"
    statuses = iter(
        [
            weather.MeshStatus("same-state", "cond-1", "BRC 95F", ()),
            weather.MeshStatus("same-state", "cond-1", "BRC 95F", ()),
            weather.MeshStatus("same-state", "cond-2", "BRC 95F", ()),
        ]
    )
    monkeypatch.setattr(
        weather, "fetch_mesh_status", lambda url, timeout: next(statuses)
    )
    messages = []

    def send(message):
        messages.append(message)
        return len(messages), "explicit_ack"

    first = weather.attempt_mesh_alert(
        send,
        state_file=state_file,
        now=datetime(2026, 8, 20, 16, tzinfo=timezone.utc),
    )
    unchanged = weather.attempt_mesh_alert(
        send,
        state_file=state_file,
        now=datetime(2026, 8, 20, 17, tzinfo=timezone.utc),
    )
    changed = weather.attempt_mesh_alert(
        send,
        state_file=state_file,
        now=datetime(2026, 8, 20, 18, tzinfo=timezone.utc),
    )

    assert (first.status, unchanged.status, changed.status) == (
        "sent",
        "already_sent",
        "sent",
    )
    assert messages == ["CONDITIONS: BRC 95F", "CONDITIONS: BRC 95F"]


def test_state_change_without_alerts_does_not_rebroadcast_conditions(
    tmp_path, monkeypatch
):
    state_file = tmp_path / "weather-state.json"
    statuses = iter(
        [
            weather.MeshStatus("state-1", "cond-1", "BRC 95F", ()),
            weather.MeshStatus("state-2", "cond-1", "BRC 95F", ()),
        ]
    )
    monkeypatch.setattr(
        weather, "fetch_mesh_status", lambda url, timeout: next(statuses)
    )
    messages = []

    def send(message):
        messages.append(message)
        return len(messages), "explicit_ack"

    first = weather.attempt_mesh_alert(
        send,
        state_file=state_file,
        now=datetime(2026, 8, 20, 16, tzinfo=timezone.utc),
    )
    second = weather.attempt_mesh_alert(
        send,
        state_file=state_file,
        now=datetime(2026, 8, 20, 17, tzinfo=timezone.utc),
    )

    assert (first.status, second.status) == ("sent", "already_sent")
    assert messages == ["CONDITIONS: BRC 95F"]


def test_live_alert_is_sent_once_and_alert_state_distinguishes_occurrences(
    tmp_path, monkeypatch
):
    state_file = tmp_path / "weather-state.json"
    statuses = iter(
        [
            weather.MeshStatus("event-1", "cond-1", "BRC 95F", ("High wind",)),
            weather.MeshStatus("event-1", "cond-1", "BRC 95F", ("High wind",)),
            weather.MeshStatus("event-2", "cond-1", "BRC 95F", ("High wind",)),
        ]
    )
    monkeypatch.setattr(
        weather, "fetch_mesh_status", lambda url, timeout: next(statuses)
    )
    messages = []

    def send(message):
        messages.append(message)
        return len(messages), "implicit_ack"

    first = weather.attempt_mesh_alert(send, state_file=state_file)
    duplicate = weather.attempt_mesh_alert(
        send,
        state_file=state_file,
        now=datetime(2026, 8, 20, 17, tzinfo=timezone.utc),
    )
    new_event = weather.attempt_mesh_alert(
        send,
        state_file=state_file,
        now=datetime(2026, 8, 20, 18, tzinfo=timezone.utc),
    )

    assert first.kind == "alert"
    assert duplicate.status == "already_sent"
    assert new_event.status == "sent"
    assert messages == ["ALERT: High wind", "ALERT: High wind"]


def test_live_alert_is_not_marked_sent_without_ack_and_retries_next_poll(
    tmp_path, monkeypatch
):
    state_file = tmp_path / "weather-state.json"
    status = weather.MeshStatus("event-1", "cond-1", "BRC 95F", ("High wind",))
    monkeypatch.setattr(weather, "fetch_mesh_status", lambda url, timeout: status)
    attempts = []

    def fail_send(message):
        attempts.append(message)
        raise weather.DeliveryError("no acknowledgment")

    with pytest.raises(weather.DeliveryError):
        weather.attempt_mesh_alert(
            fail_send,
            state_file=state_file,
            now=datetime(2026, 8, 20, 16, 0, tzinfo=timezone.utc),
        )

    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["sent_hashes"] == {}

    def succeed_send(message):
        attempts.append(message)
        return 22, "implicit_ack"

    result = weather.attempt_mesh_alert(
        succeed_send,
        state_file=state_file,
        now=datetime(2026, 8, 20, 16, 2, tzinfo=timezone.utc),
    )

    assert result.status == "sent"
    assert attempts == ["ALERT: High wind", "ALERT: High wind"]
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert len(state["sent_hashes"]) == 1
