# -*- coding: utf-8 -*-
"""
server/services/description_evaluator.py — 产品描述质量评估服务

改进后的评估逻辑：
1. 规则引擎优先：短且不含模糊词的输入直接当产品名搜索
2. LLM辅助：只在规则判断不确定时调用LLM
3. 搜索验证：用联网搜索确认产品是否有足够信息
4. 搜索降级：搜索失败时用规则引擎评估
5. 智能提问：根据描述推断可能的产品名，让用户确认
"""

from __future__ import annotations

import re
from core.search_client import SearchClient
from core.llm_client import async_llm_call, parse_llm_json

# 评估阈值
QUALITY_THRESHOLD = 0.7

# 搜索结果阈值
_SEARCH_RESULT_THRESHOLD = 2

# 模糊词列表 - 包含这些词的描述不是具体产品名
_VAGUE_WORDS = [
    "一个", "某", "自研", "新出", "类似", "平台", "软件", "工具", "系统",
    "应用", "APP", "产品", "服务", "解决方案", "旗下的", "开发的",
]


def _looks_like_product_name(desc: str) -> bool:
    """
    规则判断输入是否像产品名称。
    条件：
    1. 长度 < 15字
    2. 不包含模糊词
    3. 不包含描述性短语
    """
    if len(desc) >= 15:
        return False

    # 检查是否包含模糊词
    for word in _VAGUE_WORDS:
        if word in desc:
            return False

    # 检查是否包含"的"（可能是描述性短语，如"字节跳动的飞书"）
    # 但如果"的"不在中间，可能是产品名的一部分
    if "的" in desc and len(desc) > 5:
        return False

    return True


def _extract_possible_product_name(desc: str) -> str | None:
    """
    从描述中提取可能的产品名称（规则引擎）。
    例如："字节跳动的飞书" → "飞书"
    """
    # 模式1：XX的YY → YY是产品名（2-6字）
    company_pattern = r'(?:字节跳动|阿里巴巴|腾讯|百度|美团|京东|拼多多|网易|小米|华为|蚂蚁|快手|携程)的(.{2,6})$'
    match = re.search(company_pattern, desc)
    if match:
        candidate = match.group(1).strip()
        # 排除通用词
        generic_words = ["平台", "软件", "工具", "系统", "应用", "产品", "服务", "解决方案",
                         "企业协同办公", "协同办公", "办公平台"]
        if candidate not in generic_words and len(candidate) >= 2:
            return candidate

    return None


async def _llm_extract_product_name(description: str) -> dict:
    """
    用LLM从描述中提取产品名称（仅在规则引擎不确定时调用）。

    Returns:
        {"product_name": str, "is_specific": bool, "possible_names": list[str]}
    """
    prompt = """任务：从产品描述中提取产品名称。

规则：
- 如果有明确产品名称，返回该名称，is_specific=true
- 如果是模糊描述，返回空字符串，is_specific=false
- 如果能推断出可能的产品名，放入possible_names
- 只返回JSON，不要解释

```json
{"product_name": "飞书", "is_specific": true, "possible_names": []}
```
或
```json
{"product_name": "", "is_specific": false, "possible_names": ["飞书", "钉钉"]}
```"""

    try:
        result = await async_llm_call(
            system_prompt=prompt,
            user_message=f"描述：{description}",
            temperature=0.1,
            max_tokens=256,
            agent_id="DescriptionEvaluator",
        )

        content = result.get("content", "")
        if content:
            parsed = parse_llm_json(content)
            if parsed:
                return {
                    "product_name": parsed.get("product_name", ""),
                    "is_specific": parsed.get("is_specific", False),
                    "possible_names": parsed.get("possible_names", []),
                }
    except Exception as e:
        print(f"  [DescriptionEvaluator] ⚠️ LLM提取失败: {e}")

    return {"product_name": "", "is_specific": False, "possible_names": []}


async def _search_product_info(product_name: str) -> dict:
    """
    搜索产品信息。

    Returns:
        {
            "success": bool,
            "has_results": bool,
            "result_count": int,
            "summary": str,
        }
    """
    try:
        client = SearchClient()
        query = f"{product_name} 是什么 产品介绍"
        result = await client.async_search(query)

        references = result.get("references", [])
        summary = SearchClient.extract_text(result)

        return {
            "success": True,
            "has_results": len(references) >= _SEARCH_RESULT_THRESHOLD,
            "result_count": len(references),
            "summary": summary[:2000],
        }
    except Exception as e:
        print(f"  [DescriptionEvaluator] ⚠️ 搜索失败: {e}")
        return {
            "success": False,
            "has_results": False,
            "result_count": 0,
            "summary": "",
        }


