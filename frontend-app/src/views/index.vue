<script setup>
// 首页: Vant Tabs + 单一 List 渲染三种 Feed(推荐/置顶/分页)
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { articleApi, categoryApi, recApi } from '../api'

defineOptions({ name: 'index' })

const router = useRouter()
const REC = 'rec'
const TOP = 'top'
const strategyText = { profile: '猜你喜欢', tag: '兴趣推荐', fallback: '热门精选' }
const thumb = (url) => url || 'https://picsum.photos/200/200'

const categories = ref([])
const activeTab = ref(REC)
const recs = ref([])
const tops = ref([])
const articles = ref([])
const page = ref(1)
const loading = ref(false)
const finished = ref(true) // 推荐/置顶无分页, 默认 finished
const refreshing = ref(false)

const isRec = computed(() => activeTab.value === REC)
const isTop = computed(() => activeTab.value === TOP)
const isList = computed(() => !isRec.value && !isTop.value)
// 当前 Tab 对应的数据源, 模板只渲染一份卡片
const feed = computed(() => (isRec.value ? recs.value : isTop.value ? tops.value : articles.value))
const emptyText = computed(() => (isRec.value ? '暂无推荐内容' : isTop.value ? '暂无置顶文章' : ''))

const loadRec = async () => {
  try {
    // 推荐 Tab: 匿名按 size 共享缓存, 登录按 user_id + size 命中后端多级缓存
    recs.value = (await recApi.articles({ size: 10 })).list || []
  } catch {
    recs.value = []
  }
}

const loadTop = async () => {
  // 置顶 Tab: 命中后端 L1+L2, 无分页
  tops.value = await articleApi.top()
}

const onLoad = async () => {
  // 非分类列表 Tab 不拉分页接口
  if (!isList.value) {
    loading.value = false
    finished.value = true
    return
  }
  // page=1 命中后端多级缓存; page>1 直查 MySQL
  const params = { page: page.value, page_size: 10 }
  // 全部 Tab name=0, 与后端 cat=all 对齐
  if (activeTab.value) params.category_id = activeTab.value
  const res = await articleApi.list(params)
  articles.value.push(...res.list)
  page.value++
  loading.value = false
  if (articles.value.length >= res.total) finished.value = true
}

const onTabChange = (name) => {
  if (name === REC || name === TOP) {
    finished.value = true
    return name === REC ? loadRec() : loadTop()
  }
  articles.value = []
  page.value = 1
  finished.value = false
  loading.value = true
  onLoad()
}

const onRefresh = async () => {
  if (isRec.value) await loadRec()
  else if (isTop.value) await loadTop()
  else {
    articles.value = []
    page.value = 1
    finished.value = false
    loading.value = true
    await onLoad()
  }
  refreshing.value = false
}

onMounted(() =>
  Promise.all([categoryApi.list().then((r) => (categories.value = r)), loadRec()]),
)
</script>

<template>
  <div class="app-page">
    <van-nav-bar title="AI 博客" fixed placeholder />
    <van-search readonly placeholder="搜索文章" @click="router.push('/search')" />

    <van-tabs v-model:active="activeTab" sticky @change="onTabChange">
      <van-tab :name="REC" title="为你推荐" />
      <van-tab :name="TOP" title="置顶" />
      <van-tab :name="0" title="全部" />
      <van-tab v-for="c in categories" :key="c.id" :name="c.id" :title="c.name" />
    </van-tabs>

    <van-pull-refresh v-model="refreshing" @refresh="onRefresh">
      <van-list
        v-model:loading="loading"
        :finished="finished"
        :immediate-check="false"
        finished-text="没有更多了"
        @load="onLoad"
      >
        <van-card
          v-for="a in feed"
          :key="a.id"
          :title="a.title"
          :desc="a.summary"
          :thumb="thumb(a.cover)"
          @click="router.push(`/article/${a.id}`)"
        >
          <template #tags>
            <van-tag v-if="isTop" plain type="danger">置顶</van-tag>
            <van-tag plain type="primary" :class="{ 'tag-gap': isTop }">浏览 {{ a.view_count }}</van-tag>
            <van-tag v-if="isRec" plain type="success" class="tag-gap">
              {{ strategyText[a.strategy] || '推荐' }}
            </van-tag>
          </template>
        </van-card>
        <van-empty v-if="!isList && !feed.length" :description="emptyText" />
      </van-list>
    </van-pull-refresh>
  </div>
</template>

<style scoped>
.tag-gap { margin-left: 6px; }
</style>
