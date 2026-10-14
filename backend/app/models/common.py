"""通用响应模型 -- 统一的后端响应格式.

这个文件是干什么的:
所有接口都返回这个 ApiResponse 结构, 保证前端拿到的永远是 {code, message, data}.
code=0 表示成功, 非 0 表示失败 (不同 code 代表不同错误类型).
"""

from typing import Any, Optional
from pydantic import BaseModel


class ApiResponse(BaseModel):
    """统一响应体: code (0 成功) + message + data."""
    code: int = 0
    message: str = "ok"
    data: Optional[Any] = None

    @classmethod
    def success(cls, data: Any = None, message: str = "ok") -> "ApiResponse":
        """构造成功响应 (code=0)."""
        return cls(code=0, message=message, data=data)

    @classmethod
    def error(cls, code: int, message: str) -> "ApiResponse":
        """构造失败响应 (code 非 0)."""
        return cls(code=code, message=message, data=None)
