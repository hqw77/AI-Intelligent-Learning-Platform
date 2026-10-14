"""出题 Prompt -- 让 DeepSeek 生成闯关题目的提示词模板.

这套提示词的核心:
1. 角色设定: 让 LLM 扮演「AI 学习教练」
2. 硬性约束: 只能输出合法 JSON (结构化输出的第一层保险)
3. 出题规则: 题型比例, 选项数量, 难度等
4. JSON 结构模板: 给出标准输出格式, 让 LLM 照着填
"""

# 系统提示词: 定角色 + 硬性要求 (只输出 JSON, 优先用参考资料)
QUIZ_SYSTEM_PROMPT = "你是一名专业的 AI 学习教练。你只能输出合法 JSON，不要输出任何 JSON 之外的内容，包括 markdown、注释、说明文字。当提供了参考资料时，必须优先基于参考资料出题，确保知识的准确性和时效性。"

# 用户提示词: 具体的出题要求 + JSON 结构模板.
# 注意里面的 {{ }} 是 LangChain 模板的转义: {{ 会被渲染成字面 {,
# 因为 {question_count} 这样的单花括号是「占位符」, 要被真实值替换.
QUIZ_HUMAN_PROMPT = """请根据用户提供的学习内容生成一组用于小程序闯关答题的题目。

要求：
1. 输出必须是合法 JSON，不要输出任何 JSON 之外的内容。
2. 题目总数为 {question_count} 题。
3. 题型包含：单选题(single)、多选题(multiple)、判断题(judge)，比例大致为 3:1:1。
4. 每道题必须包含：题目编号(id)、题型(type)、题干(stem)、选项(options)、正确答案(answer)、详细讲解(explanation)、知识点标签(knowledge_point)、难度(difficulty)。
5. 讲解必须适合初学者阅读，避免过度学术化。
6. 如果用户输入内容过短，可以基于常识进行合理补充，但不要偏离主题。
7. 难度要求：{difficulty}。
8. 判断题选项固定为 A 正确、B 错误。
9. 多选题的正确答案至少 2 个。
10. difficulty 只能取值 easy、medium、hard。

JSON 输出结构如下（严格按此结构输出）：
{{
  "title": "学习主题",
  "summary": "本次题库的主题摘要",
  "questions": [
    {{
      "id": "q1",
      "type": "single",
      "stem": "题干",
      "options": [
        {{"key": "A", "text": "选项A"}},
        {{"key": "B", "text": "选项B"}},
        {{"key": "C", "text": "选项C"}},
        {{"key": "D", "text": "选项D"}}
      ],
      "answer": ["A"],
      "explanation": "详细讲解",
      "knowledge_point": "知识点",
      "difficulty": "easy"
    }}
  ]
}}

{search_context_section}
用户学习内容如下：
{user_input}"""

# 搜索上下文模板: 把联网搜索/RAG 拿到的参考资料塞进提示词.
# 占位符 {search_context} 会被替换成实际的参考资料文本.
SEARCH_CONTEXT_TEMPLATE = """以下是通过联网搜索获取的参考资料，请优先基于这些资料出题，确保知识准确性：

{search_context}
"""
