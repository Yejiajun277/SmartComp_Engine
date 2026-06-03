# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest

from pydantic import ValidationError

from models.schema import AgentRole, PayloadType, build_agent_message, validate_payload


VALID_PRODUCT_ANALYSIS = {
    "feature_matrix": [
        {
            "feature": "AI assistant",
            "values": {"OurProduct": "partial", "CompetitorA": "supported"},
            "citations": ["CompetitorA:product_features:citation:1"],
            "competitor_citations": {
                "CompetitorA": ["CompetitorA:product_features:citation:1"]
            },
        }
    ],
    "competitive_advantages": [
        {
            "competitor": "CompetitorA",
            "our_advantage": "Lower setup complexity",
            "their_advantage": "Broader integrations",
            "citations": ["CompetitorA:product_features:citation:1"],
        }
    ],
    "differentiation_points": ["Faster setup"],
    "feature_tree": [
        {
            "name": "AI assistant",
            "description": "Assistant capabilities",
            "supported_competitors": ["CompetitorA"],
            "children": [],
        }
    ],
    "conclusions": [
        {
            "id": "product:conclusion:1",
            "dimension": "product",
            "statement": "CompetitorA has broader integrations.",
            "citations": ["CompetitorA:product_features:citation:1"],
            "confidence": 0.8,
            "evidence_topics": ["product_features"],
        }
    ],
    "citations": [
        {
            "id": "CompetitorA:product_features:citation:1",
            "title": "Source",
            "url": "https://example.com",
            "snippet": "integration evidence",
            "source_quality": "official",
            "confidence": 0.9,
        }
    ],
    "summary": "Product comparison summary.",
}


class StrictSchemaTests(unittest.TestCase):
    def test_product_analysis_payload_validates(self):
        payload = validate_payload(PayloadType.PRODUCT_ANALYSIS, VALID_PRODUCT_ANALYSIS)

        self.assertEqual(payload.feature_matrix[0].feature, "AI assistant")

    def test_missing_required_business_field_fails(self):
        invalid = dict(VALID_PRODUCT_ANALYSIS)
        invalid["feature_tree"] = []

        with self.assertRaises(ValidationError):
            validate_payload(PayloadType.PRODUCT_ANALYSIS, invalid)

    def test_extra_field_fails(self):
        invalid = dict(VALID_PRODUCT_ANALYSIS)
        invalid["unexpected"] = "not allowed"

        with self.assertRaises(ValidationError):
            validate_payload(PayloadType.PRODUCT_ANALYSIS, invalid)

    def test_plain_text_payload_fails(self):
        with self.assertRaises(ValidationError):
            build_agent_message(
                run_id="run-1",
                sender=AgentRole.ProductAgent,
                receiver=AgentRole.QualityAgent,
                payload_type=PayloadType.PRODUCT_ANALYSIS,
                payload="natural language summary",
            )

    def test_agent_message_validates_payload_type(self):
        message = build_agent_message(
            run_id="run-1",
            sender=AgentRole.ProductAgent,
            receiver=AgentRole.QualityAgent,
            payload_type=PayloadType.PRODUCT_ANALYSIS,
            payload=VALID_PRODUCT_ANALYSIS,
            citations=["CompetitorA:product_features:citation:1"],
        )

        self.assertEqual(message.payload_type, PayloadType.PRODUCT_ANALYSIS)
        self.assertEqual(message.payload["feature_matrix"][0]["feature"], "AI assistant")


if __name__ == "__main__":
    unittest.main()
