"""BRC Meshtastic ePaper Map — main display loop.

Polls a Meshtastic radio for node positions and renders them on a
WaveShare ePaper display (or desktop window in --screen mode).
"""

import argparse
import time
from datetime import datetime

from PIL import Image, ImageDraw

import config as c
from coordinates import distance_ft, gps_to_image_coordinates
from mesh import (
    add_bm_coordinates,
    get_mesh_info,
)
from mesh import (
    connect_serial as connect_mesh_serial,
)
from renderer import (
    draw_dot,
    draw_node_labels,
    draw_test_coordinates,
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


def _new_frame(base):
    """Create a clean frame with the static trash-fence outline."""
    frame = base.copy()
    draw = ImageDraw.Draw(frame)
    draw_upward_pentagon(
        draw,
        center=c.man_svg,
        radius=c.svg_city_man_to_trashfence_pixel,
    )
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


def _filter_friend_burners(burners, friend_store):
    """Filter mesh burners and merge their persistent friend emoji."""
    friends = {friend["node_id"]: friend for friend in friend_store.get_friends()}
    filtered = {
        name: data for name, data in burners.items() if data.get("node_id") in friends
    }
    for data in filtered.values():
        data["emoji"] = friends[data["node_id"]]["emoji"]
    return filtered, friends


def main(args):
    base = _load_map()
    frame, draw = _new_frame(base)

    # Friend filtering
    friend_store = None
    friend_srv = None
    if not args.no_friends:
        from friend_server import FriendServer
        from friend_store import FriendStore

        friend_store = FriendStore(c.friends_file)
        logging.info("loaded %d friends from %s", friend_store.count(), c.friends_file)
        friend_srv = FriendServer(friend_store, port=c.friend_server_port)
        friend_srv.start()
        logging.info("friend server at http://0.0.0.0:%d", c.friend_server_port)

    epd = None
    if not args.screen:
        epd = _init_epd()

    interface = None
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
            if friend_srv is not None:
                friend_srv.set_mesh(interface)

        while True:
            if not args.debug:
                mesh = get_mesh_info(interface)
                burners = add_bm_coordinates(mesh)

                # Filter to friends only
                if friend_store is not None:
                    burners, friends = _filter_friend_burners(burners, friend_store)
                    # Update last_seen for displayed friends
                    for data in burners.values():
                        friend_store.update_last_seen(data["node_id"])
                    friend_store.flush_last_seen()
                    logging.debug(
                        "showing %d/%d friends", len(burners), len(friends)
                    )

                if burners:
                    with open(c.log_file, "a") as f:
                        for name, data in burners.items():
                            f.write(
                                f"{datetime.now().isoformat()} {name} "
                                f"{data['coordinates']}\n"
                            )
                            f.flush()

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
        if interface is not None:
            interface.close()
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
        help="show all mesh nodes (disable friend filtering)",
    )

    args = parser.parse_args()
    main(args)
