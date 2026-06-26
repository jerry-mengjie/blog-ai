<script setup>
// 引入响应式 API
import { ref } from 'vue'
// 引入路由
import { useRouter } from 'vue-router'
// 引入消息提示
import { ElMessage } from 'element-plus'
// 引入用户状态
import { useUserStore } from '../store/user'

// 路由实例
const router = useRouter()
// 用户状态
const userStore = useUserStore()

// 表单引用(用于校验)
const formRef = ref()
// 登录表单数据(默认填充演示账号)
const form = ref({ username: 'admin', password: 'admin123' })
// 提交加载状态
const loading = ref(false)

// 表单校验规则
const rules = {
  // 用户名必填
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  // 密码必填
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

// 提交登录
const onSubmit = async () => {
  // 先做表单校验
  await formRef.value.validate()
  // 开启加载
  loading.value = true
  // 捕获异常
  try {
    // 调用登录(内部校验管理员身份)
    await userStore.login(form.value)
    // 成功提示
    ElMessage.success('登录成功')
    // 跳转后台首页
    router.push('/')
  } catch (e) {
    // 失败提示(非权限错误已被拦截器提示)
    if (e.message) ElMessage.error(e.message)
  } finally {
    // 关闭加载
    loading.value = false
  }
}
</script>

<template>
  <!-- 登录页容器 -->
  <div class="login-page">
    <!-- 登录卡片 -->
    <el-card class="login-card">
      <!-- 标题 -->
      <h2 class="title">AI 博客 · 管理后台</h2>
      <!-- 表单 -->
      <el-form ref="formRef" :model="form" :rules="rules" @keyup.enter="onSubmit">
        <!-- 用户名 -->
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="用户名" :prefix-icon="'User'" size="large" />
        </el-form-item>
        <!-- 密码 -->
        <el-form-item prop="password">
          <el-input v-model="form.password" type="password" placeholder="密码" :prefix-icon="'Lock'" size="large" show-password />
        </el-form-item>
        <!-- 登录按钮 -->
        <el-form-item>
          <el-button type="primary" size="large" :loading="loading" style="width: 100%" @click="onSubmit">登 录</el-button>
        </el-form-item>
      </el-form>
      <!-- 提示 -->
      <div class="tip">默认管理员: admin / admin123</div>
    </el-card>
  </div>
</template>

<style scoped>
/* 登录页全屏渐变背景 */
.login-page {
  height: 100vh; display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #1890ff 0%, #001529 100%);
}
/* 登录卡片 */
.login-card { width: 380px; padding: 20px; border-radius: 10px; }
/* 标题 */
.title { text-align: center; margin-bottom: 24px; color: #001529; }
/* 提示 */
.tip { text-align: center; color: #909399; font-size: 12px; }
</style>
