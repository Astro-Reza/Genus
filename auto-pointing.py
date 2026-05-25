import math

def calculate_look_angles(sat_lon, site_lat, site_lon):
    """
    Calculates Azimuth and Elevation for a Geostationary Satellite.
    
    Args:
        sat_lon (float): Satellite Longitude (degrees). East is positive, West is negative.
        site_lat (float): Earth Station Latitude (degrees). North positive.
        site_lon (float): Earth Station Longitude (degrees). East positive.
        
    Returns:
        dict: {'azimuth': float, 'elevation': float}
    """
    # Constants
    EARTH_RADIUS_KM = 6378.14
    SAT_HEIGHT_KM = 35786.0 
    SAT_RADIUS_KM = EARTH_RADIUS_KM + SAT_HEIGHT_KM

    # Convert to radians
    sat_lon_rad = math.radians(sat_lon)
    site_lat_rad = math.radians(site_lat)
    site_lon_rad = math.radians(site_lon)

    # Difference in longitude
    delta_lon = sat_lon_rad - site_lon_rad

    # 1. Calculate Elevation
    # The central angle between the earth station and the satellite
    # formula: cos(gamma) = cos(lat) * cos(delta_lon)
    cos_gamma = math.cos(site_lat_rad) * math.cos(delta_lon)
    
    # Calculate Elevation using the formula for Geostationary orbit
    # v = rs / re (Ratio of satellite radius to earth radius)
    v = SAT_RADIUS_KM / EARTH_RADIUS_KM
    
    # el = arctan( (cos(gamma) - 1/v) / sin(gamma) )
    # We use sin(gamma) = sqrt(1 - cos^2(gamma))
    sin_gamma = math.sqrt(1 - cos_gamma**2)
    
    if sin_gamma == 0:
        return {'azimuth': 0, 'elevation': 90} # Directly overhead

    elevation_rad = math.atan((cos_gamma - (1/v)) / sin_gamma)
    elevation_deg = math.degrees(elevation_rad)

    # 2. Calculate Azimuth
    # Simple formula: tan(alpha) = tan(delta_lon) / sin(lat)
    # We need to handle quadrants correctly for the final Azimuth (0-360 deg from True North)
    
    az_rad = math.atan2(math.tan(delta_lon), math.sin(site_lat_rad))
    az_deg = math.degrees(az_rad)

    # Adjust Azimuth based on hemisphere to get 0-360 degrees relative to True North
    # The raw atan2 result needs to be projected from the South pole in N hemisphere
    azimuth_deg = 180 + az_deg
    
    return {
        'azimuth': round(azimuth_deg, 2),
        'elevation': round(elevation_deg, 2)
    }

# --- Example Usage ---
my_lat = 40.7128
my_lon = -74.0060
target_sat_lon = -87.0

angles = calculate_look_angles(target_sat_lon, my_lat, my_lon)

print(f"--- Look Angles ---")
print(f"Azimuth:   {angles['azimuth']}° (True North)")
print(f"Elevation: {angles['elevation']}°")