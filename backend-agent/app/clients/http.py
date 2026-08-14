"""服务间 HTTP 客户端基类: 统一连接池、令牌与 {code, message, data} 解包。

性能要点:
1. 每个下游服务一个 AsyncClient 单例, 复用 TCP 与 keep-alive, 免去反复握手
2. 显式超时: 下游卡住时快速失败, 避免请求堆积耗尽本服务的事件循环
3. 令牌写在客户端默认请求头上, 每次调用无需重复拼装
"""

# 导入日志
import logging
# 导入类型注解
from typing import Any

# 导入异步 HTTP 客户端
import httpx

# 导入全局配置
from app.core.config import settings

# 模块日志器
logger = logging.getLogger(__name__)

# 已创建的客户端登记表, 供应用关闭时统一释放
_registry: list["ServiceClient"] = []


# 下游服务不可用时抛出的异常, 由路由层转换为 502/503
class ServiceError(RuntimeError):
    """下游服务调用失败。"""


# 服务客户端: 封装一个下游服务的地址、连接池与响应解包
class ServiceClient:
    # 初始化: 服务名(日志用)与基础地址
    def __init__(self, name: str, base_url: str, timeout: float | None = None) -> None:
        # 服务名, 出错时便于定位
        self._name = name
        # 基础地址
        self._base_url = base_url.rstrip("/")
        # 超时秒数
        self._timeout = timeout if timeout is not None else settings.HTTP_TIMEOUT
        # 延迟创建的客户端
        self._client: httpx.AsyncClient | None = None
        # 登记以便统一关闭
        _registry.append(self)

    # 获取(或创建)底层 AsyncClient
    def _ensure_client(self) -> httpx.AsyncClient:
        # 首次调用时创建
        if self._client is None:
            # 连接池与超时按配置设定
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                limits=httpx.Limits(
                    max_connections=settings.HTTP_MAX_CONNECTIONS,
                    max_keepalive_connections=settings.HTTP_MAX_CONNECTIONS // 2,
                ),
                # 服务间调用令牌, 由下游的内部路由校验
                headers={"X-Internal-Token": settings.INTERNAL_TOKEN},
            )
        # 返回客户端
        return self._client

    # 内部工具: 校验状态码并取出信封中的 data
    def _unwrap(self, resp: httpx.Response) -> Any:
        # 非 2xx 视为调用失败
        if resp.status_code >= 400:
            # 带上服务名与状态码便于排查
            raise ServiceError(f"{self._name} 返回 HTTP {resp.status_code}")
        # 解析统一信封
        body = resp.json()
        # 业务码非 0 视为失败
        if body.get("code") != 0:
            # 抛出带业务信息的异常
            raise ServiceError(f"{self._name} 业务错误: {body.get('message')}")
        # 返回数据体
        return body.get("data")

    # 发起请求并解包; 网络异常统一转为 ServiceError
    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        timeout: float | None = None,
    ) -> Any:
        # 网络层异常与业务层异常统一出口
        try:
            # 执行请求
            resp = await self._ensure_client().request(
                method, path, params=params, json=json, timeout=timeout
            )
        except httpx.HTTPError as exc:
            # 超时/连接失败等
            raise ServiceError(f"{self._name} 不可达: {exc}") from exc
        # 解包响应
        return self._unwrap(resp)

    # GET 快捷方法
    async def get(self, path: str, *, params: dict | None = None, timeout: float | None = None) -> Any:
        # 委托统一入口
        return await self.request("GET", path, params=params, timeout=timeout)

    # POST 快捷方法
    async def post(self, path: str, *, json: dict | None = None, timeout: float | None = None) -> Any:
        # 委托统一入口
        return await self.request("POST", path, json=json, timeout=timeout)

    # DELETE 快捷方法
    async def delete(self, path: str, *, timeout: float | None = None) -> Any:
        # 委托统一入口
        return await self.request("DELETE", path, timeout=timeout)

    # 释放连接池
    async def aclose(self) -> None:
        # 已创建则关闭
        if self._client is not None:
            # 关闭连接池
            await self._client.aclose()
            # 置空
            self._client = None


# 应用关闭时释放全部下游客户端连接池
async def close_all_clients() -> None:
    # 逐个关闭
    for client in _registry:
        # 单个失败不影响其余
        try:
            # 释放连接池
            await client.aclose()
        except Exception:
            # 仅告警
            logger.warning("释放服务客户端连接池失败", exc_info=True)
