<template>
  <section class="page" data-module="pollutant">
    <header class="page-head">
      <div>
        <h2>船舶污染物接收单据</h2>
        <p class="page-desc">{{ roleHint }}</p>
      </div>
      <div class="page-actions">
        <button v-if="store.can('接收单据填报')" class="btn primary" type="button" @click="openCreate">
          填报本航次接收单据
        </button>
        <button class="btn" type="button" @click="exportRows">导出接收清单与汇总</button>
      </div>
    </header>

    <!-- 接收汇总：数量与接收单据逐张对账 -->
    <div class="stat-row">
      <article v-for="item in summaryCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">汇总对账</span>
        <strong :class="summary?.对账?.一致 ? 'stat-value ok' : 'stat-value bad'">
          {{ summary?.对账?.一致 ? '一致' : '有差额' }}
        </strong>
      </article>
    </div>
    <table v-if="voyageGroups.length" class="data-table summary-table">
      <thead>
        <tr><th>船名/航次</th><th v-for="f in quantityFields" :key="f">{{ f }}（吨）</th><th>对应单据</th></tr>
      </thead>
      <tbody>
        <tr v-for="g in voyageGroups" :key="g.船名 + g.航次">
          <td>{{ g.船名 }} / {{ g.航次 }}</td>
          <td v-for="f in quantityFields" :key="f">{{ fmt(g[f]) }}</td>
          <td>{{ (g.接收单号 || []).join('、') }}</td>
        </tr>
      </tbody>
    </table>
    <p class="recon-note">{{ summary?.口径 }}；{{ summary?.对账?.说明 }}</p>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>关键字</span>
        <input v-model="keyword" placeholder="按接收单号、船名、航次检索" />
      </label>
      <label class="filter-item">
        <span>状态</span>
        <select v-model="statusFilter">
          <option value="">全部</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>操作（按当前角色权限呈现）</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <span v-if="column === '状态'" class="status-badge" :class="statusClass(row.status)">{{ row.status }}</span>
            <template v-else-if="column === '原填报人'">
              {{ row.原填报人 }}
              <span class="owner-fixed" title="人员调班后归属仍为首次填报人">归属固定</span>
            </template>
            <template v-else-if="column === '打回理由'">
              <span :class="row.打回理由 ? 'reject-reason' : ''">{{ row.打回理由 || '—' }}</span>
            </template>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openHistory(row)">操作记录</button>
            <template v-if="store.can('接收单据填报')">
              <button v-if="row.status === '已打回'" class="link" type="button" @click="openEdit(row)">修改接收量</button>
              <button v-if="row.status === '已打回'" class="link" type="button" @click="resubmit(row)">重新提交</button>
            </template>
            <template v-if="store.can('接收单据打回')">
              <button v-if="row.status === '待值班长确认'" class="link danger" type="button" @click="openReject(row)">打回重报</button>
            </template>
            <template v-if="store.can('接收单确认')">
              <button v-if="row.status === '待值班长确认'" class="link" type="button" @click="confirmEntry(row)">确认接收</button>
            </template>
            <template v-if="store.can('上岸转运登记')">
              <button v-if="row.status === '已确认'" class="link" type="button" @click="openTransfer(row)">登记上岸转运</button>
            </template>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">{{ emptyHint }}</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 张接收单据</span>
      <span v-if="message" :class="messageOk ? 'ok-text' : 'error-text'">{{ message }}</span>
    </footer>

    <!-- 填报 / 改量 -->
    <div v-if="formOpen" class="modal-mask" @click.self="formOpen = false">
      <div class="modal">
        <h3>{{ formMode === 'create' ? '填报本航次接收单据' : `修改接收量（${editing?.接收单号}）` }}</h3>
        <div class="form-row">
          <label>船名</label>
          <input :value="form.船名" disabled />
        </div>
        <div class="form-row">
          <label>航次</label>
          <input :value="form.航次" disabled />
        </div>
        <p class="form-note">大副只能填报自己所在船舶/本航次的单据；同一艘船同一航次只认第一次提交的单据。</p>
        <div v-for="f in quantityFields" :key="f" class="form-row">
          <label>{{ f }}（吨）</label>
          <input v-model.number="form[f]" type="number" min="0" step="0.01" />
        </div>
        <p v-if="formMode === 'edit'" class="form-note">被打回单据修改后需重新提交；每次修改都会写入操作记录。</p>
        <div class="modal-actions">
          <button class="btn" type="button" @click="formOpen = false">取消</button>
          <button class="btn primary" type="button" @click="submitForm">提交</button>
        </div>
      </div>
    </div>

    <!-- 打回理由 -->
    <div v-if="rejectOpen" class="modal-mask" @click.self="rejectOpen = false">
      <div class="modal">
        <h3>打回接收单据 {{ rejectRow?.接收单号 }}</h3>
        <p class="form-note">打回必须写清理由，大副修改接收量后可重新提交。</p>
        <div class="form-row column">
          <label>打回理由</label>
          <textarea v-model="rejectReason" rows="3" placeholder="例如：含油污水量与流量计读数不一致，请核对"></textarea>
        </div>
        <div class="modal-actions">
          <button class="btn" type="button" @click="rejectOpen = false">取消</button>
          <button class="btn primary" type="button" @click="rejectEntry">确认打回</button>
        </div>
      </div>
    </div>

    <!-- 上岸转运去向 -->
    <div v-if="transferOpen" class="modal-mask" @click.self="transferOpen = false">
      <div class="modal">
        <h3>登记上岸转运（{{ transferRow?.接收单号 }}）</h3>
        <div class="form-row column">
          <label>转运去向</label>
          <textarea v-model="transferDestination" rows="2" placeholder="例如：市污染物处置中心 / 接收联单号"></textarea>
        </div>
        <p class="form-note">登记完成后单据转为只读，仅环保专责可查看。</p>
        <div class="modal-actions">
          <button class="btn" type="button" @click="transferOpen = false">取消</button>
          <button class="btn primary" type="button" @click="confirmTransfer">完成上岸转运</button>
        </div>
      </div>
    </div>

    <!-- 操作记录（含越权改派验证入口） -->
    <div v-if="historyOpen" class="modal-mask wide" @click.self="historyOpen = false">
      <div class="modal">
        <h3>操作记录 · {{ historyRow?.接收单号 }}</h3>
        <p class="form-note">
          单据归属固定为「{{ historyRow?.原填报人 }}」，人员调班也不改标。以下记录可查到接收量被谁改过。
        </p>
        <table class="data-table">
          <thead><tr><th>时间</th><th>操作人</th><th>角色</th><th>动作</th><th>明细</th></tr></thead>
          <tbody>
            <tr v-for="(item, idx) in historyItems" :key="idx">
              <td>{{ item.时间 }}</td><td>{{ item.操作人 }}</td><td>{{ item.角色 }}</td>
              <td>{{ item.动作 }}</td><td>{{ item.明细 }}</td>
            </tr>
            <tr v-if="!historyItems.length"><td colspan="5" class="empty-state">暂无操作记录</td></tr>
          </tbody>
        </table>
        <div class="reassign-box">
          <span>越权拦截验证：尝试把本单据改派给</span>
          <select v-model="reassignTarget">
            <option v-for="person in operators" :key="person.id" :value="person.id">
              {{ person.name }}（{{ person.role }}）
            </option>
          </select>
          <button class="btn" type="button" @click="tryReassign">改派单据</button>
          <span class="form-note">任何角色都不持有「单据改派」权限，请求会被当场驳回。</span>
        </div>
        <div class="modal-actions">
          <button class="btn primary" type="button" @click="historyOpen = false">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'

