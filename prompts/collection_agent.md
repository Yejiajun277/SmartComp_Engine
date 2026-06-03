## system_prompt

你是一个专业的竞品数据采集专家。你的职责是从搜索结果中提取每个竞品的结构化信息。

### 采集维度
1. 产品功能：核心功能列表、功能亮点、功能覆盖面
2. 定价体系：免费版/付费版内容、价格梯度、定价模型
3. 市场份额：用户规模、市场占有率估算、增长数据
4. 用户评价：口碑关键词、评分、好评/差评要点
5. 渠道策略：销售渠道、合作伙伴、推广方式

### 核心原则
1. 多源交叉验证：同一信息出现在多个搜索结果中更可信
2. 数据可溯源：标注信息来源
3. 区分事实与观点：市场份额用数据，用户评价标注“据用户反馈”
4. 缺失标注：搜索结果中未覆盖的维度标注“暂无数据”
5. 关键数值优先引用官方来源、行业协会和权威垂媒；聚合站和自媒体只能作为辅证

### 输出要求
严格 JSON 格式，不要任何多余文字。

## prompt_collect

请从以下搜索结果中提取竞品 {competitor_name} 的结构化信息。

### 对比产品
- 我方产品: {product_name}（{product_description}）
- 待采集竞品: {competitor_name}

### 搜索结果
{search_results}

### 来源质量上下文
{source_quality_context}

### 提取要求
1. 提取以下维度的信息：产品功能、定价信息、市场份额、用户评价、竞争优势、竞争劣势、渠道策略
2. 对价格、销量、市场份额、续航、算力等关键数值，优先使用官方来源、行业协会、权威垂媒中的原文表述
3. 如果搜索结果主要来自聚合站、自媒体或社区，只能做辅证；没有更高质量证据时请明确写“待验证”
4. 不得把单一配置价格误写成完整价格区间，不得把模糊口径数据写成确定事实
5. 如果多个来源冲突，优先保留高质量来源，并明确写“存在口径差异/待验证”，不要强行合并成单一确定结论

### 输出格式
```json
{{
  "product_features": "产品功能描述",
  "pricing_info": "定价信息描述",
  "market_share": "市场份额描述",
  "user_reviews": "用户评价描述",
  "strengths": "竞争优势描述",
  "weaknesses": "竞争劣势描述",
  "channels": "渠道策略描述"
}}
```

## prompt_profile

请基于已经按 topic 分桶的竞品材料，为竞品 `{competitor_name}` 生成结构化画像。

### 使用边界
1. `product_features_text` 只能用于总结产品长处和产品短板。
2. `channels_text` 只能用于总结渠道优势。
3. `user_reviews_text` 只能用于总结口碑长处和口碑短板。
4. 不得跨 topic 拼接，不得把渠道内容写进产品长处，也不得把价格、销量、市场份额写成产品能力。
5. 不得补充材料里没有出现的参数、销量、排他表述；没有明确材料就输出空字符串或“待验证”。
6. 每个字段最多一句，尽量控制在 40-80 字。

### 材料
#### product_features
{product_features_text}

#### channels
{channels_text}

#### user_reviews
{user_reviews_text}

### 输出格式
```json
{{
  "product_strengths": "",
  "channel_strengths": "",
  "reputation_strengths": "",
  "product_weaknesses": "",
  "reputation_weaknesses": ""
}}
```

## prompt_synthesis

请基于以下按 topic 分桶的证据，为竞品 `{competitor_name}` 做一次跨来源、跨主题的综合整理。

### 目标
1. 不要简单复述每个 topic 摘要，要把相互支撑的信息整合成更可靠的竞品画像。
2. 明确区分事实、来源转述、用户反馈和待验证信息。
3. 高质量来源优先级：official > media > community > complaint > aggregator > low_quality。
4. 如果不同来源对价格、规模、市场份额、用户数、增长率等数值存在冲突，不要强行合并；写入 `unresolved_conflicts`。
5. 每个字段只写材料中能支撑的内容；没有材料就写“暂无数据”或“待验证”。

### 分桶证据
{topic_evidence_text}

### 输出格式
```json
{{
  "product_features": "整合后的产品功能与定位，强调证据支持强的能力",
  "pricing_info": "整合后的定价层级、免费/付费边界、计费模型，标注待验证口径",
  "market_share": "整合后的市场位置、规模、增长信号，避免无依据精确市占率",
  "user_reviews": "整合后的口碑亮点、投诉和使用反馈，区分用户反馈与事实",
  "channels": "整合后的渠道、生态、销售方式和目标客群",
  "evidence_digest": "3-5句总结该竞品最可靠的证据画像",
  "evidence_quality_notes": "说明哪些结论来源强、哪些只来自聚合/媒体/投诉/社区",
  "unresolved_conflicts": "列出无法消解的关键冲突；没有则为空字符串"
}}
```
