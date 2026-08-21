#!/usr/bin/env python3
"""Send and schedule BRC weather messages on Meshtastic channel 0.

The day is marked complete only after Meshtastic reports an ACK. For a
broadcast, this is normally an implicit ACK generated after another mesh node
rebroadcasts the packet. The integrated scheduler starts each delivery day at
9:00 AM Pacific and makes at most one attempt per clock hour until confirmed.
A file lock prevents overlapping processes from sending concurrently.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sys
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from meshtastic import BROADCAST_ADDR
from meshtastic.protobuf import mesh_pb2
from meshtastic.serial_interface import SerialInterface

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_URL = "https://brcforecast.corbett.vc/api/public/mesh/morning.txt"
DEFAULT_MESH_STATUS_URL = "https://brcforecast.corbett.vc/api/public/mesh"
DEFAULT_STATE_FILE = ROOT / ".daily-weather-state.json"
DEFAULT_TIMEZONE = "America/Los_Angeles"
CHANNEL_INDEX = 0
START_HOUR = 9
DEFAULT_FETCH_TIMEOUT = 20.0
DEFAULT_CONNECTION_TIMEOUT = 30.0
DEFAULT_ACK_TIMEOUT = 60.0
STATE_VERSION = 2
MAX_MESSAGE_BYTES = int(mesh_pb2.Constants.DATA_PAYLOAD_LEN)


class DeliveryError(RuntimeError):
    """Raised when Meshtastic does not confirm delivery."""


@dataclass(frozen=True)
class WeatherAttemptResult:
    """Outcome of one scheduler check."""

    status: str
    day: str | None = None
    packet_id: int | None = None
    ack_type: str | None = None
    kind: str | None = None


@dataclass(frozen=True)
class MeshStatus:
    """Validated response from the live BRC mesh forecast endpoint."""

    state: str
    conditions: str
    alerts: tuple[str, ...]


class AckTracker:
    """Capture the ACK/NAK callback for one outgoing packet."""

    def __init__(self, local_node_num: int):
        self.local_node_num = int(local_node_num)
        self.ack_type: str | None = None
        self.error_reason: str | None = None
        self._event = threading.Event()

    # Meshtastic recognizes this exact callback name and permits normal ACKs.
    def onAckNak(self, packet):
        """Handle the response callback expected by Meshtastic's SDK."""
        routing = packet.get("decoded", {}).get("routing", {})
        error_reason = routing.get("errorReason", "NONE")
        if error_reason not in (None, "", "NONE"):
            self.error_reason = str(error_reason)
            self.ack_type = "nak"
        else:
            try:
                response_from = int(packet.get("from"))
            except (TypeError, ValueError):
                response_from = None
            self.ack_type = (
                "implicit_ack"
                if response_from == self.local_node_num
                else "explicit_ack"
            )
        self._event.set()

    def wait(self, timeout: float) -> str:
        """Wait for an ACK and return its type, or raise on timeout/NAK."""
        if not self._event.wait(timeout):
            raise DeliveryError(
                f"no mesh acknowledgment received within {timeout:g} seconds"
            )
        if self.error_reason:
            raise DeliveryError(f"mesh returned NAK: {self.error_reason}")
        if self.ack_type not in {"implicit_ack", "explicit_ack"}:
            raise DeliveryError("mesh returned an unrecognized acknowledgment")
        return self.ack_type


def fetch_forecast(url: str, timeout: float) -> str:
    """Download and validate the single Meshtastic forecast message."""
    response = requests.get(
        url,
        timeout=(min(timeout, 10), timeout),
        headers={"User-Agent": "BRC-Meshtastic-Daily-Weather/1.0"},
    )
    response.raise_for_status()
    try:
        message = response.content.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise ValueError("forecast response is not valid UTF-8") from exc

    if not message:
        raise ValueError("forecast response is empty")
    message_bytes = len(message.encode("utf-8"))
    if message_bytes > MAX_MESSAGE_BYTES:
        raise ValueError(
            f"forecast is {message_bytes} bytes; Meshtastic permits "
            f"{MAX_MESSAGE_BYTES} bytes in one packet"
        )
    return message


