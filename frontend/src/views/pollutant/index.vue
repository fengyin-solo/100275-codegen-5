<template>
  <section class="page" data-module="pollutant">
    <header class="page-head">
      <div>
        <h2>船舶污染物接收单据</h2>
        <p class="page-desc">
          归属固定：大副只能填报本航次自己的单据，值班长可打回并写明理由，环保专责对已完成上岸转运单据只读；
          同船同航次只认第一次提交，接收量改动逐条留痕。
        </p>
      </div>
      <div class="page-actions">
        <button v-if="can('pollutant:create')" class="btn primary" type="button" @click="openCreate">填报接收单据</button>
        <button class="btn" type="button" @click="toggleSummary">{{ showSummary ? '收起接收汇总' : '查看接收汇总' }}</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <!-- 接收汇总：数量实时来自接收单据，并显示对账结果 -->
    <section v-if="showSummary" class="summary-panel">
      <header class="summary-head">
        <strong>接收汇总（{{ summary?.['口径'] ?? '全部有效单据' }}）</strong>
        <div class="summary-tools">
          <label class="inline">
            口径
            <select v-model="summaryScope" @change="reloadSummary">
              <option value="effective">全部有效单据</option>
              <option value="transferred">已完成上岸转运</option>
            </select>
          </label>
          <span :class="['recon-badge', summary?.对账?.matched ? 'ok' : 'bad']">
            {{ summary?.对账?.matched ? '汇总与单据核对一致' : '汇总与单据存在差异' }}
          </span>
        </div>
      </header>
      <table class="data-table">
        <thead>
          <tr><th>污染物类别</th><th>汇总数量</th><th>单位</th></tr>
        </thead>
        <tbody>
          <tr v-for="cat in summary?.['分类合计'] ?? []" :key="cat.类别">
            <td>{{ cat.类别 }}</td>
            <td>{{ cat.数量 }}</td>
            <td>{{ cat.单位 }}</td>
          </tr>
          <tr>
            <td><strong>数量总计</strong></td>
            <td><strong>{{ summary?.['数量总计'] ?? 0 }}</strong></td>
            <td>分类合计求和 {{ summary?.对账?.['分类合计求和'] ?? 0 }} / 单据逐项求和 {{ summary?.对账?.['单据逐项求和'] ?? 0 }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="(summary?.对账?.['重复船次']?.length ?? 0) > 0" class="error-text">
        发现同船同航次重复单据：{{ dupText }}
      </p>
    </section>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>单据编号</span>
        <input v-model="filters.keyword" placeholder="按单据编号检索" />
      </label>
      <label class="filter-item">
        <span>船名</span>
        <input v-model="filters.ship" placeholder="按船名检索" />
      </label>
      <label class="filter-item">
        <span>航次</span>
        <input v-model="filters.voyage" placeholder="按航次检索" />
      </label>
      <label class="filter-item">
        <span>状态</span>
        <select v-model="filters.status">
          <option value="">全部</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td>{{ row['单据编号'] }}</td>
          <td>{{ row['船名'] }}</td>
          <td>{{ row['航次'] }}</td>
          <td>
            <span v-for="d in row['污染物明细']" :key="d.类别" class="detail-chip">
              {{ d.类别 }} {{ d.数量 }}{{ d.单位 }}
            </span>
          </td>
          <td>{{ row['接收总量'] }}</td>
          <td>
            {{ row['原填报人'] }}
            <span v-if="!row['原填报人在岗']" class="shift-tag" title="人员已调班，归属仍保留为原填报人">已调班</span>
          </td>
          <td>{{ row['填报时间'] }}</td>
          <td><span :class="['status-tag', statusClass(row.status)]">{{ row.status }}</span></td>
          <td>
            <span v-if="row.status === '已打回'" class="reject-reason">{{ row['驳回理由'] }}</span>
            <span v-else>—</span>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openLogs(row)">留痕</button>
            <template v-for="action in actionsFor(row)" :key="action.key">
              <button class="link" type="button" @click="runAction(action.key, row)">{{ action.label }}</button>
            </template>
            <span v-if="actionsFor(row).length === 0" class="muted">仅可查看</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无接收单据数据</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 张接收单据</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 填报 / 修改 / 重新提交 -->
    <div v-if="form.open" class="modal-mask" @click.self="closeForm">
      <div class="modal">
        <h3>{{ form.title }}</h3>
        <p v-if="form.hint" class="muted">{{ form.hint }}</p>
        <label class="form-item">
          <span>船名</span>
          <input v-model="form.ship" :disabled="form.mode !== 'create' || !!me?.ship" />
        </label>
        <label class="form-item">
          <span>航次</span>
          <input v-model="form.voyage" :disabled="form.mode !== 'create' || !!me?.voyage" />
        </label>
        <fieldset class="form-item">
          <legend>各类污染物接收量（单位按目录固定）</legend>
          <label v-for="unit in pollutantUnits" :key="unit.cat" class="qty-item">
            <span>{{ unit.cat }}（{{ unit.unit }}）</span>
            <input v-model.number="form.details[unit.cat]" type="number" min="0" step="0.001" placeholder="0" />
          </label>
        </fieldset>
        <label class="form-item">
          <span>修改说明</span>
          <input v-model="form.note" placeholder="可填，留痕里会带上" />
        </label>
        <div class="modal-actions">
          <button class="btn" type="button" @click="closeForm">取消</button>
          <button class="btn primary" type="button" :disabled="form.saving" @click="submitForm">{{ form.saving ? '提交中…' : '提交' }}</button>
        </div>
      </div>
    </div>

    <!-- 打回理由 -->
    <div v-if="reject.open" class="modal-mask" @click.self="reject.open = false">
      <div class="modal">
        <h3>打回单据 {{ reject.row?.['单据编号'] }}</h3>
        <label class="form-item">
          <span>打回理由（必填，原填报人凭此修订）</span>
          <textarea v-model="reject.reason" rows="4" placeholder="例如：含油污水接收量与船方流量计读数不一致，请核对后重新提交"></textarea>
        </label>
        <div class="modal-actions">
          <button class="btn" type="button" @click="reject.open = false">取消</button>
          <button class="btn primary" type="button" :disabled="reject.saving" @click="submitReject">{{ reject.saving ? '提交中…' : '确认打回' }}</button>
        </div>
      </div>
    </div>

    <!-- 数量改动留痕 -->
    <div v-if="logs.open" class="modal-mask" @click.self="logs.open = false">
      <div class="modal modal-wide">
        <h3>操作留痕 · {{ logs.row?.['单据编号'] }}</h3>
        <table class="data-table">
          <thead>
            <tr><th>时间</th><th>动作</th><th>操作人</th><th>角色</th><th>数量变化（原值 → 新值）</th><th>说明</th></tr>
          </thead>
          <tbody>
            <tr v-for="(log, index) in logs.items" :key="index">
              <td>{{ log['时间'] }}</td>
              <td>{{ log['动作'] }}</td>
              <td>{{ log['操作人'] }}</td>
              <td>{{ log['操作人角色'] }}</td>
              <td>
                <span v-for="change in log['数量变化']" :key="change.类别" class="change-line">
                  {{ change.类别 }}：{{ change.原值 }} → {{ change.新值 }} {{ change.单位 }}（{{ change.改动量 >= 0 ? '+' : '' }}{{ change.改动量 }}）
                </span>
                <span v-if="!log['数量变化']?.length" class="muted">无数量改动</span>
              </td>
              <td>{{ log['说明'] }}</td>
            </tr>
          </tbody>
        </table>
        <div class="modal-actions">
          <button class="btn primary" type="button" @click="logs.open = false">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'

import { parseError, request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

const ENDPOINT = '/api/pollutant'

type Detail = { 类别: string; 数量: number; 单位: string }
type Row = {
  id: number
  单据编号: string
  船名: string
  航次: string
  污染物明细: Detail[]
  接收总量: number
  原填报人: string
  原填报人在岗: boolean
  填报人ID: string
  填报时间: string
  status: string
  驳回理由: string
}
type LogEntry = {
  时间: string
  动作: string
  操作人: string
  操作人角色: string
  数量变化: { 类别: string; 原值: number; 新值: number; 改动量: number; 单位: string }[]
  说明: string
}
type Summary = {
  口径: string
  单据数: number
  分类合计: { 类别: string; 数量: number; 单位: string }[]
  数量总计: number
  对账: { matched: boolean; 单据逐项求和: number; 分类合计求和: number; 差异: number; 重复船次: { 船名: string; 航次: string }[] }
}

const store = useSessionStore()
const me = computed(() => store.current)
const can = (permission: string) => store.can(permission)

const columns = ['单据编号', '船名', '航次', '污染物明细', '接收总量', '原填报人', '填报时间', '状态', '驳回理由']
const statuses = ['待码头确认', '已打回', '已接收', '已完成上岸转运']
const pollutantUnits = [
  { cat: '含油污水', unit: '立方米' },
  { cat: '生活污水', unit: '立方米' },
  { cat: '生活垃圾', unit: '千克' },
  { cat: '食品废弃物', unit: '千克' },
  { cat: '废矿物油', unit: '升' },
]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const showSummary = ref(false)
const summary = ref<Summary | null>(null)
const summaryScope = ref('effective')
const filters = reactive({ keyword: '', ship: '', voyage: '', status: '' })

const stats = computed(() => statuses.map((status) => ({
  label: status,
  value: rows.value.filter((row) => row.status === status).length,
})))

const dupText = computed(() =>
  (summary.value?.对账?.重复船次 ?? []).map((item) => `${item.船名}/${item.航次}`).join('、'))

type ActionDef = { key: 'edit' | 'resubmit' | 'reject' | 'confirm' | 'transfer'; label: string }

function actionsFor(row: Row): ActionDef[] {
  const mine = me.value?.id === row['填报人ID']
  const list: ActionDef[] = []
  if (row.status === '待码头确认') {
    if (can('pollutant:edit') && mine) list.push({ key: 'edit', label: '修改接收量' })
    if (can('pollutant:reject')) list.push({ key: 'reject', label: '打回' })
    if (can('pollutant:confirm')) list.push({ key: 'confirm', label: '确认接收' })
  } else if (row.status === '已打回') {
    if (can('pollutant:edit') && mine) list.push({ key: 'resubmit', label: '修订重新提交' })
  } else if (row.status === '已接收') {
    if (can('pollutant:transfer')) list.push({ key: 'transfer', label: '登记完成上岸转运' })
  }
  // 已完成上岸转运：任何角色都没有动作，只能查看与留痕
  return list
}

function statusClass(status: string) {
  return {
    待码头确认: 'st-pending',
    已打回: 'st-rejected',
    已接收: 'st-received',
    已完成上岸转运: 'st-done',
  }[status] ?? ''
}

// ---------------------------------------------------------------- 列表/汇总
async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  Object.entries(filters).forEach(([key, value]) => {
    if (value) query.set(key, value)
  })
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) throw new Error(await parseError(response))
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (showSummary.value) await reloadSummary()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '接收单据列表读取失败'
  }
}

