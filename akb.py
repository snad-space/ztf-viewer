import logging
from urllib.parse import urljoin

import requests

from util import NotFound


class AKB:
    _base_api_url = 'https://akb.ztf.snad.space/'
    _tags_api_url = urljoin(_base_api_url, '/tags/')
    _objects_api_url = urljoin(_base_api_url, '/objects/')

    def __init__(self):
        self.session = requests.Session()

    def _get(self, url):
        resp = self.session.get(url)
        if resp.status_code != 200:
            message = f'{resp.url} returned {resp.status_code}: {resp.text}'
            logging.info(message)
            raise NotFound(message)
        return resp.json()

    def get_tags(self):
        tags = self._get(self._tags_api_url)
        names = [tag['name'] for tag in sorted(tags, key=lambda tag: tag['id'])]
        return names

    def get_objects(self):
        return self._get(self._objects_api_url)

    def get_by_oid(self, oid):
        url = urljoin(self._objects_api_url, f'{oid}/')
        return self._get(url)

    def post_object(self, oid, tags, description):
        resp = self.session.post(self._objects_api_url,
                                 json=dict(oid=oid, tags=tags, description=description))
        try:
            resp.raise_for_status()
        except requests.HTTPError as e:
            logging.info(f'Post into {resp.url} returned {resp.status_code}: {resp.text}')
            raise RuntimeError from e


akb = AKB()
