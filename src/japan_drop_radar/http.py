from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

import requests
from protego import Protego
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


@dataclass
class RespectfulHttpClient:
    min_interval: float = 1.5
    timeout: int = 20
    user_agent: str = field(default_factory=lambda: os.getenv("RADAR_USER_AGENT", "JapanDropRadar/0.1 (+local-research)"))

    def __post_init__(self) -> None:
        self.session = requests.Session()
        retry = Retry(total=2, backoff_factor=0.8, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        self.session.headers.update({"User-Agent": self.user_agent, "Accept-Language": "ja,en;q=0.7"})
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, Protego] = {}

    def _origin(self, url: str) -> str:
        parts = urlsplit(url)
        return urlunsplit((parts.scheme, parts.netloc, "", "", ""))

    def allowed(self, url: str) -> bool:
        origin = self._origin(url)
        if origin not in self._robots:
            try:
                response = self.session.get(origin + "/robots.txt", timeout=self.timeout)
                rules = response.text if response.ok else ""
            except Exception:
                # robots.txt が取得不能なら、公開ページへの低頻度アクセスだけを許可。
                rules = ""
            self._robots[origin] = Protego.parse(rules)
        return self._robots[origin].can_fetch(url, self.user_agent)

    def get(self, url: str, *, check_robots: bool = True) -> requests.Response:
        if check_robots and not self.allowed(url):
            raise PermissionError(f"robots.txt により取得不可: {url}")
        origin = self._origin(url)
        elapsed = time.monotonic() - self._last_request.get(origin, 0.0)
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        response = self.session.get(url, timeout=self.timeout)
        self._last_request[origin] = time.monotonic()
        response.raise_for_status()
        return response