async function reloadSummary() {
  const response = await request(`${ENDPOINT}/summary?scope=${summaryScope.value}`)
  if (response.ok) summary.value = await response.json()
}

function toggleSummary() {
  showSummary.value = !showSummary.value
  if (showSummary.value) void reloadSummary()
}

function resetFilters() {
  filters.keyword = ''
  filters.ship = ''
  filters.voyage = ''
  filters.status = ''
  void reload()
}

// ---------------------------------------------------------------- 表单
const form = reactive({
  open: false,
  saving: false,
  mode: 'create' as 'create' | 'edit' | 'resubmit',
  title: '',
  hint: '',
  id: 0,
  ship: '',
  voyage: '',
  note: '',
  details: {} as Record<string, number | null>,
})

function blankDetails(): Record<string, number | null> {
  return Object.fromEntries(pollutantUnits.map((item) => [item.cat, null]))
}

function openCreate() {
  Object.assign(form, {
    open: true, mode: 'create', id: 0, title: '填报本航次接收单据',
    hint: `归属将固定为当前身份：${me.value?.name}（${me.value?.roleLabel}），船名航次须与本人绑定一致。`,
    ship: me.value?.ship ?? '', voyage: me.value?.voyage ?? '', note: '', details: blankDetails(),
  })
}

