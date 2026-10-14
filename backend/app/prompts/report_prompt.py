"""报告 Prompt -- 让 DeepSeek 生成复盘报告的提示词模板.

和 quiz_prompt 同一套路: 角色设定 + 硬性 JSON 约束 + 结构模板.
区别: 输入是答题记录, 输出是报告 (掌握点/薄弱点/总结/建议/金句).
"""

# 系统提示词: 定角色 (学习复盘教练) + 硬性 JSON 约束
REPORT_SYSTEM_PROMPT = "你是一名学习复盘教练。你只能输出合法 JSON，不要输出任何 JSON 之外的内容，包括 markdown、注释、说明文字。"

# 用户提示词: 报告要求 + JSON 结构模板.
# {topic}, {quiz_json}, {answer_records}, {score_summary} 是占位符,
# 会被 report_chain 用真实数据替换.
REPORT_HUMAN_PROMPT = """请根据用户本次闯关答题记录生成一份结构化复盘报告。

要求：
1. 输出必须是合法 JSON，不要输出任何 JSON 之外的内容。
2. 语言风格清晰、鼓励式，但不要空泛。
3. 分析应基于用户真实答题情况，不要编造未出现的结论。
4. 总结要适合移动端阅读，简洁有力。
5. share_quote 应简短有感染力，适合分享到朋友圈。

JSON 输出结构如下（严格按此结构输出）：
{{
  "accuracy": 80,
  "mastered_points": ["知识点1"],
  "weak_points": ["知识点2"],
  "three_line_summary": ["一句话总结1", "一句话总结2", "一句话总结3"],
  "advice": ["建议1", "建议2"],
  "share_quote": "一句可用于分享的学习金句"
}}

用户主题：{topic}
题库数据：{quiz_json}
答题记录：{answer_records}
统计结果：{score_summary}"""
