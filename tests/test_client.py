from __future__ import annotations

import httpx
import pytest
import respx

from massive_access import MassiveAPIError, MassiveAuthError, MassiveClient

STATUS_URL = "https://api.massive.com/v1/marketstatus/now"
OK_BODY = {"market": "closed", "serverTime": "2020-11-10T00:00:00-05:00"}
ERROR_BODY = {"status": "ERROR", "request_id": "req-123", "error": "Unknown API Key"}


def make_client(**kwargs) -> MassiveClient:
    kwargs.setdefault("api_key", "test-key")
    kwargs.setdefault("sleep_fn", lambda *_: None)
    return MassiveClient(**kwargs)


@respx.mock
def test_sends_bearer_auth_header():
    route = respx.get(STATUS_URL).mock(return_value=httpx.Response(200, json=OK_BODY))
    make_client().get_json("/v1/marketstatus/now")
    assert route.called
    assert route.calls[0].request.headers["Authorization"] == "Bearer test-key"


@respx.mock
def test_retries_on_429_honoring_retry_after():
    route = respx.get(STATUS_URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "5"}),
            httpx.Response(200, json=OK_BODY),
        ]
    )
    waits: list[float] = []
    client = make_client(sleep_fn=waits.append)
    assert client.get_json("/v1/marketstatus/now") == OK_BODY
    assert len(route.calls) == 2
    assert waits == [5.0]


@respx.mock
def test_retries_transient_5xx_then_succeeds():
    route = respx.get(STATUS_URL).mock(
        side_effect=[
            httpx.Response(500, json=ERROR_BODY),
            httpx.Response(503, json=ERROR_BODY),
            httpx.Response(200, json=OK_BODY),
        ]
    )
    assert make_client().get_json("/v1/marketstatus/now") == OK_BODY
    assert len(route.calls) == 3


@respx.mock
def test_transport_error_is_retried():
    route = respx.get(STATUS_URL).mock(
        side_effect=[httpx.ConnectTimeout("boom"), httpx.Response(200, json=OK_BODY)]
    )
    assert make_client().get_json("/v1/marketstatus/now") == OK_BODY
    assert len(route.calls) == 2


@respx.mock
def test_retries_exhausted_raises():
    route = respx.get(STATUS_URL).mock(
        side_effect=[httpx.Response(503, json=ERROR_BODY)] * 3
    )
    with pytest.raises(MassiveAPIError) as exc:
        make_client(max_retries=2).get_json("/v1/marketstatus/now")
    assert exc.value.status == 503
    assert len(route.calls) == 3  # initial + 2 retries


@respx.mock
def test_401_raises_auth_error_with_request_id_and_signup_hint():
    respx.get(STATUS_URL).mock(return_value=httpx.Response(401, json=ERROR_BODY))
    with pytest.raises(MassiveAuthError) as exc:
        make_client().get_json("/v1/marketstatus/now")
    assert exc.value.status == 401
    assert exc.value.request_id == "req-123"
    assert "Unknown API Key" in str(exc.value)
    assert "massive.com" in str(exc.value)


@respx.mock
def test_400_is_not_retried():
    route = respx.get(STATUS_URL).mock(return_value=httpx.Response(400, json=ERROR_BODY))
    with pytest.raises(MassiveAPIError):
        make_client().get_json("/v1/marketstatus/now")
    assert len(route.calls) == 1


@respx.mock
def test_pagination_follows_next_url(fixture):
    page1 = fixture("aggregates_page1.json")
    page2 = fixture("aggregates_page2.json")
    route_aggs = respx.get(
        "https://api.massive.com/v2/aggs/ticker/AAPL/range/1/day/2020-01-01/2020-01-10"
    ).mock(return_value=httpx.Response(200, json=page1))
    route_next = respx.get(page1["next_url"]).mock(
        return_value=httpx.Response(200, json=page2)
    )

    pages = list(
        make_client().iter_pages(
            "/v2/aggs/ticker/AAPL/range/1/day/2020-01-01/2020-01-10",
            params={"adjusted": True, "sort": "asc"},
        )
    )

    assert pages == [page1, page2]
    assert route_aggs.called
    assert route_next.called
    # params attach to page 1; the cursor URL is fetched as-is on page 2
    assert route_aggs.calls[0].request.url.params["adjusted"] == "true"
    assert "cursor" in route_next.calls[0].request.url.params


@respx.mock
def test_off_host_next_url_refused():
    respx.get(STATUS_URL).mock(
        return_value=httpx.Response(200, json={"next_url": "https://evil.example/x"})
    )
    client = make_client()
    pages = client.iter_pages("/v1/marketstatus/now")
    assert next(pages) is not None
    with pytest.raises(MassiveAPIError, match="next_url"):
        next(pages)
