#!/usr/bin/env python3
"""Writes data/world.json, the outlines behind the map on the talks page.

    python3 tools/world_map.py COUNTRIES.geojson PROVINCES.geojson

COUNTRIES is Natural Earth's ne_50m_admin_0_countries.geojson and PROVINCES its
ne_10m_admin_1_states_provinces.geojson (public domain, naturalearthdata.com;
the 5.1.2 release is what data/world.json was made from). The build reads only
data/world.json, so run this again only to change the outlines themselves.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from build import MAP_HEIGHT, MAP_SOUTH, MAP_WIDTH, WORLD, project  # noqa: E402

# Talks are in Europe and the Middle East, so outlines there are kept fine for
# the zoomed-in map; everywhere else they are drawn coarse.
DETAIL_BOX = (-12, 20, 62, 62)
FINE, COARSE, PROVINCE = 0.08, 0.6, 0.05
MIN_AREA_FINE, MIN_AREA_COARSE = 0.02, 2.0


def simplify(points, tolerance):
    if len(points) < 4:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = points[a], points[b]
        dx, dy = bx - ax, by - ay
        norm = (dx * dx + dy * dy) ** 0.5
        worst, index = 0, None
        for i in range(a + 1, b):
            px, py = points[i]
            d = abs(dy * (px - ax) - dx * (py - ay)) / norm if norm else ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
            if d > worst:
                worst, index = d, i
        if index is not None and worst > tolerance:
            keep[index] = True
            stack += [(a, index), (index, b)]
    return [p for p, k in zip(points, keep) if k]


def area(points):
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1]))) / 2


def in_detail_box(ring):
    west, south, east, north = DETAIL_BOX
    return any(west <= lon <= east and south <= lat <= north for lon, lat in ring)


def polygons(geometry):
    if geometry['type'] == 'Polygon':
        return [geometry['coordinates']]
    return geometry['coordinates']


def path(geometry, tolerance=None):
    out = []
    for polygon in polygons(geometry):
        for ring in polygon:
            ring = [(lon, max(lat, MAP_SOUTH)) for lon, lat in ring]
            fine = tolerance is not None or in_detail_box(ring)
            points = [project(lon, lat) for lon, lat in ring[:-1]]
            points = simplify(points + points[:1], tolerance or (FINE if fine else COARSE))[:-1]
            if len(points) < 3 or area(points) < (MIN_AREA_FINE if fine else MIN_AREA_COARSE):
                continue
            q = [(round(x * 10), round(y * 10)) for x, y in points]
            steps = ['M{},{}'.format(*q[0])]
            for (x0, y0), (x1, y1) in zip(q, q[1:]):
                if (x1, y1) != (x0, y0):
                    steps.append('l{},{}'.format(x1 - x0, y1 - y0))
            out.append(''.join(steps) + 'z')
    return ''.join(out)


def country_code(props):
    for key in ('ISO_A2_EH', 'ISO_A2', 'ADM0_A3'):
        if props.get(key) and props[key] != '-99':
            return props[key]


def inside(point, ring):
    x, y = point
    hit = False
    for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            hit = not hit
    return hit


# Natural Earth draws de facto borders. This map draws Crimea inside Ukraine,
# its internationally recognised border and Türkiye's position; Kosovo, which
# Türkiye recognises, stays a country of its own.
TRANSFERS = [((34.10, 44.95), 'RUS', 'UKR')]


def transfer(features, point, source, target):
    """Moves the polygon of `source` holding `point` into `target`, dissolving the border they share."""
    def multi(code):
        g = features[code]['geometry']
        if g['type'] == 'Polygon':
            g['type'], g['coordinates'] = 'MultiPolygon', [g['coordinates']]
        return g['coordinates']

    donor = multi(source)
    moved = [p for p in donor if inside(point, p[0])]
    if len(moved) != 1 or len(moved[0]) != 1:
        sys.exit('{} has no single hole-free polygon at {}'.format(source, point))
    piece = moved[0][0][:-1]
    shared = {tuple(v) for v in piece}
    for polygon in multi(target):
        ring = polygon[0][:-1]
        run = [i for i, v in enumerate(ring) if tuple(v) in shared]
        if not run:
            continue
        if run != list(range(run[0], run[-1] + 1)) or len(run) < 2:
            sys.exit('{} and {} share a border in more than one stretch at {}'.format(source, target, point))
        start, end = ring[run[0]], ring[run[-1]]
        j = [tuple(v) for v in piece].index(tuple(start))
        piece = piece[j:] + piece[:j]
        if tuple(piece[-(len(run) - 1)]) != tuple(end):
            sys.exit('{} and {} are wound in opposite directions at {}'.format(source, target, point))
        merged = ring[:run[0] + 1] + piece[1:len(piece) - len(run) + 1] + ring[run[-1]:]
        polygon[0] = merged + merged[:1]
        donor.remove(moved[0])
        return
    sys.exit('{} shares no border with {} at {}'.format(target, source, point))


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    with open(sys.argv[1], encoding='utf-8') as f:
        countries = json.load(f)['features']
    by_code = {f['properties']['ADM0_A3']: f for f in countries}
    for point, source, target in TRANSFERS:
        transfer(by_code, point, source, target)
    with open(sys.argv[2], encoding='utf-8') as f:
        provinces = [p for p in json.load(f)['features'] if p['properties'].get('adm0_a3') == 'TUR']

    world = {'note': 'Generated by tools/world_map.py from Natural Earth. Coordinates are tenths of a map unit.',
             'width': MAP_WIDTH, 'height': round(MAP_HEIGHT, 1), 'countries': {}, 'provinces': {}}
    for feature in sorted(countries, key=lambda f: country_code(f['properties'])):
        props = feature['properties']
        if props['ADM0_A3'] == 'ATA':
            continue
        d = path(feature['geometry'])
        if d:
            code = country_code(props)
            world['countries'][code] = world['countries'].get(code, '') + d
    for feature in sorted(provinces, key=lambda f: f['properties']['iso_3166_2']):
        props = feature['properties']
        world['provinces'][props['iso_3166_2']] = {'name': props['name_tr'], 'd': path(feature['geometry'], PROVINCE)}

    os.makedirs(os.path.dirname(WORLD), exist_ok=True)
    with open(WORLD, 'w', encoding='utf-8') as f:
        json.dump(world, f, ensure_ascii=False, indent=0, separators=(',', ':'))
        f.write('\n')
    print('wrote {}: {} countries, {} provinces, {} bytes'.format(
        os.path.relpath(WORLD), len(world['countries']), len(world['provinces']), os.path.getsize(WORLD)))


if __name__ == '__main__':
    main()
