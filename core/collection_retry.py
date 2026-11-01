"""Route collection repairs without dropping findings outside missing fields."""
from dataclasses import asdict
import asyncio
import json
from copy import deepcopy
from datetime import datetime
import hashlib
import unicodedata

from core.artifact_store import to_jsonable


def _identity(name):
    return unicodedata.normalize("NFKC", name).strip().casefold()


def validate_collection_names(competitor_list):
    """Reject discovery identities before a collection dict can overwrite them."""
    names = [competitor_list.product_name, *(c.name for c in competitor_list.competitors)]
    normalized = [_identity(name) for name in names]
    if len(set(normalized)) != len(normalized):
        raise ValueError("Duplicate target/rival collection identity")


def collection_entities(competitors_data, target_product_data=None, product_name=""):
    """Temporary QA/repair view; the saved rival mapping is never modified."""
    entities = dict(competitors_data)
    identities = []
    for key, data in entities.items():
        identities.append(_identity(key))
    if len(set(identities)) != len(identities):
        raise ValueError("Duplicate rival collection identity")
    if target_product_data is not None:
        name = product_name or target_product_data.name
        target_names = {_identity(name), _identity(target_product_data.name)}
        if any(_identity(key) in target_names or _identity(data.name) in target_names
               for key, data in entities.items()):
            raise ValueError("Duplicate target/rival collection identity")
        entities[name] = target_product_data
    return entities


def split_collection_entities(entities, target_product_data=None, product_name=""):
    rivals = dict(entities)
    target = target_product_data
    if target is not None:
        name = product_name or target.name
        target = rivals.pop(name)
    return rivals, target


def target_source_snapshot(source_texts, target_product_data=None, product_name=""):
    if target_product_data is None:
        return {}
    names = {_identity(product_name), _identity(target_product_data.name)}
    return deepcopy({name: text for name, text in source_texts.items() if _identity(name) in names})


def collection_source_snapshot(target_sources, rival_sources):
    # Target originals were captured before competitor.run could reset the cache.
    return {**deepcopy(rival_sources), **deepcopy(target_sources)}


def completed_collection_repairs(data, result):
    """Select exact owners of real findings, never an unfinished review itself."""
    trace = getattr(result, "entity_review_trace", [])
    if trace:
        completed = {row.get("entity") for row in trace
                     if isinstance(row, dict) and row.get("completed") is True}
    else:
        # Older saved checks persist the incomplete-entity map in the system
        # issue. Only that machine-readable map establishes which other entity
        # checks completed; an opaque failure is not evidence for a repair.
        failed = set()
        for issue in result.issues:
            if issue.field != "__hallucination_check__":
                continue
            candidates = [issue.actual] if isinstance(issue.actual, str) and issue.actual.strip() else []
            prefix, suffix = "幻觉检测未能完成（", "），结果可信度未知"
            description = issue.description
            if isinstance(description, str) and description.startswith(prefix) and description.endswith(suffix):
                candidates.append(description[len(prefix):-len(suffix)])
            for text in candidates:
                try:
                    failures = json.loads(text)
                except (TypeError, ValueError):
                    continue
                if (isinstance(failures, dict) and failures
                        and all(name in data and isinstance(reason, str) and reason.strip()
                                for name, reason in failures.items())):
                    failed.update(failures)
        completed = set(data) - failed if failed else set()
    selected = set()
    for issue in result.issues:
        if issue.field == "__hallucination_check__":
            continue
        owners = [name for name in data if issue.field == name or issue.field.startswith(name + ".")]
        if len(owners) == 1 and owners[0] in completed:
            selected.add(owners[0])
    return {name: value for name, value in data.items() if name in selected}


def collection_retry_mode(result, missing_fields, data=None):
    # Incomplete review alone supplies no correction. A separately completed
    # entity's explicit finding can still be repaired against its saved source.
    if result.hallucination_status == "failed":
        return "reextract" if data and completed_collection_repairs(data, result) else "recheck"
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


def affected_collection_entities(data, issues):
    """Use exact field ownership only; ambiguous/global findings check all."""
    affected = set()
    for issue in issues:
        owners = [name for name in data if issue.field == name or issue.field.startswith(name + ".")]
        if len(owners) != 1:
            return data
        affected.add(owners[0])
    return {name: item for name, item in data.items() if name in affected} if affected else data


