"""BRC Meshtastic ePaper Map — main display loop.

Polls a Meshtastic radio for node positions and renders them on a
WaveShare ePaper display (or desktop window in --screen mode).
"""

import argparse
import time

from PIL import Image, ImageDraw
from pubsub import pub

import config as c
from coordinates import distance_ft, gps_to_image_coordinates
from history_store import HistoryStore, sender_name_for_packet
from mesh import (
    ChannelPositionCache,
    add_bm_coordinates,
)
from mesh import (
    connect_serial as connect_mesh_serial,
)
from renderer import (
    assign_burner_emojis,
    draw_chat_messages,
    draw_dot,
    draw_node_labels,
    draw_test_coordinates,
    draw_updated_timestamp,
    draw_upward_pentagon,
)
from tools.send_daily_weather import MeshAlertScheduler, WeatherAlertScheduler

logging = c.logging


def equal_bm_coordinates(new, old):
    """Return False if any burners moved significantly or joined/left.

    Checks for added/removed nodes and any node that moved more than
    min_distance_refresh_ft from its last known position.
    """
    if set(new.keys()) != set(old.keys()):
        logging.debug("nodes joined or left")
        return False

    for burner in new:
        if new[burner].get("emoji") != old[burner].get("emoji"):
            logging.debug("emoji changed for %s", burner)
            return False
        if "latitude" in new[burner].get("coordinates", {}):
            dist = distance_ft(
                (
                    new[burner]["coordinates"]["latitude"],
                    new[burner]["coordinates"]["longitude"],
                ),
                (
                    old[burner]["coordinates"]["latitude"],
                    old[burner]["coordinates"]["longitude"],
                ),
            )
            if dist >= c.min_distance_refresh_ft:
                logging.debug("node %s moved %.0f ft", burner, dist)
                return False
        else:
            logging.debug("no position for %s", burner)
            return False

    logging.debug("no significant movement")
    return True


def _load_map():
    """Load the map into an RGB canvas suitable for the E6 panel."""
    png = Image.open(c.map_file).convert("RGB")
    base = Image.new("RGB", (c.WIDTH, c.HEIGHT), "white")
    base.paste(png, c.image_position)
    return base


def _new_frame(base, updated_at=None):
    """Create a clean frame with the static trash-fence outline."""
    frame = base.copy()
    draw = ImageDraw.Draw(frame)
    draw_upward_pentagon(
        draw,
        center=c.man_svg,
        radius=c.svg_city_man_to_trashfence_pixel,
    )
    draw_updated_timestamp(draw, updated_at)
    return frame, draw


def _draw_debug_overlay(base):
    """Draw calibration marks and test coordinates for --debug mode."""
    frame, draw = _new_frame(base)

    # Landmark dots
    draw_dot(draw, c.man_svg)
    draw_dot(draw, c.temple_svg)
    draw_dot(draw, c.centercamp_svg)

    # Bounding box corner markers
    min_coords_svg = gps_to_image_coordinates((c.lat_min, c.lon_min, "min"))
    max_coords_svg = gps_to_image_coordinates((c.lat_max, c.lon_max, "12"))
    trash_svg = gps_to_image_coordinates(
        (c.top_trash_fence.latitude, c.top_trash_fence.longitude, "max")
    )

    draw_dot(draw, min_coords_svg)
    draw_dot(draw, trash_svg)
    draw_dot(draw, max_coords_svg)
    draw.line([trash_svg, min_coords_svg], fill="red", width=1)

    # Boundary lines
    shapes = [
        [(c.left_limit, 0), (c.left_limit, c.HEIGHT - 10)],
        [(c.right_limit, 0), (c.right_limit, c.HEIGHT - 10)],
        [(0, c.top_limit), (c.HEIGHT - 10, c.top_limit)],
        [(0, c.twelve_limit), (c.HEIGHT - 10, c.twelve_limit)],
        [(0, c.bottom_limit), (c.HEIGHT - 10, c.bottom_limit)],
        [(0, c.man_svg[1]), (c.HEIGHT - 10, c.man_svg[1])],
        [(c.man_svg[0], 0), (c.man_svg[0], c.HEIGHT - 10)],
    ]
    for shape in shapes:
        draw.line(shape, fill="red", width=1)

    draw_test_coordinates(draw)
    return frame


def _init_epd():
    """Initialize the WaveShare 7.3-inch E6 PhotoPainter display."""
    from waveshare_epd import epd7in3e

    epd = epd7in3e.EPD()
    logging.info("initializing 7.3-inch E6 ePaper")
    if epd.init() != 0:
        raise RuntimeError("ePaper initialization failed")
    return epd