def _rule_engine_evaluate(description: str) -> dict:
    """
    规则引擎评估：当搜索不可用时的降级方案。
    """
    desc = description.strip()
    desc_len = len(desc)

    # 类别关键词
    category_keywords = ["社交", "电商", "办公", "视频", "音乐", "出行", "外卖",
                         "支付", "云", "AI", "教育", "医疗", "游戏", "直播"]
    has_category = any(kw in desc for kw in category_keywords)

    # 功能关键词
    feature_keywords = ["功能", "支持", "提供", "具备", "包含", "服务", "平台", "工具", "系统", "软件"]
    has_features = any(kw in desc for kw in feature_keywords)

    # 用户关键词
    user_keywords = ["用户", "客户", "企业", "个人", "B端", "C端", "市场", "行业"]
    has_users = any(kw in desc for kw in user_keywords)

    # 计算分数（调整权重使高质量描述能通过0.7阈值）
    category_score = 0.9 if has_category else 0.5
    features_score = 0.8 if has_features else 0.4
    users_score = 0.7 if has_users else 0.3
    diff_score = 0.7 if desc_len > 30 else (0.5 if desc_len > 15 else 0.3)

    overall = category_score * 0.3 + features_score * 0.3 + users_score * 0.2 + diff_score * 0.2

    return {
        "quality_score": round(overall, 2),
        "quality": "good" if overall >= QUALITY_THRESHOLD else "insufficient",
        "missing_dimensions": [],
        "questions": [],
    }


def _generate_smart_questions(description: str, possible_names: list[str] = None) -> dict:
    """
    生成智能问题。
    如果有推断的产品名，让用户确认；否则问产品名。
    """
    questions = []

    # 如果有推断的产品名，让用户确认
    if possible_names:
        questions.append({
            "question": f"您想分析的是以下哪个产品？",
            "field": "product_name",
            "options": possible_names[:4] + ["其他产品"],
        })
    else:
        questions.append({
            "question": "您想分析的具体产品名称是什么？",
            "field": "product_name",
            "options": None,
        })

    return {
        "quality_score": 0.3,
        "quality": "insufficient",
        "missing_dimensions": ["产品名称"],
        "questions": questions,
    }


async def evaluate_description(description: str) -> dict:
    """
    评估产品描述质量。

    完整策略：
    1. 空描述 → 返回不足
    2. 规则判断像产品名 → 直接搜索验证
    3. 规则判断不像产品名 → 提取可能的产品名 → 生成智能问题
    4. 搜索失败 → 降级到规则引擎

    Args:
        description: 用户输入的产品描述

    Returns:
        {
            "quality_score": float,
            "quality": str,
            "missing_dimensions": list[str],
            "questions": list[dict],
        }
    """
    desc = description.strip()

    # 空描述
    if not desc:
        return {
            "quality_score": 0.0,
            "quality": "insufficient",
            "missing_dimensions": ["产品描述"],
            "questions": [{
                "question": "请输入您想要分析的产品名称或描述。",
                "field": "general",
                "options": None,
            }],
        }

    print(f"  [DescriptionEvaluator] 🔍 分析描述: {desc}")

    # Step 1: 规则判断是否像产品名
    if _looks_like_product_name(desc):
        print(f"  [DescriptionEvaluator] 📝 识别为产品名称，搜索验证...")
        search_info = await _search_product_info(desc)

        if search_info["success"] and search_info["has_results"]:
            print(f"  [DescriptionEvaluator] ✅ 搜索到足够信息")
            return {
                "quality_score": 0.85,
                "quality": "good",
                "missing_dimensions": [],
                "questions": [],
            }

        if not search_info["success"]:
            # 搜索失败，降级到规则引擎
            print(f"  [DescriptionEvaluator] ⚠️ 搜索失败，降级到规则引擎")
            return _rule_engine_evaluate(desc)

        # 搜索成功但结果不足
        print(f"  [DescriptionEvaluator] ❓ 搜索结果不足")
        return _generate_smart_questions(desc)

    # Step 2: 不像产品名，尝试规则提取
    possible_name = _extract_possible_product_name(desc)
    if possible_name:
        print(f"  [DescriptionEvaluator] 📝 规则提取到可能的产品名: {possible_name}")
        search_info = await _search_product_info(possible_name)

        if search_info["success"] and search_info["has_results"]:
            print(f"  [DescriptionEvaluator] ✅ 搜索到足够信息")
            return {
                "quality_score": 0.85,
                "quality": "good",
                "missing_dimensions": [],
                "questions": [],
            }

    # Step 3: 用LLM辅助提取
    print(f"  [DescriptionEvaluator] 🤖 调用LLM辅助分析...")
    llm_result = await _llm_extract_product_name(desc)

    # LLM找到了明确的产品名
    if llm_result["is_specific"] and llm_result["product_name"]:
        product_name = llm_result["product_name"]
        print(f"  [DescriptionEvaluator] 📝 LLM提取到产品名: {product_name}")
        search_info = await _search_product_info(product_name)

        if search_info["success"] and search_info["has_results"]:
            print(f"  [DescriptionEvaluator] ✅ 搜索到足够信息")
            return {
                "quality_score": 0.85,
                "quality": "good",
                "missing_dimensions": [],
                "questions": [],
            }

    # Step 4: 生成智能问题
    possible_names = llm_result.get("possible_names", [])
    if possible_name and possible_name not in possible_names:
        possible_names.insert(0, possible_name)

    print(f"  [DescriptionEvaluator] ❓ 生成补充问题")
    return _generate_smart_questions(desc, possible_names)
