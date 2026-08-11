import logging
from pathlib import Path


def make_logger(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("battle_narrator")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    formatter = logging.Formatter(
        "%(asctime)s.%(msecs)03d %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(file_handler)
    logger.addHandler(console)
    return logger
