import argparse
import math
import time
from datetime import datetime

import meshtastic
import meshtastic.serial_interface
import meshtastic.tcp_interface
from PIL import Image, ImageDraw, ImageFont

import config as c
from coordinates import distance_ft, gps_to_burning_man, gps_to_image_coordinates

logging = c.logging

fill = 0
# fill = (0,0,255)  #for RGB

# Retry settings for mesh connection
_MESH_RETRY_BASE_SEC = 5
_MESH_RETRY_MAX_SEC = 120
_MESH_RETRY_FACTOR = 2


def time_from_timestamp(timestamp):
    # Convert timestamp to datetime object
    dt_object = datetime.fromtimestamp(timestamp)
    # Extract and print the time
    time = dt_object.strftime("%H:%M:%S")
    return time


def draw_dot(draw, coord, radius=5, fill_color=fill):
    """
    This function draws a dot at a given position on a PIL ImageDraw object.

    Parameters:
    - draw: The PIL ImageDraw object to draw on.
    - coord: A tuple (x, y) specifying the pixel coordinates for the center of the dot.
    - radius: The radius of the dot in pixels. Default is 5.
    - fill_color: A tuple (r, g, b) specifying the color of the dot. Default is blue.

    Returns: Nothing. The dot is drawn directly on the draw object.
    """

    x, y = coord
    draw.ellipse([(x - radius, y - radius), (x + radius, y + radius)], fill=fill_color)


def draw_upward_pentagon(draw, center, radius, outline_color="black", fill_color=None):
    # draw = ImageDraw.Draw(image)

    # Define the points for the pentagon
    pentagon = []
    for i in range(5):
        angle = math.radians(90 - i * 72)  # Start from 90 degrees and go clockwise
        x = center[0] + radius * math.cos(angle)
        y = center[1] - radius * math.sin(
            angle
        )  # Subtract because PIL's y-axis points down
        pentagon.append((x, y))

    # Draw the pentagon (filled with transparent color)
    draw.polygon(pentagon, outline=None, fill=fill_color)

    # Simulate a dotted outline by drawing a series of small lines (or dots)
    dot_spacing = 4  # Change this to adjust the spacing between the dots
    for i in range(5):
        start = pentagon[i]
        end = pentagon[(i + 1) % 5]
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        distance = math.sqrt(dx * dx + dy * dy)
        num_dots = int(distance / dot_spacing)
        for j in range(num_dots):
            x = start[0] + j / num_dots * dx
            y = start[1] + j / num_dots * dy
            draw.line([(x, y), (x + 1, y)], fill=outline_color)

    return draw


def connect_mesh_serial():
    """Connect to a Meshtastic device over serial with retries."""
    delay = _MESH_RETRY_BASE_SEC
    while True:
        try:
            logging.info("connecting to Meshtastic over serial...")
            iface = meshtastic.serial_interface.SerialInterface()
            logging.info("connected")
            return iface
        except Exception as e:
            logging.warning("mesh connection failed: %s — retrying in %ds", e, delay)
            time.sleep(delay)
            delay = min(delay * _MESH_RETRY_FACTOR, _MESH_RETRY_MAX_SEC)


def connect_mesh_tcp(host):
    """Connect to a Meshtastic device over TCP with retries."""
    delay = _MESH_RETRY_BASE_SEC
    while True:
        try:
            logging.info("connecting to Meshtastic at %s...", host)
            iface = meshtastic.tcp_interface.TCPInterface(host)
            logging.info("connected")
            return iface
        except Exception as e:
            logging.warning(
                "mesh connection to %s failed: %s — retrying in %ds", host, e, delay
            )
            time.sleep(delay)
            delay = min(delay * _MESH_RETRY_FACTOR, _MESH_RETRY_MAX_SEC)


def get_mesh_info(interface):
    """Poll mesh nodes with retry on transient failures."""
    delay = _MESH_RETRY_BASE_SEC
    while True:
        try:
            return interface.nodes.items()
        except Exception as e:
            logging.warning("mesh poll failed: %s — retrying in %ds", e, delay)
            time.sleep(delay)
            delay = min(delay * _MESH_RETRY_FACTOR, _MESH_RETRY_MAX_SEC)


def add_bm_coordinates(burners):
    output = {}
    for nodename, data in burners:
        logging.debug("processing node %s", nodename)
        logging.debug("%s", data)
        username = data["user"]["longName"]

        if "coordinates" in data and "latitude" in data["coordinates"]:
            output[username] = {}
            output[username]["coordinates"] = data["coordinates"]

            # get "hours" from gps coordinates
            output[username]["bm_coordinates"] = gps_to_burning_man(
                output[username]["coordinates"]["latitude"],
                output[username]["coordinates"]["longitude"],
            )
            output[username]["image_coordinates"] = gps_to_image_coordinates(
                (
                    output[username]["coordinates"]["latitude"],
                    output[username]["coordinates"]["longitude"],
                    username,
                )
            )
            logging.debug("image coordinates %s", output[username]["image_coordinates"])
        else:
            logging.info("no position for %s %s", username, data)

    return output