function openEdit(mode: 'edit' | 'resubmit', row: Row) {
  const details = blankDetails()
  row.污染物明细.forEach((item) => { details[item.类别] = item.数量 })
  Object.assign(form, {
    open: true, mode, id: row.id, ship: row.船名, voyage: row.航次, note: '', details,
    title: mode === 'resubmit' ? '按打回理由修订并重新提交' : '修改接收量',
    hint: mode === 'resubmit'
      ? `单据 ${row.单据编号} 打回理由：${row.驳回理由}`
      : `仅允许原填报人修改本人单据；每次改动都会留痕。`,
  })
}

function closeForm() { form.open = false }

async function submitForm() {
  form.saving = true
  errorMessage.value = ''
  const 污染物明细: Record<string, number> = {}
  Object.entries(form.details).forEach(([cat, value]) => {
    if (value !== null && value !== undefined && !Number.isNaN(value)) 污染物明细[cat] = value
  })
  const path = form.mode === 'create'
    ? ENDPOINT
    : `${ENDPOINT}/${form.id}/${form.mode === 'resubmit' ? 'resubmit' : 'edit'}`
  try {
    const response = await request(path, {
      method: 'POST',
      body: JSON.stringify({ values: { 船名: form.ship, 航次: form.voyage, 污染物明细, 修改说明: form.note } }),
    })
    const payload = await response.json()
    if (!response.ok || payload.ok === false) {
      throw new Error(!response.ok ? await parseError(response) : payload.message)
    }
    form.open = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '提交失败'
  } finally {
    form.saving = false
  }
}

