"""LangChain 结构化输出 Schema -- 统一导出 LLM 输出结构.

这个文件只是一个「出口」: 把 QuizOutput 和 ReportOutput 从 models 层 re-export,
方便其他模块统一从这里 import LLM 输出结构.
"""

from app.models.quiz import QuizOutput
from app.models.report import ReportOutput

__all__ = ["QuizOutput", "ReportOutput"]  # 明确声明本模块对外暴露哪些名字
