<script setup>
// 关于页为纯静态展示, 无需逻辑
</script>

<template>
  <div class="app-page">
    <!-- 顶部标题 -->
    <van-nav-bar title="关于本站" fixed placeholder />

    <!-- 站点介绍卡片 -->
    <div class="about">
      <!-- LOGO -->
      <van-image round width="80" height="80" src="https://picsum.photos/120/120" />
      <!-- 站名 -->
      <h2 class="name">AI 博客</h2>
      <!-- 版本 -->
      <div class="ver">v1.0.0</div>
      <!-- 介绍文字 -->
      <p class="desc">
        这是一个基于 Vue3 + Vant 构建的移动端博客系统,
        后端采用 FastAPI + MySQL, 支持文章浏览、搜索、评论与收藏。
      </p>
      <!-- 信息列表 -->
      <van-cell-group inset>
        <van-cell title="技术栈" value="Vue3 / Vant / FastAPI" />
        <van-cell title="数据库" value="MySQL 9.7" />
        <van-cell title="联系邮箱" value="admin@blog.ai" />
      </van-cell-group>
    </div>
  </div>
</template>

<style scoped>
/* 关于容器居中 */
.about { text-align: center; padding: 30px 16px; }
.name { margin: 14px 0 4px; }
.ver { color: #969799; font-size: 13px; margin-bottom: 16px; }
.desc { font-size: 14px; line-height: 1.8; color: #646566; margin-bottom: 24px; text-align: left; }
</style>
