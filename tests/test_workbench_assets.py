"""Keep the offline browser entry point and its accessibility contract in the wheel."""
from html.parser import HTMLParser
from importlib.resources import files


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        self.ids.add(fields.get("id"))
        if tag in {"link", "script"}:
            self.links.append(fields.get("src", fields.get("href")))


def test_offline_entry_point_and_assets():
    assets = files("dfo_optimizer").joinpath("data", "workbench")
    page = Page()
    page.feed(assets.joinpath("index.html").read_text(encoding="utf-8"))
    assert {"navigation", "workspace", "status", "title"} <= page.ids
    assert page.links
    for url in page.links:
        assert url and ":" not in url and "//" not in url
        assert assets.joinpath(url.lstrip("/")).is_file()
