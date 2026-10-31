"""Route collection repairs without dropping findings outside missing fields."""
from dataclasses import asdict
import json


def collection_retry_mode(result, missing_fields):
    # Transport/parse failure supplies no factual correction. Recheck the same
    # snapshot rather than replacing evidence merely because review failed.
    if result.hallucination_status == "failed":
        return "recheck"
    supported = {"strengths", "weaknesses", "channels", "market_share",
                 "user_reviews", "pricing_tiers"}
    covered = {f"{name}.{field}" for name, fields in missing_fields.items()
               for field in fields if field in supported}
    if covered and result.issues and all(
        issue.category in ("completeness", "schema") and issue.field in covered
        for issue in result.issues
    ):
        return "supplement"
    return "recollect"


def collection_feedback(result):
    # A model-generated 512-token summary previously lost later findings. Keep
    # every original field, scope and suggestion, including warning details.
    return ("请根据原始来源修正以下全部采集质检问题。建议不是新证据；"
            "来源不支持时删除断言或保留未知，不得猜测引用或补全截断报价。\n"
            + json.dumps([asdict(issue) for issue in result.issues],
                         ensure_ascii=False, indent=2))
