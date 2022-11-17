def add_id_to_obs(data):
    """Add top-level key to observations as "oid", it mutates input"""
    for identifier, lc in data.items():
        for obs in lc:
            obs["oid"] = identifier
    return data
