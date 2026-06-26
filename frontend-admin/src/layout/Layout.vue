<script setup>
// 引入计算属性
import { computed, onMounted } from 'vue'
// 引入路由
import { useRouter, useRoute } from 'vue-router'
// 引入用户状态
import { useUserStore } from '../store/user'
// 引入消息确认
import { ElMessageBox } from 'element-plus'

// 路由实例
const router = useRouter()
// 当前路由
const route = useRoute()
// 用户状态
const userStore = useUserStore()

// 根据路由表 + RBAC 权限动态生成菜单项
const menus = computed(() => {
  // 找到布局根路由的子路由
  const root = router.options.routes.find((r) => r.path === '/')
  // 过滤出有标题且当前用户有权限访问的菜单
  return (root?.children || []).filter(
    (c) => c.meta?.title && userStore.hasPermission(c.meta.permission)
  )
})

// 当前激活菜单(基于路径)
const activeMenu = computed(() => route.path)

// 退出登录
const handleLogout = async () => {
  // 二次确认
  await ElMessageBox.confirm('确认退出登录?', '提示', { type: 'warning' })
  // 执行退出
  await userStore.logout()
  // 跳转登录
  router.push('/login')
}

// 挂载时确保用户信息已加载
onMounted(async () => {
  // 若缺信息则拉取
  if (!userStore.userInfo) await userStore.fetchInfo()
})
</script>

<template>
  <!-- 整体容器: 左侧菜单 + 右侧内容 -->
  <el-container class="layout">
    <!-- 侧边栏 -->
    <el-aside width="220px" class="aside">
      <!-- LOGO 区 -->
      <div class="logo">AI 博客后台</div>
      <!-- 菜单 -->
      <el-menu :default-active="activeMenu" router class="menu" background-color="#001529" text-color="rgba(255,255,255,0.85)" active-text-color="#409eff">
        <!-- 动态菜单项 -->
        <el-menu-item v-for="m in menus" :key="m.path" :index="'/' + m.path">
          <!-- 图标 -->
          <el-icon><component :is="m.meta.icon" /></el-icon>
          <!-- 文本 -->
          <span>{{ m.meta.title }}</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <!-- 右侧主区 -->
    <el-container>
      <!-- 顶部栏 -->
      <el-header class="header">
        <!-- 当前页标题 -->
        <div class="page-title">{{ route.meta.title }}</div>
        <!-- 右侧用户区 -->
        <el-dropdown @command="handleLogout">
          <!-- 用户信息触发器 -->
          <span class="user">
            <el-avatar :size="32" :src="userStore.userInfo?.avatar || 'https://picsum.photos/40/40'" />
            <span class="nick">{{ userStore.userInfo?.nickname }}</span>
            <!-- 角色标签, 体现 RBAC -->
            <el-tag size="small" type="success">{{ userStore.role }}</el-tag>
            <el-icon><ArrowDown /></el-icon>
          </span>
          <!-- 下拉菜单 -->
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>

      <!-- 内容区: 路由出口 -->
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
/* 整体高度铺满 */
.layout { height: 100vh; }
/* 侧边栏背景 */
.aside { background: #001529; }
/* LOGO */
.logo { height: 60px; line-height: 60px; text-align: center; color: #fff; font-size: 18px; font-weight: 600; }
/* 菜单去掉右边框 */
.menu { border-right: none; }
/* 顶部栏布局 */
.header { display: flex; align-items: center; justify-content: space-between; background: #fff; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
/* 页面标题 */
.page-title { font-size: 16px; font-weight: 600; }
/* 用户区 */
.user { display: flex; align-items: center; gap: 8px; cursor: pointer; }
.nick { font-size: 14px; }
/* 内容区背景 */
.main { background: #f0f2f5; padding: 20px; }
</style>
