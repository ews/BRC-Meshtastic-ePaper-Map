import numpy as np
import geopy
import geopy.distance  #move this away
from geopy.distance import geodesic as GD

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("debug.log"),
        logging.StreamHandler()
    ]
)

#screen dimension
WIDTH=480
HEIGHT=800

#check mesh and refresh every X seconds
sleep_seconds = 60

#golden spike
MAN_LAT = 40.786400
MAN_LONG = -119.203500


STREET_DISTANCE = 0.002  # Replace with actual distance between streets
FEET_PER_DEGREE = 364000  # Approx. feet per degree of latitude
STREET_NAMES = ['Esplanade'] + [chr(i) for i in range(ord('A'), ord('K')+1)]


#in feet bc fuck you imperial system
distance_man_esplanade = 2500
#distance_man_to_end_trashfence_ft = 8940
distance_man_to_end_trashfence_ft = 8479
#from esplanade to k street
DISTANCE_STREETS = [400,250,250,250,250,250,450,250,250,250,150,150]
BRC_NOON = 1.5

#position of the SVG within the screen
#
image_position = (6,400)

# position of the map in pixels on the screen
man_svg = (240, 516)

#distance bigger than this will trigger refresh
min_distance_refresh_ft = 50

#using this as a ratio of the image2gives problems, let's out radius manually
svg_city_esplanade_radius_pixel = 98
svg_city_radius_pixel = 230


#save locations and movement to file
log_file = 'burners.log'
burners_log = open(log_file, "a")

#derived values, don't change anything below this point
svg_city_man_to_trashfence_pixel = (distance_man_to_end_trashfence_ft*svg_city_esplanade_radius_pixel)/distance_man_esplanade


#limits of the city in the screen / dimensions on the city are all relative to the man position + radius
left_limit=man_svg[0]-svg_city_radius_pixel
right_limit=man_svg[0]+svg_city_radius_pixel
top_limit=man_svg[1]-svg_city_man_to_trashfence_pixel
twelve_limit=man_svg[1]-svg_city_radius_pixel   #12:00 + K
bottom_limit=man_svg[1]+svg_city_radius_pixel

#BRC landmarks to test the map
temple_svg = (man_svg[0], man_svg[1]-svg_city_esplanade_radius_pixel)
centercamp_svg = (man_svg[0], man_svg[1]+svg_city_esplanade_radius_pixel)




#using geopy
#TODO we need to take into account man to trash fence pentagon
#in the past that's  8175 ft
city_radius_ft = distance_man_esplanade + np.sum(DISTANCE_STREETS)
logging.debug('distances %s %s', distance_man_to_end_trashfence_ft, city_radius_ft)
center = geopy.Point(MAN_LAT, MAN_LONG)

top_trash_fence = geopy.distance.distance(feet=distance_man_to_end_trashfence_ft).destination(center, bearing=45)
twelve_city = geopy.distance.distance(feet=city_radius_ft).destination(center, bearing=45)
bottom_city  = geopy.distance.distance(feet=city_radius_ft).destination(center, bearing=225)

#where are the top and bottom of the city in the screen ?
top_trash_fence_screen = (800,0)
bottom_city_screen = (0,480)

# Calculate destination points at 0, 90, 180 and 270 degrees
north = geopy.distance.distance(feet=city_radius_ft).destination(center, bearing=0)
east = geopy.distance.distance(feet=city_radius_ft).destination(center, bearing=90)
south = geopy.distance.distance(feet=city_radius_ft).destination(center, bearing=180)
west = geopy.distance.distance(feet=city_radius_ft).destination(center, bearing=270)

# Extract max and min latitudes and longitudes
lat_max = north.latitude
lat_min = south.latitude
lon_max = east.longitude
lon_min = west.longitude

