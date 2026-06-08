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


def test_rss_collector_cleans_html_and_records_matched_keywords(tmp_path) -> None:
    feed = tmp_path / "feed.xml"
    feed.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>Defense</title>
<item>
  <title>IRGC drone activity reported</title>
  <link>https://example.com/irgc-drone</link>
  <description><![CDATA[<p>Shahed activity &amp; missile reporting.</p>]]></description>
</item>
</channel></rss>
""",
        encoding="utf-8",
    )

    artifacts = RSSCollector([str(feed)], keywords=["IRGC", "Shahed", "not-present"]).collect()

    assert len(artifacts) == 1
    assert artifacts[0].text == "IRGC drone activity reported\n\nShahed activity & missile reporting."
    assert artifacts[0].metadata["matched_keywords"] == ["irgc", "shahed"]


def test_rss_collector_keyword_matching_uses_word_boundaries(tmp_path) -> None:
    feed = tmp_path / "feed.xml"
    feed.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>Plans</title>
<item><title>Shipyard plans a future launch</title><link>https://example.com/a</link></item>
<item><title>PLA Navy exercise begins</title><link>https://example.com/b</link></item>
</channel></rss>
""",
        encoding="utf-8",
    )

    artifacts = RSSCollector([str(feed)], keywords=["PLAN", "PLA"]).collect()

    assert len(artifacts) == 1
    assert artifacts[0].raw_ref == "https://example.com/b"
    assert artifacts[0].metadata["matched_keywords"] == ["pla"]
