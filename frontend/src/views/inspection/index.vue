<template>
  <section class="page" data-module="inspection">
    <header class="page-head">
      <div>
        <h2>巡检计划管理</h2>
        <p class="page-desc">维护巡检任务，围绕巡检编号、巡检站点、巡检类型、计划日期做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记巡检任务</button>
        <button
          class="btn primary"
          type="button"
          :disabled="!selectedIds.size"
          @click="openAssign"
        >
          批量安排（{{ selectedIds.size }}）
        </button>
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
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th class="check-col">
            <input
              type="checkbox"
              :checked="allPageSelected"
              :indeterminate="somePageSelected"
              aria-label="全选本页"
              @change="togglePageSelection"
            />
          </th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td class="check-col">
            <input
              type="checkbox"
              :checked="selectedIds.has(Number(row.id))"
              :aria-label="`选择 ${row.巡检编号 ?? row.id}`"
              @change="toggleRow(Number(row.id))"
            />
          </td>
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
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
      <span>共 {{ total }} 条巡检计划记录，已选 {{ selectedIds.size }} 条（跨页保留）</span>
      <span class="pager">
        <button class="btn ghost" type="button" :disabled="page <= 1" @click="changePage(page - 1)">上一页</button>
        <span>第 {{ page }} / {{ totalPages }} 页</span>
        <button class="btn ghost" type="button" :disabled="page >= totalPages" @click="changePage(page + 1)">下一页</button>
        <select v-model.number="size" @change="changeSize">
          <option v-for="option in sizeOptions" :key="option" :value="option">{{ option }} 条/页</option>
        </select>
      </span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="showAssign" class="dialog-mask" @click.self="closeAssign">
      <div class="dialog-panel">
        <h3>批量安排巡检任务</h3>
        <template v-if="!assignResults">
          <p class="dialog-desc">
            已选 {{ selectedIds.size }} 条任务（跨页勾选会一起提交），为它们统一安排执行人员与巡检路线；
            缺少计划日期的任务会被单独拦截，不影响同批其他任务。
          </p>
          <label class="dialog-field">
            <span>执行人员</span>
            <input v-model.trim="assignForm.executor" placeholder="例如：张三" />
          </label>
          <label class="dialog-field">
            <span>巡检路线</span>
            <input v-model.trim="assignForm.route" placeholder="例如：A 区一号路线" />
          </label>
          <p v-if="assignError" class="error-text">{{ assignError }}</p>
          <div class="dialog-actions">
            <button class="btn ghost" type="button" :disabled="submitting" @click="closeAssign">取消</button>
            <button class="btn primary" type="button" :disabled="submitting" @click="submitAssign">
              {{ submitting ? '正在提交…' : '确认安排' }}
            </button>
          </div>
        </template>
        <template v-else>
          <p class="dialog-desc">{{ assignSummary }}</p>
          <ul class="assign-result-list">
            <li
              v-for="item in assignResults"
              :key="item.id"
              :class="item.ok ? 'result-ok' : 'result-blocked'"
            >
              {{ item.code || `任务 ${item.id}` }}：{{ item.message }}
            </li>
          </ul>
          <div class="dialog-actions">
            <button class="btn primary" type="button" @click="closeAssign">完成</button>
          </div>
        </template>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type StatCard = { label: string; value: number }
type AssignItem = { id: number; code: string; ok: boolean; message: string }

const ENDPOINT = '/api/inspection'
const columns = ["巡检编号", "巡检站点", "巡检类型", "计划日期", "巡检人员", "巡检路线", "发现缺陷数", "巡检状态"]
const actions = ["开始巡检", "完成巡检", "标记漏检"]
const sizeOptions = [5, 10, 20, 50]

const rows = ref<Row[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(5)
const stats = ref<StatCard[]>([
  { label: '待巡检任务', value: 0 },
  { label: '已完成巡检', value: 0 },
  { label: '漏检任务', value: 0 },
])
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

// 多选用 id 集合承载，翻页只换 rows 不动它，选择范围自然跨页保留
const selectedIds = ref<Set<number>>(new Set())
const showAssign = ref(false)
const submitting = ref(false)
const assignForm = ref({ executor: '', route: '' })
const assignError = ref('')
const assignResults = ref<AssignItem[] | null>(null)
const assignSummary = ref('')
const batchId = ref('')

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / size.value)))
const allPageSelected = computed(
  () => rows.value.length > 0 && rows.value.every((row) => selectedIds.value.has(Number(row.id))),
)
const somePageSelected = computed(
  () => !allPageSelected.value && rows.value.some((row) => selectedIds.value.has(Number(row.id))),
)

