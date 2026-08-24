#!/usr/bin/env python3

import logging

logger = logging.getLogger(__name__)
from datetime import UTC, datetime, timedelta
from urllib.parse import urljoin

import requests

BASE_URL = "http://ztf-web-viewer-proxy/products/sci/"

ZTFSTARTDATE = datetime(2017, 9, 26, tzinfo=UTC)


def request(date):
    url = urljoin(BASE_URL, f"{date.year}/{date.month:02d}{date.day:02d}/")
    logger.info(f"Requesting {url}")
    response = requests.get(url)
    logger.info(f"Status code: {response.status_code}")


def main():
    logging.basicConfig(level=logging.INFO)
    date = ZTFSTARTDATE
    today = datetime.now(tz=UTC)
    day = timedelta(days=1)
    while date < today:
        request(date)
        date += day


if __name__ == "__main__":
    main()
