import math, re
import config as c
import geopy
from geopy.distance import geodesic as GD
import math, numpy as np
logging = c.logging


def distance_ft(a, b):
    return GD(a, b).ft


#get angle
def get_bearing_ang(lat1,lon1,lat2,lon2):
    dLon = lon2 - lon1;
    y = math.sin(dLon) * math.cos(lat2);
    x = math.cos(lat1)*math.sin(lat2) - math.sin(lat1)*math.cos(lat2)*math.cos(dLon);
    brng = np.rad2deg(math.atan2(y, x));
    if brng < 0:
        brng+= 360
    return brng

def get_bearing_rad(lat1, long1, lat2, long2):
    dLon = (long2 - long1)

    y = math.sin(dLon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dLon)

    brng = math.atan2(y, x)
    return brng

#angle between 2 points, which is used for the coords -> hour:mins calculation
def calculate_initial_compass_bearing(lat_from, long_from, lat_to, long_to):

#    if (type(start) != tuple) or (type(end) != tuple):
#        raise TypeError("Only tuples are supported as arguments")
    start = (lat_from, long_from)
    end = (lat_to, long_to)

    lat1 = math.radians(start[0])
    lat2 = math.radians(end[0])

    diffLong = math.radians(end[1] - start[1])

    x = math.sin(diffLong) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - (math.sin(lat1)
                                           * math.cos(lat2) * math.cos(diffLong))

    initial_bearing = math.atan2(x, y)

    # Now we have the initial bearing but math.atan2 return values
    # from -180° to + 180° which is not what we want for a compass bearing
    # The solution is to normalize the initial bearing as shown below
    initial_bearing = math.degrees(initial_bearing)
    compass_bearing = (initial_bearing + 360) % 360

    return compass_bearing

#lat/long -> hours:minutes + street OR distance
#TODO : minutes has a zero when <10
#TODO : show open playa / center of the city
#TODO : show camp name ? using
def gps_to_burning_man(lat, long, city_angle=45):

    #put known camp as name -> hour, distance from man
    #TODO move this to config / their own file
    #TODO the man is a special case, if distance < 100 ft you are at the man
    known_camps = {'Temple': ['12:00', 2500], 'The Man': ['12:00', 0]}
    camp_radius = 50 #feet if you are in that distance from camp, show camp name

    RAD_TO_HOUR = (6.0/3.14159);

    distance = GD((c.MAN_LAT, c.MAN_LONG), (lat, long)).feet

    angle_deg = calculate_initial_compass_bearing(c.MAN_LAT, c.MAN_LONG, lat, long)
    angle = angle_deg * (3.1415/180)

    bearing_to_man = angle * RAD_TO_HOUR
    bearing_to_man += 12.0 - c.BRC_NOON;
    if (bearing_to_man > 12.0):
        bearing_to_man -= 12.0;

    clock_hour = int(bearing_to_man)
    clock_minutes = int((bearing_to_man - int(bearing_to_man))*60.0)
    if(clock_hour == 0):
        clock_hour = 12

    # Convert distance to street name
    remaining_distance = distance - c.distance_man_esplanade

    for i, street_distance in enumerate(c.DISTANCE_STREETS):
        if remaining_distance < street_distance:
            street_name = c.STREET_NAMES[i]
            break
        remaining_distance -= street_distance
    else:
        # If we've exhausted all the street distances, we're beyond the last street.
        # Represent this as a distance from the Man in feet.
        street_name = '{:.0f}ft'.format(distance)

    #make them strings
    if clock_hour < 10:
        str_clock_hour = "0" + str(clock_hour)
    else:
        str_clock_hour = str(clock_hour)

    if clock_minutes < 10:
        str_clock_minutes = "0" + str(clock_minutes)
    else:
        str_clock_minutes = str(clock_minutes)


    return (str_clock_hour + ":" + str_clock_minutes + " + " + street_name)

def gps_to_image_coordinates(coord, rotation_angle=-45):
    man_position_screen = c.man_svg  # coordinates of the man in pixels
    left_position = c.left_limit
    right_position = c.right_limit
    top_position = c.twelve_limit
    bottom_position = c.bottom_limit

    # Convert GPS to normalized coordinates
    latitude = coord[0]
    longitude = coord[1]
    point_name = coord[2]

    x_norm = (longitude - c.lon_min) / (c.lon_max - c.lon_min)
    y_norm = (c.lat_max - latitude) / (c.lat_max - c.lat_min)

    # Convert normalized coordinates to pixel coordinates
    x = left_position + x_norm * (right_position - left_position)
    y = top_position + y_norm * (bottom_position - top_position)  # use height for y-coordinate

    # Calculate distance from man
    dx = x - man_position_screen[0]
    dy = y - man_position_screen[1]
    print ('dx dy', point_name, dx, dy)

    # Rotate coordinates
    rotation_angle = math.radians(rotation_angle)  # Convert to radians
    dx_rot = dx * math.cos(rotation_angle) - dy * math.sin(rotation_angle)
    dy_rot = dx * math.sin(rotation_angle) + dy * math.cos(rotation_angle)

    # Translate back to original position
    x_rot = man_position_screen[0] + dx_rot
    y_rot = man_position_screen[1] + dy_rot

    # Clamp to screen size and return as a tuple of integers
    x_clamped = max(0, min(right_position, int(x_rot)))  # clamping to the limit of map position in pixels
    y_clamped = max(0, min(bottom_position, int(y_rot)))

    return (x_clamped, y_clamped)



# bm coordinates ['9:30', 'a']-> lat/lon
def burning_man_to_gps(coordinates, shift_deg=0):
    # Parse input coordinates
    clock_time, street_name = coordinates
    clock_time = [int(i) for i in clock_time.split(':')]

    # Convert clock time to angle in degrees. Adjusting for the layout of Burning Man.
    #angle_deg = (-(clock_time[0]*60 + clock_time[1]) + 180 + shift_deg) % 360
    #angle_rad = math.radians(angle_deg)

    # Convert clock time to angle in degrees
    # Angle increases in clockwise direction, so subtract from 180
    # Normalize to range -180 to 180
    angle_deg = ((clock_time[0]*60 + clock_time[1]) + shift_deg)
    if angle_deg > 180:
        angle_deg -= 180
    angle_rad = math.radians(angle_deg)

    # Determine distance from Man in feet
    if isinstance(street_name, int):
        distance_feet = int(street_name)
    elif street_name.isdigit():
        distance_feet = int(street_name)
    else:
        distance_feet = c.distance_man_esplanade + sum(c.DISTANCE_STREETS[:c.STREET_NAMES.index(street_name)])

    # Convert distance from feet to degrees
    distance_deg = distance_feet / c.FEET_PER_DEGREE

    # Calculate GPS coordinates
    lat = c.MAN_LAT + distance_deg * math.cos(angle_rad)
    long = c.MAN_LONG + distance_deg * math.sin(angle_rad)

    return lat, long
