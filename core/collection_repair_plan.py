"""Compile structured QA ownership into bounded, snapshot-bound fact patches."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import re
import unicodedata

from models.domain import CompetitorData, FeatureItem, PricingTier


ARRAY_FIELDS = {"product_features": ("name", "description", "citations"),
                "pricing_tiers": ("tier_name", "price", "features", "citations")}


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def item_id(field, index, item):
    return f"{field}[{index}]@{_digest(asdict(item))}"


def _key(value):
    return unicodedata.normalize("NFKC", value).strip().casefold()


def build_collection_repair_plan(data, issues):
    """Only issue.field grants authority; prose, expected and suggestions do not."""
    plans = {name: {"version": 1, "snapshot_sha256": _digest(asdict(value)),
                    "text_fields": [], "arrays": {}, "unresolved": []}
             for name, value in data.items()}
    for issue in issues:
        path = getattr(issue, "field", None)
        if not isinstance(path, str):
            continue
        owners = [name for name in data if path == name or path.startswith(name + ".")]
        if len(owners) != 1:
            for plan in plans.values():
                plan["unresolved"].append({"field": path, "reason": "unowned_or_ambiguous_entity"})
            continue
        name = owners[0]
        plan, original = plans[name], data[name]
        tail = path[len(name) + 1:]
        if tail in CompetitorData.TEXT_FIELDS:
            if tail not in plan["text_fields"]:
                plan["text_fields"].append(tail)
            continue
        match = re.fullmatch(r"(product_features|pricing_tiers)(?:\[([^\[\]]+)\]|（([^（）]+)）)?(?:\.(\w+))?", tail)
        if not match:
            plan["unresolved"].append({"field": path, "reason": "unsupported_field_path"})
            continue
        field, bracket, parenthesis, attribute = match.groups()
        selector = bracket if bracket is not None else parenthesis
        # A broad field finding never says which existing facts are wrong.
        # Completeness may append missing records, but cannot rewrite old ones.
        if attribute is None:
            if selector is None and getattr(issue, "category", "") == "completeness":
                plan["arrays"].setdefault(field, {"items": {}, "allow_add": True})["allow_add"] = True
            else:
                plan["unresolved"].append({"field": path, "reason": "missing_precise_item_attribute"})
            continue
        if selector is None:
            plan["unresolved"].append({"field": path, "reason": "missing_item_selector"})
            continue
        # Nested condition arrays need their own element update protocol. Until
        # supported, retain the explicit gap instead of deleting other benefits.
        if attribute == "features":
            plan["unresolved"].append({"field": path, "reason": "unsupported_nested_array_path"})
            continue
        if attribute and attribute not in ARRAY_FIELDS[field]:
            plan["unresolved"].append({"field": path, "reason": "unsupported_item_attribute"})
            continue
        rows = getattr(original, field)
        if selector is None or selector == "*":
            indexes = list(range(len(rows)))
        elif re.fullmatch(r"0|[1-9][0-9]*", selector):
            indexes = [int(selector)] if int(selector) < len(rows) else []
        else:
            indexes = []
            for index, row in enumerate(rows):
                label = row.name if field == "product_features" else row.tier_name
                # Literal full labels and their explicitly delimited scope are
                # useful legacy selectors. Never use fuzzy/substring matching.
                aliases = [label, re.split(r"[（(]", label, maxsplit=1)[0],
                           *re.findall(r"[（(]([^（）()]+)[）)]", label)]
                if _key(selector) in {_key(alias) for alias in aliases if alias.strip()}:
                    indexes.append(index)
            if len(indexes) != 1:
                indexes = []
        allow_add = False
        if not indexes and not allow_add:
            plan["unresolved"].append({"field": path, "reason": "missing_or_ambiguous_item"})
            continue
        array = plan["arrays"].setdefault(field, {"items": {}, "allow_add": False})
        array["allow_add"] = array["allow_add"] or allow_add
        for index in indexes:
            identity = item_id(field, index, rows[index])
            entry = array["items"].setdefault(identity, {"index": index, "fields": [], "issue_fields": []})
            for attr in [attribute] if attribute else ARRAY_FIELDS[field]:
                if attr not in entry["fields"]:
                    entry["fields"].append(attr)
            # A repaired claim must be able to replace its own stale evidence
            # binding. This grants no other claim or other item's text fields.
            if attribute != "citations" and "citations" not in entry["fields"]:
                entry["fields"].append("citations")
                entry["dependency_fields"] = ["citations"]
            if path not in entry["issue_fields"]:
                entry["issue_fields"].append(path)
    return plans


def repair_changes(original, candidate):
    """Actual fact diffs are separate from the immutable source fingerprint."""
    changed_fields, changed_items, preserved_items = [], [], []
    for field in (*CompetitorData.TEXT_FIELDS, *ARRAY_FIELDS):
        if getattr(original, field) != getattr(candidate, field):
            changed_fields.append(field)
    for field in ARRAY_FIELDS:
        before, after = getattr(original, field), getattr(candidate, field)
        for index, row in enumerate(before):
            identity = item_id(field, index, row)
            (preserved_items if index < len(after) and row == after[index] else changed_items).append(identity)
        changed_items.extend(f"added:{item_id(field, index, row)}"
                             for index, row in enumerate(after) if index >= len(before))
    return {"applied_fields": changed_fields, "changed_item_ids": changed_items,
            "preserved_item_ids": preserved_items,
            "preserved_fields": [field for field in (*ARRAY_FIELDS, *CompetitorData.TEXT_FIELDS)
                                 if field not in changed_fields]}


def apply_collection_repair_patch(original, result, plan, visible_ids):
    """Validate the whole entity patch before returning any candidate changes."""
    errors, candidate = [], deepcopy(original)

    def error(path, reason, value=None):
        errors.append({"field": path, "reason": reason, "actual_type": type(value).__name__})

    if (not isinstance(plan, dict) or plan.get("version") != 1
            or plan.get("snapshot_sha256") != _digest(asdict(original))):
        error("$", "missing_or_stale_repair_plan", plan)
        return candidate, errors
    if not isinstance(result, dict) or not result:
        error("$", "empty_or_invalid_patch", result)
        return candidate, errors
    allowed = set(plan["text_fields"]) | set(plan["arrays"])
    for field, value in result.items():
        if field not in allowed:
            error(field, "unauthorized_field", value)
            continue
        if field in plan["text_fields"]:
            if not isinstance(value, str):
                error(field, "invalid_type", value)
            else:
                setattr(candidate, field, value)
            continue
        if not isinstance(value, list):
            error(field, "invalid_type", value)
            continue
        array, seen, additions = plan["arrays"][field], set(), set()
        for offset, operation in enumerate(value):
            path = f"{field}[{offset}]"
            if not isinstance(operation, dict):
                error(path, "invalid_operation", operation)
                continue
            adding = set(operation) == {"add"}
            if adding:
                if not array["allow_add"]:
                    error(path, "unauthorized_add", operation)
                    continue
                changes, attributes = operation["add"], set(ARRAY_FIELDS[field])
                if not isinstance(changes, dict) or set(changes) != attributes:
                    error(path, "incomplete_added_item", changes)
                    continue
                current = FeatureItem() if field == "product_features" else PricingTier("")
            else:
                if set(operation) != {"item_id", "changes"} or not isinstance(operation.get("item_id"), str):
                    error(path, "invalid_update_operation", operation)
                    continue
                identity = operation["item_id"]
                if identity in seen or identity not in array["items"]:
                    error(path, "duplicate_or_unauthorized_item_id", identity)
                    continue
                seen.add(identity)
                entry = array["items"][identity]
                index = entry["index"]
                if (index >= len(getattr(original, field))
                        or item_id(field, index, getattr(original, field)[index]) != identity):
                    error(path, "stale_item_id", identity)
                    continue
                current = deepcopy(getattr(candidate, field)[index])
                changes, attributes = operation["changes"], set(entry["fields"])
                if not isinstance(changes, dict) or not changes:
                    error(path, "empty_or_invalid_item_changes", changes)
                    continue
            for attr, updated in changes.items():
                if attr not in attributes:
                    error(f"{path}.{attr}", "unauthorized_item_attribute", updated)
                    continue
                if attr in ("features", "citations"):
                    valid = isinstance(updated, list)
                    if valid:
                        bad_items = [(index, part) for index, part in enumerate(updated) if not isinstance(part, str)]
                        for index, part in bad_items:
                            error(f"{path}.{attr}[{index}]", "invalid_type", part)
                        if bad_items:
                            continue
                else:
                    valid = isinstance(updated, str)
                if not valid:
                    error(f"{path}.{attr}", "invalid_type", updated)
                    continue
                if attr == "citations" and any(cid not in visible_ids for cid in updated):
                    error(f"{path}.{attr}", "unknown_source_id", updated)
                    continue
                setattr(current, attr, deepcopy(updated))
            if adding:
                identity = _digest(asdict(current))
                label = current.name if field == "product_features" else current.tier_name
                if not label.strip() or identity in additions or current in getattr(candidate, field):
                    error(path, "empty_or_duplicate_added_item", operation)
                    continue
                additions.add(identity)
                getattr(candidate, field).append(current)
            else:
                getattr(candidate, field)[index] = current
    return (deepcopy(original) if errors else candidate), errors
