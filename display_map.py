import io
import cairosvg
import meshtastic
import meshtastic.serial_interface
import meshtastic.tcp_interface
import fontawesome as fa
from PIL import Image, ImageDraw, ImageFont, ImageOps
import time
from datetime import datetime
from coordinates import gps_to_burning_man, gps_to_image_coordinates, burning_man_to_gps, distance_ft
import config as c
import math
import argparse
logging = c.logging

fill = 0
#fill = (0,0,255)  #for RGB

def time_from_timestamp(timestamp):
    # Convert timestamp to datetime object
    dt_object = datetime.fromtimestamp(timestamp)
    # Extract and print the time
    time = dt_object.strftime('%H:%M:%S')
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

def draw_upward_pentagon(draw, center, radius, outline_color='black', fill_color=None):
    #draw = ImageDraw.Draw(image)

    # Define the points for the pentagon
    pentagon = []
    for i in range(5):
        angle = math.radians(90 - i * 72)  # Start from 90 degrees and go clockwise
        x = center[0] + radius * math.cos(angle)
        y = center[1] - radius * math.sin(angle)  # Subtract because PIL's y-axis points down
        pentagon.append((x, y))

    # Draw the pentagon (filled with transparent color)
    draw.polygon(pentagon, outline=None, fill=fill_color)

    # Simulate a dotted outline by drawing a series of small lines (or dots)
    dot_spacing = 4  # Change this to adjust the spacing between the dots
    for i in range(5):
        start = pentagon[i]
        end = pentagon[(i+1)%5]
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        distance = math.sqrt(dx*dx + dy*dy)
        num_dots = int(distance / dot_spacing)
        for j in range(num_dots):
            x = start[0] + j / num_dots * dx
            y = start[1] + j / num_dots * dy
            draw.line([(x, y), (x+1, y)], fill=outline_color)

    return draw

def get_mesh_info(interface):
    return interface.nodes.items()

def add_bm_coordinates(burners):
    output = {}
    for nodename, data in burners:
        print("processing node %s", nodename)
        print(data)
        username = data['user']['longName']

        if 'coordinates' in data and 'latitude' in data['coordinates']:

            output[username] = {}
            output[username]['coordinates'] = data['coordinates']

            #get "hours" from gps coordinates
            output[username]['bm_coordinates'] = gps_to_burning_man(
                output[username]['coordinates']['latitude'], output[username]['coordinates']['longitude'])
            output[username]['image_coordinates'] = gps_to_image_coordinates((output[username]['coordinates']['latitude'], output[username]['coordinates']['longitude'], username))
            print("image coordinates %s" , output[username]['image_coordinates'])
        else:
            print('ERROR no position for %s %s', username, data)

    return output

def show_mesh_info(burners, draw_black, draw_red):

    font12 = ImageFont.truetype('./media/fontawesome-regular.ttf', 24)
    font12_regular = ImageFont.truetype('./media/Font.ttc', 12)


    # Set the start position for text
    #text_start_height = c.HEIGHT - len(burners)*14 - 10
    text_start_height = 20

    for name in burners:
        burner = burners[name]

        # Draw the icon at the calculated position
        # Change fill to be red
        draw_red.text(burner['image_coordinates'], 'x', font=font12_regular, fill=fill)

        # Draw user's details on the bottom left
        # TODO check if time is provided
        user_detail_str = f"{name}: {burner['bm_coordinates']} at {time_from_timestamp(burner['coordinates']['time'])}"
        draw_red.text((10, text_start_height), user_detail_str,
                         font=font12_regular, fill=fill)  # Change fill to be blue
        text_start_height += 14  # Move to next line


    return (draw_black, draw_red)

# demo / test
#
def run_demo_coordinates(black):
    #test_coords = [[c.MAN_LAT, c.MAN_LONG, 'man']]
    test_coords = [[40.7933127, -119.2110380 , '9b'],
                   [40.7870292, -119.2144870 , '730b'],
                   [40.7918738, -119.1963410, 'TT'],
                   [c.MAN_LAT, c.MAN_LONG, 'man'],
                   [40.782814, -119.233566, 'p1'],
                   [40.807028, -119.217274, 'p2'],
                   [40.802722, -119.181931, 'p3'],
                   [40.775857, -119.176407, 'p4'],
                   [40.763558, -119.208301, 'p5']
                   ]
    #test_coords = [[40.7918738, -119.1963410, 'temple']]

    font12 = ImageFont.truetype('./media/fontawesome-regular.ttf', 24)
    font12_regular = ImageFont.truetype('./media/Font.ttc', 12)

    for coordinates in test_coords:
        print("coord", coordinates)
        image_coordinates = gps_to_image_coordinates(coordinates)
        black.text(image_coordinates, coordinates[2], font=font12_regular, fill=fill)

    return(black)

#works and passes
def run_demo_coords_to_streets():
    for coord in test_coords:
        print(gps_to_burning_man(coord[0], coord[1]))


#    run_demo_coords_to_streets()

