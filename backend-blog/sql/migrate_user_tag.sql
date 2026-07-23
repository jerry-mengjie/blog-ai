-- ===================================================================
-- 迁移: 用户兴趣标签 + 用户列表复合索引 (已有库增量执行)
-- 适用: 已按旧版 init.sql 建库、不想全量重建的环境
-- 说明: 可重复执行时请先确认索引/表是否已存在; 本脚本默认一次性执行
-- ===================================================================

USE `blog_ai`;

-- 1. 用户表增加管理端列表复合索引(状态过滤 + 时间倒序)
-- 若索引已存在会报 Duplicate key name, 可忽略或先 DROP
ALTER TABLE `tb_user`
  ADD KEY `idx_status_create` (`status`, `create_time`);

-- 2. 用户-兴趣标签关联表(复用 tb_tag, 不另建标签名)
CREATE TABLE IF NOT EXISTS `tb_user_tag` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `user_id` BIGINT UNSIGNED NOT NULL COMMENT '用户ID',
  `tag_id` BIGINT UNSIGNED NOT NULL COMMENT '标签ID(引用 tb_tag)',
  `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '绑定时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_tag` (`user_id`, `tag_id`),
  KEY `idx_tag` (`tag_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用户兴趣标签关联表';
