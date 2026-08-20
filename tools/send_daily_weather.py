#!/usr/bin/env python3
"""Send the BRC morning forecast to Meshtastic channel 0 once per day.

The day is marked complete only after Meshtastic reports an ACK. For a
broadcast, this is normally an implicit ACK generated after another mesh node
rebroadcasts the packet. A file lock prevents overlapping cron invocations
from sending the same day's message concurrently.
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
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from meshtastic import BROADCAST_ADDR
from meshtastic.protobuf import mesh_pb2
from meshtastic.serial_interface import SerialInterface

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_URL = "https://brcforecast.corbett.vc/api/public/mesh/morning.txt"
DEFAULT_STATE_FILE = ROOT / ".daily-weather-state.json"
DEFAULT_TIMEZONE = "America/Los_Angeles"
CHANNEL_INDEX = 0
STATE_VERSION = 1
MAX_MESSAGE_BYTES = int(mesh_pb2.Constants.DATA_PAYLOAD_LEN)


class DeliveryError(RuntimeError):
    """Raised when Meshtastic does not confirm delivery."""


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


def load_state(path: Path) -> dict:
    """Load state, failing closed if an existing state file is invalid."""
    if not path.exists():
        return {"version": STATE_VERSION, "sent_dates": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read state file {path}: {exc}") from exc
    if not isinstance(state, dict) or not isinstance(state.get("sent_dates"), dict):
        raise TypeError(f"invalid state file {path}; refusing a possible duplicate")
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


def run(args, *, now: datetime | None = None) -> int:
    """Run one cron attempt and return a process exit code."""
    timezone = ZoneInfo(args.timezone)
    current = now.astimezone(timezone) if now is not None else datetime.now(timezone)
    day = current.date().isoformat()
    state_path = args.state_file.resolve()

    with daily_lock(state_path):
        state = load_state(state_path)
        if day in state["sent_dates"]:
            print("already sent")
            return 0

        message = fetch_forecast(args.url, args.fetch_timeout)
        packet_id, ack_type = send_and_wait(
            message,
            device=args.device,
            connection_timeout=args.connection_timeout,
            ack_timeout=args.ack_timeout,
        )

        state["version"] = STATE_VERSION
        state["sent_dates"][day] = {
            "ack": ack_type,
            "feed_url": args.url,
            "message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
            "packet_id": packet_id,
            "sent_at": datetime.now(timezone).isoformat(timespec="seconds"),
        }
        save_state(state_path, state)
        print(f"sent and acknowledged ({ack_type}, packet {packet_id})")
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
    parser.add_argument("--fetch-timeout", type=positive_float, default=20.0)
    parser.add_argument("--connection-timeout", type=positive_float, default=30.0)
    parser.add_argument("--ack-timeout", type=positive_float, default=60.0)
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
