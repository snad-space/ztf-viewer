from typing import Any


class NotFound(Exception):
    pass


class CatalogUnavailable(Exception):
    def __init__(self, *args, catalog: Any = None, prolongate: bool = True):
        # We wouldn't like to have a circular import, so we import it here
        from ztf_viewer.catalogs.conesearch import _BaseCatalogQuery
        from ztf_viewer.catalogs.unavailable_catalogs import unavailable_catalogs

        if not isinstance(catalog, _BaseCatalogQuery):
            super().__init__(*args)
            return

        query_name = catalog.query_name
        super().__init__(f"Catalog {query_name} is unavailable: {args}")

        if prolongate:
            unavailable_catalogs.add(query_name)


class UnAuthorized(Exception):
    pass
