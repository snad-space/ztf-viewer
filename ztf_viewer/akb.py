import logging

logger = logging.getLogger(__name__)
from urllib.parse import urljoin

import dash
import httpx

from ztf_viewer.cache import cache
from ztf_viewer.config import TIMEOUT_AKB
from ztf_viewer.exceptions import NotFound, UnAuthorized
from ztf_viewer.http import get_client


class AKB:
    _base_api_url = "https://akb.ztf.snad.space/"
    _tags_api_url = urljoin(_base_api_url, "/tags/")
    _objects_api_url = urljoin(_base_api_url, "/objects/")
    _whoami_api_url = urljoin(_base_api_url, "/whoami/")

    async def _get(self, url, token=None):
        client = get_client()
        response = await client.get(url, headers=self._token_header(token), timeout=TIMEOUT_AKB)
        if response.status_code == 200:
            return response.json()
        message = f"{response.url} returned {response.status_code}: {response.text}"
        logger.info(message)
        if response.status_code == 401:
            return UnAuthorized(message)
        if response.status_code == 404:
            raise NotFound(message)
        response.raise_for_status()

    async def _head(self, url, token=None):
        client = get_client()
        return await client.head(url, headers=self._token_header(token), timeout=TIMEOUT_AKB)

    def _token_from_cookies(self):
        try:
            return dash.ctx.cookies["akb_token"]
        except KeyError:
            raise UnAuthorized

    def _token_header(self, token=None):
        if token is None:
            token = self._token_from_cookies()
        return {"Authorization": f"Token {token}"}

    def _object_url(self, oid):
        return urljoin(self._objects_api_url, f"{oid}/")

    def _object_log_url(self, oid):
        return urljoin(self._objects_api_url, f"{oid}/log/")

    def _tag_url(self, tag_name):
        return urljoin(self._tags_api_url, f"{tag_name}/")

    async def _put_or_post(self, put_url, post_url, data, token=None):
        client = get_client()
        headers = self._token_header(token)
        resp = await client.put(put_url, json=data, headers=headers, timeout=TIMEOUT_AKB)
        if resp.status_code == 404:
            resp = await client.post(post_url, json=data, headers=headers, timeout=TIMEOUT_AKB)
        try:
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.info(f"Post into {resp.url} returned {resp.status_code}: {resp.text}")
            raise RuntimeError from e

    async def get_tags(self, token=None):
        return await self._get(self._tags_api_url, token=token)

    async def get_tag_names(self, token=None):
        tags = await self.get_tags(token=token)
        names = [tag["name"] for tag in sorted(tags, key=lambda tag: tag["priority"])]
        return names

    async def post_tag(self, name, priority=None, description=None, token=None):
        if priority is None:
            priority = max((tag["priority"] for tag in await self.get_tags()), default=-1) + 1
        data = {"name": name, "priority": priority}
        if description is not None:
            data["description"] = description
        await self._put_or_post(self._tag_url(name), self._tags_api_url, data, token=token)

    async def post_tags(self, tags, token=None):
        for tag in tags:
            await self.post_tag(tag["name"], tag["priority"], tag.get("description"), token=token)

    async def get_objects(self, token=None):
        return await self._get(self._objects_api_url, token=token)

    async def get_by_oid(self, oid, token=None):
        return await self._get(self._object_url(oid), token=token)

    async def oid_exists(self, oid, token=None):
        response = await self._head(self._object_url(oid), token=token)
        if response.status_code == 200:
            return True
        if response.status_code == 404:
            return False
        response.raise_for_status()
        raise RuntimeError("Unexpected error while HEAD request to AKB server")

    async def post_object(self, oid, tags, description, token=None):
        data = {"oid": oid, "tags": tags, "description": description}
        await self._put_or_post(self._object_url(oid), self._objects_api_url, data, token=token)

    async def get_object_log(self, oid, token=None):
        try:
            return await self._get(self._object_log_url(oid), token=token)
        except NotFound:
            return []

    @cache()
    async def whoami(self, token):
        if not isinstance(token, str):
            raise TypeError(f"token must be a str, not {type(token)}")
        client = get_client()
        resp = await client.get(self._whoami_api_url, headers=self._token_header(token), timeout=TIMEOUT_AKB)
        if resp.status_code == 401:
            raise UnAuthorized
        resp.raise_for_status()
        return resp.json()

    async def username(self, token=None):
        if token is None:
            token = self._token_from_cookies()
        json = await self.whoami(token=token)
        if json["first_name"] or json["last_name"]:
            return f"{json['first_name']} {json['last_name']}"
        return json["username"]

    @cache()
    async def _is_token_valid(self, token):
        try:
            await self.whoami(token)
            return True
        except UnAuthorized:
            return False

    async def is_token_valid(self, token=None):
        if token is None:
            try:
                token = self._token_from_cookies()
            except UnAuthorized:
                return False
        return await self._is_token_valid(token=token)


akb = AKB()
