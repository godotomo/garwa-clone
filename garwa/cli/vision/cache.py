"""cli/vision/cache.py
Dipecah lebih lanjut dari cli/vision.py.
"""
import argparse
import base64
import copy
import difflib
import json
import mimetypes
import os
import re
import select
import shlex
import shutil
import sys
import time
import unicodedata
from collections import OrderedDict
from datetime import datetime
from urllib.parse import unquote, urlparse

try:

    import readline  # noqa: F401
except ImportError:
    readline = None

import requests

from ...tools import TOOLS
from .. import _state as state
from ..file_drop import _human_size



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
