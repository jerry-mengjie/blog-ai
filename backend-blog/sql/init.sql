-- ===================================================================
-- 博客系统数据库初始化脚本 (MySQL 9.7)
-- 数据库名: blog_ai   字符集: utf8mb4   引擎: InnoDB
-- 设计要点: 主键自增 BIGINT、合理索引、覆盖查询、避免大字段拖慢列表查询
-- ===================================================================

-- 创建数据库, 名称含连字符需用反引号包裹, 指定 utf8mb4 以支持 emoji 与多语言
CREATE DATABASE IF NOT EXISTS blog_ai
DEFAULT CHARACTER SET utf8mb4
COLLATE utf8mb4_0900_ai_ci;
-- 切换到目标数据库
USE `blog_ai`;

-- -------------------------------------------------------------------
-- 1. 用户表 tb_user
-- -------------------------------------------------------------------
-- 若已存在则先删除, 便于反复初始化(生产环境慎用)
DROP TABLE IF EXISTS `tb_user`;
-- 创建用户表
CREATE TABLE `tb_user` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '用户主键ID',
  `username` VARCHAR(50) NOT NULL COMMENT '登录用户名(唯一)',
  `password` VARCHAR(100) NOT NULL COMMENT '密码(bcrypt加密存储)',
  `nickname` VARCHAR(50) NOT NULL DEFAULT '' COMMENT '昵称',
  `avatar` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '头像URL',
  `email` VARCHAR(100) NOT NULL DEFAULT '' COMMENT '邮箱',
  `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `status` TINYINT NOT NULL DEFAULT 1 COMMENT '状态: 1正常 0禁用',
  `is_admin` TINYINT NOT NULL DEFAULT 0 COMMENT '是否管理员: 1是 0否',
  PRIMARY KEY (`id`),                                  -- 主键索引
  UNIQUE KEY `uk_username` (`username`),               -- 用户名唯一索引, 加速登录查询并防重
  KEY `idx_email` (`email`),                           -- 邮箱普通索引, 加速找回密码等场景
  -- 复合索引: 管理端列表常用「状态过滤 + 创建时间倒序」, 命中索引避免 filesort
  KEY `idx_status_create` (`status`, `create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用户表';

