import os

import yaml
from dataclasses import dataclass, field


@dataclass
class DeviceConfig:
    device_uid: str
    wda_url: str
    name: str = ""


@dataclass
class AuthConfig:
    username: str = "admin"
    password: str = "admin123"


@dataclass
class USBMonitorConfig:
    enabled: bool = True
    scan_interval: int = 5
    wda_ipa_path: str = ""


@dataclass
class AgentConfig:
    server_url: str
    machine_id: str
    server_http_url: str = "http://localhost:8000"
    heartbeat_interval: int = 30
    reconnect_interval: int = 5
    max_reconnect_attempts: int = 0  # 0 = unlimited
    devices: list[DeviceConfig] = field(default_factory=list)
    auth: AuthConfig = field(default_factory=AuthConfig)
    usb_monitor: USBMonitorConfig = field(default_factory=USBMonitorConfig)


def load_config(path: str | None = None) -> AgentConfig:
    if path is None:
        path = os.environ.get("AGENT_CONFIG_PATH", "config.yaml")
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    active = os.environ.get("AGENT_PROFILE") or raw.get("active", "")
    profiles = raw.get("profiles", {})
    if active and active in profiles:
        profile = profiles[active]
        raw.setdefault("server_url", profile.get("server_url"))
        raw.setdefault("server_http_url", profile.get("server_http_url"))
        for k, v in profile.items():
            if v is not None:
                raw.setdefault(k, v)

    devices = [DeviceConfig(**d) for d in raw.get("devices", [])]
    auth_raw = raw.get("auth", {})
    auth = AuthConfig(
        username=auth_raw.get("username", "admin"),
        password=auth_raw.get("password", "admin123"),
    )
    usb_raw = raw.get("usb_monitor", {})
    usb_monitor = USBMonitorConfig(
        enabled=usb_raw.get("enabled", True),
        scan_interval=usb_raw.get("scan_interval", 5),
        wda_ipa_path=usb_raw.get("wda_ipa_path", ""),
    )

    return AgentConfig(
        server_url=raw["server_url"],
        machine_id=raw["machine_id"],
        server_http_url=raw.get("server_http_url", "http://localhost:8000"),
        heartbeat_interval=raw.get("heartbeat_interval", 30),
        reconnect_interval=raw.get("reconnect_interval", 5),
        max_reconnect_attempts=raw.get("max_reconnect_attempts", 0),
        devices=devices,
        auth=auth,
        usb_monitor=usb_monitor,
    )
