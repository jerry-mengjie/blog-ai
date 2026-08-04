-- ===================================================================
-- 迁移: 文章列表按分类复合索引 idx_status_cat_top_time (已有库增量执行)
-- 用途: /api/article/list?category_id= 排序 is_top DESC, create_time DESC 免 filesort
-- ===================================================================

USE `blog_ai`;

-- 若不存在则添加(重复执行会报 Duplicate key name, 可忽略或先检查)
ALTER TABLE `tb_article`
  ADD KEY `idx_status_cat_top_time` (`status`, `category_id`, `is_top`, `create_time`);
