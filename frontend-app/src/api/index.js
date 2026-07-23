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
  // 分页列表
  list: (params) => request.get('/api/article/list', { params }),
  // 详情
  detail: (id) => request.get(`/api/article/detail/${id}`),
  // 发布
  add: (data) => request.post('/api/article/add', data),
  // 编辑
  update: (id, data) => request.put(`/api/article/update/${id}`, data),
  // 删除
  del: (id) => request.delete(`/api/article/del/${id}`),
  // 置顶列表
  top: () => request.get('/api/article/top'),
  // 搜索
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

// 浏览足迹接口(登录用户)
export const browseApi = {
  // 上报一次浏览(次数+1, 累加时长); silent 避免离开页弹错
  report: (data) => request.post('/api/browse/report', data, { silent: true }),
  // 我的足迹分页
  list: (params) => request.get('/api/browse/list', { params })
}
