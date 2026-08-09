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
        if "position" in new[burner] and "latitude" in new[burner]["coordinates"]:
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
    """Load the base map image and prepare PIL drawing surfaces."""
    png = Image.open("./media/Map_1bit.png")
    black_layer = Image.new("1", (c.WIDTH, c.HEIGHT), 255)
    black_layer.paste(png, c.image_position)

    red_layer = Image.new("1", (c.WIDTH, c.HEIGHT), 255)

    draw_black = ImageDraw.Draw(black_layer)
    draw_red = ImageDraw.Draw(red_layer)
    draw_red = draw_upward_pentagon(
        draw_red,
        center=c.man_svg,
        radius=c.svg_city_man_to_trashfence_pixel,
    )

    return black_layer, red_layer, draw_black, draw_red


def _draw_debug_overlay(draw_black, draw_red, black_layer, red_layer):
    """Draw calibration marks and test coordinates for --debug mode."""
    # Clear drawing layers
    draw_black = ImageDraw.Draw(black_layer)
    draw_red = ImageDraw.Draw(red_layer)
    draw_red = draw_upward_pentagon(
        draw_red,
        center=c.man_svg,
        radius=c.svg_city_man_to_trashfence_pixel,
    )

    # Landmark dots
    draw_dot(draw_red, c.man_svg)
    draw_dot(draw_red, c.temple_svg)
    draw_dot(draw_red, c.centercamp_svg)

    # Bounding box corner markers
    min_coords_svg = gps_to_image_coordinates((c.lat_min, c.lon_min, "min"))
    max_coords_svg = gps_to_image_coordinates((c.lat_max, c.lon_max, "12"))
    trash_svg = gps_to_image_coordinates(
        (c.top_trash_fence.latitude, c.top_trash_fence.longitude, "max")
    )

    draw_dot(draw_red, min_coords_svg)
    draw_dot(draw_red, trash_svg)
    draw_dot(draw_red, max_coords_svg)
    draw_dot(draw_red, (c.lat_min, c.lon_min))
    draw_dot(draw_red, (c.lat_max, c.lon_max))
    draw_red.line([trash_svg, min_coords_svg], fill=0, width=0)

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
        draw_red.line(shape, fill=0, width=0)

    draw_black = draw_test_coordinates(draw_black)

    return draw_black, draw_red


def _init_epd():
    """Initialize the WaveShare ePaper display (Pi-only)."""
    from waveshare_epd import epd7in5b_V2

    epd = epd7in5b_V2.EPD()
    logging.info("ePaper init and Clear")
    epd.init()
    return epd


def main(args):
    black_layer, red_layer, draw_black, draw_red = _load_map()

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
    if not args.debug:
        interface = connect_mesh_serial()
        if friend_srv is not None:
            friend_srv.set_mesh(interface)

    old_coords = {}

    try:
        while True:
            if args.debug:
                draw_black, draw_red = _draw_debug_overlay(
                    draw_black, draw_red, black_layer, red_layer
                )
            else:
                # Clear red layer and redraw pentagon
                draw_red = ImageDraw.Draw(red_layer)
                draw_red = draw_upward_pentagon(
                    draw_red,
                    center=c.man_svg,
                    radius=c.svg_city_man_to_trashfence_pixel,
                )

                mesh = get_mesh_info(interface)
                burners = add_bm_coordinates(mesh)

                # Filter to friends only
                if friend_store is not None:
                    friend_ids = friend_store.get_friend_ids()
                    burners = {
                        name: data
                        for name, data in burners.items()
                        if data.get("node_id") in friend_ids
                    }
                    # Update last_seen for displayed friends
                    for data in burners.values():
                        friend_store.update_last_seen(data["node_id"])
                    friend_store.flush_last_seen()
                    logging.debug(
                        "showing %d/%d friends", len(burners), len(friend_ids)
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
                    draw_black, draw_red = draw_node_labels(
                        burners, draw_black, draw_red
                    )
                else:
                    logging.debug("points are not really moving")

            if args.screen:
                black_layer.show()
            elif epd is not None:
                epd.display(epd.getbuffer(black_layer), epd.getbuffer(red_layer))

            logging.debug("sleeping %ds", c.sleep_seconds)
            time.sleep(c.sleep_seconds)

    finally:
        if interface is not None:
            interface.close()
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
