import time
import functools
from utils.logger import get_logger

logger = get_logger("retry")

def retry(max_attempts=3, delay=1.0):
    """Decorator that retries a function on exception."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    logger.warning(f"{func.__name__} attempt {attempt}/{max_attempts} failed: {e}")
                    if attempt < max_attempts:
                        time.sleep(delay)
            logger.error(f"{func.__name__} failed after {max_attempts} attempts")
            raise last_error
        return wrapper
    return decorator
