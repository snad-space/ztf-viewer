import httpx
import pytest

from ztf_viewer.date_with_frac import DateWithFrac, ProductsListingError, correct_date

LISTING = '<a href="079271/">079271/</a>\n<a href="079734/">079734/</a>\n<a href="080220/">080220/</a>\n'


@pytest.fixture(autouse=True)
def no_retry_delays(monkeypatch):
    monkeypatch.setattr("ztf_viewer.date_with_frac.LISTING_RETRY_DELAYS", (0.0, 0.0, 0.0))


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
    "failure, error",
    [
        (httpx.Response(404, text="Not Found"), httpx.HTTPStatusError),
        (httpx.Response(200, text="<html>nothing here</html>"), ProductsListingError),
    ],
    ids=["http-error", "empty-listing"],
)
async def test_failed_listing_is_not_cached(monkeypatch, failure, error):
    calls = _patch_client(monkeypatch, [failure, httpx.Response(200, text=LISTING)])

    with pytest.raises(error):
        await correct_date(_date())

    date = _date()
    await correct_date(date)
    assert date.frac_digits(6) == 79734
    assert len(calls) == 2


async def test_listing_is_retried_while_server_is_busy(monkeypatch):
    """The FITS server answers 503 when busy; a later attempt usually succeeds."""
    busy = httpx.Response(503, text="Service Unavailable")
    calls = _patch_client(monkeypatch, [busy, busy, httpx.Response(200, text=LISTING)])

    date = _date()
    await correct_date(date)

    assert date.frac_digits(6) == 79734
    assert len(calls) == 3


async def test_listing_gives_up_after_retries(monkeypatch):
    calls = _patch_client(monkeypatch, [httpx.Response(503, text="Service Unavailable") for _ in range(4)])

    with pytest.raises(httpx.HTTPStatusError):
        await correct_date(_date())

    assert len(calls) == 4


async def test_client_error_is_not_retried(monkeypatch):
    calls = _patch_client(monkeypatch, [httpx.Response(404, text="Not Found")])

    with pytest.raises(httpx.HTTPStatusError):
        await correct_date(_date())

    assert len(calls) == 1
