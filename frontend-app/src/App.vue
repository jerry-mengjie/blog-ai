<script setup>
// 引入路由相关 API
import { useRoute, useRouter } from 'vue-router'
// 引入计算属性
import { computed } from 'vue'

// 当前路由对象
const route = useRoute()
// 路由实例
const router = useRouter()

// 计算当前激活的 tab(基于路径)
const active = computed(() => route.path)

// 仅在主页面显示底部导航(详情/搜索页隐藏)
const showTab = computed(() =>
  ['/', '/personal', '/about'].includes(route.path)
)

// 切换 tab 时跳转对应路由
const onTabChange = (name) => router.push(name)
</script>

<template>
  <!-- 路由出口, 使用 keep-alive 缓存列表页提升体验 -->
  <router-view v-slot="{ Component }">
    <keep-alive include="index">
      <component :is="Component" />
    </keep-alive>
  </router-view>

  <!-- 底部导航栏, 仅主页面显示 -->
  <van-tabbar v-if="showTab" :model-value="active" @change="onTabChange">
    <!-- 首页 tab -->
    <van-tabbar-item name="/" icon="home-o">首页</van-tabbar-item>
    <!-- 关于 tab -->
    <van-tabbar-item name="/about" icon="info-o">关于</van-tabbar-item>
    <!-- 我的 tab -->
    <van-tabbar-item name="/personal" icon="user-o">我的</van-tabbar-item>
  </van-tabbar>
</template>
