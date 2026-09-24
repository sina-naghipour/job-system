import logging
import os


def configure_logging(component: str) -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format=f"%(asctime)s [{component}] %(levelname)s %(message)s",
    )