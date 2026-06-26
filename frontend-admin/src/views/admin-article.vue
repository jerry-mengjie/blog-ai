<script setup>
// 引入响应式 API 与生命周期
import { ref, reactive, onMounted } from 'vue'
// 引入消息与确认
import { ElMessage, ElMessageBox } from 'element-plus'
// 引入接口
import { articleApi, categoryApi, tagApi } from '../api'
// 引入用户状态(RBAC 按钮级控制)
import { useUserStore } from '../store/user'
// 引入权限码
import { PERMISSIONS } from '../rbac/permissions'

// 用户状态
const userStore = useUserStore()

// 文章列表数据
const list = ref([])
// 总条数
const total = ref(0)
// 列表加载状态
const loading = ref(false)
// 查询条件
const query = reactive({ page: 1, page_size: 10, keyword: '' })
// 分类选项
const categories = ref([])
// 标签选项
const tags = ref([])

// 弹窗显隐
const dialogVisible = ref(false)
// 弹窗标题
const dialogTitle = ref('新增文章')
// 表单引用
const formRef = ref()
// 文章表单
const form = reactive({
  id: null,
  title: '',
  cover: '',
  summary: '',
  content: '',
  category_id: null,
  tag_ids: [],
  is_top: 0
})

// 表单校验规则
const rules = {
  // 标题必填
  title: [{ required: true, message: '请输入标题', trigger: 'blur' }],
  // 正文必填
  content: [{ required: true, message: '请输入正文', trigger: 'blur' }]
}

// 加载文章列表
const loadList = async () => {
  // 开启加载
  loading.value = true
  // 捕获异常
  try {
    // 有关键字走搜索, 否则走列表
    const res = query.keyword
      ? await articleApi.search({ keyword: query.keyword, page: query.page, page_size: query.page_size })
      : await articleApi.list({ page: query.page, page_size: query.page_size })
    // 写入列表
    list.value = res.list
    // 写入总数
    total.value = res.total
  } finally {
    // 关闭加载
    loading.value = false
  }
}

// 加载分类与标签下拉
const loadOptions = async () => {
  // 并行加载
  categories.value = await categoryApi.list()
  tags.value = await tagApi.list()
}

// 重置表单
const resetForm = () => {
  // 逐字段重置
  Object.assign(form, { id: null, title: '', cover: '', summary: '', content: '', category_id: null, tag_ids: [], is_top: 0 })
}

// 打开新增弹窗
const openAdd = () => {
  // 重置表单
  resetForm()
  // 设置标题
  dialogTitle.value = '新增文章'
  // 显示弹窗
  dialogVisible.value = true
}

// 打开编辑弹窗(需加载详情拿到正文与标签)
const openEdit = async (row) => {
  // 设置标题
  dialogTitle.value = '编辑文章'
  // 请求详情
  const detail = await articleApi.detail(row.id)
  // 标签名转回标签 ID
  const tagIds = tags.value.filter((t) => detail.tags.includes(t.name)).map((t) => t.id)
  // 填充表单
  Object.assign(form, {
    id: detail.id,
    title: detail.title,
    cover: detail.cover,
    summary: detail.summary,
    content: detail.content,
    category_id: detail.category_id || null,
    tag_ids: tagIds,
    is_top: detail.is_top
  })
  // 显示弹窗
  dialogVisible.value = true
}

// 提交表单(新增或编辑)
const onSubmit = async () => {
  // 表单校验
  await formRef.value.validate()
  // 构造提交数据
  const payload = {
    title: form.title,
    cover: form.cover,
    summary: form.summary,
    content: form.content,
    category_id: form.category_id || 0,
    tag_ids: form.tag_ids,
    is_top: form.is_top
  }
  // 区分新增/编辑
  if (form.id) {
    // 编辑
    await articleApi.update(form.id, payload)
    // 提示
    ElMessage.success('更新成功')
  } else {
    // 新增
    await articleApi.add(payload)
    // 提示
    ElMessage.success('发布成功')
  }
  // 关闭弹窗
  dialogVisible.value = false
  // 刷新列表
  await loadList()
}

// 删除文章
const onDelete = async (row) => {
  // 二次确认
  await ElMessageBox.confirm(`确认删除文章「${row.title}」?`, '提示', { type: 'warning' })
  // 调用删除
  await articleApi.del(row.id)
  // 提示
  ElMessage.success('删除成功')
  // 刷新
  await loadList()
}

