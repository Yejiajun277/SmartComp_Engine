"""Citation display must keep prose readable and each link traceable."""
import unittest
from html.parser import HTMLParser

from agents.base_agent import BaseAgent
from agents.strategy_agent import StrategyAgent
from models.domain import Citation, CitationIndex, IntroItem, StrategyReport, TargetProductIntro
from core.report_citations import normalize_report_citations


class VisibleHtml(HTMLParser):
    def __init__(self, markup):
        super().__init__(convert_charrefs=True)
        self.text = []
        self.ids = set()
        self.references = []
        self.event_attributes = []
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        self.event_attributes.extend((tag, key, value) for key, value in attrs if key.lower().startswith("on"))
        if values.get("id"):
            self.ids.add(values["id"])
        if tag == "a" and values.get("href", "").startswith("#cite-"):
            self.references.append(values["href"][1:])

    def handle_data(self, data):
        self.text.append(data)


class ReportCitationIntegrationTests(unittest.TestCase):
    def report(self, **kwargs):
        index = CitationIndex()
        index.add(Citation("iPhone DUO:q0:r0", "Official display", "https://example.test/display"))
        return StrategyReport("iPhone DUO", competitor_count=1, citation_index=index, **kwargs)

    def test_internal_source_ids_are_numbered_without_changing_the_sentence(self):
        report = self.report(summary="Largest display [iPhone DUO:q0:r0]; ordinary [2026] stays.")
        parsed = VisibleHtml(StrategyAgent().format_html_report(report))
        prose = "".join(parsed.text)
        self.assertNotIn("[iPhone DUO:q0:r0]", prose)
        self.assertIn("Largest display [1]; ordinary [2026] stays.", prose)
        self.assertTrue(parsed.references)
        self.assertTrue(set(parsed.references).issubset(parsed.ids))

    def test_intro_only_citations_have_actual_appendix_targets(self):
        report = self.report(target_product_intro=TargetProductIntro(
            core_capabilities=[IntroItem("Folding display", "Largest display", ["iPhone DUO:q0:r0"])]))
        parsed = VisibleHtml(StrategyAgent().format_html_report(report))
        self.assertTrue(parsed.references)
        self.assertTrue(set(parsed.references).issubset(parsed.ids), parsed.references)
        self.assertIn("Official display", "".join(parsed.text))

    def test_extraction_handles_spaces_chinese_wrapped_ids_and_string_field(self):
        data = {"citations": "[iPhone DUO:q0:r0]", "summary": "支持 [华为 Mate X:q1:r2]。"}
        self.assertEqual(BaseAgent.extract_citation_ids(data),
                         ["iPhone DUO:q0:r0", "华为 Mate X:q1:r2"])
        self.assertEqual(BaseAgent.extract_citation_ids({
            "citations": ["[iPhone DUO:q0:r0]", " iPhone DUO:q0:r0 ", "plain-source"]}),
            ["iPhone DUO:q0:r0", "plain-source"])

    def test_quote_containing_citation_ids_cannot_inject_html_attributes(self):
        for source_id in ('Phone "Pro":q0:r0', 'Phone" onmouseover="alert(1)//:q0:r0'):
            with self.subTest(source_id=source_id):
                index = CitationIndex()
                index.add(Citation(source_id, 'Saved source', 'https://example.test/source'))
                intro = StrategyAgent()._parse_target_product_intro({'target_product_intro': {
                    'core_capabilities': [{'title': 'Display', 'summary': 'Claim [' + source_id + ']'}]}})
                report = StrategyReport('Phone', competitor_count=1, citation_index=index,
                                        target_product_intro=intro)
                parsed = VisibleHtml(StrategyAgent().format_html_report(report))
                self.assertEqual(parsed.event_attributes, [])
                self.assertIn('cite-' + source_id, parsed.ids)
                self.assertTrue(set(parsed.references).issubset(parsed.ids))


