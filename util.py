import math
import re


def dict_to_bullet(d):
    return '\n'.join(f'* **{k}**: {v}' for k, v in d.items())


def db_coord_to_degrees(coord):
    match = re.search(r'^\((\S+)\s*,\s*(\S+)\)$', coord)
    ra = math.degrees(float(match.group(1)))
    dec = math.degrees(float(match.group(2)))
    return ra, dec
