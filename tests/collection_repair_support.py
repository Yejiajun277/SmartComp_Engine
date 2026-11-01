"""Explicit QA fixtures and conversion of legacy test facts into item patches."""
from copy import deepcopy
from core.collection_repair_plan import ARRAY_FIELDS, build_collection_repair_plan, item_id
from models.domain import CompetitorData, QualityIssue


def reviewed_plan(data, fields=None):
    fields = fields or [*ARRAY_FIELDS, *CompetitorData.TEXT_FIELDS]
    fields = [path for field in fields for path in (
        [f"{field}[*].{attribute}" for attribute in ARRAY_FIELDS[field] if attribute != "features"]
        if field in ARRAY_FIELDS else [field])]
    return build_collection_repair_plan(data, [QualityIssue("critical", "citation", f"{name}.{field}",
        "This saved field has an independently recorded QA scope/citation finding.")
        for name in data for field in fields])


def wire_patch(data, payload):
    result = deepcopy(payload)
    if not isinstance(result, dict):
        return result
    original = next(iter(data.values()))
    for field in ARRAY_FIELDS:
        if not isinstance(result.get(field), list):
            continue
        rows = getattr(original, field)
        # Explicit field patches do not repeat an unchanged nested condition
        # array. Condition edits require a separate, precise nested protocol.
        for index, row in enumerate(result[field]):
            if (isinstance(row, dict) and index < len(rows) and field == "pricing_tiers"
                    and row.get("features") == rows[index].features):
                row.pop("features", None)
        result[field] = [{"item_id": item_id(field, i, rows[i]), "changes": row}
                         if i < len(rows) and isinstance(row, dict) else {"add": row}
                         for i, row in enumerate(result[field])]
    return result
