"""异常定义 -- 5 个自定义业务异常类.

这个文件是干什么的:
定义项目里的业务异常. 业务代码里 raise 这些异常,
main.py 里的 @app.exception_handler 会统一捕获并转成规范的 JSON 响应.

为什么不用 FastAPI 自带的 HTTPException:
自定义异常能让错误码 (code) 更语义化, 比如 4010 鉴权失败, 5001 出题失败,
前端可以根据 code 做不同处理 (如 4010 时清除本地登录态).
"""


class QuizGenerationError(Exception):
    """题库生成失败 (对应 code 5001)"""

    def __init__(self, message: str = "题库生成失败，请稍后重试"):
        self.message = message
        super().__init__(self.message)


class ReportGenerationError(Exception):
    """报告生成失败 (对应 code 5002)"""

    def __init__(self, message: str = "报告生成失败，请稍后重试"):
        self.message = message
        super().__init__(self.message)


class ContentFilterError(Exception):
    """内容过滤异常 -- 输入含敏感词 (对应 code 4000)"""

    def __init__(self, message: str = "输入内容包含敏感词，请修改后重试"):
        self.message = message
        super().__init__(self.message)


class AuthenticationError(Exception):
    """鉴权失败 (对应 code 4010)"""

    def __init__(self, message: str = "未登录或登录已过期"):
        self.message = message
        super().__init__(self.message)


class KnowledgeBaseError(Exception):
    """知识库操作异常 -- 格式/大小/数量校验失败, 文档不存在或未就绪等 (对应 code 4001)"""

    def __init__(self, message: str = "知识库操作失败"):
        self.message = message
        super().__init__(self.message)
