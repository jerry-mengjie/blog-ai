<script setup>
// 用户管理: 列表筛选 / 资料编辑 / 兴趣标签(复用文章标签)
import { ref, reactive, onMounted } from 'vue'
// 消息提示
import { ElMessage } from 'element-plus'
// 管理端用户接口 + 标签词典
import { adminUserApi, tagApi } from '../api'
// RBAC 用户状态
import { useUserStore } from '../store/user'
// 权限码
import { PERMISSIONS } from '../rbac/permissions'

// 当前登录态(按钮级权限)
const userStore = useUserStore()

// ---------- 列表状态 ----------
const list = ref([])
const total = ref(0)
const loading = ref(false)
// 查询条件: 关键字 + 状态(空串表示不过滤)
const query = reactive({ page: 1, page_size: 10, keyword: '', status: '' })

// ---------- 标签词典(兴趣标签下拉) ----------
const tags = ref([])

// ---------- 编辑资料弹窗 ----------
const editVisible = ref(false)
const editFormRef = ref()
const editForm = reactive({
  id: null,
  nickname: '',
  email: '',
  avatar: '',
  status: 1,
  is_admin: 0
})

// ---------- 兴趣标签弹窗 ----------
const tagVisible = ref(false)
const tagUserId = ref(null)
const tagUserName = ref('')
const selectedTagIds = ref([])

// 是否可编辑(资料 / 兴趣标签)
const canEdit = () => userStore.hasPermission(PERMISSIONS.USER_EDIT)

// 加载用户分页列表
const loadList = async () => {
  loading.value = true
  try {
    // status 空串不传, 避免后端收到非法值
    const params = {
      page: query.page,
      page_size: query.page_size,
      keyword: query.keyword || undefined,
      status: query.status === '' ? undefined : query.status
    }
    const res = await adminUserApi.list(params)
    list.value = res.list
    total.value = res.total
  } finally {
    loading.value = false
  }
}

// 加载全局标签词典(与文章标签同一套)
const loadTags = async () => {
  tags.value = await tagApi.list()
}

// 打开编辑资料
const openEdit = (row) => {
  Object.assign(editForm, {
    id: row.id,
    nickname: row.nickname,
    email: row.email,
    avatar: row.avatar,
    status: row.status,
    is_admin: row.is_admin
  })
  editVisible.value = true
}

// 提交资料更新
const onSubmitEdit = async () => {
  await editFormRef.value?.validate?.()
  await adminUserApi.update(editForm.id, {
    nickname: editForm.nickname,
    email: editForm.email,
    avatar: editForm.avatar,
    status: editForm.status,
    is_admin: editForm.is_admin
  })
  ElMessage.success('更新成功')
  editVisible.value = false
  await loadList()
}

// 打开兴趣标签编辑(全量替换)
const openTags = (row) => {
  tagUserId.value = row.id
  tagUserName.value = row.nickname || row.username
  // 已绑定标签 ID
  selectedTagIds.value = (row.interest_tags || []).map((t) => t.id)
  tagVisible.value = true
}

// 提交兴趣标签
const onSubmitTags = async () => {
  await adminUserApi.setTags(tagUserId.value, { tag_ids: selectedTagIds.value })
  ElMessage.success('兴趣标签已更新')
  tagVisible.value = false
  await loadList()
}

// 搜索: 重置页码
const onSearch = () => {
  query.page = 1
  loadList()
}

// 分页
const onPageChange = (p) => {
  query.page = p
  loadList()
}

onMounted(async () => {
  await Promise.all([loadTags(), loadList()])
})
</script>

<template>
  <div>
    <!-- 工具栏: 关键字 + 状态筛选 -->
    <el-card shadow="never" class="toolbar">
      <el-input
        v-model="query.keyword"
        placeholder="用户名/昵称"
        style="width: 220px"
        clearable
        @keyup.enter="onSearch"
      />
      <el-select v-model="query.status" placeholder="状态" clearable style="width: 120px" @change="onSearch">
        <el-option label="正常" :value="1" />
        <el-option label="禁用" :value="0" />
      </el-select>
      <el-button type="primary" :icon="'Search'" @click="onSearch">搜索</el-button>
    </el-card>

    <!-- 用户表格 -->
    <el-card shadow="never">
      <el-table v-loading="loading" :data="list" border stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="username" label="用户名" width="120" />
        <el-table-column prop="nickname" label="昵称" width="120" show-overflow-tooltip />
        <el-table-column prop="email" label="邮箱" min-width="160" show-overflow-tooltip />
        <!-- 状态 -->
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === 1 ? 'success' : 'info'" size="small">
              {{ row.status === 1 ? '正常' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <!-- 角色 -->
        <el-table-column label="角色" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.is_admin === 1" type="warning" size="small">管理员</el-tag>
            <span v-else>用户</span>
          </template>
        </el-table-column>
        <!-- 兴趣标签(复用文章标签) -->
        <el-table-column label="兴趣标签" min-width="200">
          <template #default="{ row }">
            <template v-if="row.interest_tags?.length">
              <el-tag
                v-for="t in row.interest_tags"
                :key="t.id"
                class="tag-chip"
                size="small"
              >{{ t.name }}</el-tag>
            </template>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="注册时间" width="170">
          <template #default="{ row }">{{ row.create_time?.replace('T', ' ').slice(0, 16) }}</template>
        </el-table-column>
        <!-- 操作 -->
        <el-table-column v-if="canEdit()" label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="primary" @click="openTags(row)">兴趣标签</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        class="pager"
        background
        layout="total, prev, pager, next"
        :total="total"
        :page-size="query.page_size"
        :current-page="query.page"
        @current-change="onPageChange"
      />
    </el-card>

    <!-- 编辑资料 -->
    <el-dialog v-model="editVisible" title="编辑用户" width="480px">
      <el-form ref="editFormRef" :model="editForm" label-width="80px">
        <el-form-item label="昵称">
          <el-input v-model="editForm.nickname" maxlength="50" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="editForm.email" maxlength="100" />
        </el-form-item>
        <el-form-item label="头像">
          <el-input v-model="editForm.avatar" placeholder="头像 URL" maxlength="255" />
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="editForm.status" :active-value="1" :inactive-value="0" active-text="正常" inactive-text="禁用" />
        </el-form-item>
        <el-form-item label="管理员">
          <el-switch v-model="editForm.is_admin" :active-value="1" :inactive-value="0" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" @click="onSubmitEdit">确定</el-button>
      </template>
    </el-dialog>

    <!-- 兴趣标签(多选, 选项来自文章标签) -->
    <el-dialog v-model="tagVisible" :title="`兴趣标签 · ${tagUserName}`" width="480px">
      <el-select
        v-model="selectedTagIds"
        multiple
        filterable
        placeholder="选择兴趣标签"
        style="width: 100%"
      >
        <el-option v-for="t in tags" :key="t.id" :label="t.name" :value="t.id" />
      </el-select>
      <p class="hint">标签与文章标签共用同一词典，可在「分类标签」页新增。</p>
      <template #footer>
        <el-button @click="tagVisible = false">取消</el-button>
        <el-button type="primary" @click="onSubmitTags">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar { margin-bottom: 16px; display: flex; gap: 12px; flex-wrap: wrap; }
.pager { margin-top: 16px; justify-content: flex-end; }
.tag-chip { margin-right: 6px; margin-bottom: 4px; }
.muted { color: #909399; }
.hint { margin: 12px 0 0; font-size: 12px; color: #909399; }
</style>
