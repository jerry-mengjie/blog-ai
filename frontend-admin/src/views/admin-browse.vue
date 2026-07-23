<script setup>
// 浏览统计: 用户×文章累计次数/时长/最好浏览时间
import { ref, reactive, onMounted } from 'vue'
import { adminBrowseApi } from '../api'

const list = ref([])
const total = ref(0)
const loading = ref(false)
// 筛选: 关键字 / 用户ID / 文章ID
const query = reactive({
  page: 1,
  page_size: 10,
  keyword: '',
  user_id: '',
  article_id: ''
})

// 秒转可读时长
const formatDuration = (sec) => {
  const s = Number(sec) || 0
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const r = s % 60
  if (m < 60) return r ? `${m}m${r}s` : `${m}m`
  const h = Math.floor(m / 60)
  return `${h}h${m % 60}m`
}

const formatTime = (t) => (t ? String(t).replace('T', ' ').slice(0, 16) : '-')

const loadList = async () => {
  loading.value = true
  try {
    const params = {
      page: query.page,
      page_size: query.page_size,
      keyword: query.keyword || undefined,
      user_id: query.user_id === '' ? undefined : Number(query.user_id),
      article_id: query.article_id === '' ? undefined : Number(query.article_id)
    }
    const res = await adminBrowseApi.list(params)
    list.value = res.list
    total.value = res.total
  } finally {
    loading.value = false
  }
}

const onSearch = () => {
  query.page = 1
  loadList()
}

const onPageChange = (p) => {
  query.page = p
  loadList()
}

onMounted(loadList)
</script>

<template>
  <div>
    <el-card shadow="never" class="toolbar">
      <el-input
        v-model="query.keyword"
        placeholder="用户名/昵称/标题"
        style="width: 200px"
        clearable
        @keyup.enter="onSearch"
      />
      <el-input
        v-model="query.user_id"
        placeholder="用户ID"
        style="width: 110px"
        clearable
        @keyup.enter="onSearch"
      />
      <el-input
        v-model="query.article_id"
        placeholder="文章ID"
        style="width: 110px"
        clearable
        @keyup.enter="onSearch"
      />
      <el-button type="primary" :icon="'Search'" @click="onSearch">搜索</el-button>
    </el-card>

    <el-card shadow="never">
      <el-table v-loading="loading" :data="list" border stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column label="用户" min-width="140">
          <template #default="{ row }">
            <div>{{ row.nickname || row.username }}</div>
            <div class="sub">ID {{ row.user_id }} · {{ row.username }}</div>
          </template>
        </el-table-column>
        <el-table-column label="文章" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <div>{{ row.title || '-' }}</div>
            <div class="sub">ID {{ row.article_id }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="view_count" label="浏览次数" width="100" />
        <el-table-column label="总时长" width="100">
          <template #default="{ row }">{{ formatDuration(row.total_duration) }}</template>
        </el-table-column>
        <el-table-column label="最长单次" width="100">
          <template #default="{ row }">{{ formatDuration(row.best_duration) }}</template>
        </el-table-column>
        <el-table-column label="最好浏览时间" width="160">
          <template #default="{ row }">{{ formatTime(row.best_browse_time) }}</template>
        </el-table-column>
        <el-table-column label="最近浏览" width="160">
          <template #default="{ row }">{{ formatTime(row.last_browse_time) }}</template>
        </el-table-column>
      </el-table>

      <el-pagination
        class="pager"
        background
        layout="total, prev, pager, next"
        :total="total"
        :page-size="query.page_size"
        :current-page="query.page"
        @current-change="onPageChange"
      />
    </el-card>
  </div>
</template>

<style scoped>
.toolbar { margin-bottom: 16px; display: flex; gap: 12px; flex-wrap: wrap; }
.pager { margin-top: 16px; justify-content: flex-end; }
.sub { font-size: 12px; color: #909399; margin-top: 2px; }
</style>