def _display_frame(frame, screen, epd):
    """Send one completed frame to the desktop preview or e-paper."""
    if screen:
        frame.show()
    elif epd is not None:
        epd.display(epd.getbuffer(frame))


def _apply_friend_emojis(burners, friend_store):
    """Apply optional persistent emoji overrides without filtering nodes."""
    friends = {friend["node_id"]: friend for friend in friend_store.get_friends()}
    for data in burners.values():
        friend = friends.get(data.get("node_id"))
        if friend:
            data["emoji"] = friend["emoji"]
    return burners, friends


def _cached_burners(channel_positions, interface, friend_store):
    """Build display-ready burners from all retained last-known positions."""
    burners = add_bm_coordinates(channel_positions.snapshot(interface))
    if friend_store is not None:
        burners, friends = _apply_friend_emojis(burners, friend_store)
        logging.debug(
            "showing %d retained locations with %d emoji overrides",
            len(burners),
            len(friends),
        )
    assign_burner_emojis(burners)
    return burners


def _render_content(base, burners, chat_messages=None):
    """Compose the map, location list, and optional channel-chat panel."""
    frame, draw = _new_frame(base)
    draw_node_labels(burners, draw)
    if chat_messages is not None:
        draw_chat_messages(draw, chat_messages, location_count=len(burners))
    return frame, draw


def _latest_chat_messages(history, enabled):
    """Read recent chat without requiring it from lightweight test doubles."""
    if not enabled:
        return []
    reader = getattr(history, "latest_messages", None)
    return reader(c.location_channel_index) if reader is not None else []


