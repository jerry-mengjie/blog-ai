<script setup>
// 文章详情: 正文/评论/收藏 + 登录用户停留时长上报
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showToast, showConfirmDialog } from 'vant'
import { articleApi, browseApi, commentApi, favoriteApi } from '../api'
import { useUserStore } from '../store/user'
import AiAsk from '../components/ai-ask.vue'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const article = ref(null)
const comments = ref([])
const commentText = ref('')
const favorited = ref(false)
const articleId = route.params.id

// ---------- 浏览计时(仅登录用户上报) ----------
let activeStart = 0
let accumulatedMs = 0
let reported = false

// 累计可见时段毫秒
const flushVisible = () => {
  if (activeStart > 0) {
    accumulatedMs += Date.now() - activeStart
    activeStart = 0
  }
}

// 页面可见性变化: 切后台暂停计时
const onVisibility = () => {
  if (document.hidden) flushVisible()
  else if (userStore.isLogin) activeStart = Date.now()
}

// 上报本次停留(静默失败, 避免离开页时弹 Toast/跳转干扰)
const reportBrowse = async () => {
  if (!userStore.isLogin || reported) return
  reported = true
  flushVisible()
  const duration = Math.floor(accumulatedMs / 1000)
  try {
    await browseApi.report({ article_id: Number(articleId), duration })
  } catch (_) {
    // 忽略: 离开页时网络/401 不打断体验
  }
}

const loadDetail = async () => {
  article.value = await articleApi.detail(articleId)
}

const loadComments = async () => {
  comments.value = await commentApi.list(articleId)
}

const submitComment = async () => {
  if (!userStore.isLogin) {
    showToast('请先登录')
    return router.push('/personal')
  }
  if (!commentText.value.trim()) return showToast('请输入评论内容')
  await commentApi.add({ article_id: Number(articleId), content: commentText.value })
  commentText.value = ''
  showToast('评论成功')
  await loadComments()
}

const removeComment = async (id) => {
  await showConfirmDialog({ title: '提示', message: '确认删除该评论?' })
  await commentApi.del(id)
  await loadComments()
}

const toggleFavorite = async () => {
  if (!userStore.isLogin) {
    showToast('请先登录')
    return router.push('/personal')
  }
  const res = await favoriteApi.toggle({ article_id: Number(articleId) })
  favorited.value = res.favorited
}

onMounted(async () => {
  await Promise.all([loadDetail(), loadComments()])
  // 登录用户开始计时
  if (userStore.isLogin) {
    activeStart = Date.now()
    document.addEventListener('visibilitychange', onVisibility)
  }
})

onUnmounted(() => {
  document.removeEventListener('visibilitychange', onVisibility)
  reportBrowse()
})
</script>

<template>
  <div class="app-page detail-page">
    <van-nav-bar title="文章详情" left-arrow fixed placeholder @click-left="router.back()" />

    <div v-if="article" class="content">
      <h1 class="title">{{ article.title }}</h1>
      <div class="meta">
        <span>浏览 {{ article.view_count }}</span>
        <span>{{ article.create_time?.slice(0, 10) }}</span>
      </div>
      <div class="tags">
        <van-tag v-for="t in article.tags" :key="t" type="primary" plain class="tag">{{ t }}</van-tag>
      </div>
      <div class="article-body">{{ article.content }}</div>
    </div>

    <ai-ask v-if="article" :article-id="Number(articleId)" />

    <div class="comments">
      <div class="comment-title">评论 ({{ comments.length }})</div>
      <div v-for="c in comments" :key="c.id" class="comment-item">
        <van-image round width="36" height="36" :src="c.avatar || 'https://picsum.photos/40/40'" />
        <div class="comment-main">
          <div class="comment-nick">{{ c.nickname }}</div>
          <div class="comment-text">{{ c.content }}</div>
          <div class="comment-foot">
            <span>{{ c.create_time?.slice(0, 16) }}</span>
            <span v-if="userStore.userInfo?.id === c.user_id" class="del" @click="removeComment(c.id)">删除</span>
          </div>
        </div>
      </div>
      <van-empty v-if="!comments.length" description="暂无评论, 快来抢沙发" />
    </div>

    <div class="action-bar">
      <van-field v-model="commentText" placeholder="写评论..." class="comment-input" />
      <van-icon :name="favorited ? 'star' : 'star-o'" :color="favorited ? '#ffd21e' : '#969799'" size="26" @click="toggleFavorite" />
      <van-button type="primary" size="small" @click="submitComment">发送</van-button>
    </div>
  </div>
</template>

<style scoped>
.content { padding: 16px; background: #fff; }
.title { font-size: 20px; line-height: 1.4; }
.meta { display: flex; gap: 16px; color: #969799; font-size: 12px; margin: 10px 0; }
.tags { margin-bottom: 12px; }
.tag { margin-right: 6px; }
.article-body { font-size: 15px; line-height: 1.8; white-space: pre-wrap; }
.comments { padding: 16px; background: #fff; margin-top: 8px; padding-bottom: 70px; }
.comment-title { font-weight: 600; margin-bottom: 12px; }
.comment-item { display: flex; gap: 10px; margin-bottom: 16px; }
.comment-main { flex: 1; }
.comment-nick { font-size: 13px; color: #323233; font-weight: 500; }
.comment-text { font-size: 14px; margin: 4px 0; }
.comment-foot { font-size: 12px; color: #969799; display: flex; justify-content: space-between; }
.del { color: #ee0a24; }
.action-bar {
  position: fixed; bottom: 0; left: 0; right: 0;
  display: flex; align-items: center; gap: 10px;
  padding: 8px 12px; background: #fff; box-shadow: 0 -1px 4px rgba(0,0,0,0.06);
}
.comment-input { flex: 1; background: #f7f8fa; border-radius: 16px; }
</style>