function toggleRow(id: number) {
  if (selectedIds.value.has(id)) {
    selectedIds.value.delete(id)
  } else {
    selectedIds.value.add(id)
  }
}

function togglePageSelection() {
  if (allPageSelected.value) {
    rows.value.forEach((row) => selectedIds.value.delete(Number(row.id)))
  } else {
    rows.value.forEach((row) => selectedIds.value.add(Number(row.id)))
  }
}

function changePage(target: number) {
  if (target < 1 || target > totalPages.value || target === page.value) {
    return
  }
  page.value = target
  void reload()
}

function changeSize() {
  page.value = 1
  void reload()
}

function applyFilters() {
  page.value = 1
  void reload()
}

function resetFilters() {
  filters.value = {}
  page.value = 1
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '巡检任务登记入口尚未接入审批流'
}

function createBatchId() {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `batch-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function openAssign() {
  if (!selectedIds.value.size) {
    errorMessage.value = '请先勾选需要安排的巡检任务'
    return
  }
  errorMessage.value = ''
  assignForm.value = { executor: '', route: '' }
  assignError.value = ''
  assignResults.value = null
  assignSummary.value = ''
  // 每次打开对话框生成一个幂等键：同一次批量动作的重试、连点都带它，后端只安排一次
  batchId.value = createBatchId()
  showAssign.value = true
}

function closeAssign() {
  if (submitting.value) {
    return
  }
  showAssign.value = false
  assignResults.value = null
}

async function submitAssign() {
  if (submitting.value) {
    return
  }
  if (!assignForm.value.executor || !assignForm.value.route) {
    assignError.value = '请填写执行人员与巡检路线'
    return
  }
  submitting.value = true
  assignError.value = ''
  try {
    const response = await request(`${ENDPOINT}/batch-assign`, {
      method: 'POST',
      body: JSON.stringify({
        ids: [...selectedIds.value],
        values: { 巡检人员: assignForm.value.executor, 巡检路线: assignForm.value.route },
        batch_id: batchId.value,
      }),
    })
    const payload = await response.json()
    if (!response.ok) {
      throw new Error(payload?.detail ?? '批量安排提交失败，请稍后重试')
    }
    if (!payload.ok) {
      assignError.value = payload.message || '批量安排未生效'
      return
    }
    assignResults.value = payload.results ?? []
    assignSummary.value = payload.duplicated ? `${payload.message}（重复提交，未重复安排）` : payload.message
    // 已安排的任务退出多选；被拦截的保留勾选，补齐信息后可直接再次提交
    const succeeded = new Set<number>(
      (payload.results ?? []).filter((item: AssignItem) => item.ok).map((item: AssignItem) => item.id),
    )
    selectedIds.value = new Set([...selectedIds.value].filter((id) => !succeeded.has(id)))
    // 整组提交完成后，任务列表和数量卡片同步重算
    await refreshAll()
  } catch (error) {
    assignError.value = error instanceof Error ? error.message : '批量安排提交失败'
  } finally {
    submitting.value = false
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('巡检计划动作未生效，请稍后重试')
    }
    await refreshAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '巡检计划操作失败'
  }
}

async function refreshAll() {
  await Promise.all([reload(), loadStats()])
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams({
    ...(filters.value as Record<string, string>),
    page: String(page.value),
    size: String(size.value),
  }).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('巡检任务列表读取失败')
    }
    const payload = await response.json()
    total.value = payload.total ?? 0
    const maxPage = Math.max(1, Math.ceil(total.value / size.value))
    if (page.value > maxPage) {
      page.value = maxPage
      return reload()
    }
    rows.value = payload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '巡检计划列表读取失败'
  }
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) {
      throw new Error('巡检数量卡片读取失败')
    }
    const payload = await response.json()
    if (Array.isArray(payload.cards)) {
      stats.value = payload.cards
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '巡检数量卡片读取失败'
  }
}

onMounted(refreshAll)
</script>