def show_mesh_info(burners, draw_black, draw_red):

    font12_regular = ImageFont.truetype("./media/Font.ttc", 12)

    # Set the start position for text
    # text_start_height = c.HEIGHT - len(burners)*14 - 10
    text_start_height = 20

    for name in burners:
        burner = burners[name]

        # Draw the icon at the calculated position
        # Change fill to be red
        draw_red.text(burner["image_coordinates"], "x", font=font12_regular, fill=fill)

        # Draw user's details on the bottom left
        # TODO check if time is provided
        user_detail_str = f"{name}: {burner['bm_coordinates']} at {time_from_timestamp(burner['coordinates']['time'])}"
        draw_red.text(
            (10, text_start_height), user_detail_str, font=font12_regular, fill=fill
        )  # Change fill to be blue
        text_start_height += 14  # Move to next line

    return (draw_black, draw_red)


# demo / test
#
# --- test coordinates from official 2026 GIS data ---
# Source: /home/ews/sources/innovate-GIS-data/2026/GeoJSON/
_TEST_COORDS = [
    # The Man (cpns.geojson FID 33)
    [40.783247, -119.207884, "man"],
    # The Temple (cpns.geojson FID 34)
    [40.788099, -119.201500, "temple"],
    # Center Camp (cpns.geojson FID 31)
    [40.777372, -119.215612, "center"],
    # 9:00 & G Plaza
    [40.792611, -119.220207, "9G"],
    # 7:30 & G Plaza
    [40.783245, -119.225308, "730G"],
    # 4:30 & G Plaza
    [40.770004, -119.207883, "430G"],
    # 3:00 & G Plaza
    [40.773883, -119.195565, "3G"],
    # Trash fence pentagram vertices (trash_fence.geojson)
    [40.779710, -119.237418, "pt1"],
    [40.803521, -119.221408, "pt2"],
    [40.799288, -119.186672, "pt3"],
    [40.772884, -119.181240, "pt4"],
    [40.760788, -119.212582, "pt5"],
]


def run_demo_coordinates(draw, calibrate=False):
    font12_regular = ImageFont.truetype("./media/Font.ttc", 12)

    for lat, lon, name in _TEST_COORDS:
        addr = gps_to_burning_man(lat, lon)
        px = gps_to_image_coordinates((lat, lon, name))

        if calibrate:
            logging.info(
                "CALIB %6s | GPS=(%.6f,%.6f) | BRC=%s | pixel=(%d,%d) | screen=%s",
                name, lat, lon, addr, px[0], px[1],
                "in" if (c.left_limit <= px[0] <= c.right_limit
                          and c.twelve_limit <= px[1] <= c.bottom_limit) else "OFF"
            )

        draw.text(px, name, font=font12_regular, fill=fill)

    return draw


# are the points moving far enough to trigger redraw?
def equal_bm_coordinates(new, old):
    # detect added or removed nodes
    if set(new.keys()) != set(old.keys()):
        logging.debug("nodes joined or left")
        return False

    for burner in new:
        if "position" in new[burner] and "latitude" in new[burner]["coordinates"]:
            if (
                distance_ft(
                    (
                        new[burner]["coordinates"]["latitude"],
                        new[burner]["coordinates"]["longitude"],
                    ),
                    (
                        old[burner]["coordinates"]["latitude"],
                        old[burner]["coordinates"]["longitude"],
                    ),
                )
                < c.min_distance_refresh_ft
            ):
                logging.debug("moved less than threshold, still similar")
            else:
                logging.debug("we have moved")
                return False
        else:
            logging.debug("no position %s", new)
            return False

    logging.debug("returning similar True")
    return True


