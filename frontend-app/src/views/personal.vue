<script setup>
// 引入响应式 API 与生命周期
import { ref, onMounted } from 'vue'
// 引入路由
import { useRouter } from 'vue-router'
// 引入 Vant 提示
import { showToast } from 'vant'
// 引入用户状态与接口
import { useUserStore } from '../store/user'
import { userApi, favoriteApi, browseApi } from '../api'

// 路由实例
const router = useRouter()
// 用户状态
const userStore = useUserStore()

// 当前是登录还是注册模式
const isRegister = ref(false)
// 登录/注册表单
const form = ref({ username: '', password: '', nickname: '' })
// 个人资料编辑表单
const profile = ref({ nickname: '', email: '', avatar: '' })
// 我的收藏列表
const favorites = ref([])
// 我的足迹列表
const browses = ref([])
// 资料编辑弹窗显隐
const showEdit = ref(false)

// 登录或注册提交
const onSubmit = async () => {
  // 注册模式
  if (isRegister.value) {
    // 调用注册接口
    await userApi.register(form.value)
    // 提示并切换登录
    showToast('注册成功, 请登录')
    isRegister.value = false
    return
  }
  // 登录模式
  await userStore.login(form.value)
  // 登录成功后加载收藏与足迹
  await Promise.all([loadFavorites(), loadBrowses()])
  showToast('登录成功')
}

// 加载个人信息
const loadInfo = async () => {
  // 拉取信息
  await userStore.fetchInfo()
  // 同步到编辑表单
  if (userStore.userInfo) {
    profile.value = {
      nickname: userStore.userInfo.nickname,
      email: userStore.userInfo.email,
      avatar: userStore.userInfo.avatar
    }
  }
}

// 加载我的收藏
const loadFavorites = async () => {
  favorites.value = await favoriteApi.list()
}

// 加载我的足迹(最近浏览)
const loadBrowses = async () => {
  const res = await browseApi.list({ page: 1, page_size: 20 })
  browses.value = res.list || []
}

// 格式化时长展示
const formatDuration = (sec) => {
  const s = Number(sec) || 0
  if (s < 60) return `${s}秒`
  const m = Math.floor(s / 60)
  const r = s % 60
  return r ? `${m}分${r}秒` : `${m}分钟`
}

// 保存资料修改
const saveProfile = async () => {
  // 调用更新接口
  await userApi.update(profile.value)
  // 刷新信息
  await loadInfo()
  // 关闭弹窗并提示
  showEdit.value = false
  showToast('保存成功')
}

// 退出登录
const onLogout = async () => {
  // 调用退出
  await userStore.logout()
  favorites.value = []
  browses.value = []
  showToast('已退出')
}

// 跳转详情
const goDetail = (id) => router.push(`/article/${id}`)

// 挂载时若已登录则加载数据
onMounted(async () => {
  if (userStore.isLogin) {
    await loadInfo()
    await Promise.all([loadFavorites(), loadBrowses()])
  }
})
</script>

<template>
  <div class="app-page">
    <!-- 顶部标题 -->
    <van-nav-bar title="我的" fixed placeholder />

    <!-- 未登录: 显示登录/注册表单 -->
    <div v-if="!userStore.isLogin" class="auth">
      <!-- 标题 -->
      <div class="auth-title">{{ isRegister ? '注册账号' : '登录' }}</div>
      <!-- 表单 -->
      <van-cell-group inset>
        <!-- 用户名 -->
        <van-field v-model="form.username" label="用户名" placeholder="请输入用户名" />
        <!-- 密码 -->
        <van-field v-model="form.password" type="password" label="密码" placeholder="请输入密码" />
        <!-- 注册时显示昵称 -->
        <van-field v-if="isRegister" v-model="form.nickname" label="昵称" placeholder="请输入昵称" />
      </van-cell-group>
      <!-- 提交按钮 -->
      <div class="auth-btn">
        <van-button type="primary" block round @click="onSubmit">
          {{ isRegister ? '注册' : '登录' }}
        </van-button>
        <!-- 切换登录/注册 -->
        <div class="switch" @click="isRegister = !isRegister">
          {{ isRegister ? '已有账号? 去登录' : '没有账号? 去注册' }}
        </div>
      </div>
    </div>

    <!-- 已登录: 显示个人信息与收藏 -->
    <div v-else>
      <!-- 用户卡片 -->
      <div class="user-card">
        <!-- 头像 -->
        <van-image round width="60" height="60" :src="userStore.userInfo?.avatar || 'https://picsum.photos/80/80'" />
        <!-- 信息 -->
        <div class="user-info">
          <div class="nick">{{ userStore.userInfo?.nickname }}</div>
          <div class="email">{{ userStore.userInfo?.email || '未设置邮箱' }}</div>
        </div>
        <!-- 编辑按钮 -->
        <van-button size="small" plain type="primary" @click="showEdit = true">编辑</van-button>
      </div>

      <!-- 我的足迹 -->
      <div class="section-title">我的足迹</div>
      <van-card
        v-for="b in browses"
        :key="b.id"
        :title="b.title"
        :desc="`浏览 ${b.view_count} 次 · 共 ${formatDuration(b.total_duration)}`"
        :thumb="b.cover || 'https://picsum.photos/200/200'"
        @click="goDetail(b.article_id)"
      />
      <van-empty v-if="!browses.length" description="还没有浏览记录" />

      <!-- 我的收藏标题 -->
      <div class="section-title">我的收藏</div>
      <!-- 收藏列表 -->
      <van-card
        v-for="a in favorites"
        :key="a.id"
        :title="a.title"
        :desc="a.summary"
        :thumb="a.cover || 'https://picsum.photos/200/200'"
        @click="goDetail(a.id)"
      />
      <!-- 空状态 -->
      <van-empty v-if="!favorites.length" description="还没有收藏文章" />

      <!-- 退出登录 -->
      <div class="logout">
        <van-button block round type="danger" plain @click="onLogout">退出登录</van-button>
      </div>
    </div>

    <!-- 资料编辑弹窗 -->
    <van-popup v-model:show="showEdit" position="bottom" round :style="{ padding: '20px' }">
      <!-- 弹窗标题 -->
      <div class="popup-title">编辑资料</div>
      <!-- 昵称 -->
      <van-field v-model="profile.nickname" label="昵称" placeholder="请输入昵称" />
      <!-- 邮箱 -->
      <van-field v-model="profile.email" label="邮箱" placeholder="请输入邮箱" />
      <!-- 头像 URL -->
      <van-field v-model="profile.avatar" label="头像" placeholder="请输入头像链接" />
      <!-- 保存按钮 -->
      <van-button type="primary" block round style="margin-top: 16px" @click="saveProfile">保存</van-button>
    </van-popup>
  </div>
</template>

<style scoped>
/* 登录区域 */
.auth { padding-top: 30px; }
.auth-title { text-align: center; font-size: 20px; font-weight: 600; margin-bottom: 20px; }
.auth-btn { padding: 20px 16px; }
.switch { text-align: center; color: #1989fa; font-size: 13px; margin-top: 12px; }
/* 用户卡片 */
.user-card { display: flex; align-items: center; gap: 14px; padding: 20px 16px; background: #fff; }
.user-info { flex: 1; }
.nick { font-size: 17px; font-weight: 600; }
.email { font-size: 13px; color: #969799; margin-top: 4px; }
/* 区块标题 */
.section-title { padding: 14px 16px 6px; font-weight: 600; }
/* 退出按钮区域 */
.logout { padding: 20px 16px; }
/* 弹窗标题 */
.popup-title { text-align: center; font-weight: 600; margin-bottom: 16px; }
</style>