-- -------------------------------------------------------------------
-- 2. 分类表 tb_category
-- -------------------------------------------------------------------
DROP TABLE IF EXISTS `tb_category`;
CREATE TABLE `tb_category` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '分类主键ID',
  `name` VARCHAR(50) NOT NULL COMMENT '分类名称',
  `sort` INT NOT NULL DEFAULT 0 COMMENT '排序值(越小越靠前)',
  `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),                                  -- 主键索引
  UNIQUE KEY `uk_name` (`name`),                       -- 分类名唯一, 防止重复分类
  KEY `idx_sort` (`sort`)                              -- 排序字段索引, 加速按 sort 排序的列表查询
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='分类表';

-- -------------------------------------------------------------------
-- 3. 标签表 tb_tag
-- -------------------------------------------------------------------
DROP TABLE IF EXISTS `tb_tag`;
CREATE TABLE `tb_tag` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '标签主键ID',
  `name` VARCHAR(50) NOT NULL COMMENT '标签名称',
  PRIMARY KEY (`id`),                                  -- 主键索引
  UNIQUE KEY `uk_name` (`name`)                        -- 标签名唯一索引
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='标签表';

-- -------------------------------------------------------------------
-- 4. 文章表 tb_article
-- -------------------------------------------------------------------
DROP TABLE IF EXISTS `tb_article`;
CREATE TABLE `tb_article` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '文章主键ID',
  `user_id` BIGINT UNSIGNED NOT NULL COMMENT '作者用户ID',
  `title` VARCHAR(200) NOT NULL COMMENT '文章标题',
  `cover` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '封面图URL',
  `content` LONGTEXT COMMENT '文章正文(大字段, 列表查询时不应 SELECT *)',
  `summary` VARCHAR(500) NOT NULL DEFAULT '' COMMENT '文章摘要',
  `category_id` BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '分类ID',
  `view_count` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '浏览量',
  `is_top` TINYINT NOT NULL DEFAULT 0 COMMENT '是否置顶: 1是 0否',
  `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `status` TINYINT NOT NULL DEFAULT 1 COMMENT '状态: 1已发布 0草稿/下架',
  PRIMARY KEY (`id`),                                  -- 主键索引
  KEY `idx_user` (`user_id`),                          -- 作者索引, 加速查询某人的文章
  KEY `idx_category` (`category_id`),                  -- 分类索引, 加速按分类筛选
  -- 复合索引: 列表页常用 "状态过滤 + 置顶优先 + 时间倒序", 命中索引避免 filesort
  KEY `idx_status_top_time` (`status`, `is_top`, `create_time`),
  -- 标题前缀索引, 兼顾搜索与索引体积(全文检索可改用 FULLTEXT)
  KEY `idx_title` (`title`(64)),
  -- 推荐兜底"最新文章": 状态过滤 + 时间倒序, 命中索引避免 filesort
  KEY `idx_status_create` (`status`, `create_time`),
  -- 推荐兜底"热门文章": 状态过滤 + 浏览量倒序, 命中索引避免 filesort
  KEY `idx_status_view` (`status`, `view_count`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='文章表';

-- -------------------------------------------------------------------
-- 5. 文章-标签 中间表 tb_article_tag (多对多)
-- -------------------------------------------------------------------
DROP TABLE IF EXISTS `tb_article_tag`;
CREATE TABLE `tb_article_tag` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `article_id` BIGINT UNSIGNED NOT NULL COMMENT '文章ID',
  `tag_id` BIGINT UNSIGNED NOT NULL COMMENT '标签ID',
  PRIMARY KEY (`id`),                                  -- 主键索引
  UNIQUE KEY `uk_article_tag` (`article_id`, `tag_id`),-- 防止同一文章重复绑定同一标签
  KEY `idx_tag` (`tag_id`)                             -- 按标签反查文章列表
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='文章标签关联表';

-- -------------------------------------------------------------------
-- 6. 评论表 tb_comment
-- -------------------------------------------------------------------
DROP TABLE IF EXISTS `tb_comment`;
CREATE TABLE `tb_comment` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '评论主键ID',
  `article_id` BIGINT UNSIGNED NOT NULL COMMENT '所属文章ID',
  `user_id` BIGINT UNSIGNED NOT NULL COMMENT '评论用户ID',
  `parent_id` BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '父评论ID(0为顶级评论)',
  `content` VARCHAR(1000) NOT NULL COMMENT '评论内容',
  `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `status` TINYINT NOT NULL DEFAULT 1 COMMENT '状态: 1正常 0删除/屏蔽',
  PRIMARY KEY (`id`),                                  -- 主键索引
  -- 复合索引: 文章评论列表常用 "文章ID过滤 + 时间倒序"
  KEY `idx_article_time` (`article_id`, `create_time`),
  KEY `idx_user` (`user_id`)                           -- 用户维度查询索引
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='评论表';

-- -------------------------------------------------------------------
-- 7. 收藏表 tb_favorite
-- -------------------------------------------------------------------
DROP TABLE IF EXISTS `tb_favorite`;
CREATE TABLE `tb_favorite` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '收藏主键ID',
  `user_id` BIGINT UNSIGNED NOT NULL COMMENT '用户ID',
  `article_id` BIGINT UNSIGNED NOT NULL COMMENT '文章ID',
  `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '收藏时间',
  PRIMARY KEY (`id`),                                  -- 主键索引
  UNIQUE KEY `uk_user_article` (`user_id`, `article_id`), -- 防止重复收藏, 同时加速"是否已收藏"判断
  KEY `idx_article` (`article_id`)                     -- 按文章统计收藏数
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='收藏表';

-- -------------------------------------------------------------------
-- 8. 用户-兴趣标签 中间表 tb_user_tag (多对多, 复用 tb_tag 词典)
-- -------------------------------------------------------------------
DROP TABLE IF EXISTS `tb_user_tag`;
CREATE TABLE `tb_user_tag` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `user_id` BIGINT UNSIGNED NOT NULL COMMENT '用户ID',
  `tag_id` BIGINT UNSIGNED NOT NULL COMMENT '标签ID(引用 tb_tag)',
  `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '绑定时间',
  PRIMARY KEY (`id`),                                  -- 主键索引
  UNIQUE KEY `uk_user_tag` (`user_id`, `tag_id`),     -- 防止同一用户重复绑定同一标签, 同时加速「用户是否已绑某标签」
  KEY `idx_tag` (`tag_id`)                             -- 按标签反查感兴趣的用户
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用户兴趣标签关联表';

-- -------------------------------------------------------------------
-- 9. 用户-文章浏览统计表 tb_user_browse (累计非流水)
-- -------------------------------------------------------------------
DROP TABLE IF EXISTS `tb_user_browse`;
CREATE TABLE `tb_user_browse` (
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
  -- 同一用户同一文章一行, 支撑 ON DUPLICATE KEY UPDATE 原子累计
  UNIQUE KEY `uk_user_browse` (`user_id`, `article_id`),
  -- 我的足迹: 用户过滤 + 最近浏览倒序
  KEY `idx_user_last` (`user_id`, `last_browse_time`),
  -- 按文章反查读者/统计
  KEY `idx_article` (`article_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用户文章浏览统计表';

-- -------------------------------------------------------------------
-- 初始化种子数据
-- -------------------------------------------------------------------
-- 默认管理员账号 admin, 密码为 admin123 的 bcrypt 哈希(已验证, 可在后端登录后修改)
INSERT INTO `tb_user` (`username`, `password`, `nickname`, `email`, `is_admin`) VALUES
('admin', '$2b$12$upupx/uFJyRtLW0n72QXQu12rGBmagzTQG5rhuZAkh2CP8OyGQGEa', '超级管理员', 'admin@blog.ai', 1);
-- 默认分类
INSERT INTO `tb_category` (`name`, `sort`) VALUES ('技术', 1), ('生活', 2), ('随笔', 3);
-- 默认标签
INSERT INTO `tb_tag` (`name`) VALUES ('Vue'), ('Python'), ('FastAPI'), ('MySQL');
