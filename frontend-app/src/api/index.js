// 接口集中管理: 按模块封装所有后端 API 调用
import request from './request'

// 用户模块接口
export const userApi = {
  // 注册
  register: (data) => request.post('/api/user/register', data),
  // 登录
  login: (data) => request.post('/api/user/login', data),
  // 获取个人信息
  info: () => request.get('/api/user/info'),
  // 修改个人资料
  update: (data) => request.put('/api/user/info', data),
  // 退出登录
  logout: () => request.post('/api/user/logout')
}

// 文章模块接口
export const articleApi = {
  // 分页列表: 后端对「全部分类第 1 页」做 L1 内存 + L2 Redis 多级缓存
  list: (params) => request.get('/api/article/list', { params }),
  // 详情(含正文; PV 异步写入, 列表浏览量允许短时缓存陈旧)
  detail: (id) => request.get(`/api/article/detail/${id}`),
  // 发布(成功后后端失效 list+top 缓存)
  add: (data) => request.post('/api/article/add', data),
  // 编辑(成功后后端失效 list+top 缓存)
  update: (id, data) => request.put(`/api/article/update/${id}`, data),
  // 删除(成功后后端失效 list+top 缓存)
  del: (id) => request.delete(`/api/article/del/${id}`),
  // 置顶列表: 后端 L1 内存 + L2 Redis 多级缓存(固定 Top10)
  top: () => request.get('/api/article/top'),
  // 搜索(不走 Feed 多级缓存)
  search: (params) => request.get('/api/article/search', { params })
}

// 分类模块接口
export const categoryApi = {
  // 全部分类
  list: () => request.get('/api/category/list'),
  // 新增分类
  add: (data) => request.post('/api/category/add', data)
}

// 标签模块接口
export const tagApi = {
  // 全部标签
  list: () => request.get('/api/tag/list'),
  // 新增标签
  add: (data) => request.post('/api/tag/add', data)
}

// 评论模块接口
export const commentApi = {
  // 文章评论列表
  list: (articleId) => request.get(`/api/comment/list/${articleId}`),
  // 发表评论
  add: (data) => request.post('/api/comment/add', data),
  // 删除评论
  del: (id) => request.delete(`/api/comment/del/${id}`)
}

// 收藏模块接口
export const favoriteApi = {
  // 收藏/取消收藏
  toggle: (data) => request.post('/api/favorite/add', data),
  // 我的收藏
  list: () => request.get('/api/favorite/list')
}

// 推荐模块接口(匿名可用, 登录后个性化)
export const recApi = {
  // 推荐文章列表: 后端先查 L1+L2; miss 才执行画像向量 → 兴趣标签 → 兜底
  articles: (params) => request.get('/api/rec/articles', { params })
}

// 浏览足迹接口(登录用户)
export const browseApi = {
  // 上报浏览: 后端优先进 RocketMQ 异步落库(失败同步回落); silent 避免离开页弹错
  report: (data) => request.post('/api/browse/report', data, { silent: true }),
  // 我的足迹分页(读 MySQL; MQ 消费后可能略有延迟)
  list: (params) => request.get('/api/browse/list', { params })
}
