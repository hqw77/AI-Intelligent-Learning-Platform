"""用户相关数据模型 -- 用 Pydantic 定义用户和闯关历史的结构."""

from typing import Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """登录请求 -- 前端传 wx.login 拿到的 code."""
    code: str = Field(min_length=1, description="wx.login() 返回的 code")


class LoginResponse(BaseModel):
    """登录响应 -- token + 用户简要信息."""
    token: str
    user: "UserBrief"


class UserBrief(BaseModel):
    """用户简要信息 (首页展示用)."""
    id: int
    nickname: str
    avatar_url: str
    total_xp: int  # 累计经验值


class UserProfile(BaseModel):
    """用户完整档案 (个人中心展示用, 含统计)."""
    id: int
    nickname: str
    avatar_url: str
    total_xp: int
    quiz_count: int          # 闯关次数
    correct_count: int       # 答对题数
    average_accuracy: int    # 平均正确率


class UpdateProfileRequest(BaseModel):
    """更新资料请求 (昵称/头像, 都可选)."""
    nickname: Optional[str] = Field(default=None, max_length=100)
    avatar_url: Optional[str] = Field(default=None, max_length=500)


class QuizHistoryItem(BaseModel):
    """闯关历史列表项."""
    quiz_id: str
    title: str
    accuracy: float
    question_count: int
    created_at: str


class QuizHistoryList(BaseModel):
    """闯关历史列表 (分页)."""
    items: list[QuizHistoryItem]
    total: int
    page: int
    page_size: int


class QuizDetailResponse(BaseModel):
    """单次闯关详情 (含题目, 答题记录, 报告, 用于回看)."""
    quiz_id: str
    title: str
    summary: str
    user_input: Optional[str] = None
    questions: list  # 题目列表 (raw JSON)
    answer_records: Optional[list] = None  # 答题记录
    report: Optional[dict] = None          # 复盘报告
    created_at: str
