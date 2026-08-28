"""cli/vision/cache.py
Dipecah lebih lanjut dari cli/vision.py.
"""

try:

    import readline  # noqa: F401
except ImportError:
    readline = None


from .. import _state as state



def _vision_cache_get(key):
    val = state._VISION_IMAGE_CACHE.get(key)
    if val is not None:
        state._VISION_IMAGE_CACHE.move_to_end(key)
    return val


def _vision_cache_put(key, val):
    state._VISION_IMAGE_CACHE[key] = val
    state._VISION_IMAGE_CACHE.move_to_end(key)
    while len(state._VISION_IMAGE_CACHE) > state._VISION_CACHE_MAX_ENTRIES:
        state._VISION_IMAGE_CACHE.popitem(last=False)
