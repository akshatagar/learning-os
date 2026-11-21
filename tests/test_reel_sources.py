"""The Supabase mailbox client against a mocked PostgREST, no network."""
import httpx

from reel_inbox.sources import SupabaseSource

ROWS = [{"id": "11111111-1111-1111-1111-111111111111",
         "url": "https://www.instagram.com/reel/A/", "note": "x",
         "created_at": "2026-11-15T10:00:00.123+00:00"}]


def _client(log):
    def handler(request: httpx.Request) -> httpx.Response:
        log.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=ROWS)
        return httpx.Response(204)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_pull_reads_the_oldest_rows_with_the_secret_key():
    log = []
    rows = SupabaseSource("https://p.supabase.co/", "sb_secret_abc", _client(log)).pull()

    assert [(r.id, r.url, r.note) for r in rows] == [
        (ROWS[0]["id"], "https://www.instagram.com/reel/A/", "x")]
    assert rows[0].captured_at.tzinfo is not None
    request = log[0]
    assert request.url.path == "/rest/v1/captures"
    assert request.url.params["order"] == "created_at.asc"
    assert request.headers["apikey"] == "sb_secret_abc"
    # A new-style key is not a JWT: sent as a Bearer token, Supabase drops it.
    assert "authorization" not in request.headers


def test_a_legacy_jwt_key_is_also_sent_as_a_bearer_token():
    log = []
    SupabaseSource("https://p.supabase.co", "eyJhbGciOi.x.y", _client(log)).pull()
    assert log[0].headers["apikey"] == "eyJhbGciOi.x.y"
    assert log[0].headers["authorization"] == "Bearer eyJhbGciOi.x.y"


def test_ack_deletes_exactly_the_pulled_ids():
    log = []
    SupabaseSource("https://p.supabase.co", "k", _client(log)).ack(["a", "b"])
    assert log[0].method == "DELETE"
    assert log[0].url.params["id"] == "in.(a,b)"


def test_ack_with_nothing_makes_no_request():
    log = []
    SupabaseSource("https://p.supabase.co", "k", _client(log)).ack([])
    assert log == []