class ReportCitationDisplayTests(unittest.TestCase):
    def test_supplemental_collection_ids_are_readable_and_extractable(self):
        source_id = 'Bigme HiBreak Dual 系列:sup_market_0:r35'
        markup = '<p>Market statement [' + source_id + '].</p>'
        result = normalize_report_citations(markup, {
            source_id: {'title': 'Saved supplemental source', 'url': 'https://example.test/supplement'}})
        self.assertIn('Market statement [1].', ''.join(VisibleHtml(result).text))
        self.assertEqual(BaseAgent.extract_citation_ids({'summary': markup}), [source_id])
        self.assertEqual(normalize_report_citations(result), result)

    def test_existing_alias_number_tracks_the_canonical_source_number(self):
        original = ('<p><a href="#cite-Bigme:q5:r25" title="Original">[25]</a>'
                    ' and [Bigme:q5:r25].</p>'
                    '<div id="cite-Bigme:q2:r11"><span>[23]</span>'
                    '<a href="https://example.test/same">Saved source</a></div>')
        sources = {'Bigme:q5:r25': {'title': 'Duplicate source', 'url': 'https://example.test/same'}}
        result = normalize_report_citations(original, sources)
        self.assertIn('href="#cite-Bigme:q5:r25" title="Original">[23]</a>', result)
        self.assertIn(' and [23].', ''.join(VisibleHtml(result).text))
        self.assertEqual(normalize_report_citations(result, sources), result)

    def test_existing_numeric_link_uses_the_actual_appendix_number_without_changing_attributes(self):
        markup = ('<h3>ON<sup><a href="#cite-OPTIMUM NUTRITION:q3:r18" '
                  'title="Saved source" data-original="yes">[5]</a></sup></h3>'
                  '<p>Claim [OPTIMUM NUTRITION:q3:r18].</p>'
                  '<div id="cite-OPTIMUM NUTRITION:q3:r18"><span>[11]</span>Actual source</div>'
                  '<a href="#cite-OPTIMUM NUTRITION:q3:r18">Explanation [5]</a>')
        result = normalize_report_citations(markup)
        self.assertIn('title="Saved source" data-original="yes">[11]</a>', result)
        self.assertIn('>Explanation [5]</a>', result)
        self.assertIn('Claim [11].', ''.join(VisibleHtml(result).text))
        self.assertNotIn('>[5]</a>', result)
        self.assertEqual(normalize_report_citations(result), result)

    def test_plain_appendix_number_is_reused_without_a_nested_span(self):
        markup = '<p>Claim [Phone:q0:r0].</p><div id="cite-Phone:q0:r0">[7] Actual source</div>'
        result = normalize_report_citations(markup)
        self.assertIn('Claim [7].', ''.join(VisibleHtml(result).text))

    def test_screenshot_body_marker_reuses_the_existing_numbered_source(self):
        original_link = '<a href="#cite-iPhone DUO:q0:r0" title="Source">[3]</a>'
        markup = ('<h3>Display<sup>' + original_link + '</sup></h3>'
                  '<p>Largest display [iPhone DUO:q0:r0].</p>'
                  '<div id="cite-iPhone DUO:q0:r0"><span>[3]</span>Official display</div>')
        result = normalize_report_citations(markup)
        parsed = VisibleHtml(result)
        self.assertIn(original_link, result)
        self.assertIn('Largest display [3].', ''.join(parsed.text))
        self.assertEqual(parsed.references.count('cite-iPhone DUO:q0:r0'), 2)
        self.assertNotIn('[iPhone DUO:q0:r0]', ''.join(parsed.text))

    def test_multiple_adjacent_and_grouped_ids_support_chinese_and_spaces(self):
        markup = ('<p>A [iPhone DUO:q0:r0][华为 Mate X:q1:r2] B '
                  '[iPhone DUO:q0:r0, 华为 Mate X:q1:r2]。</p>'
                  '<div id="cite-iPhone DUO:q0:r0">[1] Phone</div>'
                  '<div id="cite-华为 Mate X:q1:r2">[2] Mate</div>')
        result = normalize_report_citations(markup)
        parsed = VisibleHtml(result)
        self.assertIn('A [1][2] B [1][2]。', ''.join(parsed.text))
        self.assertEqual(parsed.references,
                         ['cite-iPhone DUO:q0:r0', 'cite-华为 Mate X:q1:r2'] * 2)
        self.assertTrue(set(parsed.references).issubset(parsed.ids))

    def test_unknown_id_is_explicit_without_fabricating_a_source_or_removing_prose(self):
        result = normalize_report_citations('<p>Some claim [Unknown Phone:q8:r9] remains.</p>')
        parsed = VisibleHtml(result)
        self.assertIn('Some claim ', ''.join(parsed.text))
        self.assertIn(' remains.', ''.join(parsed.text))
        self.assertIn('来源未匹配', ''.join(parsed.text))
        self.assertNotIn('[Unknown Phone:q8:r9]', ''.join(parsed.text))
        self.assertEqual(parsed.references, [])
        self.assertEqual(normalize_report_citations(result), result)

    def test_saved_source_supplies_a_missing_appendix_and_escapes_source_metadata(self):
        result = normalize_report_citations(
            '<html><body><p>Some claim [Phone:q2:r3].</p></body></html>',
            {'Phone:q2:r3': {'title': '<img src=x onerror=alert(1)>',
                            'url': 'https://example.test/source?x=1&y=2'}})
        parsed = VisibleHtml(result)
        self.assertIn('Some claim [1].', ''.join(parsed.text))
        self.assertIn('https://example.test/source?x=1&amp;y=2', result)
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;', result)
        self.assertNotIn('<img src=x', result)
        self.assertTrue(parsed.references)
        self.assertTrue(set(parsed.references).issubset(parsed.ids))
        self.assertEqual(normalize_report_citations(result), result)

    def test_same_url_alias_reuses_number_and_repairs_existing_alias_target(self):
        original_link = '<a href="#cite-Alias Phone:q1:r8">[4]</a>'
        markup = ('<p>' + original_link + ' and [Alias Phone:q1:r8].</p>'
                  '<div id="cite-Phone:q0:r0"><span>[4]</span>'
                  '<a href="https://example.test/source">Official</a></div>')
        sources = {'Alias Phone:q1:r8': {'url': 'https://example.test/source', 'title': 'Same source'}}
        result = normalize_report_citations(markup, sources)
        parsed = VisibleHtml(result)
        self.assertIn(original_link, result)
        self.assertIn(' and [4].', ''.join(parsed.text))
        self.assertIn('href="#cite-Phone:q0:r0"', result)
        self.assertTrue(set(parsed.references).issubset(parsed.ids))
        self.assertEqual(result.count('https://example.test/source'), 1)
        self.assertEqual(normalize_report_citations(result, sources), result)

    def test_attributes_existing_links_scripts_styles_and_comments_are_unchanged(self):
        protected = ('<p title="[Phone:q1:r2]">[2026] [规格] [1.9/5]</p>'
                     '<a href="https://example.test/[Phone:q1:r2]">[Phone:q1:r2]</a>'
                     '<script>var source="[Phone:q1:r2]";</script>'
                     '<style>.x:after{content:"[Phone:q1:r2]"}</style>'
                     '<!-- [Phone:q1:r2] -->')
        self.assertEqual(normalize_report_citations(protected), protected)

    def test_entities_and_ordinary_brackets_are_preserved_outside_source_markers(self):
        markup = '<p>Fish &amp; chips&nbsp;[2026] [A &amp; B:q0:r0].</p>'
        result = normalize_report_citations(markup, {
            'A & B:q0:r0': {'title': 'Source', 'url': 'https://example.test/source'}})
        self.assertIn('Fish &amp; chips&nbsp;[2026] ', result)
        self.assertIn('href="#cite-A &amp; B:q0:r0"', result)
        self.assertNotIn('[A &amp; B:q0:r0]', result)

    def test_unsafe_saved_url_cannot_become_an_executable_link(self):
        result = normalize_report_citations('<p>Claim [Phone:q1:r2].</p>', {
            'Phone:q1:r2': {'title': 'Source title', 'url': 'javascript:alert(1)'}})
        self.assertNotIn('href="javascript:', result)
        parsed = VisibleHtml(result)
        self.assertTrue(set(parsed.references).issubset(parsed.ids))

    def test_repeated_normalization_is_identical_with_duplicate_markers(self):
        sources = {'Phone:q0:r0': {'title': 'Source', 'url': 'https://example.test/source'}}
        once = normalize_report_citations('<p>First [Phone:q0:r0], next [Phone:q0:r0].</p>', sources)
        self.assertEqual(normalize_report_citations(once, sources), once)
        parsed = VisibleHtml(once)
        self.assertEqual(parsed.references, ['cite-Phone:q0:r0'] * 2)
        self.assertEqual(len(parsed.ids), 1)


if __name__ == "__main__":
    unittest.main()
