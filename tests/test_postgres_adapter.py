# tests/test_postgres_adapter.py
import pytest

from app.services.postgresql_adapter import PostgresAdapter  # ← adjust if needed

pytestmark = pytest.mark.asyncio

async def test_create_user_and_fetch_user():
    ad = PostgresAdapter()
    u = await ad.create_user("Alice", "alice@example.com")
    got = await ad.fetch_user(u["id"])
    assert got["email"] == "alice@example.com"

async def test_insert_site_and_fetch_variants():
    ad = PostgresAdapter()
    u = await ad.create_user("Bob", "bob@example.com")
    site = await ad.insert_historical_site(u["id"], "HS1", "desc", 41.1, -112.2, None)

    # fetch_one_site
    s = await ad.fetch_one_site(site["id"])
    assert s["title"] == "HS1"

    # fetch_site_location
    loc = await ad.fetch_site_location(site["id"])
    assert pytest.approx(float(loc["latitude"]), rel=1e-6) == 41.1
    assert pytest.approx(float(loc["longitude"]), rel=1e-6) == -112.2

async def test_posts_and_comments_flow():
    ad = PostgresAdapter()
    u = await ad.create_user("Carol", "carol@example.com")
    s = await ad.insert_historical_site(u["id"], "HS2", "d", 40.0, -111.0, None)

    await ad.insert_post(u["id"], "T1", "C1", s["id"], "img1")
    posts = await ad.fetch_posts_by_site(s["id"])
    assert len(posts) == 1
    pid = posts[0]["id"]

    p = await ad.fetch_post(pid)
    assert p["title"] == "T1"

    u2 = await ad.create_user("Dan", "dan@example.com")
    await ad.insert_comment(u2["id"], pid, "ct", "cc", "ci")
    comments = await ad.fetch_comments_by_post(pid)
    assert len(comments) == 1
    assert comments[0]["title"] == "ct"

    await ad.update_post_image(pid, "img2")
    p2 = await ad.fetch_post(pid)
    assert p2["image"] == "img2"

async def test_fetch_sites_within_bounds_limit():
    ad = PostgresAdapter()
    u = await ad.create_user("Eve", "eve@example.com")
    # inside bounds
    await ad.insert_historical_site(u["id"], "Inside", "d", 40.0, -111.0, None)
    # outside bounds
    await ad.insert_historical_site(u["id"], "Outside", "d", 10.0, -10.0, None)

    res = await ad.fetch_sites_within_bounds(
        ne_lat=41.0, ne_lng=-110.0, sw_lat=39.0, sw_lng=-112.0
    )
    titles = {r["title"] for r in res}
    assert "Inside" in titles
    assert "Outside" not in titles
