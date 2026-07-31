"""RocketMQ 模块: 浏览统计异步解耦(经典 Producer + SimpleConsumer 方案)。

链路: API 校验后投递消息立即返回 → Worker 消费 → MySQL 原子写入。
未配置 ROCKETMQ_ENDPOINTS 或投递失败时回落同步写库, 保证本地无 MQ 也能跑通。
"""
