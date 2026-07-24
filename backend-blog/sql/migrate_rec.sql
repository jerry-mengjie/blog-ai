-- ===================================================================
-- 推荐系统增量迁移: 为既有库补充兜底查询所需的复合索引
-- 说明: 新库执行 init.sql 已包含; tb_user_browse / tb_user_tag 表已由
--       此前的浏览足迹与兴趣标签功能建好, 推荐系统直接复用, 无需新表。
-- ===================================================================

-- 兜底"最新文章": WHERE status=1 ORDER BY create_time DESC 命中索引避免 filesort
ALTER TABLE `tb_article` ADD KEY `idx_status_create` (`status`, `create_time`);

-- 兜底"热门文章": WHERE status=1 ORDER BY view_count DESC 命中索引避免 filesort
ALTER TABLE `tb_article` ADD KEY `idx_status_view` (`status`, `view_count`);