def fetch_mesh_status(url: str, timeout: float) -> MeshStatus:
    """Fetch the live conditions and alert lines from the JSON endpoint."""
    response = requests.get(
        url,
        timeout=(min(timeout, 10), timeout),
        headers={"User-Agent": "BRC-Meshtastic-Live-Weather/1.0"},
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError("mesh forecast response is not valid JSON") from exc

    if not isinstance(payload, dict):
        raise ValueError("mesh forecast response must be a JSON object")
    state = payload.get("state")
    conditions = payload.get("conditions")
    alerts = payload.get("alerts", [])
    if not isinstance(state, str) or not state.strip():
        raise ValueError("mesh forecast response has no state")
    if not isinstance(conditions, str) or not conditions.strip():
        raise ValueError("mesh forecast response has no conditions text")
    if not isinstance(alerts, list) or not all(
        isinstance(alert, str) and alert.strip() for alert in alerts
    ):
        raise ValueError("mesh forecast response has invalid alerts")

    messages = tuple(alert.strip() for alert in alerts)
    return MeshStatus(
        state=state.strip(),
        conditions=conditions.strip(),
        alerts=messages,
    )


def open_serial_interface(device: str | None, timeout: float):
    """Open the requested or automatically detected serial Meshtastic radio."""
    interface = SerialInterface(
        devPath=device,
        noNodes=True,
        timeout=max(1, int(timeout)),
    )
    if getattr(interface, "myInfo", None) is None:
        raise ConnectionError("no initialized serial Meshtastic device found")
    return interface


def send_and_wait(
    message: str,
    *,
    device: str | None,
    connection_timeout: float,
    ack_timeout: float,
) -> tuple[int, str]:
    """Broadcast one reliable text packet and wait for its ACK."""
    interface = None
    try:
        interface = open_serial_interface(device, connection_timeout)
        return send_with_interface(interface, message, ack_timeout=ack_timeout)
    finally:
        if interface is not None:
            try:
                interface.close()
            # Cleanup failure must not turn a confirmed delivery into a retry.
            except Exception as exc:  # noqa: BLE001
                print(
                    f"warning: could not close Meshtastic interface: {exc}",
                    file=sys.stderr,
                )


def send_with_interface(
    interface, message: str, *, ack_timeout: float
) -> tuple[int, str]:
    """Send through an existing Meshtastic connection and wait for its ACK."""
    local_node_num = getattr(getattr(interface, "localNode", None), "nodeNum", None)
    if local_node_num is None:
        local_node_num = getattr(
            getattr(interface, "myInfo", None), "my_node_num", None
        )
    if local_node_num is None:
        raise ConnectionError("Meshtastic device did not report its node number")

    tracker = AckTracker(local_node_num)
    packet = interface.sendText(
        message,
        destinationId=BROADCAST_ADDR,
        wantAck=True,
        channelIndex=CHANNEL_INDEX,
        onResponse=tracker.onAckNak,
    )
    ack_type = tracker.wait(ack_timeout)
    return int(packet.id), ack_type


def load_state(path: Path) -> dict:
    """Load state, failing closed if an existing state file is invalid."""
    if not path.exists():
        return {"version": STATE_VERSION, "sent_dates": {}, "sent_hashes": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read state file {path}: {exc}") from exc
    if not isinstance(state, dict) or not isinstance(state.get("sent_dates"), dict):
        raise TypeError(f"invalid state file {path}; refusing a possible duplicate")
    if "sent_hashes" in state and not isinstance(state["sent_hashes"], dict):
        raise TypeError(f"invalid sent_hashes in state file {path}")
    state.setdefault("sent_hashes", {})
    if "last_attempt" in state and not isinstance(state["last_attempt"], dict):
        raise TypeError(f"invalid state file {path}; refusing a possible duplicate")
    if "last_alert_attempt" in state and not isinstance(
        state["last_alert_attempt"], dict
    ):
        raise TypeError(f"invalid last_alert_attempt in state file {path}")
    return state


def save_state(path: Path, state: dict) -> None:
    """Atomically persist state in the same directory as the destination."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


@contextmanager
def daily_lock(state_path: Path):
    """Serialize cron runs that share a state file."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = Path(f"{state_path}.lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def positive_float(value: str) -> float:
    """Parse a strictly positive command-line duration."""
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def _local_time(now: datetime | None, timezone_name: str) -> datetime:
    """Return an aware time in the configured delivery timezone."""
    delivery_timezone = ZoneInfo(timezone_name)
    return (
        now.astimezone(delivery_timezone)
        if now is not None
        else datetime.now(delivery_timezone)
    )


def _hour_slot(current: datetime) -> str:
    """Return the persistent identifier for one local clock-hour attempt."""
    return current.strftime("%Y-%m-%dT%H")


def attempt_daily_weather(
    send_message,
    *,
    state_file: Path = DEFAULT_STATE_FILE,
    url: str = DEFAULT_URL,
    timezone: str = DEFAULT_TIMEZONE,
    start_hour: int = START_HOUR,
    fetch_timeout: float = DEFAULT_FETCH_TIMEOUT,
    now: datetime | None = None,
) -> WeatherAttemptResult:
    """Make one due hourly attempt using a supplied message sender.

    ``send_message`` receives the validated forecast text and returns
    ``(packet_id, ack_type)``. Recording the hour before network activity keeps
    restarts and overlapping processes from retrying within the same hour.
    """
    current = _local_time(now, timezone)
    if current.hour < start_hour:
        return WeatherAttemptResult("before_start")

    day = current.date().isoformat()
    slot = _hour_slot(current)
    state_path = state_file.resolve()

    with daily_lock(state_path):
        state = load_state(state_path)
        if day in state["sent_dates"]:
            return WeatherAttemptResult("already_sent", day=day)
        if state.get("last_attempt", {}).get("slot") == slot:
            return WeatherAttemptResult("already_attempted", day=day)

        state["version"] = STATE_VERSION
        state["last_attempt"] = {
            "day": day,
            "slot": slot,
            "attempted_at": current.isoformat(timespec="seconds"),
        }
        save_state(state_path, state)

        message = fetch_forecast(url, fetch_timeout)
        packet_id, ack_type = send_message(message)
        state["sent_dates"][day] = {
            "ack": ack_type,
            "feed_url": url,
            "message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
            "packet_id": packet_id,
            "sent_at": current.isoformat(timespec="seconds"),
        }
        save_state(state_path, state)
        return WeatherAttemptResult(
            "sent",
            day=day,
            packet_id=packet_id,
            ack_type=ack_type,
        )


class WeatherAlertScheduler:
    """Hourly scheduler that reuses the map's open Meshtastic interface."""

    def __init__(
        self,
        interface,
        *,
        state_file: Path = DEFAULT_STATE_FILE,
        url: str = DEFAULT_URL,
        timezone: str = DEFAULT_TIMEZONE,
        start_hour: int = START_HOUR,
        fetch_timeout: float = DEFAULT_FETCH_TIMEOUT,
        ack_timeout: float = DEFAULT_ACK_TIMEOUT,
    ):
        self.interface = interface
        self.state_file = Path(state_file)
        self.url = url
        self.timezone = timezone
        self.start_hour = start_hour
        self.fetch_timeout = fetch_timeout
        self.ack_timeout = ack_timeout
        self._last_checked_slot = None

    def maybe_send(self, *, now: datetime | None = None) -> WeatherAttemptResult:
        """Attempt once when a new eligible local clock hour begins."""
        current = _local_time(now, self.timezone)
        if current.hour < self.start_hour:
            return WeatherAttemptResult("before_start")

        slot = _hour_slot(current)
        if slot == self._last_checked_slot:
            return WeatherAttemptResult("not_due", day=current.date().isoformat())
        self._last_checked_slot = slot

        return attempt_daily_weather(
            lambda message: send_with_interface(
                self.interface,
                message,
                ack_timeout=self.ack_timeout,
            ),
            state_file=self.state_file,
            url=self.url,
            timezone=self.timezone,
            start_hour=self.start_hour,
            fetch_timeout=self.fetch_timeout,
            now=current,
        )


def _alert_hash(kind: str, message: str) -> str:
    """Return a stable, namespaced identity for one broadcast message."""
    identity = f"{kind}\0{message}".encode("utf-8")
    return hashlib.sha256(identity).hexdigest()


def attempt_mesh_alert(
    send_message,
    *,
    state_file: Path = DEFAULT_STATE_FILE,
    url: str = DEFAULT_MESH_STATUS_URL,
    timezone: str = DEFAULT_TIMEZONE,
    fetch_timeout: float = DEFAULT_FETCH_TIMEOUT,
    now: datetime | None = None,
) -> WeatherAttemptResult:
    """Send one new live condition/alert message, only after ACK.

    The endpoint's explicit alert lines take priority. If there are no new
    alert lines, a changed conditions string is sent. A hash is written only
    after ``send_message`` returns a successful ACK, so a timeout or NAK can
    be retried on a later polling hour.
    """
    current = _local_time(now, timezone)
    state_path = state_file.resolve()

    with daily_lock(state_path):
        state = load_state(state_path)
        status = fetch_mesh_status(url, fetch_timeout)
        # Send one logical broadcast per poll. Explicit alert lines take
        # priority; the conditions snapshot is sent when no alert is active.
        # This prevents one endpoint response from producing two channel-0
        # packets and keeps the alert itself the only message for that state.
        if status.alerts:
            candidates = [
                (
                    "alert",
                    "ALERT: " + "\n".join(status.alerts),
                    status.state,
                )
            ]
        else:
            candidates = [
                ("conditions", "CONDITIONS: " + status.conditions, status.state)
            ]

        sent_hashes = state["sent_hashes"]
        candidate = None
        for kind, message, event_state in candidates:
            message_hash = _alert_hash(kind, event_state + "\0" + message)
            if message_hash not in sent_hashes:
                candidate = (kind, message, message_hash)
                break

        if candidate is None:
            return WeatherAttemptResult("already_sent", day=current.date().isoformat())

        kind, message, message_hash = candidate
        message_bytes = len(message.encode("utf-8"))
        if message_bytes > MAX_MESSAGE_BYTES:
            raise ValueError(
                f"live weather {kind} alert is {message_bytes} bytes; "
                f"Meshtastic permits {MAX_MESSAGE_BYTES} bytes in one packet"
            )
        slot = _hour_slot(current)
        last_attempt = state.get("last_alert_attempt", {})
        if last_attempt.get("hash") == message_hash and last_attempt.get("slot") == slot:
            return WeatherAttemptResult(
                "already_attempted", day=current.date().isoformat()
            )

        # Persist the attempt guard before network activity. This prevents a
        # restart or a tight polling loop from sending the same unacknowledged
        # message repeatedly within one hour. It is deliberately separate from
        # sent_hashes: only a confirmed ACK makes a message sent.
        state["last_alert_attempt"] = {
            "hash": message_hash,
            "kind": kind,
            "slot": slot,
            "attempted_at": current.isoformat(timespec="seconds"),
        }
        save_state(state_path, state)

        packet_id, ack_type = send_message(message)
        sent_hashes[message_hash] = {
            "kind": kind,
            "message": message,
            "packet_id": packet_id,
            "ack": ack_type,
            "sent_at": current.isoformat(timespec="seconds"),
        }
        save_state(state_path, state)
        return WeatherAttemptResult(
            "sent",
            day=current.date().isoformat(),
            packet_id=packet_id,
            ack_type=ack_type,
            kind=kind,
        )


class MeshAlertScheduler:
    """Poll live conditions at most hourly and send each message once."""

    def __init__(
        self,
        interface,
        *,
        state_file: Path = DEFAULT_STATE_FILE,
        url: str = DEFAULT_MESH_STATUS_URL,
        timezone: str = DEFAULT_TIMEZONE,
        fetch_timeout: float = DEFAULT_FETCH_TIMEOUT,
        ack_timeout: float = DEFAULT_ACK_TIMEOUT,
    ):
        self.interface = interface
        self.state_file = Path(state_file)
        self.url = url
        self.timezone = timezone
        self.fetch_timeout = fetch_timeout
        self.ack_timeout = ack_timeout
        self._last_checked_slot = None

    def maybe_send(self, *, now: datetime | None = None) -> WeatherAttemptResult:
        """Poll once per local hour; deduplication is persisted in state."""
        current = _local_time(now, self.timezone)
        slot = _hour_slot(current)
        if slot == self._last_checked_slot:
            return WeatherAttemptResult("not_due", day=current.date().isoformat())
        self._last_checked_slot = slot

        return attempt_mesh_alert(
            lambda message: send_with_interface(
                self.interface,
                message,
                ack_timeout=self.ack_timeout,
            ),
            state_file=self.state_file,
            url=self.url,
            timezone=self.timezone,
            fetch_timeout=self.fetch_timeout,
            now=current,
        )


def run(args, *, now: datetime | None = None) -> int:
    """Run one standalone scheduled check and return a process exit code."""
    result = attempt_daily_weather(
        lambda message: send_and_wait(
            message,
            device=args.device,
            connection_timeout=args.connection_timeout,
            ack_timeout=args.ack_timeout,
        ),
        state_file=args.state_file,
        url=args.url,
        timezone=args.timezone,
        fetch_timeout=args.fetch_timeout,
        now=now,
    )
    if result.status == "sent":
        print(f"sent and acknowledged ({result.ack_type}, packet {result.packet_id})")
    elif result.status == "already_sent":
        print("already sent")
    elif result.status == "already_attempted":
        print("already attempted this hour")
    elif result.status == "before_start":
        print(f"not due before {START_HOUR}:00 AM")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Send the BRC morning forecast to Meshtastic channel 0 once daily"
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="forecast text URL")
    parser.add_argument(
        "--state-file",
        type=Path,
        default=DEFAULT_STATE_FILE,
        help=f"persistent success state (default: {DEFAULT_STATE_FILE})",
    )
    parser.add_argument(
        "--timezone",
        default=DEFAULT_TIMEZONE,
        help=f"timezone defining a day (default: {DEFAULT_TIMEZONE})",
    )
    parser.add_argument(
        "--device",
        help="serial device path such as /dev/ttyACM0 (default: auto-detect)",
    )
    parser.add_argument(
        "--fetch-timeout", type=positive_float, default=DEFAULT_FETCH_TIMEOUT
    )
    parser.add_argument(
        "--connection-timeout",
        type=positive_float,
        default=DEFAULT_CONNECTION_TIMEOUT,
    )
    parser.add_argument(
        "--ack-timeout", type=positive_float, default=DEFAULT_ACK_TIMEOUT
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except KeyboardInterrupt:
        print("weather send interrupted", file=sys.stderr)
        return 130
    # This is the cron process boundary: report any operational failure nonzero.
    except Exception as exc:  # noqa: BLE001
        print(f"weather send failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