def main(args):

    ## Load the PNG image data to PIL. The mode (including "1" for 1-bit images) is auto-detected.
    png_image = Image.open("./media/Map_1bit.png")

    # Create base images
    Himage = Image.new("1", (c.WIDTH, c.HEIGHT), 255)
    red = Image.new("1", (c.WIDTH, c.HEIGHT), 255)

    # Paste the processed SVG image
    Himage.paste(png_image, c.image_position)

    # Perform additional drawing operations
    draw_Himage = ImageDraw.Draw(Himage)
    draw_red = ImageDraw.Draw(red)
    draw_red = draw_upward_pentagon(
        draw_red, center=c.man_svg, radius=c.svg_city_man_to_trashfence_pixel
    )

    epd = None
    if not args.screen:
        # TODO remove this because we dont want to load the lib at every refresh
        from waveshare_epd import epd7in5b_V2

        epd = epd7in5b_V2.EPD()
        logging.info("init and Clear")
        epd.init()
    #        epd.Clear()
    #

    interface = None
    if not args.debug:
        interface = connect_mesh_serial()

    old_coords = {}

    try:
        while True:
            if args.debug:
                # clear drawing layers each iteration
                draw_Himage = ImageDraw.Draw(Himage)
                draw_red = ImageDraw.Draw(red)
                draw_red = draw_upward_pentagon(
                    draw_red,
                    center=c.man_svg,
                    radius=c.svg_city_man_to_trashfence_pixel,
                )

                draw_dot(draw_red, c.man_svg)
                draw_dot(draw_red, c.temple_svg)
                draw_dot(draw_red, c.centercamp_svg)

                # lat/lon min and max
                min_coords = (c.lat_min, c.lon_min, "min")
                trash_coords = (
                    c.top_trash_fence.latitude,
                    c.top_trash_fence.longitude,
                    "max",
                )
                min_coords_svg = gps_to_image_coordinates(min_coords)
                trash_coords_svg = gps_to_image_coordinates(trash_coords)
                twelve_coords_svg = gps_to_image_coordinates(
                    (c.lat_max, c.lon_max, "12")
                )

                draw_dot(draw_red, min_coords_svg)
                draw_dot(draw_red, trash_coords_svg)
                draw_dot(draw_red, twelve_coords_svg)
                logging.debug("max %s %s", twelve_coords_svg, trash_coords_svg)

                draw_dot(draw_red, (c.lat_min, c.lon_min))
                draw_dot(draw_red, (c.lat_max, c.lon_max))

                # make a line between max and min, it should pass through the center
                shape_max_min = [trash_coords_svg, min_coords_svg]
                draw_red.line(shape_max_min, fill=fill, width=0)

                # display lines to know we got the coordinates right
                shape_left = [(c.left_limit, 0), (c.left_limit, c.HEIGHT - 10)]
                shape_right = [(c.right_limit, 0), (c.right_limit, c.HEIGHT - 10)]
                shape_fence = [(0, c.top_limit), (c.HEIGHT - 10, c.top_limit)]
                shape_twelve = [(0, c.twelve_limit), (c.HEIGHT - 10, c.twelve_limit)]
                shape_bottom = [(0, c.bottom_limit), (c.HEIGHT - 10, c.bottom_limit)]

                shape_man_horiz = [(0, c.man_svg[1]), (c.HEIGHT - 10, c.man_svg[1])]
                shape_man_vertical = [(c.man_svg[0], 0), (c.man_svg[0], c.HEIGHT - 10)]

                draw_red.line(shape_left, fill=fill, width=0)
                draw_red.line(shape_right, fill=fill, width=0)
                draw_red.line(shape_fence, fill=fill, width=0)
                draw_red.line(shape_twelve, fill=fill, width=0)
                draw_red.line(shape_bottom, fill=fill, width=0)
                draw_red.line(shape_man_horiz, fill=fill, width=0)
                draw_red.line(shape_man_vertical, fill=fill, width=0)

                draw_Himage = run_demo_coordinates(draw_Himage, calibrate=args.calibrate)
            else:
                # clear drawing layers each iteration
                draw_red = ImageDraw.Draw(red)
                draw_red = draw_upward_pentagon(
                    draw_red,
                    center=c.man_svg,
                    radius=c.svg_city_man_to_trashfence_pixel,
                )

                mesh = get_mesh_info(interface)
                burners = add_bm_coordinates(mesh)
                # log burners movements
                if burners:
                    with open(c.log_file, "a") as f:
                        for burner_name, burner_data in burners.items():
                            f.write(
                                f"{datetime.now().isoformat()} {burner_name} {burner_data['coordinates']}\n"
                            )
                            f.flush()
                # do we need to refresh the screen ?
                if not equal_bm_coordinates(burners, old_coords):
                    old_coords = burners
                    (draw_Himage, draw_red) = show_mesh_info(
                        burners, draw_Himage, draw_red
                    )
                else:
                    logging.debug("points are not really moving")

            if args.screen:
                Himage.show()
            elif epd is not None:
                epd.display(epd.getbuffer(Himage), epd.getbuffer(red))

            logging.debug("sleeping")
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
        help="display it in a screen rather than eink",
    )
    parser.add_argument(
        "-c",
        "--calibrate",
        action="store_true",
        help="print detailed coordinate conversion for each test point",
    )

    args = parser.parse_args()

    main(args)
