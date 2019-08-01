from functools import lru_cache

import pandas as pd
import sqlalchemy

from util import db_coord_to_degrees


CACHE_SIZE = 1 << 14

POSTGRESQL_CONNECTION = sqlalchemy.create_engine('postgresql://ztf@/ztf').connect()

LC_QUERY_TEMPLATE = '''
    SELECT *
    FROM dr1_good_lc
    WHERE oid = {oid}
    ORDER BY mjd
'''
META_QUERY_TEMPLATE = '''
    SELECT *
    FROM dr1_meta
    INNER JOIN dr1_info USING(oid)
    WHERE oid = {oid}
'''


def normalize_oid(oid):
    try:
        oid = int(oid)
    except ValueError:
        return None
    if oid < 0:
        return None
    if len(str(oid)) != 15:
        return None
    return oid


@lru_cache(maxsize=CACHE_SIZE)
def get_light_curve(oid):
    oid = normalize_oid(oid)
    if oid is None:
        return None
    query = LC_QUERY_TEMPLATE.format(oid=oid)
    df = pd.read_sql_query(query, POSTGRESQL_CONNECTION)
    if df.empty:
        return None
    df['mjd_58000'] = df['mjd'] - 58000
    return df


@lru_cache(maxsize=CACHE_SIZE)
def get_meta(oid):
    oid = normalize_oid(oid)
    if oid is None:
        return None
    query = META_QUERY_TEMPLATE.format(oid=oid)
    result = POSTGRESQL_CONNECTION.execute(query)
    row = result.first()
    if row is None:
        return None
    d = dict(zip(result.keys(), row))
    ra, dec = db_coord_to_degrees(d['coord'])
    d['coord'] = f'{ra}, {dec}'
    return d
