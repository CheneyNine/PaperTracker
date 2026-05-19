"""OpenReview HTML client.

Fetches server-rendered OpenReview submission lists and forum pages for a small
set of curated venues that complement DBLP and arXiv.
"""

from __future__ import annotations

from urllib.parse import urljoin

import requests

OPENREVIEW_BASE_URL = "https://openreview.net/"
HEADERS = {
    "User-Agent": "paper-tracker/0.2 (+https://github.com/CheneyNine/PaperTracker)",
}


class OpenReviewHtmlClient:
    """HTTP client for server-rendered OpenReview pages."""

    def __init__(self) -> None:
        self._session = requests.Session()

    def close(self) -> None:
        """Close session resources."""
        self._session.close()

    def fetch_text(self, path_or_url: str) -> str:
        """Fetch page text from OpenReview."""
        url = path_or_url if path_or_url.startswith("http") else urljoin(OPENREVIEW_BASE_URL, path_or_url.lstrip("/"))
        response = self._session.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        return response.text
