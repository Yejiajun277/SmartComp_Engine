"""Unused search candidates are evidence inventory, not broken citations."""
import unittest

from agents.quality_agent import QualityAgent
from models.domain import Citation


class CollectionSourceCatalogTests(unittest.TestCase):
    def test_unreferenced_search_sources_do_not_force_spurious_claims(self):
        sources = [Citation(f"Rival:q0:r{i}", f"Source {i}", f"https://example.test/{i}")
                   for i in range(35)]
        issues = QualityAgent()._check_citation_validity(sources, [sources[0].id])
        self.assertEqual(issues, [])

    def test_claimed_nonexistent_source_still_fails(self):
        sources = [Citation("Rival:q0:r0", "Known source", "https://example.test/source")]
        issues = QualityAgent()._check_citation_validity(sources, ["Rival:q0:r99"])
        self.assertTrue(any(issue.severity == "critical" and "r99" in issue.field for issue in issues))

    def test_incomplete_source_metadata_remains_visible(self):
        issues = QualityAgent()._check_citation_validity([Citation("Rival:q0:r0", "", "")], [])
        self.assertEqual({issue.field for issue in issues},
                         {"citations.Rival:q0:r0.title", "citations.Rival:q0:r0.url"})


if __name__ == "__main__":
    unittest.main()
