<template>
  <section class="page" data-module="inspection">
    <header class="page-head">
      <div>
        <h2>巡检计划管理</h2>
        <p class="page-desc">维护巡检任务，围绕巡检编号、巡检站点、巡检类型、计划日期做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记巡检任务</button>
        <button class="btn" type="button" @click="exportRows">导出巡检计划清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="applyFilters">
      <label class="filter-item">
        <span>巡检编号</span>
        <input v-model="filters.keyword" placeholder="按巡检编号检索" />
      </label>
      <label class="filter-item">
        <span>巡检状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div v-if="selectedIds.size" class="batch-bar">
      <span>已选 <strong>{{ selectedIds.size }}</strong> 条巡检任务（跨页保留）</span>
      <button class="btn" type="button" @click="clearSelection">清空选择</button>
      <button class="btn primary" type="button" @click="openBatch">批量安排执行人员 / 巡检路线</button>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th class="col-check">
            <input
              ref="headerCheck"
              type="checkbox"
              :checked="allCurrentSelected"
              @change="toggleCurrentPage"
            />
          </th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td class="col-check">
            <input
              type="checkbox"
              :checked="isSelected(Number(row.id))"
              @change="toggleOne(Number(row.id))"
            />
          </td>
          <td v-for="column in columns" :key="column">{{ displayCell(row, column) }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无巡检计划数据，可先登记巡检任务</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条巡检计划记录，第 {{ page }} / {{ totalPages || 1 }} 页</span>
      <div class="pager">
        <label>
          每页
          <select v-model.number="size" @change="changePageSize">
            <option :value="5">5</option>
            <option :value="10">10</option>
            <option :value="20">20</option>
          </select>
          条
        </label>
        <button class="btn" type="button" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
        <button class="btn" type="button" :disabled="page >= totalPages" @click="goPage(page + 1)">下一页</button>
      </div>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="batchVisible" class="modal-mask" @click.self="closeBatch">
      <div class="modal">
        <h3>批量安排巡检任务</h3>
        <p class="modal-tip">将为已勾选的 {{ selectedIds.size }} 条任务统一安排执行人员与巡检路线；缺少计划日期的任务会被单独拦截。</p>
        <form v-if="!batchResult" class="modal-form" @submit.prevent="submitBatch">
          <label>
            <span>执行人员 <em>*</em></span>
            <input v-model="batchForm.inspector" placeholder="如：李四" />
          </label>
          <label>
            <span>巡检路线 <em>*</em></span>
            <input v-model="batchForm.route" placeholder="如：A区组件-逆变器环线" />
          </label>
          <p v-if="batchError" class="error-text">{{ batchError }}</p>
          <div class="modal-actions">
            <button class="btn" type="button" :disabled="submitting" @click="closeBatch">取消</button>
            <button class="btn primary" type="submit" :disabled="submitting">
              {{ submitting ? '正在提交…' : '确认安排' }}
            </button>
          </div>
        </form>
        <div v-else class="modal-result">
          <p class="result-summary">
            {{ batchResult.message }}，逐条结果如下：
          </p>
          <ul class="result-list">
            <li v-for="item in batchResult.results" :key="item.entry_id" :class="item.ok ? 'ok' : 'fail'">
              <span class="result-mark">{{ item.ok ? '成功' : '拦截' }}</span>
              {{ item.message }}
            </li>
          </ul>
          <div class="modal-actions">
            <button class="btn primary" type="button" @click="closeBatch">完成</button>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watchEffect } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

interface StatsPayload {
  pending: number
  in_progress: number
  completed: number
  missed: number
  total: number
}

interface BatchItemResult {
  entry_id: number
  ok: boolean
  message: string
}

interface BatchResultPayload {
  ok: boolean
  message: string
  success_count: number
  failed_count: number
  results: BatchItemResult[]
}

const ENDPOINT = '/api/inspection'
const columns = ['巡检编号', '巡检站点', '巡检类型', '计划日期', '巡检人员', '巡检路线', '发现缺陷数', '巡检状态']
const actions = ['开始巡检', '完成巡检', '标记漏检']
const statuses = ['待执行', '执行中', '已完成', '已漏检']

