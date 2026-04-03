import os
from dataclasses import dataclass


@dataclass
class BotConfig:
    """Runtime configuration loaded from environment variables.

    Required:
        DISCORD_BOT_TOKEN  — Discord bot token from the developer portal.
        TAVERN_API_URL     — Base URL of the Tavern REST API (e.g. http://tavern:8000).
        TAVERN_WS_URL      — Base URL for WebSocket connections (e.g. ws://tavern:8000).

    Optional:
        STT_PROVIDER       — Speech-to-text provider identifier (V2).
        TTS_PROVIDER       — Text-to-speech provider identifier (V2).
        LOG_LEVEL          — Python logging level name (default: INFO).
    """

    discord_bot_token: str
    tavern_api_url: str
    tavern_ws_url: str
    stt_provider: str
    tts_provider: str
    log_level: str

    def __init__(self) -> None:
        _required = ("DISCORD_BOT_TOKEN", "TAVERN_API_URL", "TAVERN_WS_URL")
        missing = [v for v in _required if not os.environ.get(v)]
        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}"
            )

        self.discord_bot_token = os.environ["DISCORD_BOT_TOKEN"]
        self.tavern_api_url = os.environ["TAVERN_API_URL"].rstrip("/")
        self.tavern_ws_url = os.environ["TAVERN_WS_URL"].rstrip("/")
        self.stt_provider = os.environ.get("STT_PROVIDER", "")
        self.tts_provider = os.environ.get("TTS_PROVIDER", "")
        self.log_level = os.environ.get("LOG_LEVEL", "INFO")
