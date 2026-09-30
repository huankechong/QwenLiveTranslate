"""TranslateError 分类（分离式 MT 引擎的统一错误语义）。

借鉴 LiveCaptionsTranslator 三段式（超时/网络/HTTP 状态），摒弃其
"[ERROR] 字符串上屏"——错误对象化后由 worker 决定重试/放弃/上报。
"""


class TranslateError(Exception):
    """翻译失败。kind 决定 worker 的重试策略。"""

    def __init__(self, kind: str, detail: str = "", status: int | None = None):
        super().__init__(f"[{kind}] {detail}")
        self.kind = kind      # timeout | network | http | auth | quota | permanent
        self.detail = detail
        self.status = status  # HTTP 状态码（http 类才有）

    @property
    def retryable(self) -> bool:
        """worker 据此决定是否退避重试：
        - timeout/network/5xx/429 → 可重试
        - 401/403（key 无效）/402（余额）/其他 4xx → 永久失败不重试
        """
        if self.kind in ("timeout", "network"):
            return True
        if self.kind == "http":
            if self.status is None:
                return True
            if self.status == 429 or self.status >= 500:
                return True
            return False
        return False  # auth/quota/permanent

    def user_message(self) -> str:
        """面向用户的一行提示（不进字幕正文，只进状态行/错误标签）。"""
        if self.kind == "auth":
            return "API key 无效或未授权（401/403），请检查配置"
        if self.kind == "quota":
            return "账户余额不足（402），请充值或切换配置档"
        if self.kind == "timeout":
            return f"翻译请求超时：{self.detail}"
        if self.kind == "network":
            return f"网络异常：{self.detail}"
        if self.kind == "http":
            return f"服务返回 HTTP {self.status}"
        return str(self.detail or self.kind)


def from_http_status(status: int, body: str = "") -> TranslateError:
    """HTTP 状态码 → 分类错误（openai_compat 系引擎共用）。"""
    if status in (401, 403):
        return TranslateError("auth", body[:200], status)
    if status == 402:
        return TranslateError("quota", body[:200], status)
    return TranslateError("http", body[:200], status)
