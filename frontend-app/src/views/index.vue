<script setup>
// 引入响应式 API 与生命周期
import { ref, onMounted } from 'vue'
// 引入路由
import { useRouter } from 'vue-router'
// 引入接口
import { articleApi, categoryApi } from '../api'

// 路由实例
const router = useRouter()

// 分类列表
const categories = ref([])
// 当前选中分类 ID, 0 表示全部
const activeCategory = ref(0)
// 置顶/热门文章
const topArticles = ref([])
// 文章列表
const articles = ref([])
// 当前页码
const page = ref(1)
// 列表加载中状态(Vant List 需要)
const loading = ref(false)
// 是否全部加载完成
const finished = ref(false)
// 下拉刷新状态
const refreshing = ref(false)

// 加载分类导航
const loadCategories = async () => {
  // 请求全部分类
  categories.value = await categoryApi.list()
}

// 加载热门(置顶)文章
const loadTop = async () => {
  // 请求置顶文章
  topArticles.value = await articleApi.top()
}

// 加载文章列表(分页)
const onLoad = async () => {
  // 构造分页参数, 携带可选分类
  const params = { page: page.value, page_size: 10 }
  // 若选中具体分类则附加
  if (activeCategory.value) params.category_id = activeCategory.value
  // 请求列表
  const res = await articleApi.list(params)
  // 追加数据
  articles.value.push(...res.list)
  // 页码自增
  page.value++
  // 关闭本次加载状态
  loading.value = false
  // 判断是否已加载完毕
  if (articles.value.length >= res.total) finished.value = true
}

// 切换分类时重置并重新加载
const onCategoryChange = (id) => {
  // 设置当前分类
  activeCategory.value = id
  // 重置列表
  articles.value = []
  // 重置页码
  page.value = 1
  // 重置完成标记
  finished.value = false
  // 触发加载
  onLoad()
}

// 下拉刷新处理
const onRefresh = async () => {
  // 重置列表与分页
  articles.value = []
  page.value = 1
  finished.value = false
  // 重新加载置顶与列表
  await loadTop()
  await onLoad()
  // 关闭刷新动画
  refreshing.value = false
}

// 跳转到文章详情
const goDetail = (id) => router.push(`/article/${id}`)

// 组件挂载时初始化数据
onMounted(async () => {
  // 加载分类与置顶
  await loadCategories()
  await loadTop()
})
</script>

<template>
  <div class="app-page">
    <!-- 顶部标题栏 -->
    <van-nav-bar title="AI 博客" fixed placeholder />

    <!-- 搜索入口(只读, 点击跳转搜索页) -->
    <van-search readonly placeholder="搜索文章" @click="router.push('/search')" />

    <!-- 分类导航: 横向标签 -->
    <van-tabs v-model:active="activeCategory" sticky @change="onCategoryChange">
      <!-- 全部分类项 -->
      <van-tab :name="0" title="全部" />
      <!-- 动态分类项 -->
      <van-tab v-for="c in categories" :key="c.id" :name="c.id" :title="c.name" />
    </van-tabs>

    <!-- 热门(置顶)文章横向滚动 -->
    <div v-if="topArticles.length" class="hot-section">
      <!-- 区块标题 -->
      <div class="hot-title">🔥 热门推荐</div>
      <!-- 横向滚动容器 -->
      <div class="hot-scroll">
        <div v-for="t in topArticles" :key="t.id" class="hot-card" @click="goDetail(t.id)">
          <!-- 热门文章封面 -->
          <van-image :src="t.cover || 'https://picsum.photos/200/120'" width="160" height="90" radius="8" fit="cover" />
          <!-- 热门文章标题 -->
          <div class="hot-card-title">{{ t.title }}</div>
        </div>
      </div>
    </div>

    <!-- 文章列表: 下拉刷新 + 上拉加载 -->
    <van-pull-refresh v-model="refreshing" @refresh="onRefresh">
      <van-list v-model:loading="loading" :finished="finished" finished-text="没有更多了" @load="onLoad">
        <!-- 单篇文章卡片 -->
        <van-card
          v-for="a in articles"
          :key="a.id"
          :title="a.title"
          :desc="a.summary"
          :thumb="a.cover || 'https://picsum.photos/200/200'"
          @click="goDetail(a.id)"
        >
          <!-- 底部展示浏览量 -->
          <template #tags>
            <van-tag plain type="primary">浏览 {{ a.view_count }}</van-tag>
          </template>
        </van-card>
      </van-list>
    </van-pull-refresh>
  </div>
</template>

<style scoped>
/* 热门区块容器 */
.hot-section { padding: 12px; background: #fff; margin-bottom: 8px; }
/* 热门标题 */
.hot-title { font-size: 16px; font-weight: 600; margin-bottom: 10px; }
/* 横向滚动区 */
.hot-scroll { display: flex; gap: 12px; overflow-x: auto; }
/* 热门卡片 */
.hot-card { flex: 0 0 auto; width: 160px; }
/* 热门卡片标题: 两行省略 */
.hot-card-title {
  font-size: 13px; margin-top: 6px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
</style>