// 搜索
const onSearch = () => {
  // 重置页码
  query.page = 1
  // 重新加载
  loadList()
}

// 分页页码变化
const onPageChange = (p) => {
  // 更新页码
  query.page = p
  // 重新加载
  loadList()
}

// 根据分类 ID 获取分类名(表格展示)
const categoryName = (id) => categories.value.find((c) => c.id === id)?.name || '-'

// 挂载初始化
onMounted(async () => {
  // 先加载选项再加载列表
  await loadOptions()
  await loadList()
})
</script>

<template>
  <div>
    <!-- 操作栏: 搜索 + 新增 -->
    <el-card shadow="never" class="toolbar">
      <!-- 搜索输入 -->
      <el-input v-model="query.keyword" placeholder="搜索标题" style="width: 240px" clearable @keyup.enter="onSearch" />
      <!-- 搜索按钮 -->
      <el-button type="primary" :icon="'Search'" @click="onSearch">搜索</el-button>
      <!-- 新增按钮(需编辑权限, 体现按钮级 RBAC) -->
      <el-button v-if="userStore.hasPermission(PERMISSIONS.ARTICLE_EDIT)" type="success" :icon="'Plus'" @click="openAdd">新增文章</el-button>
    </el-card>

    <!-- 文章表格 -->
    <el-card shadow="never">
      <el-table v-loading="loading" :data="list" border stripe>
        <!-- ID -->
        <el-table-column prop="id" label="ID" width="70" />
        <!-- 标题 -->
        <el-table-column prop="title" label="标题" min-width="200" show-overflow-tooltip />
        <!-- 分类 -->
        <el-table-column label="分类" width="100">
          <template #default="{ row }">{{ categoryName(row.category_id) }}</template>
        </el-table-column>
        <!-- 浏览量 -->
        <el-table-column prop="view_count" label="浏览" width="90" />
        <!-- 置顶 -->
        <el-table-column label="置顶" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.is_top" type="danger" size="small">置顶</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <!-- 时间 -->
        <el-table-column label="发布时间" width="170">
          <template #default="{ row }">{{ row.create_time?.replace('T', ' ').slice(0, 16) }}</template>
        </el-table-column>
        <!-- 操作 -->
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <!-- 编辑按钮(需编辑权限) -->
            <el-button v-if="userStore.hasPermission(PERMISSIONS.ARTICLE_EDIT)" link type="primary" @click="openEdit(row)">编辑</el-button>
            <!-- 删除按钮(需删除权限) -->
            <el-button v-if="userStore.hasPermission(PERMISSIONS.ARTICLE_DELETE)" link type="danger" @click="onDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
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

    <!-- 新增/编辑弹窗 -->
    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="640px">
      <!-- 表单 -->
      <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
        <!-- 标题 -->
        <el-form-item label="标题" prop="title">
          <el-input v-model="form.title" placeholder="请输入标题" />
        </el-form-item>
        <!-- 封面 -->
        <el-form-item label="封面">
          <el-input v-model="form.cover" placeholder="封面图片 URL" />
        </el-form-item>
        <!-- 分类 -->
        <el-form-item label="分类">
          <el-select v-model="form.category_id" placeholder="选择分类" clearable style="width: 100%">
            <el-option v-for="c in categories" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <!-- 标签(多选) -->
        <el-form-item label="标签">
          <el-select v-model="form.tag_ids" multiple placeholder="选择标签" style="width: 100%">
            <el-option v-for="t in tags" :key="t.id" :label="t.name" :value="t.id" />
          </el-select>
        </el-form-item>
        <!-- 摘要 -->
        <el-form-item label="摘要">
          <el-input v-model="form.summary" type="textarea" :rows="2" placeholder="文章摘要" />
        </el-form-item>
        <!-- 正文 -->
        <el-form-item label="正文" prop="content">
          <el-input v-model="form.content" type="textarea" :rows="8" placeholder="文章正文" />
        </el-form-item>
        <!-- 置顶 -->
        <el-form-item label="置顶">
          <el-switch v-model="form.is_top" :active-value="1" :inactive-value="0" />
        </el-form-item>
      </el-form>
      <!-- 底部按钮 -->
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="onSubmit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
/* 工具栏间距 */
.toolbar { margin-bottom: 16px; display: flex; gap: 12px; }
/* 分页右对齐 */
.pager { margin-top: 16px; justify-content: flex-end; }
</style>
