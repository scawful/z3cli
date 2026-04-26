from services.inventory.cache import InventoryCache


def test_inventory_cache_returns_fresh_snapshot_and_tracks_generation() -> None:
    cache = InventoryCache(ttl_ms=5000)

    stored = cache.put("oracle-pro-5090", {"source": "oracle-pro-5090"})

    assert stored["generation"] == 1
    assert cache.get("oracle-pro-5090")["generation"] == 1


def test_inventory_cache_hides_stale_snapshot_unless_requested() -> None:
    cache = InventoryCache(ttl_ms=1)
    cache.put("route", {"source": "route"})
    cache._entries["route"].observed_monotonic_s -= 10

    assert cache.get("route") is None
    assert cache.get("route", allow_stale=True)["source"] == "route"