def main(args):
    base = _load_map()
    frame, _ = _new_frame(base)
    channel_positions = ChannelPositionCache(c.location_channel_index)
    interface = None

    # Friend metadata is optional and affects emojis only, never visibility.
    friend_store = None
    friend_srv = None
    if not args.no_friends:
        from friend_server import FriendServer
        from friend_store import FriendStore

        friend_store = FriendStore(c.friends_file)
        logging.info(
            "loaded %d optional emoji overrides from %s",
            friend_store.count(),
            c.friends_file,
        )
        friend_srv = FriendServer(
            friend_store,
            node_source=lambda: channel_positions.web_nodes(interface),
            port=c.friend_server_port,
        )
        friend_srv.start()
        logging.info(
            "Channel 1 location web app at http://0.0.0.0:%d",
            c.friend_server_port,
        )

    epd = None
    if not args.screen:
        epd = _init_epd()

    history = HistoryStore(c.history_database)
    restored = channel_positions.restore(history.latest_positions())
    if restored:
        logging.info(
            "restored %d last-known positions from %s",
            restored,
            c.history_database,
        )
    chat_callback = None
    position_callback = None
    old_coords = {}
    old_chat_messages = []
    needs_refresh = False
    last_display_time = time.monotonic()
    weather_scheduler = None
    mesh_alert_scheduler = None

    try:
        # Put useful content on the panel before mesh discovery/retries can block.
        if args.debug:
            frame = _draw_debug_overlay(base)
        elif channel_positions.count() or not getattr(args, "no_chat", False):
            old_coords = _cached_burners(
                channel_positions,
                interface,
                friend_store,
            )
            old_chat_messages = _latest_chat_messages(
                history, not getattr(args, "no_chat", False)
            )
            frame, _ = _render_content(
                base,
                old_coords,
                None if getattr(args, "no_chat", False) else old_chat_messages,
            )
        logging.info("displaying initial map")
        _display_frame(frame, args.screen, epd)
        last_display_time = time.monotonic()

        if not args.debug:
            interface = connect_mesh_serial()
            restored = channel_positions.restore(
                (getattr(interface, "nodes", {}) or {}).items()
            )
            if restored:
                logging.info(
                    "loaded %d additional last-known positions from radio NodeDB",
                    restored,
                )

            def save_chat(packet, interface):
                name = sender_name_for_packet(packet, interface)
                if history.record_message(packet, name):
                    logging.info("saved chat message from %s", name or "unknown")

            chat_callback = save_chat
            pub.subscribe(chat_callback, "meshtastic.receive.text")
            position_callback = channel_positions.receive
            pub.subscribe(position_callback, "meshtastic.receive.position")
            logging.info(
                "tracking live positions on Meshtastic channel %d; "
                "retaining last-known positions indefinitely",
                c.location_channel_index,
            )
            if getattr(args, "weather_alerts", True):
                weather_scheduler = WeatherAlertScheduler(interface)
                mesh_alert_scheduler = MeshAlertScheduler(interface)
                logging.info(
                    "daily weather forecast and live condition alerts enabled on "
                    "channel 0; forecast starts at 9:00 AM Pacific and live "
                    "conditions are polled hourly"
                )
        while True:
            if not args.debug:
                burners = _cached_burners(
                    channel_positions,
                    interface,
                    friend_store,
                )
                saved = history.record_positions(burners)
                if saved:
                    logging.info("saved %d new position reports", saved)

                chat_messages = _latest_chat_messages(
                    history, not getattr(args, "no_chat", False)
                )
                locations_changed = not equal_bm_coordinates(burners, old_coords)
                chat_changed = chat_messages != old_chat_messages
                if locations_changed or chat_changed:
                    old_coords = burners
                    old_chat_messages = chat_messages
                    frame, _ = _render_content(
                        base,
                        burners,
                        None if getattr(args, "no_chat", False) else chat_messages,
                    )
                    needs_refresh = True
                else:
                    logging.debug("points are not really moving")

                if weather_scheduler is not None:
                    try:
                        weather_result = weather_scheduler.maybe_send()
                    # A weather failure must never take down the live map.
                    except Exception as exc:  # noqa: BLE001
                        logging.warning(
                            "weather alert attempt failed for this hour: %s",
                            exc,
                        )
                    else:
                        if weather_result.status == "sent":
                            logging.info(
                                "weather alert sent and acknowledged (%s, packet %s)",
                                weather_result.ack_type,
                                weather_result.packet_id,
                            )

                if mesh_alert_scheduler is not None:
                    try:
                        mesh_alert_result = mesh_alert_scheduler.maybe_send()
                    # A live-alert failure must never take down the map.
                    except Exception as exc:  # noqa: BLE001
                        logging.warning(
                            "live weather alert check failed for this hour: %s",
                            exc,
                        )
                    else:
                        if mesh_alert_result.status == "sent":
                            logging.info(
                                "live weather %s sent and acknowledged (%s, packet %s)",
                                mesh_alert_result.kind or "message",
                                mesh_alert_result.ack_type,
                                mesh_alert_result.packet_id,
                            )

            # Forced periodic refresh keeps the bottom-right updated timestamp
            # current even when positions and chat are unchanged.
            if (
                not needs_refresh
                and time.monotonic() - last_display_time >= c.forced_refresh_seconds
            ):
                if args.debug:
                    frame = _draw_debug_overlay(base)
                else:
                    frame, _ = _render_content(
                        base,
                        old_coords,
                        None
                        if getattr(args, "no_chat", False)
                        else old_chat_messages,
                    )
                needs_refresh = True
                logging.info(
                    "forced periodic refresh after %.0fs without changes",
                    time.monotonic() - last_display_time,
                )

            if needs_refresh:
                _display_frame(frame, args.screen, epd)
                needs_refresh = False
                last_display_time = time.monotonic()

            logging.debug("sleeping %ds", c.sleep_seconds)
            time.sleep(c.sleep_seconds)

    finally:
        if chat_callback is not None:
            pub.unsubscribe(chat_callback, "meshtastic.receive.text")
        if position_callback is not None:
            pub.unsubscribe(position_callback, "meshtastic.receive.position")
        if interface is not None:
            interface.close()
        history.close()
        if epd is not None:
            epd.sleep()
        logging.info("shutdown complete")


def build_parser():
    """Build the command-line parser for the map process."""
    parser = argparse.ArgumentParser(
        prog="Display BRC Map",
        description="Your meshtastic friends on a map",
        epilog="Do not get too lost out there",
    )
    parser.add_argument("-d", "--debug", action="store_true")
    parser.add_argument(
        "-s",
        "--screen",
        action="store_true",
        help="display on desktop window rather than ePaper",
    )
    parser.add_argument(
        "-c",
        "--calibrate",
        action="store_true",
        help="print detailed GPS→pixel conversion for each test point",
    )
    parser.add_argument(
        "--no-friends",
        action="store_true",
        help="disable the optional friend/emoji web server and overrides",
    )
    parser.add_argument(
        "--no-chat",
        action="store_true",
        help="disable the Channel 1 recent-chat panel",
    )
    parser.add_argument(
        "--weather-alerts",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "send the channel-0 morning forecast after 9 AM Pacific, retrying "
            "hourly until acknowledged (default: enabled)"
        ),
    )
    return parser


if __name__ == "__main__":
    main(build_parser().parse_args())
