import math


def haversine_distance_m(
    coord1: tuple[float, float],
    coord2: tuple[float, float],
) -> float:
    """
    Odległość w metrach między dwoma punktami (lat, lon) w układzie WGS84.
    Prosty wzór haversine – wystarczający na prototyp.
    """
    lat1, lon1 = coord1
    lat2, lon2 = coord2

    earth_radius_m = 6_371_000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    a = min(1.0, max(0.0, a))
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return earth_radius_m * c
