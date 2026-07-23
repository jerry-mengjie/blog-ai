-- ===================================================================
-- 迁移: 用户文章浏览统计表 tb_user_browse (已有库增量执行)
-- ===================================================================

USE `blog_ai`;

CREATE TABLE IF NOT EXISTS `tb_user_browse` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `user_id` BIGINT UNSIGNED NOT NULL COMMENT '用户ID',
  `article_id` BIGINT UNSIGNED NOT NULL COMMENT '文章ID',
  `view_count` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '浏览总次数',
  `total_duration` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '总时长(秒)',
  `best_duration` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '单次最长浏览时长(秒)',
  `best_browse_time` DATETIME NULL DEFAULT NULL COMMENT '最好浏览时间(最长那次发生时刻)',
  `last_browse_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最近浏览时间',
  `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '首次记录时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_browse` (`user_id`, `article_id`),
  KEY `idx_user_last` (`user_id`, `last_browse_time`),
  KEY `idx_article` (`article_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用户文章浏览统计表';
