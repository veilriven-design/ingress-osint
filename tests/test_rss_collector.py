from __future__ import annotations

from ingress.collectors.rss import RSSCollector


def test_multi_feed_collector_keeps_per_feed_source_names(tmp_path) -> None:
    feed_a = tmp_path / "alpha.xml"
    feed_b = tmp_path / "bravo.xml"
    feed_a.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>Alpha</title>
<item><title>Alpha item</title><link>https://example.com/a</link></item>
</channel></rss>
""",
        encoding="utf-8",
    )
    feed_b.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>Bravo</title>
<item><title>Bravo item</title><link>https://example.com/b</link></item>
</channel></rss>
""",
        encoding="utf-8",
    )

    artifacts = RSSCollector([str(feed_a), str(feed_b)]).collect()

    assert [artifact.source.name for artifact in artifacts] == ["alpha.xml", "bravo.xml"]
    assert len({artifact.source.id for artifact in artifacts}) == 2
