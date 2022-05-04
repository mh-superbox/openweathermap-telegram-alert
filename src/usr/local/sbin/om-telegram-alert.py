#!/usr/bin/env python3
import json
import logging
import re
from dataclasses import dataclass
from dataclasses import field
from dataclasses import is_dataclass
from datetime import datetime
from pathlib import Path
from tempfile import gettempdir
from typing import Final
from typing import List
from typing import Tuple

import requests
import yaml

OM_ONECALL_URL: Final[str] = "https://api.openweathermap.org/data/2.5/onecall"
TELEGRAM_SEND_MSG_URL: Final[str] = "https://api.telegram.org/bot$TOKEN/sendMessage"

logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
logger = logging.getLogger("OpenWeatherMapTelegramAlert")


@dataclass
class ConfigBase:
    def update(self, new):
        for key, value in new.items():
            if hasattr(self, key):
                item = getattr(self, key)

                if is_dataclass(item):
                    item.update(value)
                else:
                    setattr(self, key, value)


@dataclass
class OpenWeaterMapConfig(ConfigBase):
    appid: str = field(default_factory=str)
    lat: float = field(default_factory=float)
    lon: float = field(default_factory=float)
    exclude_tags: list = field(default_factory=list)


@dataclass
class TelegramConfig(ConfigBase):
    token: str = field(default_factory=str)
    chat_ids: List[int] = field(default_factory=list)


@dataclass
class Config(ConfigBase):
    om: OpenWeaterMapConfig = field(default=OpenWeaterMapConfig())
    telegram: TelegramConfig = field(default=TelegramConfig())

    def __post_init__(self):
        config_path: Path = Path("/etc/default/om-telegram-alert.yaml")

        _config: dict = self.get_config(config_path)
        self.update(_config)

    @staticmethod
    def get_config(config_path: Path) -> dict:
        _config: dict = {}

        if config_path.exists():
            _config = yaml.load(config_path.read_text(), Loader=yaml.FullLoader)

        return _config


def send_telegram_message(config: Config, text: str):
    if text:
        for chat_id in config.telegram.chat_ids:
            data: dict = {"chat_id": chat_id, "parse_mode": "Markdown", "text": text}
            r = requests.post(f"https://api.telegram.org/bot{config.telegram.token}/sendMessage", data=data)

            try:
                r.raise_for_status()
            except requests.exceptions.HTTPError as e:
                logger.error("[TELEGRAM] %s", str(e))


def check_alerts(config: Config):
    temp_filename = Path(gettempdir(), "om-alerts")
    temp_alerts: List[dict] = []

    if temp_filename.exists():
        temp_alerts = json.loads(temp_filename.read_text())

    om_url: str = (
        f"{OM_ONECALL_URL}"
        f"?lat={config.om.lat}&lon={config.om.lon}&exclude=current,minutely,hourly,daily"
        f"&appid={config.om.appid}"
    )

    r = requests.get(om_url)

    try:
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        logger.error("[OM] %s", str(e))

    if r.status_code == 200:
        data: dict = r.json()
        alerts: List[dict] = data.get("alerts", [])

        # alerts = [
        #     {
        #         "sender_name": "ZAMG Zentralanstalt für Meteorologie und Geodynamik",
        #         "event": "Thunderstormwarning",
        #         "start": 1651659170,
        #         "end": 1651666370,
        #         "description": "Henceforth (04.05.2022 12:12) thunderstorms are possible.",
        #         "tags": ["Thunderstorm"],
        #     },
        #     {
        #         "sender_name": "ZAMG Zentralanstalt für Meteorologie und Geodynamik",
        #         "event": "Thunderstormwarning",
        #         "start": 1651660082,
        #         "end": 1651667282,
        #         "description": "Henceforth (04.05.2022 12:29) thunderstorms are possible.",
        #         "tags": ["Thunderstorm"],
        #     },
        #     {
        #         "sender_name": "ZAMG Zentralanstalt für Meteorologie und Geodynamik",
        #         "event": "Thunderstormwarning",
        #         "start": 1651674868,
        #         "end": 1651682068,
        #         "description": "Henceforth (04.05.2022 16:34) thunderstorms with gusts and hail are possible.",
        #         "tags": ["Thunderstorm"],
        #     },
        # ]

        regex_replaces: List[Tuple[str, str]] = [
            # Remove Date/Time from alert description to avoid duplicate warnings!
            (r"\s\(\d{2}\.\d{2}\.\d{4}\s\d{2}:\d{2}\)", ""),
        ]

        if alerts:
            for alert in alerts:
                for regex_replace in regex_replaces:
                    alert["description"] = re.sub(regex_replace[0], regex_replace[1], alert["description"])

                if alert in temp_alerts:
                    continue

                tags: List[str] = alert["tags"]

                if not any(tag in tags for tag in config.om.exclude_tags):
                    message: str = (
                        f"""*{alert["event"]}!* {alert["description"]}\n\n"""
                        f"""Time: {datetime.utcfromtimestamp(alert["start"]).strftime("%d.%m.%Y, %H:%M")}\n"""
                        f"""Tags: {",".join(alert["tags"])}"""
                    )

                    send_telegram_message(config, message)
                    temp_alerts.append(alert)

            if len(temp_alerts) > 20:
                temp_alerts = temp_alerts[10:]

            temp_filename.write_text(json.dumps(temp_alerts))


def main():
    config = Config()
    check_alerts(config)


if __name__ == "__main__":
    main()