const rows = ref<Row[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(10)
const errorMessage = ref('')
const filters = reactive({ keyword: '', status: '' })

const stats = ref([
  { label: '待巡检任务', value: 0 },
  { label: '执行中任务', value: 0 },
  { label: '已完成巡检', value: 0 },
  { label: '漏检任务', value: 0 },
])

// 勾选只保存任务 id，翻页、筛选、重查都不丢失
const selectedIds = ref<Set<number>>(new Set())
const headerCheck = ref<HTMLInputElement | null>(null)

const totalPages = computed(() => Math.ceil(total.value / size.value) || 1)
const currentPageIds = computed(() => rows.value.map((row) => Number(row.id)))
const allCurrentSelected = computed(
  () => currentPageIds.value.length > 0
    && currentPageIds.value.every((id) => selectedIds.value.has(id)),
)

// 表头复选框需要 indeterminate 态：当前页部分选中
watchEffect(() => {
  const el = headerCheck.value
  if (!el) return
  const selectedOnPage = currentPageIds.value.filter((id) => selectedIds.value.has(id)).length
  el.indeterminate = selectedOnPage > 0 && selectedOnPage < currentPageIds.value.length
})

function displayCell(row: Row, column: string) {
  const value = row[column]
  return value === null || value === undefined || value === '' ? '—' : value
}

function isSelected(id: number) {
  return selectedIds.value.has(id)
}

function toggleOne(id: number) {
  const next = new Set(selectedIds.value)
  if (next.has(id)) {
    next.delete(id)
  } else {
    next.add(id)
  }
  selectedIds.value = next
}

function toggleCurrentPage() {
  const next = new Set(selectedIds.value)
  if (allCurrentSelected.value) {
    currentPageIds.value.forEach((id) => next.delete(id))
  } else {
    currentPageIds.value.forEach((id) => next.add(id))
  }
  selectedIds.value = next
}

function clearSelection() {
  selectedIds.value = new Set()
}

async function reloadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) {
      return
    }
    const payload = (await response.json()) as StatsPayload
    stats.value = [
      { label: '待巡检任务', value: payload.pending },
      { label: '执行中任务', value: payload.in_progress },
      { label: '已完成巡检', value: payload.completed },
      { label: '漏检任务', value: payload.missed },
    ]
  } catch {
    // 卡片刷新失败不阻断列表操作
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.keyword.trim()) query.set('keyword', filters.keyword.trim())
  if (filters.status) query.set('status', filters.status)
  query.set('page', String(page.value))
  query.set('size', String(size.value))
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('巡检任务列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '巡检计划列表读取失败'
  }
}

function applyFilters() {
  page.value = 1
  void reload()
}

function resetFilters() {
  filters.keyword = ''
  filters.status = ''
  page.value = 1
  void reload()
}

function goPage(target: number) {
  if (target < 1 || target > totalPages.value) return
  page.value = target
  void reload()
}

function changePageSize() {
  page.value = 1
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '巡检任务登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message ?? '巡检计划动作未生效，请稍后重试')
    }
    await Promise.all([reload(), reloadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '巡检计划操作失败'
  }
}

const batchVisible = ref(false)
const submitting = ref(false)
const batchError = ref('')
const batchForm = reactive({ inspector: '', route: '' })
const batchResult = ref<BatchResultPayload | null>(null)
let batchToken = ''

function openBatch() {
  if (!selectedIds.value.size) return
  batchForm.inspector = ''
  batchForm.route = ''
  batchError.value = ''
  batchResult.value = null
  batchToken = `${Date.now()}-${Math.random().toString(36).slice(2)}`
  batchVisible.value = true
}

function closeBatch() {
  // 提交进行中不允许关闭，避免重复触发同一次批量动作
  if (submitting.value) return
  batchVisible.value = false
}

async function submitBatch() {
  if (submitting.value) return
  batchError.value = ''
  if (!batchForm.inspector.trim() || !batchForm.route.trim()) {
    batchError.value = '请先填写执行人员和巡检路线'
    return
  }
  submitting.value = true
  try {
    const response = await request(`${ENDPOINT}/batch/arrange`, {
      method: 'POST',
      body: JSON.stringify({
        entry_ids: [...selectedIds.value],
        inspector: batchForm.inspector.trim(),
        route: batchForm.route.trim(),
        client_token: batchToken,
      }),
    })
    const payload = (await response.json()) as BatchResultPayload
    if (!response.ok || !payload.ok) {
      throw new Error(payload?.message ?? '批量安排失败，请稍后重试')
    }
    batchResult.value = payload
    // 整组提交完成：清空选择，列表回到第一页，数量卡片同步重算
    clearSelection()
    page.value = 1
    await Promise.all([reload(), reloadStats()])
  } catch (error) {
    batchError.value = error instanceof Error ? error.message : '批量安排失败'
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  void reload()
  void reloadStats()
})
</script>

<style scoped>
.col-check {
  width: 36px;
  text-align: center;
}
.batch-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #eef4ff;
  border: 1px solid #b9d2ff;
  border-radius: 8px;
  padding: 8px 12px;
  margin-bottom: 12px;
  font-size: 13px;
}
.pager {
  display: flex;
  align-items: center;
  gap: 8px;
}
.pager select {
  padding: 2px 4px;
}
.pager .btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal {
  width: 520px;
  max-height: 80vh;
  overflow-y: auto;
  background: #fff;
  border-radius: 10px;
  padding: 18px 20px;
}
.modal h3 {
  margin: 0 0 8px;
}
.modal-tip {
  color: var(--muted);
  font-size: 13px;
  margin: 0 0 14px;
}
.modal-form label {
  display: block;
  margin-bottom: 12px;
}
.modal-form label span {
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 4px;
}
.modal-form label em {
  color: #b42318;
  font-style: normal;
}
.modal-form input {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 12px;
}
.result-summary {
  margin: 0 0 8px;
  font-size: 13px;
}
.result-list {
  list-style: none;
  margin: 0;
  padding: 0;
  border: 1px solid var(--border);
  border-radius: 8px;
  max-height: 320px;
  overflow-y: auto;
}
.result-list li {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  padding: 8px 10px;
  font-size: 13px;
  border-bottom: 1px solid var(--border);
}
.result-list li:last-child {
  border-bottom: none;
}
.result-mark {
  flex-shrink: 0;
  border-radius: 4px;
  padding: 0 6px;
  font-size: 12px;
  line-height: 18px;
}
.result-list li.ok .result-mark {
  background: #e7f6ec;
  color: #1a7f37;
}
.result-list li.fail .result-mark {
  background: #fdecea;
  color: #b42318;
}
</style>
