import os

from tinyfish import TinyFish


def get_tinyfish_client():
    api_key = os.getenv("TINYFISH_API_KEY")

    if not api_key:
        raise ValueError("Missing TINYFISH_API_KEY")

    return TinyFish(api_key=api_key)
