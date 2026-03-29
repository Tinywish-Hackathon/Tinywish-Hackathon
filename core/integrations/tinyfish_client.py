import os

from tinyfish import TinyFish
from utils.logger import get_logger


logger = get_logger("tinyfish_client")


def get_tinyfish_client():
    api_key = os.getenv("TINYFISH_API_KEY")

    if not api_key:
        raise ValueError("Missing TINYFISH_API_KEY")

    client = TinyFish(api_key=api_key)
    logger.debug(f"[TINYFISH] Client methods: {dir(client)}")
    return client


def discover_tinyfish_run_method(client, active_logger=None, log_prefix="[TINYFISH]", warn_on_missing=True):
    resolved_logger = active_logger or logger

    for method_name in ["run", "agent_run", "run_agent", "create_run", "execute"]:
        if hasattr(client, method_name):
            resolved_logger.info(f"{log_prefix} Found TinyFish method: {method_name}")
            return getattr(client, method_name)

    agent = getattr(client, "agent", None)
    if agent is not None and hasattr(agent, "run"):
        resolved_logger.info(f"{log_prefix} Found TinyFish method: agent.run")
        return getattr(agent, "run")

    if warn_on_missing:
        resolved_logger.warning(f"{log_prefix} No valid TinyFish run method found, using fallback")
    else:
        resolved_logger.debug(f"{log_prefix} No valid TinyFish run method found")
    return None