import { postAction, putAction, request } from '@/api/client'
import { OPERATORS, useSessionStore } from '@/stores/session'

type Row = Record<string, string | number | null>
type HistoryItem = { 时间: string; 操作人: string; 角色: string; 动作: string; 明细: string }
type VoyageGroup = {
  船名: string
  航次: string
  单据数: number
  接收单号: string[]
  [key: string]: string | number | string[]
}
type Summary = {
  单据数: number
  接收总量: number
  分类型合计: Record<string, number>
  按船舶航次: VoyageGroup[]
  口径: string
  对账: { 一致: boolean; 说明: string }
}
type ActionPayload = {
  ok: boolean
  message: string
  entry?: unknown
  missingPermission?: string
}

const ENDPOINT = '/api/pollutant'
const store = useSessionStore()
const operators = OPERATORS

const quantityFields = ['生活垃圾', '含油污水', '生活污水', '残油废油']
const columns = ['接收单号', '船名', '航次', '原填报人', ...quantityFields, '状态', '打回理由', '转运去向', '接收时间']
const statuses = ['待值班长确认', '已打回', '已确认', '已完成上岸转运']

const rows = ref<Row[]>([])
const total = ref(0)
const summary = ref<Summary | null>(null)
const keyword = ref('')
const statusFilter = ref('')
const message = ref('')
const messageOk = ref(false)

