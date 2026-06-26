// Axios 封装: 统一基础地址、请求头携带 token、响应拦截处理统一结构
import axios from 'axios'
// 引入 Vant 轻提示
import { showToast } from 'vant'
// 引入路由用于登录失效跳转
import router from '../router'

// 创建 axios 实例
const request = axios.create({
  // 基础路径, 配合 vite 代理转发到后端
  baseURL: '/',
  // 超时时间(毫秒)
  timeout: 10000
})

// 请求拦截器: 自动注入鉴权令牌
request.interceptors.request.use((config) => {
  // 从本地存储读取 token
  const token = localStorage.getItem('token')
  // 若存在则写入 Authorization 头
  if (token) config.headers.Authorization = `Bearer ${token}`
  // 返回处理后的配置
  return config
})

// 响应拦截器: 解构统一结构 {code, message, data}
request.interceptors.response.use(
  (response) => {
    // 取出后端返回体
    const res = response.data
    // code 为 0 表示成功, 直接返回 data
    if (res.code === 0) return res.data
    // 非 0 弹出错误提示
    showToast(res.message || '请求失败')
    // 抛出错误中断后续 then
    return Promise.reject(res)
  },
  (error) => {
    // 读取 HTTP 状态码
    const status = error.response?.status
    // 401 表示未登录或令牌失效
    if (status === 401) {
      // 清除本地令牌
      localStorage.removeItem('token')
      // 跳转到个人中心(内含登录)
      router.push('/personal')
    }
    // 统一错误提示
    showToast(error.response?.data?.message || '网络异常')
    // 抛出错误
    return Promise.reject(error)
  }
)

// 导出实例
export default request
