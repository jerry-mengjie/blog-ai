// 接口集中管理(管理后台使用的子集)
import request from './request'

// 用户/鉴权接口
export const userApi = {
  // 管理员登录
  login: (data) => request.post('/api/user/login', data),
  // 获取个人信息
  info: () => request.get('/api/user/info'),
  // 退出登录
  logout: () => request.post('/api/user/logout')
}

// 文章管理接口
export const articleApi = {
  // 分页列表
  list: (params) => request.get('/api/article/list', { params }),
  // 详情
  detail: (id) => request.get(`/api/article/detail/${id}`),
  // 新增
  add: (data) => request.post('/api/article/add', data),
  // 编辑
  update: (id, data) => request.put(`/api/article/update/${id}`, data),
  // 删除
  del: (id) => request.delete(`/api/article/del/${id}`),
  // 搜索
  search: (params) => request.get('/api/article/search', { params })
}

// 分类接口
export const categoryApi = {
  // 列表
  list: () => request.get('/api/category/list'),
  // 新增
  add: (data) => request.post('/api/category/add', data)
}

// 标签接口
export const tagApi = {
  // 列表
  list: () => request.get('/api/tag/list'),
  // 新增
  add: (data) => request.post('/api/tag/add', data)
}