def source_fingerprint(data, source_texts):
    evidence = {"original_search_texts": source_texts,
                "citations": {name: value.citations for name, value in data.items()},
                "search_sources": {name: value.search_sources for name, value in data.items()}}
    encoded = json.dumps(to_jsonable(evidence), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def repair_collection(orchestrator, product_name, product_description, data,
                            source_texts, qa_result, attempt, missing_fields, *, target_name=None):
    """Archive first, then repair staged facts; QA remains the only acceptance gate."""
    mode = collection_retry_mode(qa_result, missing_fields, data)
    if mode == "supplement" and target_name in missing_fields:
        # A target correction uses its already captured evidence, not a new
        # search whose scope could silently replace the original target facts.
        mode = "reextract"
    before_data, before_sources = deepcopy(data), deepcopy(source_texts)
    fingerprint = source_fingerprint(before_data, before_sources)
    prefix = f"02_collection_retries/attempt_{attempt:02d}"
    audit = {"attempt": attempt, "mode": mode,
             "evidence_mode": "fresh_search_supplement" if mode == "supplement" else "saved_sources",
             "status": "started", "started_at": datetime.now().isoformat(timespec="seconds"),
             "source_fingerprint": fingerprint, "result_source_fingerprint": fingerprint,
             "entity_outcomes": []}
    orchestrator._save_artifact_json(prefix + "_before.json", {
        "competitors_data": {name: item for name, item in before_data.items() if name != target_name},
        **({"target_product_data": before_data[target_name]} if target_name is not None else {}),
        "original_search_texts": before_sources,
        "qa_collection": qa_result, "attempt": attempt, "mode": mode,
        "source_fingerprint": fingerprint,
    })
    orchestrator._save_artifact_json(prefix + "_result.json", audit)
    agent = orchestrator.collection_agent
    agent.restore_source_snapshot(before_sources)
    feedback = (orchestrator.quality_agent.build_supplement_feedback(missing_fields)
                if mode == "supplement" else await orchestrator.quality_agent.async_build_feedback(qa_result))
    if mode == "reextract" and qa_result.hallucination_status == "failed":
        feedback = ("部分实体检查未完成；未完成检查不是事实判断。仅修复本次选中实体在已完成检查中明确指出的问题，"
                    "未归属或其他实体的问题保留等待完整复查，不据此新增或改写事实。\n" + feedback)
    result_data, result_sources = before_data, before_sources
    try:
        if mode == "recheck":
            audit.update(status="not_attempted", reason="qa_incomplete_recheck_same_snapshot")
        elif mode == "supplement":
            result_data = await agent.async_supplement_missing_fields(
                product_name, deepcopy(before_data), missing_fields)
            result_sources = {**before_sources, **agent.get_search_texts()}
        else:
            selected = (completed_collection_repairs(before_data, qa_result)
                        if qa_result.hallucination_status == "failed"
                        else affected_collection_entities(before_data, qa_result.issues))
            audit["repair_entities"] = list(selected)
            if qa_result.hallucination_status == "failed":
                audit["incomplete_review_preserved"] = True
            repaired = await agent.async_reextract_saved_sources(
                product_name, product_description, deepcopy(selected), deepcopy(before_sources), feedback)
            if set(repaired) != set(selected):
                raise ValueError("Collection repair changed target/rival identities")
            result_data = {**before_data, **repaired}
            result_sources = before_sources
        if set(result_data) != set(before_data) or any(
                result_data[name].name != item.name for name, item in before_data.items()):
            raise ValueError("Collection repair changed target/rival identities")
        if mode == "reextract" and source_fingerprint(result_data, result_sources) != fingerprint:
            raise ValueError("Saved-source repair changed original evidence")
        if mode != "recheck":
            outcomes = agent.get_repair_outcomes()
            audit["entity_outcomes"] = outcomes
            accepted = sum(item.get("status") == "accepted" for item in outcomes)
            audit["status"] = ("accepted" if outcomes and accepted == len(outcomes)
                               else "partial" if accepted else "failed")
    except asyncio.CancelledError:
        agent.restore_source_snapshot(before_sources)
        audit.update(status="interrupted", reason="collection_repair_cancelled",
                     result_source_fingerprint=fingerprint,
                     finished_at=datetime.now().isoformat(timespec="seconds"))
        orchestrator._save_artifact_json(prefix + "_result.json", audit)
        raise
    except Exception as error:
        result_data, result_sources = before_data, before_sources
        agent.restore_source_snapshot(before_sources)
        audit.update(status="failed", reason=f"{type(error).__name__}: {str(error)[:200]}")
    audit["result_source_fingerprint"] = source_fingerprint(result_data, result_sources)
    agent.restore_source_snapshot(result_sources)
    audit["finished_at"] = datetime.now().isoformat(timespec="seconds")
    orchestrator._save_artifact_json(prefix + "_result.json", audit)
    return result_data, result_sources, feedback
