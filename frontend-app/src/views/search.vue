<script setup>
// 引入响应式 API
import { ref } from 'vue'
// 引入路由
import { useRouter } from 'vue-router'
// 引入接口
import { articleApi } from '../api'

// 路由实例
const router = useRouter()
// 搜索关键字
const keyword = ref('')
// 搜索结果列表
const results = ref([])
// 是否已搜索过(用于空状态展示)
const searched = ref(false)

// 执行搜索
const onSearch = async () => {
  // 空关键字直接返回
  if (!keyword.value.trim()) return
  // 请求搜索接口
  const res = await articleApi.search({ keyword: keyword.value, page: 1, page_size: 20 })
  // 保存结果
  results.value = res.list
  // 标记已搜索
  searched.value = true
}

// 跳转详情
const goDetail = (id) => router.push(`/article/${id}`)
</script>

<template>
  <div class="app-page">
    <!-- 搜索框, 带返回与确认搜索 -->
    <van-search
      v-model="keyword"
      show-action
      placeholder="输入关键字搜索文章"
      @search="onSearch"
    >
      <!-- 自定义右侧动作: 返回 -->
      <template #action>
        <div @click="router.back()">取消</div>
      </template>
    </van-search>

    <!-- 搜索结果列表 -->
    <van-card
      v-for="a in results"
      :key="a.id"
      :title="a.title"
      :desc="a.summary"
      :thumb="a.cover || 'https://picsum.photos/200/200'"
      @click="goDetail(a.id)"
    />

    <!-- 空状态 -->
    <van-empty v-if="searched && !results.length" description="没有找到相关文章" />
  </div>
</template>
