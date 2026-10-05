#  -*- coding: utf-8 -*-
#
#  MIT License
#
#  Copyright (c) 2024-2026 Christian Kvasny chris(at)ckvsoft.at
#

"""
Solar position -- elevation and azimuth of the sun for a location at
an instant (NOAA low-precision algorithm). Pure math, no network.

Accuracy ~0.1 deg, far beyond what horizon shading needs. Used to
evaluate per-panel horizon profiles (trees, hills) across seasons:
the profile is geometry, the sun's path varies -- their intersection
produces the seasonal shading automatically.

Azimuth convention: 0 = north, 90 = east, 180 = south, 270 = west.
"""

import math


def sun_position(lat, lon, when_utc):
    """
    Return (elevation_deg, azimuth_deg) for latitude/longitude in
    degrees at the given timezone-aware datetime.
    """
    jd = when_utc.timestamp() / 86400.0 + 2440587.5
    n = jd - 2451545.0

    mean_lon = (280.460 + 0.9856474 * n) % 360.0
    mean_anom = math.radians((357.528 + 0.9856003 * n) % 360.0)
    ecl_lon = math.radians(
        mean_lon + 1.915 * math.sin(mean_anom)
        + 0.020 * math.sin(2.0 * mean_anom)
    )
    obliq = math.radians(23.439 - 0.0000004 * n)

    ra = math.atan2(math.cos(obliq) * math.sin(ecl_lon), math.cos(ecl_lon))
    dec = math.asin(math.sin(obliq) * math.sin(ecl_lon))

    gmst = (18.697374558 + 24.06570982441908 * n) % 24.0
    lst = math.radians((gmst * 15.0 + lon) % 360.0)
    hour_angle = lst - ra
    lat_rad = math.radians(lat)

    sin_el = (
        math.sin(lat_rad) * math.sin(dec)
        + math.cos(lat_rad) * math.cos(dec) * math.cos(hour_angle)
    )
    sin_el = max(-1.0, min(1.0, sin_el))
    elevation = math.degrees(math.asin(sin_el))

    az = math.degrees(math.atan2(
        -math.cos(dec) * math.sin(hour_angle),
        math.sin(dec) * math.cos(lat_rad)
        - math.cos(dec) * math.sin(lat_rad) * math.cos(hour_angle),
    ))
    azimuth = (az + 360.0) % 360.0
    return elevation, azimuth


def horizon_elevation(horizon, azimuth):
    """
    Obstruction elevation (deg) at the given azimuth for a horizon
    profile [[azimuth, elevation], ...]. Linear interpolation between
    waypoints, wraps at 360. Empty/invalid profile -> 0.0 (open sky).
    """
    try:
        pts = sorted((float(az) % 360.0, float(el)) for az, el in horizon)
    except (TypeError, ValueError):
        return 0.0
    if not pts:
        return 0.0

    az = float(azimuth) % 360.0
    # Extend with the wrap-around segment (last point -> first + 360).
    ext = pts + [(pts[0][0] + 360.0, pts[0][1])]
    for (az1, el1), (az2, el2) in zip(ext, ext[1:]):
        if az1 <= az <= az2:
            if az2 <= az1:
                return el1
            t = (az - az1) / (az2 - az1)
            return el1 + t * (el2 - el1)
    return pts[-1][1]
