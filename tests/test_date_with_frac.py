import httpx
import pytest

from ztf_viewer.date_with_frac import DateWithFrac, correct_date

LISTING = '<a href="079271/">079271/</a>\n<a href="079734/">079734/</a>\n<a href="080220/">080220/</a>\n'


def _patch_client(monkeypatch, responses):
    calls = []

    async def handler(request):
        calls.append(str(request.url))
        return responses.pop(0)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("ztf_viewer.date_with_frac.get_client", lambda: client)
    return calls


def _date():
    return DateWithFrac(year=2020, month=12, day=4, fraction=0.079924)


async def test_correct_date_snaps_to_preceding_exposure(monkeypatch):
    _patch_client(monkeypatch, [httpx.Response(200, text=LISTING)])
    date = _date()
    await correct_date(date)
    assert date.frac_digits(6) == 79734


@pytest.mark.parametrize(
    "failure",
    [httpx.Response(502, text="Bad Gateway"), httpx.Response(200, text="<html>nothing here</html>")],
    ids=["http-error", "empty-listing"],
)
async def test_failed_listing_is_not_cached(monkeypatch, failure):
    calls = _patch_client(monkeypatch, [failure, httpx.Response(200, text=LISTING)])

    with pytest.raises((httpx.HTTPStatusError, ValueError)):
        await correct_date(_date())

    date = _date()
    await correct_date(date)
    assert date.frac_digits(6) == 79734
    assert len(calls) == 2
