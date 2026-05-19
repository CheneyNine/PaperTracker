"""Tests for DBLP source venue scanning."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from PaperTracker.ccf.store import CCFVenue
from PaperTracker.core.query import FieldQuery, SearchQuery
from PaperTracker.sources.dblp.source import DBLPSource


class _FakeClient:
    def __init__(self, payloads: dict[str, str]) -> None:
        self.payloads = payloads

    def fetch_text(self, path: str) -> str:
        if path not in self.payloads:
            raise AssertionError(f"Unexpected fetch: {path}")
        return self.payloads[path]

    def close(self) -> None:
        return None


class _FakeVenueStore:
    def __init__(self, venues: list[CCFVenue]) -> None:
        self._venues = venues

    def list_venues(self, *, ranks: tuple[str, ...] = ("A", "B")) -> list[CCFVenue]:
        del ranks
        return list(self._venues)


class _FakeSearchConfig:
    ccf_enabled = True
    ccf_ranks = ("A", "B")
    dblp_recent_years = 2


class TestDBLPSource(unittest.TestCase):
    def test_search_scans_venues_beyond_old_front_cap(self) -> None:
        venues: list[CCFVenue] = []
        payloads: dict[str, str] = {}
        current_year = 2026

        for index in range(25):
            stream = f"db/conf/test{index}"
            short_name = f"V{index}"
            venues.append(
                CCFVenue(
                    short_name=short_name,
                    full_name=f"Venue {index}",
                    rank="A",
                    venue_type="conference",
                    dblp_stream=stream,
                    openreview_venues=(),
                )
            )
            payloads[f"{stream}/index.xml"] = (
                "<dblp>"
                f'<ref href="{stream}/2026.html">{short_name} {current_year}</ref>'
                "</dblp>"
            )
            title = "Traffic reasoning benchmark in venue tail" if index == 24 else f"Unrelated paper {index}"
            payloads[f"https://dblp.org/{stream}/2026.html"] = f"""
                <ul>
                  <li class="entry inproceedings" id="conf/test{index}/paper">
                    <span class="title">{title}</span>
                    <span itemprop="author"><a href="#">Author {index}</a></span>
                  </li>
                </ul>
            """

        source = DBLPSource(
            client=_FakeClient(payloads),
            venue_store=_FakeVenueStore(venues),
            search_config=_FakeSearchConfig(),
        )
        query = SearchQuery(
            name="traffic benchmark",
            fields={"TEXT": FieldQuery(OR=("traffic", "benchmark"))},
        )

        papers = source.search(query, max_results=1)

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].source, "dblp")
        self.assertEqual(papers[0].extra.get("venue"), "V24")
        self.assertEqual(papers[0].extra.get("venue_name"), "Venue 24")
        self.assertEqual(papers[0].extra.get("venue_type"), "conference")
        self.assertEqual(papers[0].extra.get("ccf_rank"), "CCF-A")
        self.assertEqual(papers[0].extra.get("ccf_venue"), "V24")


if __name__ == "__main__":
    unittest.main()
