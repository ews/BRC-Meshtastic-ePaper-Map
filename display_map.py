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
    draw_dot,
    draw_node_labels,
    draw_test_coordinates,
    draw_updated_timestamp,
    draw_upward_pentagon,
)

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


def main(args):
    base = _load_map()
    frame, draw = _new_frame(base)

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
        friend_srv = FriendServer(friend_store, port=c.friend_server_port)
        friend_srv.start()
        logging.info("friend server at http://0.0.0.0:%d", c.friend_server_port)

    epd = None
    if not args.screen:
        epd = _init_epd()

    interface = None
    history = HistoryStore(c.history_database)
    chat_callback = None
    position_callback = None
    channel_positions = ChannelPositionCache(c.location_channel_index)
    old_coords = {}
    needs_refresh = False

    try:
        # Put useful content on the panel before mesh discovery/retries can block.
        if args.debug:
            frame = _draw_debug_overlay(base)
        logging.info("displaying initial map")
        _display_frame(frame, args.screen, epd)

        if not args.debug:
            interface = connect_mesh_serial()

            def save_chat(packet, interface):
                name = sender_name_for_packet(packet, interface)
                if history.record_message(packet, name):
                    logging.info("saved chat message from %s", name or "unknown")

            chat_callback = save_chat
            pub.subscribe(chat_callback, "meshtastic.receive.text")
            position_callback = channel_positions.receive
            pub.subscribe(position_callback, "meshtastic.receive.position")
            logging.info(
                "showing positions received on Meshtastic channel %d",
                c.location_channel_index,
            )
            if friend_srv is not None:
                friend_srv.set_mesh(interface)

        while True:
            if not args.debug:
                burners = add_bm_coordinates(channel_positions.snapshot(interface))
                saved = history.record_positions(burners)
                if saved:
                    logging.info("saved %d new position reports", saved)

                # Friend records are optional emoji overrides, not an allowlist.
                if friend_store is not None:
                    burners, friends = _apply_friend_emojis(burners, friend_store)
                    logging.debug(
                        "showing %d channel locations with %d emoji overrides",
                        len(burners),
                        len(friends),
                    )

                if not equal_bm_coordinates(burners, old_coords):
                    old_coords = burners
                    frame, draw = _new_frame(base)
                    draw_node_labels(burners, draw)
                    needs_refresh = True
                else:
                    logging.debug("points are not really moving")

            if needs_refresh:
                _display_frame(frame, args.screen, epd)
                needs_refresh = False

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


if __name__ == "__main__":
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

    args = parser.parse_args()
    main(args)
