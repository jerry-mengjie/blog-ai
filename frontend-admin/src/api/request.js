// Axios 封装: 统一携带 token、处理统一响应结构与登录失效
import axios from 'axios'
// Element Plus 消息提示
import { ElMessage } from 'element-plus'
// 路由实例(登录失效跳转)
import router from '../router'

// 创建实例
const request = axios.create({
  // 基础路径(配合 vite 代理)
  baseURL: '/',
  // 超时时间
  timeout: 10000
})

// 请求拦截: 注入令牌
request.interceptors.request.use((config) => {
  // 读取本地令牌
  const token = localStorage.getItem('admin_token')
  // 存在则附加
  if (token) config.headers.Authorization = `Bearer ${token}`
  // 返回配置
  return config
})

// 响应拦截: 解构数据
request.interceptors.response.use(
  (response) => {
    // 后端返回体
    const res = response.data
    // 成功直接返回 data
    if (res.code === 0) return res.data
    // 失败提示
    ElMessage.error(res.message || '请求失败')
    // 中断
    return Promise.reject(res)
  },
  (error) => {
    // HTTP 状态码
    const status = error.response?.status
    // 401 未登录/失效
    if (status === 401) {
      // 清除令牌
      localStorage.removeItem('admin_token')
      // 跳转登录
      router.push('/login')
    }
    // 错误提示
    ElMessage.error(error.response?.data?.message || '网络异常')
    // 中断
    return Promise.reject(error)
  }
)

// 导出
export default request
