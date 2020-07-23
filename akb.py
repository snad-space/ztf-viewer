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

    def _object_url(self, oid):
        return urljoin(self._objects_api_url, f'{oid}/')

    def _tag_url(self, tag_name):
        return urljoin(self._tags_api_url, f'{tag_name}/')

    def _put_or_post(self, put_url, post_url, data):
        resp = self.session.put(put_url, json=data)
        if resp.status_code == 404:
            resp = self.session.post(post_url, json=data)
        try:
            resp.raise_for_status()
        except requests.HTTPError as e:
            logging.info(f'Post into {resp.url} returned {resp.status_code}: {resp.text}')
            raise RuntimeError from e

    def get_tags(self):
        return self._get(self._tags_api_url)

    def get_tag_names(self):
        tags = self.get_tags()
        names = [tag['name'] for tag in sorted(tags, key=lambda tag: tag['priority'])]
        return names

    def post_tag(self, name, priority=None):
        if priority is None:
            priority = max((tag['priority'] for tag in self.get_tags()), default=-1) + 1
        data = dict(name=name, priority=priority)
        self._put_or_post(self._tag_url(name), self._tags_api_url, data)

    def post_tags(self, tags):
        for tag in tags:
            self.post_tag(tag['name'], tag['priority'])

    def get_objects(self):
        return self._get(self._objects_api_url)

    def get_by_oid(self, oid):
        return self._get(self._object_url(oid))

    def post_object(self, oid, tags, description):
        data = dict(oid=oid, tags=tags, description=description)
        self._put_or_post(self._object_url(oid), self._objects_api_url, data)


akb = AKB()
