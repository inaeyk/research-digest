from __future__ import annotations

import unittest
from collections.abc import Callable
from dataclasses import dataclass

from research_digest.ui import app


@dataclass(frozen=True)
class PageCall:
    page: Callable[[], None]
    title: str | None
    icon: str | None
    url_path: str | None
    default: bool

    @property
    def effective_url_path(self) -> str:
        return "" if self.default else self.url_path or self.page.__name__


class FakeStreamlit:
    def Page(
        self,
        page: Callable[[], None],
        *,
        title: str | None = None,
        icon: str | None = None,
        url_path: str | None = None,
        default: bool = False,
    ) -> PageCall:
        return PageCall(page=page, title=title, icon=icon, url_path=url_path, default=default)


class NavigationTests(unittest.TestCase):
    def test_pages_have_stable_unique_url_paths(self) -> None:
        pages = app._build_pages(FakeStreamlit())

        self.assertEqual(
            [page.title for page in pages],
            ["Today", "History", "Interests", "Sources", "Settings"],
        )
        self.assertEqual(
            [page.effective_url_path for page in pages],
            ["", "history", "interests", "sources", "settings"],
        )
        self.assertEqual(
            [page.icon for page in pages],
            [
                ":material/today:",
                ":material/history:",
                ":material/person_search:",
                ":material/travel_explore:",
                ":material/settings:",
            ],
        )
        self.assertEqual(
            len({page.effective_url_path for page in pages}),
            len(pages),
        )


if __name__ == "__main__":
    unittest.main()
