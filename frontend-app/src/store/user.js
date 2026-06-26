// 用户状态管理: 保存登录令牌与用户信息
import { defineStore } from 'pinia'
// 引入用户接口
import { userApi } from '../api'

// 定义并导出 user store
export const useUserStore = defineStore('user', {
  // 状态定义
  state: () => ({
    // 登录令牌, 初始从本地存储读取
    token: localStorage.getItem('token') || '',
    // 当前用户信息对象
    userInfo: null
  }),
  // 计算属性
  getters: {
    // 是否已登录
    isLogin: (state) => !!state.token
  },
  // 动作方法
  actions: {
    // 设置令牌并持久化
    setToken(token) {
      // 写入状态
      this.token = token
      // 持久化到本地存储
      localStorage.setItem('token', token)
    },
    // 登录: 调用接口并保存结果
    async login(form) {
      // 请求登录接口
      const data = await userApi.login(form)
      // 保存令牌
      this.setToken(data.token)
      // 保存用户信息
      this.userInfo = data.user
      // 返回数据
      return data
    },
    // 拉取个人信息
    async fetchInfo() {
      // 未登录则直接返回
      if (!this.token) return
      // 请求个人信息
      this.userInfo = await userApi.info()
    },
    // 退出登录: 清除状态与本地存储
    async logout() {
      // 尝试通知后端(失败也忽略)
      try { await userApi.logout() } catch (e) { /* 忽略 */ }
      // 清空令牌
      this.token = ''
      // 清空用户信息
      this.userInfo = null
      // 移除本地存储
      localStorage.removeItem('token')
    }
  }
})