const roleHints: Record<string, string> = {
  船上大副: '只可填报本航次自己的接收单据；被打回后可修改接收量（全程留痕）并重新提交，单据归属始终是你本人。',
  码头值班长: '可对待确认单据打回（必须写清理由）、确认接收，并对已确认单据登记上岸转运。',
  环保专责: '已完成上岸转运的单据仅可查看，可核对接收汇总与操作记录；不能填报、改量或流转。',
}
const roleHint = computed(() => roleHints[store.role] ?? '')
const emptyHint = computed(() => {
  if (store.role === '环保专责') return '当前还没有已完成上岸转运的接收单据'
  if (store.role === '船上大副') return `${store.vessel}/${store.voyage} 本航次暂无接收单据，可在右上角填报`
  return '当前范围内暂无接收单据'
})

const summaryCards = computed(() => {
  const totals = summary.value?.分类型合计 ?? {}
  return [
    { label: '可见单据', value: summary.value?.单据数 ?? 0 },
    ...quantityFields.map((f) => ({ label: `${f}（吨）`, value: fmt(totals[f] ?? 0) })),
    { label: '接收总量（吨）', value: fmt(summary.value?.接收总量 ?? 0) },
  ]
})
const voyageGroups = computed<VoyageGroup[]>(() => summary.value?.按船舶航次 ?? [])

function fmt(value: unknown): string {
  const n = Number(value)
  return Number.isFinite(n) ? String(Math.round(n * 1000) / 1000) : '0'
}
function statusClass(status: unknown): string {
  return {
    待值班长确认: 'st-pending',
    已打回: 'st-rejected',
    已确认: 'st-confirmed',
    已完成上岸转运: 'st-done',
  }[String(status)] ?? ''
}

function flash(result: ActionPayload) {
  message.value = result.missingPermission
    ? `${result.message}（缺失权限：${result.missingPermission}）`
    : result.message
  messageOk.value = result.ok
}

async function reload() {
  message.value = ''
  const query = new URLSearchParams()
  if (keyword.value) query.set('keyword', keyword.value)
  if (statusFilter.value) query.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) throw new Error('接收单据列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    message.value = error instanceof Error ? error.message : '接收单据列表读取失败'
    messageOk.value = false
  }
  await loadSummary()
}

async function loadSummary() {
  try {
    const response = await request(`${ENDPOINT}/summary`)
    if (response.ok) summary.value = await response.json()
  } catch {
    summary.value = null
  }
}

// ---------- 填报 / 改量 ----------
const formOpen = ref(false)
const formMode = ref<'create' | 'edit'>('create')
const editing = ref<Row | null>(null)
const form = reactive<Record<string, string | number>>({
  船名: '', 航次: '', 生活垃圾: 0, 含油污水: 0, 生活污水: 0, 残油废油: 0,
})

function openCreate() {
  formMode.value = 'create'
  editing.value = null
  form.船名 = store.vessel
  form.航次 = store.voyage
  quantityFields.forEach((f) => { form[f] = 0 })
  formOpen.value = true
}
function openEdit(row: Row) {
  formMode.value = 'edit'
  editing.value = row
  form.船名 = String(row.船名)
  form.航次 = String(row.航次)
  quantityFields.forEach((f) => { form[f] = Number(row[f] ?? 0) })
  formOpen.value = true
}
async function submitForm() {
  const values: Record<string, unknown> = { 船名: form.船名, 航次: form.航次 }
  quantityFields.forEach((f) => { values[f] = form[f] })
  const result = formMode.value === 'create'
    ? await postAction(ENDPOINT, { values })
    : await putAction(`${ENDPOINT}/${editing.value?.id}/quantities`, { values })
  flash(result)
  if (result.ok) {
    formOpen.value = false
    await reload()
  }
}

// ---------- 打回 ----------
const rejectOpen = ref(false)
const rejectRow = ref<Row | null>(null)
const rejectReason = ref('')
function openReject(row: Row) {
  rejectRow.value = row
  rejectReason.value = ''
  rejectOpen.value = true
}
async function rejectEntry() {
  if (!rejectReason.value.trim()) {
    message.value = '打回必须写清理由'
    messageOk.value = false
    return
  }
  const result = await postAction(`${ENDPOINT}/${rejectRow.value?.id}/actions`, {
    values: { action: '打回重报', reason: rejectReason.value.trim() },
  })
  flash(result)
  rejectOpen.value = false
  await reload()
}

