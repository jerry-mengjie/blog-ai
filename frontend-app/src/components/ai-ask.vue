<script setup>
// 文章底部 AI 问答组件: 预设问题 + 范围切换 + SSE 流式回答
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { aiConfig, askAi } from '../api/ai'

// 组件属性: 当前文章 ID(问答与检索的锚点)
const props = defineProps({
  articleId: { type: Number, required: true }
})

const router = useRouter()

// AI 功能是否启用(后端未配置 API Key 时整块隐藏)
const enabled = ref(false)
// 预设问题列表(由后端下发)
const presetQuestions = ref([])
// 检索范围: article=当前文章, series=当前系列
const scope = ref('article')
// 输入框内容
const question = ref('')
// 对话记录: [{ role: 'user'|'ai', text, sources }]
const messages = ref([])
// 是否正在生成回答(期间禁止重复提问)
const loading = ref(false)
// 当前流的中断函数
let abortStream = null

// 加载 AI 配置, 决定是否渲染组件
onMounted(async () => {
  try {
    const cfg = await aiConfig()
    enabled.value = cfg.enabled
    presetQuestions.value = cfg.preset_questions
  } catch { /* 配置加载失败则不展示 AI 模块 */ }
})

// 离开页面时中断未完成的流
onUnmounted(() => abortStream?.())

// 发起提问: 追加对话记录并以 SSE 接收流式回答
const ask = (text) => {
  const q = (text || question.value).trim()
  if (!q || loading.value) return
  question.value = ''
  loading.value = true
  // 追加用户消息与 AI 占位消息
  messages.value.push({ role: 'user', text: q })
  const aiMsg = { role: 'ai', text: '', sources: [] }
  messages.value.push(aiMsg)

  abortStream = askAi(
    { article_id: props.articleId, question: q, scope: scope.value },
    {
      // 先收到引用来源, 回答结束后展示
      onSources: (sources) => { aiMsg.sources = sources },
      // 逐段追加回答文本, 实现打字机效果
      onDelta: (delta) => { aiMsg.text += delta },
      onDone: () => { loading.value = false },
      onError: (msg) => {
        aiMsg.text = aiMsg.text || msg
        loading.value = false
      }
    }
  )
}

// 点击来源文章跳转(跳转其他文章详情)
const goArticle = (id) => {
  if (id !== props.articleId) router.push(`/article/${id}`)
}
</script>

<template>
  <!-- 后端启用 AI 时才渲染 -->
  <div v-if="enabled" class="ai-ask">
    <!-- 标题栏 -->
    <div class="ai-title">
      <van-icon name="chat-o" color="#1989fa" size="18" />
      <span>关于这篇文章，问 AI</span>
    </div>

    <!-- 检索范围切换: 当前文章 / 当前系列 -->
    <div class="ai-scope">
      <span class="scope-label">回答依据</span>
      <div class="scope-tabs">
        <span :class="['scope-tab', { active: scope === 'article' }]" @click="scope = 'article'">当前文章</span>
        <span :class="['scope-tab', { active: scope === 'series' }]" @click="scope = 'series'">当前系列</span>
      </div>
    </div>

    <!-- 预设问题(点击即提问) -->
    <div v-if="!messages.length" class="ai-presets">
      <span v-for="q in presetQuestions" :key="q" class="preset" @click="ask(q)">{{ q }}</span>
    </div>

    <!-- 对话记录 -->
    <div v-if="messages.length" class="ai-messages">
      <div v-for="(m, i) in messages" :key="i" :class="['msg', m.role]">
        <!-- 消息气泡: AI 回答为流式追加文本 -->
        <div class="bubble">{{ m.text }}<span v-if="m.role === 'ai' && loading && i === messages.length - 1" class="cursor">▍</span></div>
        <!-- 引用来源(仅 AI 消息且有来源时展示) -->
        <div v-if="m.role === 'ai' && m.sources?.length && !(loading && i === messages.length - 1)" class="sources">
          <span class="sources-label">来源:</span>
          <span v-for="s in m.sources" :key="s.article_id" class="source" @click="goArticle(s.article_id)">《{{ s.title }}》</span>
        </div>
      </div>
    </div>

    <!-- 提问输入行 -->
    <div class="ai-input-row">
      <van-field v-model="question" placeholder="输入你的问题, 如: 这一段什么意思?" class="ai-input" @keyup.enter="ask()" />
      <van-button type="primary" size="small" :loading="loading" @click="ask()">提问</van-button>
    </div>
  </div>
</template>

<style scoped>
.ai-ask { padding: 16px; background: #fff; margin-top: 8px; }
.ai-title { display: flex; align-items: center; gap: 6px; font-weight: 600; font-size: 15px; margin-bottom: 12px; }
/* 范围切换 */
.ai-scope { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.scope-label { font-size: 12px; color: #969799; }
.scope-tabs { display: flex; background: #f2f3f5; border-radius: 14px; padding: 2px; }
.scope-tab { font-size: 12px; padding: 4px 12px; border-radius: 12px; color: #646566; }
.scope-tab.active { background: #1989fa; color: #fff; }
/* 预设问题 */
.ai-presets { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.preset { font-size: 13px; color: #1989fa; background: #f0f7ff; border-radius: 14px; padding: 6px 12px; }
/* 对话区 */
.ai-messages { display: flex; flex-direction: column; gap: 10px; margin-bottom: 12px; }
.msg.user { align-self: flex-end; max-width: 85%; }
.msg.ai { align-self: flex-start; max-width: 95%; }
.msg.user .bubble { background: #1989fa; color: #fff; border-radius: 12px 12px 2px 12px; }
.msg.ai .bubble { background: #f7f8fa; color: #323233; border-radius: 12px 12px 12px 2px; }
.bubble { padding: 8px 12px; font-size: 14px; line-height: 1.7; white-space: pre-wrap; word-break: break-word; }
.cursor { animation: blink 1s infinite; color: #1989fa; }
@keyframes blink { 50% { opacity: 0; } }
/* 引用来源 */
.sources { margin-top: 4px; font-size: 12px; color: #969799; }
.source { color: #1989fa; margin-right: 6px; }
/* 输入行 */
.ai-input-row { display: flex; align-items: center; gap: 10px; }
.ai-input { flex: 1; background: #f7f8fa; border-radius: 16px; }
</style>
