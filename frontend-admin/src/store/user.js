// 管理后台用户状态: 令牌、用户信息、角色与权限(RBAC 核心)
import { defineStore } from 'pinia'
// 引入接口
import { userApi } from '../api'
// 引入权限推导
import { getPermissionsByRole } from '../rbac/permissions'

// 定义 store
export const useUserStore = defineStore('admin-user', {
  // 状态
  state: () => ({
    // 令牌
    token: localStorage.getItem('admin_token') || '',
    // 用户信息
    userInfo: null
  }),
  // 计算属性
  getters: {
    // 是否已登录
    isLogin: (state) => !!state.token,
    // 根据后端 is_admin 推导角色(可扩展为后端直接返回 role)
    role: (state) => (state.userInfo?.is_admin === 1 ? 'admin' : 'editor'),
    // 当前用户拥有的权限码列表
    permissions() {
      // 依据角色取权限
      return getPermissionsByRole(this.role)
    }
  },
  // 动作
  actions: {
    // 校验是否拥有某权限码
    hasPermission(code) {
      // 未传入则放行, 否则判断是否包含
      return !code || this.permissions.includes(code)
    },
    // 设置令牌并持久化
    setToken(token) {
      // 写入状态
      this.token = token
      // 持久化
      localStorage.setItem('admin_token', token)
    },
    // 登录: 校验管理员身份
    async login(form) {
      // 调用登录接口
      const data = await userApi.login(form)
      // 仅允许管理员进入后台
      if (data.user.is_admin !== 1) {
        // 抛出业务错误
        throw new Error('该账号无管理员权限')
      }
      // 保存令牌
      this.setToken(data.token)
      // 保存用户信息
      this.userInfo = data.user
      // 返回数据
      return data
    },
    // 拉取个人信息(刷新页面后恢复状态)
    async fetchInfo() {
      // 无令牌直接返回
      if (!this.token) return
      // 请求信息
      this.userInfo = await userApi.info()
    },
    // 退出登录
    async logout() {
      // 通知后端(忽略失败)
      try { await userApi.logout() } catch (e) { /* 忽略 */ }
      // 清空令牌
      this.token = ''
      // 清空信息
      this.userInfo = null
      // 移除本地存储
      localStorage.removeItem('admin_token')
    }
  }
})
