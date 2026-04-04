"""Entry point: python -m tavern.discord_bot"""

import logging
import os

from dotenv import load_dotenv

from .bot import TavernBot
from .config import BotConfig


def main() -> None:
    load_dotenv()

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    config = BotConfig()
    bot = TavernBot(config)
    bot.run(config.discord_bot_token, log_handler=None)


if __name__ == "__main__":
    main()
