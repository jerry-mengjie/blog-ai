<script setup>
// 引入响应式 API 与生命周期
import { ref, onMounted } from 'vue'
// 引入路由
import { useRoute, useRouter } from 'vue-router'
// 引入 Vant 提示
import { showToast, showConfirmDialog } from 'vant'
// 引入接口
import { articleApi, commentApi, favoriteApi } from '../api'
// 引入用户状态
import { useUserStore } from '../store/user'

// 当前路由(取 id)
const route = useRoute()
// 路由实例
const router = useRouter()
// 用户状态
const userStore = useUserStore()

// 文章详情对象
const article = ref(null)
// 评论列表
const comments = ref([])
// 评论输入内容
const commentText = ref('')
// 是否已收藏
const favorited = ref(false)

// 文章 ID
const articleId = route.params.id

// 加载文章详情
const loadDetail = async () => {
  // 请求详情(会自动 +1 浏览量)
  article.value = await articleApi.detail(articleId)
}

// 加载评论列表
const loadComments = async () => {
  // 请求评论
  comments.value = await commentApi.list(articleId)
}

// 提交评论
const submitComment = async () => {
  // 未登录拦截
  if (!userStore.isLogin) {
    // 提示并跳转
    showToast('请先登录')
    return router.push('/personal')
  }
  // 空内容拦截
  if (!commentText.value.trim()) return showToast('请输入评论内容')
  // 调用发表评论接口
  await commentApi.add({ article_id: Number(articleId), content: commentText.value })
  // 清空输入
  commentText.value = ''
  // 提示成功
  showToast('评论成功')
  // 刷新评论
  await loadComments()
}

// 删除评论
const removeComment = async (id) => {
  // 二次确认
  await showConfirmDialog({ title: '提示', message: '确认删除该评论?' })
  // 调用删除接口
  await commentApi.del(id)
  // 刷新评论
  await loadComments()
}

// 切换收藏状态
const toggleFavorite = async () => {
  // 未登录拦截
  if (!userStore.isLogin) {
    showToast('请先登录')
    return router.push('/personal')
  }
  // 调用收藏切换接口
  const res = await favoriteApi.toggle({ article_id: Number(articleId) })
  // 更新本地收藏状态
  favorited.value = res.favorited
}

// 挂载时加载详情与评论
onMounted(async () => {
  // 并行加载
  await Promise.all([loadDetail(), loadComments()])
})
</script>

<template>
  <div class="app-page detail-page">
    <!-- 返回导航 -->
    <van-nav-bar title="文章详情" left-arrow fixed placeholder @click-left="router.back()" />

    <!-- 文章主体 -->
    <div v-if="article" class="content">
      <!-- 标题 -->
      <h1 class="title">{{ article.title }}</h1>
      <!-- 元信息 -->
      <div class="meta">
        <span>浏览 {{ article.view_count }}</span>
        <span>{{ article.create_time?.slice(0, 10) }}</span>
      </div>
      <!-- 标签 -->
      <div class="tags">
        <van-tag v-for="t in article.tags" :key="t" type="primary" plain class="tag">{{ t }}</van-tag>
      </div>
      <!-- 正文内容(纯文本展示, 如需富文本可用 v-html) -->
      <div class="article-body">{{ article.content }}</div>
    </div>

    <!-- 评论区 -->
    <div class="comments">
      <!-- 评论标题 -->
      <div class="comment-title">评论 ({{ comments.length }})</div>
      <!-- 评论列表 -->
      <div v-for="c in comments" :key="c.id" class="comment-item">
        <!-- 评论者头像 -->
        <van-image round width="36" height="36" :src="c.avatar || 'https://picsum.photos/40/40'" />
        <!-- 评论内容区 -->
        <div class="comment-main">
          <!-- 昵称 -->
          <div class="comment-nick">{{ c.nickname }}</div>
          <!-- 内容 -->
          <div class="comment-text">{{ c.content }}</div>
          <!-- 时间与删除 -->
          <div class="comment-foot">
            <span>{{ c.create_time?.slice(0, 16) }}</span>
            <span v-if="userStore.userInfo?.id === c.user_id" class="del" @click="removeComment(c.id)">删除</span>
          </div>
        </div>
      </div>
      <!-- 空状态 -->
      <van-empty v-if="!comments.length" description="暂无评论, 快来抢沙发" />
    </div>

    <!-- 底部操作栏: 评论输入 + 收藏 -->
    <div class="action-bar">
      <!-- 评论输入框 -->
      <van-field v-model="commentText" placeholder="写评论..." class="comment-input" />
      <!-- 收藏按钮 -->
      <van-icon :name="favorited ? 'star' : 'star-o'" :color="favorited ? '#ffd21e' : '#969799'" size="26" @click="toggleFavorite" />
      <!-- 发送按钮 -->
      <van-button type="primary" size="small" @click="submitComment">发送</van-button>
    </div>
  </div>
</template>

<style scoped>
/* 正文容器 */
.content { padding: 16px; background: #fff; }
/* 标题 */
.title { font-size: 20px; line-height: 1.4; }
/* 元信息 */
.meta { display: flex; gap: 16px; color: #969799; font-size: 12px; margin: 10px 0; }
/* 标签行 */
.tags { margin-bottom: 12px; }
.tag { margin-right: 6px; }
/* 正文文本 */
.article-body { font-size: 15px; line-height: 1.8; white-space: pre-wrap; }
/* 评论区 */
.comments { padding: 16px; background: #fff; margin-top: 8px; padding-bottom: 70px; }
.comment-title { font-weight: 600; margin-bottom: 12px; }
.comment-item { display: flex; gap: 10px; margin-bottom: 16px; }
.comment-main { flex: 1; }
.comment-nick { font-size: 13px; color: #323233; font-weight: 500; }
.comment-text { font-size: 14px; margin: 4px 0; }
.comment-foot { font-size: 12px; color: #969799; display: flex; justify-content: space-between; }
.del { color: #ee0a24; }
/* 底部操作栏 */
.action-bar {
  position: fixed; bottom: 0; left: 0; right: 0;
  display: flex; align-items: center; gap: 10px;
  padding: 8px 12px; background: #fff; box-shadow: 0 -1px 4px rgba(0,0,0,0.06);
}
.comment-input { flex: 1; background: #f7f8fa; border-radius: 16px; }
</style>