// ---------------------------------------------------------------- 打回
const reject = reactive({ open: false, saving: false, row: null as Row | null, reason: '' })

function runAction(key: ActionDef['key'], row: Row) {
  if (key === 'edit' || key === 'resubmit') {
    openEdit(key, row)
  } else if (key === 'reject') {
    Object.assign(reject, { open: true, row, reason: '' })
  } else {
    void runStatusAction(key, row)
  }
}

async function submitReject() {
  if (!reject.row) return
  reject.saving = true
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${reject.row.id}/reject`, {
      method: 'POST',
      body: JSON.stringify({ values: { 理由: reject.reason } }),
    })
    const payload = await response.json()
    if (!response.ok) throw new Error(await parseError(response))
    if (payload.ok === false) throw new Error(payload.message)
    reject.open = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '打回失败'
  } finally {
    reject.saving = false
  }
}

async function runStatusAction(key: 'confirm' | 'transfer', row: Row) {
  errorMessage.value = ''
  const label = key === 'confirm' ? '确认接收' : '登记完成上岸转运'
  if (!window.confirm(`确定对单据 ${row.单据编号} 执行「${label}」？`)) return
  try {
    const response = await request(`${ENDPOINT}/${row.id}/${key}`, { method: 'POST' })
    const payload = await response.json().catch(() => null)
    if (!response.ok) throw new Error(await parseError(response))
    if (payload?.ok === false) throw new Error(payload.message)
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : `${label}失败`
  }
}

// ---------------------------------------------------------------- 留痕
const logs = reactive({ open: false, row: null as Row | null, items: [] as LogEntry[] })

async function openLogs(row: Row) {
  logs.row = row
  logs.items = []
  logs.open = true
  const response = await request(`${ENDPOINT}/${row.id}/logs`)
  if (response.ok) {
    const payload = await response.json()
    logs.items = payload.logs ?? []
  } else {
    errorMessage.value = await parseError(response)
  }
}

watch(() => store.operatorId, () => { void reload() })

onMounted(() => {
  if (!store.operators.length) void store.loadOperators().then(reload)
  else void reload()
})
</script>

<style scoped>
.page-actions { display: flex; gap: 8px; }
.summary-panel { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin-bottom: 12px; }
.summary-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-size: 14px; }
.summary-tools { display: flex; gap: 12px; align-items: center; }
.inline { font-size: 13px; color: var(--muted); }
.recon-badge { font-size: 12px; padding: 2px 10px; border-radius: 999px; }
.recon-badge.ok { background: #ecfdf3; color: #027a48; border: 1px solid #abefc6; }
.recon-badge.bad { background: #fef3f2; color: #b42318; border: 1px solid #fda29b; }
.detail-chip { display: inline-block; background: #f2f4f7; border-radius: 4px; padding: 1px 6px; margin: 1px 4px 1px 0; font-size: 12px; white-space: nowrap; }
.shift-tag { font-size: 11px; color: #b54708; background: #fffaeb; border: 1px solid #fedf89; border-radius: 4px; padding: 0 4px; margin-left: 4px; }
.status-tag { font-size: 12px; padding: 2px 8px; border-radius: 999px; }
.st-pending { background: #fffaeb; color: #b54708; }
.st-rejected { background: #fef3f2; color: #b42318; }
.st-received { background: #eff8ff; color: #175cd3; }
.st-done { background: #ecfdf3; color: #027a48; }
.reject-reason { color: #b42318; font-size: 12px; }
.muted { color: var(--muted); font-size: 12px; }
.modal-mask { position: fixed; inset: 0; background: rgba(16, 24, 40, 0.45); display: flex; align-items: center; justify-content: center; z-index: 100; }
.modal { background: #fff; border-radius: 10px; padding: 20px; width: 480px; max-height: 86vh; overflow: auto; }
.modal-wide { width: 860px; }
.modal h3 { margin: 0 0 12px; }
.form-item { display: block; margin-bottom: 12px; border: none; padding: 0; }
.form-item > span, .form-item legend { display: block; font-size: 12px; color: var(--muted); margin-bottom: 4px; }
.form-item input, .form-item textarea, .form-item select { width: 100%; border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; box-sizing: border-box; }
.qty-item { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin: 6px 0; }
.qty-item span { font-size: 13px; }
.qty-item input { width: 140px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
.change-line { display: block; font-size: 12px; color: #344054; }
</style>
