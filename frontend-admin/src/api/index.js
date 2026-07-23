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

// 管理端用户接口(含兴趣标签)
export const adminUserApi = {
  // 分页列表(支持 keyword / status)
  list: (params) => request.get('/api/admin/user/list', { params }),
  // 详情
  detail: (id) => request.get(`/api/admin/user/detail/${id}`),
  // 更新资料(昵称/邮箱/头像/状态/管理员)
  update: (id, data) => request.put(`/api/admin/user/${id}`, data),
  // 全量设置兴趣标签(tag_ids 复用文章标签)
  setTags: (id, data) => request.put(`/api/admin/user/${id}/tags`, data)
}

// 管理端浏览统计
export const adminBrowseApi = {
  // 分页列表(keyword / user_id / article_id)
  list: (params) => request.get('/api/admin/browse/list', { params })
}
