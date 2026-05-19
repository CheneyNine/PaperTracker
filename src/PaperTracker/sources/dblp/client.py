"""DBLP venue page client.

Fetches DBLP index and venue-detail HTML pages used for venue-constrained paper
collection from the local CCF whitelist snapshot.
"""

from __future__ import annotations

from urllib.parse import urljoin

import requests

DBLP_BASE_URL = "https://dblp.org/"
HEADERS = {
    "User-Agent": "paper-tracker/0.1 (+https://github.com/RainerSeventeen/paper-tracker)",
}


class DBLPVenueClient:
    """HTTP client for DBLP venue pages."""

    def __init__(self) -> None:
        self._session = requests.Session()

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self._session.close()

    def fetch_text(self, path_or_url: str) -> str:
        """Fetch one DBLP page as text."""
        url = path_or_url if path_or_url.startswith("http") else urljoin(DBLP_BASE_URL, path_or_url.lstrip("/"))
        response = self._session.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        return response.text
