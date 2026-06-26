<script setup>
// 引入响应式 API 与生命周期
import { ref, onMounted } from 'vue'
// 引入消息提示
import { ElMessage } from 'element-plus'
// 引入接口
import { categoryApi, tagApi } from '../api'
// 引入用户状态(RBAC)
import { useUserStore } from '../store/user'
// 引入权限码
import { PERMISSIONS } from '../rbac/permissions'

// 用户状态
const userStore = useUserStore()

// 分类列表
const categories = ref([])
// 标签列表
const tags = ref([])
// 新增分类表单
const categoryForm = ref({ name: '', sort: 0 })
// 新增标签输入
const tagName = ref('')

// 加载分类
const loadCategories = async () => {
  // 请求分类列表
  categories.value = await categoryApi.list()
}

// 加载标签
const loadTags = async () => {
  // 请求标签列表
  tags.value = await tagApi.list()
}

// 新增分类
const addCategory = async () => {
  // 校验名称
  if (!categoryForm.value.name.trim()) return ElMessage.warning('请输入分类名称')
  // 调用接口
  await categoryApi.add(categoryForm.value)
  // 提示
  ElMessage.success('新增成功')
  // 清空表单
  categoryForm.value = { name: '', sort: 0 }
  // 刷新
  await loadCategories()
}

// 新增标签
const addTag = async () => {
  // 校验名称
  if (!tagName.value.trim()) return ElMessage.warning('请输入标签名称')
  // 调用接口
  await tagApi.add({ name: tagName.value })
  // 提示
  ElMessage.success('新增成功')
  // 清空输入
  tagName.value = ''
  // 刷新
  await loadTags()
}

// 是否拥有编辑权限(控制新增表单显示)
const canEdit = userStore.hasPermission(PERMISSIONS.CATEGORY_EDIT)

// 挂载初始化
onMounted(async () => {
  // 并行加载
  await Promise.all([loadCategories(), loadTags()])
})
</script>

<template>
  <!-- 两列布局: 左分类 右标签 -->
  <el-row :gutter="20">
    <!-- 分类管理 -->
    <el-col :span="12">
      <el-card shadow="never">
        <!-- 卡片头 -->
        <template #header>分类管理</template>
        <!-- 新增分类表单(需编辑权限) -->
        <div v-if="canEdit" class="add-form">
          <!-- 名称 -->
          <el-input v-model="categoryForm.name" placeholder="分类名称" style="width: 160px" />
          <!-- 排序 -->
          <el-input-number v-model="categoryForm.sort" :min="0" placeholder="排序" />
          <!-- 新增按钮 -->
          <el-button type="primary" :icon="'Plus'" @click="addCategory">新增</el-button>
        </div>
        <!-- 分类表格 -->
        <el-table :data="categories" border stripe>
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="name" label="名称" />
          <el-table-column prop="sort" label="排序" width="90" />
        </el-table>
      </el-card>
    </el-col>

    <!-- 标签管理 -->
    <el-col :span="12">
      <el-card shadow="never">
        <!-- 卡片头 -->
        <template #header>标签管理</template>
        <!-- 新增标签表单(需编辑权限) -->
        <div v-if="canEdit" class="add-form">
          <!-- 名称 -->
          <el-input v-model="tagName" placeholder="标签名称" style="width: 200px" />
          <!-- 新增按钮 -->
          <el-button type="primary" :icon="'Plus'" @click="addTag">新增</el-button>
        </div>
        <!-- 标签展示 -->
        <div class="tag-list">
          <el-tag v-for="t in tags" :key="t.id" class="tag-item" size="large">{{ t.name }}</el-tag>
          <!-- 空状态 -->
          <el-empty v-if="!tags.length" description="暂无标签" />
        </div>
      </el-card>
    </el-col>
  </el-row>
</template>

<style scoped>
/* 新增表单间距 */
.add-form { display: flex; gap: 12px; margin-bottom: 16px; }
/* 标签容器 */
.tag-list { display: flex; flex-wrap: wrap; gap: 10px; min-height: 100px; }
/* 标签项 */
.tag-item { margin: 0; }
</style>
