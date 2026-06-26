"""统一响应结构: 前端约定 {code, message, data} 格式。"""

# 导入类型注解
from typing import Any

# 导入 Pydantic 泛型支持
from pydantic import BaseModel


# 统一响应模型, code=0 表示成功, 非 0 表示业务错误
class Result(BaseModel):
    # 业务状态码, 0 成功
    code: int = 0
    # 提示信息
    message: str = "success"
    # 数据载荷, 任意结构
    data: Any = None


# 成功响应快捷构造函数
def ok(data: Any = None, message: str = "success") -> Result:
    # 返回 code=0 的结果
    return Result(code=0, message=message, data=data)


# 失败响应快捷构造函数
def fail(message: str = "error", code: int = 1, data: Any = None) -> Result:
    # 返回非 0 code 的结果
    return Result(code=code, message=message, data=data)
