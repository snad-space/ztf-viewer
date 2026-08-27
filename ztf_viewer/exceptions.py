from typing import Any


class NotFound(Exception):
    pass


class CatalogUnavailable(Exception):
    def __init__(self, *args, catalog: Any = None, prolongate: bool = True):
        # Duck-typed rather than an isinstance check against _BaseCatalogQuery: importing the
        # conesearch package constructs every query object, and some of those reach the network.
        query_name = getattr(catalog, "query_name", None)

        if query_name is None:
            super().__init__(*args)
            return

        super().__init__(f"Catalog {query_name} is unavailable: {args}")

        if prolongate:
            # Imported here because ztf_viewer.catalogs pulls this module back in.
            from ztf_viewer.catalogs.unavailable_catalogs import unavailable_catalogs

            unavailable_catalogs.add(query_name)


class UnAuthorized(Exception):
    pass
