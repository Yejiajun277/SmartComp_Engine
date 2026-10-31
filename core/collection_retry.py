"""Route collection repairs without dropping findings outside missing fields."""
from dataclasses import asdict
import json
from copy import deepcopy
from datetime import datetime
import hashlib

from core.artifact_store import to_jsonable


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
    return "reextract"


def collection_feedback(result):
    # A model-generated 512-token summary previously lost later findings. Keep
    # every original field, scope and suggestion, including warning details.
    return ("请根据原始来源修正以下全部采集质检问题。建议不是新证据；"
            "来源不支持时删除断言或保留未知，不得猜测引用或补全截断报价。\n"
            + json.dumps([asdict(issue) for issue in result.issues],
                         ensure_ascii=False, indent=2))


def source_fingerprint(data, source_texts):
    evidence = {"original_search_texts": source_texts,
                "citations": {name: value.citations for name, value in data.items()}}
    encoded = json.dumps(to_jsonable(evidence), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def repair_collection(orchestrator, product_name, product_description, data,
                            source_texts, qa_result, attempt, missing_fields):
    """Archive first, then repair staged facts; QA remains the only acceptance gate."""
    mode = collection_retry_mode(qa_result, missing_fields)
    before_data, before_sources = deepcopy(data), deepcopy(source_texts)
    fingerprint = source_fingerprint(before_data, before_sources)
    prefix = f"02_collection_retries/attempt_{attempt:02d}"
    audit = {"attempt": attempt, "mode": mode,
             "evidence_mode": "fresh_search_supplement" if mode == "supplement" else "saved_sources",
             "status": "started", "started_at": datetime.now().isoformat(timespec="seconds"),
             "source_fingerprint": fingerprint, "result_source_fingerprint": fingerprint,
             "entity_outcomes": []}
    orchestrator._save_artifact_json(prefix + "_before.json", {
        "competitors_data": before_data, "original_search_texts": before_sources,
        "qa_collection": qa_result, "attempt": attempt, "mode": mode,
        "source_fingerprint": fingerprint,
    })
    orchestrator._save_artifact_json(prefix + "_result.json", audit)
    agent = orchestrator.collection_agent
    agent.restore_source_snapshot(before_sources)
    feedback = (orchestrator.quality_agent.build_supplement_feedback(missing_fields)
                if mode == "supplement" else await orchestrator.quality_agent.async_build_feedback(qa_result))
    result_data, result_sources = before_data, before_sources
    try:
        if mode == "recheck":
            audit.update(status="not_attempted", reason="qa_incomplete_recheck_same_snapshot")
        elif mode == "supplement":
            result_data = await agent.async_supplement_missing_fields(
                product_name, deepcopy(before_data), missing_fields)
            result_sources = {**before_sources, **agent.get_search_texts()}
        else:
            result_data = await agent.async_reextract_saved_sources(
                product_name, product_description, deepcopy(before_data), deepcopy(before_sources), feedback)
            result_sources = before_sources
        if mode != "recheck":
            outcomes = agent.get_repair_outcomes()
            audit["entity_outcomes"] = outcomes
            accepted = sum(item.get("status") == "accepted" for item in outcomes)
            audit["status"] = ("accepted" if outcomes and accepted == len(outcomes)
                               else "partial" if accepted else "failed")
    except Exception as error:
        result_data, result_sources = before_data, before_sources
        agent.restore_source_snapshot(before_sources)
        audit.update(status="failed", reason=f"{type(error).__name__}: {str(error)[:200]}")
    audit["result_source_fingerprint"] = source_fingerprint(result_data, result_sources)
    audit["finished_at"] = datetime.now().isoformat(timespec="seconds")
    orchestrator._save_artifact_json(prefix + "_result.json", audit)
    return result_data, result_sources, feedback