async function resubmit(row: Row) {
  flash(await postAction(`${ENDPOINT}/${row.id}/actions`, { values: { action: '重新提交' } }))
  await reload()
}
async function confirmEntry(row: Row) {
  flash(await postAction(`${ENDPOINT}/${row.id}/actions`, { values: { action: '确认接收' } }))
  await reload()
}

// ---------- 上岸转运 ----------
const transferOpen = ref(false)
const transferRow = ref<Row | null>(null)
const transferDestination = ref('')
function openTransfer(row: Row) {
  transferRow.value = row
  transferDestination.value = ''
  transferOpen.value = true
}
async function confirmTransfer() {
  if (!transferDestination.value.trim()) {
    message.value = '登记上岸转运必须填写转运去向'
    messageOk.value = false
    return
  }
  const result = await postAction(`${ENDPOINT}/${transferRow.value?.id}/actions`, {
    values: { action: '登记上岸转运', destination: transferDestination.value.trim() },
  })
  flash(result)
  transferOpen.value = false
  await reload()
}

// ---------- 操作记录 / 越权改派验证 ----------
const historyOpen = ref(false)
const historyRow = ref<Row | null>(null)
const historyItems = ref<HistoryItem[]>([])
const reassignTarget = ref('chief_li')

async function openHistory(row: Row) {
  historyRow.value = row
  historyItems.value = []
  historyOpen.value = true
  try {
    const response = await request(`${ENDPOINT}/${row.id}/history`)
    if (response.ok) {
      const payload = await response.json()
      historyItems.value = payload.items ?? []
    }
  } catch {
    historyItems.value = []
  }
}
async function tryReassign() {
  const result = await postAction(`${ENDPOINT}/${historyRow.value?.id}/reassign`, {
    values: { targetId: reassignTarget.value },
  })
  flash(result)
}

function exportRows() {
  // 新开标签页无法带自定义请求头，导出接口额外支持查询参数传身份
  const query = new URLSearchParams({ operator_id: store.operatorId })
  window.open(`${ENDPOINT}/export/all?${query.toString()}`, '_blank')
}

watch(() => [store.operatorId, store.role], () => {
  message.value = ''
  void reload()
})

onMounted(reload)
</script>

<style scoped>
.ok-text { color: #067647; }
.owner-fixed { margin-left: 4px; font-size: 11px; color: #067647; border: 1px solid #abefc6; border-radius: 4px; padding: 0 4px; }
.reject-reason { color: #b42318; }
.link.danger { color: #b42318; }
.status-badge { border-radius: 10px; padding: 2px 8px; font-size: 12px; white-space: nowrap; }
.st-pending { background: #fffaeb; color: #b54708; border: 1px solid #fedf89; }
.st-rejected { background: #fef3f2; color: #b42318; border: 1px solid #fecdca; }
.st-confirmed { background: #eff8ff; color: #175cd3; border: 1px solid #b2ddff; }
.st-done { background: #ecfdf3; color: #067647; border: 1px solid #abefc6; }
.stat-value.ok { color: #067647; }
.stat-value.bad { color: #b42318; }
.summary-table { margin-bottom: 6px; }
.recon-note { color: var(--muted); font-size: 12px; margin: 4px 0 14px; }

.modal-mask { position: fixed; inset: 0; background: rgba(16, 24, 40, 0.45); display: flex; align-items: center; justify-content: center; z-index: 50; }
.modal { background: #fff; border-radius: 10px; padding: 18px 20px; width: 460px; max-height: 86vh; overflow: auto; }
.modal-mask.wide .modal { width: 760px; }
.modal h3 { margin: 0 0 12px; font-size: 16px; }
.form-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.form-row.column { flex-direction: column; align-items: stretch; }
.form-row label { width: 110px; color: var(--muted); font-size: 13px; flex: none; }
.form-row.column label { width: auto; margin-bottom: 4px; }
.form-row input, .form-row textarea, .form-row select { padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; width: 100%; }
.form-row input:disabled { background: #f2f4f7; color: var(--muted); }
.form-note { color: var(--muted); font-size: 12px; margin: 0 0 10px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
.reassign-box { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 12px 0; padding: 10px; background: #f8fafc; border: 1px dashed var(--border); border-radius: 6px; font-size: 13px; }
.reassign-box select { padding: 4px 6px; }
</style>
