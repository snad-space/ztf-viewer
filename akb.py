import logging
from urllib.parse import urljoin

import cachetools
import flask
import requests

from util import NotFound, UnAuthorized


class AKB:
    _base_api_url = 'https://akb.ztf.snad.space/'
    _tags_api_url = urljoin(_base_api_url, '/tags/')
    _objects_api_url = urljoin(_base_api_url, '/objects/')
    _whoami_api_url = urljoin(_base_api_url, '/whoami/')

    def __init__(self):
        self.session = requests.Session()

    def _get(self, url, token=None):
        resp = self.session.get(url, headers=self._token_header(token))
        if resp.status_code == 200:
            return resp.json()
        message = f'{resp.url} returned {resp.status_code}: {resp.text}'
        logging.info(message)
        if resp.status_code == 401:
            return UnAuthorized(message)
        if resp.status_code == 404:
            raise NotFound(message)
        resp.raise_for_status()

    def _token_from_cookies(self):
        try:
            return flask.request.cookies['akb_token']
        except KeyError:
            raise UnAuthorized

    def _token_header(self, token=None):
        if token is None:
            token = self._token_from_cookies()
        return {'Authorization': f'Token {token}'}

    def _object_url(self, oid):
        return urljoin(self._objects_api_url, f'{oid}/')

    def _tag_url(self, tag_name):
        return urljoin(self._tags_api_url, f'{tag_name}/')

    def _put_or_post(self, put_url, post_url, data, token=None):
        headers = self._token_header(token)
        resp = self.session.put(put_url, json=data, headers=headers)
        if resp.status_code == 404:
            resp = self.session.post(post_url, json=data, headers=headers)
        try:
            resp.raise_for_status()
        except requests.HTTPError as e:
            logging.info(f'Post into {resp.url} returned {resp.status_code}: {resp.text}')
            raise RuntimeError from e

    def get_tags(self, token=None):
        return self._get(self._tags_api_url, token=token)

    def get_tag_names(self, token=None):
        tags = self.get_tags(token=token)
        names = [tag['name'] for tag in sorted(tags, key=lambda tag: tag['priority'])]
        return names

    def post_tag(self, name, priority=None, description=None, token=None):
        if priority is None:
            priority = max((tag['priority'] for tag in self.get_tags()), default=-1) + 1
        data = dict(name=name, priority=priority)
        if description is not None:
            data['description'] = description
        self._put_or_post(self._tag_url(name), self._tags_api_url, data, token=token)

    def post_tags(self, tags, token=None):
        for tag in tags:
            self.post_tag(tag['name'], tag['priority'], tag.get('description'), token=token)

    def get_objects(self, token=None):
        return self._get(self._objects_api_url, token=token)

    def get_by_oid(self, oid, token=None):
        return self._get(self._object_url(oid), token=token)

    def post_object(self, oid, tags, description, token=None):
        data = dict(oid=oid, tags=tags, description=description)
        self._put_or_post(self._object_url(oid), self._objects_api_url, data, token=token)

    @cachetools.cached(cachetools.TTLCache(maxsize=1024, ttl=3600))
    def whoami(self, token):
        if not isinstance(token, str):
            raise ValueError(f'token must be a str, not {type(token)}')
        resp = self.session.get(self._whoami_api_url, headers=self._token_header(token))
        if resp.status_code == 401:
            raise UnAuthorized
        resp.raise_for_status()
        return resp.json()

    def username(self, token=None):
        if token is None:
            token = self._token_from_cookies()
        json = self.whoami(token=token)
        if json['first_name'] or json['last_name']:
            return f"{json['first_name']} {json['last_name']}"
        return json['username']

    @cachetools.cached(cachetools.TTLCache(maxsize=1024, ttl=3600))
    def _is_token_valid(self, token):
        try:
            self.whoami(token)
            return True
        except UnAuthorized:
            return False

    def is_token_valid(self, token=None):
        if token is None:
            token = self._token_from_cookies()
        return self._is_token_valid(token=token)


akb = AKB()
