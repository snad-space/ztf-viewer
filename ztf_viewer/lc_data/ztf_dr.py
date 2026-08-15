from ztf_viewer.catalogs import find_ztf_oid


async def ztf_dr_lc(oid, dr):
    lc = await find_ztf_oid.get_lc(oid, dr)
    meta = await find_ztf_oid.get_meta(oid, dr)
    for obs in lc:
        obs["oid"] = oid
        obs["fieldid"] = meta["fieldid"]
        obs["rcid"] = meta["rcid"]
        obs["filter"] = meta["filter"]
    return lc