#are the points moving far enough to trigger redraw?
def equal_bm_coordinates(new, old):
    similar = 1
    for burner in new.keys():
        if not burner in old:

            logging.debug("new entry")
            similar = 0
            break
        if 'position' in new[burner] and 'latitude' in new[burner]['coordinates']:
            if distance_ft((new[burgner]['coordinates']['latitude'], new[burner]['coordinates']['latitude']),(old[burner]['coordinates']['latitude'], old[burner]['coordinates']['longitude'])) < c.min_distance_refresh_ft:
                logging.debug("we have moved")
                similar = 0
                break
        else:
            logging.debug("no position %s", new)
            logging.debug("*****")
            similar = 0
            break

    logging.debug('returning similar %s', similar)
    return(similar)

def main(args):



    ## Load the PNG image data to PIL. The mode (including "1" for 1-bit images) is auto-detected.
    png_image = Image.open("./media/Map_1bit.png")

    # Create base images
    Himage = Image.new('1', (c.WIDTH, c.HEIGHT), 255)
    red = Image.new('1', (c.WIDTH, c.HEIGHT), 255)

    # Paste the processed SVG image
    Himage.paste(png_image, c.image_position)

    # Perform additional drawing operations
    draw_Himage = ImageDraw.Draw(Himage)
    draw_red = ImageDraw.Draw(red)
    draw_red = draw_upward_pentagon(draw_red, center=c.man_svg, radius=c.svg_city_man_to_trashfence_pixel)

    if not args.screen :

        #TODO remove this because we dont want to load the lib at every refresh
        from waveshare_epd import epd7in5b_V2
        epd = epd7in5b_V2.EPD()
        logging.info("init and Clear")
        epd.init()
#        epd.Clear()
#

    if not args.debug:
        #get info from mesh
        #interface = meshtastic.tcp_interface.TCPInterface('192.168.0.188')
        interface = meshtastic.serial_interface.SerialInterface()
        old_coords = {}

    while True:

        if(args.debug):

            draw_dot(draw_red, c.man_svg)
            draw_dot(draw_red, c.temple_svg)
            draw_dot(draw_red, c.centercamp_svg)

            #lat/lon min and max
            min_coords = ( c.lat_min, c.lon_min, 'min')
            trash_coords = ( c.top_trash_fence.longitude, c.top_trash_fence.latitude, 'max')
            min_coords_svg= gps_to_image_coordinates(min_coords)
            trash_coords_svg= gps_to_image_coordinates(trash_coords)
            twelve_coords_svg= gps_to_image_coordinates((c.lat_max, c.lon_max, '12'))

            draw_dot(draw_red, min_coords_svg)
            draw_dot(draw_red, trash_coords_svg)
            draw_dot(draw_red, twelve_coords_svg)
            logging.debug('max %s %s', twelve_coords_svg, trash_coords_svg)

            draw_dot(draw_red, (c.lat_min, c.lon_min))
            draw_dot(draw_red, (c.lat_max, c.lon_max))

            #make a line between max and min, it should pass through the center
            shape_max_min = [trash_coords_svg, min_coords_svg]
            draw_red.line(shape_max_min, fill=fill, width = 0)

            #display lines to know we got the coordinates right
            shape_left = [(c.left_limit, 0), (c.left_limit, c.HEIGHT - 10)]
            shape_right = [(c.right_limit, 0), (c.right_limit, c.HEIGHT- 10)]
            shape_fence= [(0, c.top_limit), (c.HEIGHT - 10, c.top_limit)]
            shape_twelve= [(0, c.twelve_limit), (c.HEIGHT - 10, c.twelve_limit)]
            shape_bottom = [(0, c.bottom_limit), (c.HEIGHT-10, c.bottom_limit)]

            shape_man_horiz= [(0, c.man_svg[1]), (c.HEIGHT-10, c.man_svg[1])]
            shape_man_vertical= [(c.man_svg[0], 0), (c.man_svg[0]), c.HEIGHT-10]

            draw_red.line(shape_left, fill=fill, width = 0)
            draw_red.line(shape_right, fill=fill, width = 0)
            draw_red.line(shape_fence, fill=fill, width = 0)
            draw_red.line(shape_twelve, fill=fill, width = 0)
            draw_red.line(shape_bottom, fill=fill, width = 0)
            draw_red.line(shape_man_horiz, fill=fill, width = 0)
            draw_red.line(shape_man_vertical, fill=fill, width = 0)

            draw_Himage = run_demo_coordinates(draw_Himage)
        else:

            mesh = get_mesh_info(interface)
            burners = add_bm_coordinates(mesh)
            #log burners movements
            for burner in burners:
                burners_log.write(burner)
            #do we need to refresh the screen ?
            if not equal_bm_coordinates(burners, old_coords):
                old_coords = burners
                (draw_Himage, draw_red) = show_mesh_info(burners, draw_Himage, draw_red)
            else:
                logging.debug("points are not really moving")

        if args.screen:
            Himage.show()
        else:
            epd.display(epd.getbuffer(Himage),epd.getbuffer(red))

        logging.debug("sleeping")
        time.sleep(c.sleep_seconds)

    if not args.debug:
        interface.close()

if __name__ == "__main__":

    parser = argparse.ArgumentParser(
                    prog='Display BRC Map',
                    description='Your meshtastic friends on a map',
                    epilog='Do not get too lost out there')
    parser.add_argument('-d', '--debug', action='store_true')
    parser.add_argument('-s', '--screen', action='store_true', help='display it in a screen rather than eink')

    args = parser.parse_args()


    main(args)
