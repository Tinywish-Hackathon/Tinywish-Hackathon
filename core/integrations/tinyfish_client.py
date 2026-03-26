import os
from tinyfish import TinyFish
from config import Config

def get_tinyfish_client():
    return TinyFish(api_key=Config.TINYFISH_API_KEY)

