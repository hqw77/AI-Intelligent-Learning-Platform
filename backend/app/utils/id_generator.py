"""ID 生成工具 -- 生成各种业务 ID.

用 uuid4 (随机) 生成 ID, 保证全局唯一, 不需要数据库自增.
格式: quiz_ + 12 位随机十六进制, 如 quiz_89897927ab5d.
"""

import uuid


def gen_quiz_id() -> str:
    """生成 quiz_id (题库编号)."""
    return f"quiz_{uuid.uuid4().hex[:12]}"
