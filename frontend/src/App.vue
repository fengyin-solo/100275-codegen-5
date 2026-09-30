<template>
  <div class="app-shell">
    <aside class="app-side">
      <h1 class="app-title">港口集装箱作业管理平台</h1>
      <nav class="nav-list">
        <RouterLink v-for="item in navItems" :key="item.path" :to="item.path" class="nav-item">
          {{ item.label }}
        </RouterLink>
      </nav>
    </aside>
    <main class="app-main">
      <header class="app-head">
        <span class="head-desc">面向港口集装箱码头船舶靠离泊、岸桥装卸、堆场翻倒、闸口进出与危险品申报的一体化作业管理后台。</span>
        <span class="head-user">
          当前值班：{{ store.operator }} · {{ store.shiftLabel }}
        </span>
      </header>
      <section v-if="showRoleSwitcher" class="role-bar">
        <div class="role-current">
          <span class="role-tag">{{ store.role }}</span>
          <strong>{{ store.operator }}</strong>
          <span v-if="store.vessel" class="role-scope">{{ store.vessel }} / {{ store.voyage }}</span>
        </div>
        <label class="role-switch">
          切换操作身份（模拟登录）：
          <select :value="store.operatorId" @change="onSwitch">
            <option v-for="person in operators" :key="person.id" :value="person.id">
              {{ person.name }}（{{ person.role }}{{ person.vessel ? ` · ${person.vessel}/${person.voyage}` : '' }}）
            </option>
          </select>
        </label>
        <span class="role-perms">持有权限：{{ store.permissions.join('、') }}</span>
      </section>
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import { useSessionStore, OPERATORS } from '@/stores/session'

const store = useSessionStore()
const route = useRoute()
const operators = OPERATORS

// 身份切换只在污染物接收单据页生效，其他模块仍保持演示态。
const showRoleSwitcher = computed(() => route.path === '/pollutant')

function onSwitch(event: Event) {
  store.setOperator((event.target as HTMLSelectElement).value)
}

const navItems = [{ label: "运营概览", path: "/" }, { label: "泊位计划", path: "/berth" }, { label: "船舶作业", path: "/vessel" }, { label: "岸桥调度", path: "/quaycrane" }, { label: "堆场策划", path: "/yardplan" }, { label: "场桥调度", path: "/rtg" }, { label: "内集卡调度", path: "/truck" }, { label: "集装箱信息", path: "/container" }, { label: "闸口管理", path: "/gate" }, { label: "危险品申报", path: "/dangerous" }, { label: "冷藏箱监控", path: "/coldchain" }, { label: "绑扎加固", path: "/lashing" }, { label: "工班管理", path: "/shift" }, { label: "箱体修洗", path: "/repair" }, { label: "理货记录", path: "/tally" }, { label: "海关查验", path: "/customs" }, { label: "支线驳船", path: "/feeder" }, { label: "超限箱管理", path: "/oog" }, { label: "空箱堆存", path: "/emptystack" }, { label: "能耗监测", path: "/energy" }, { label: "安全巡检", path: "/safetycheck" }, { label: "船舶污染物接收", path: "/pollutant" }]
</script>

<style scoped>
.role-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 16px;
  background: #eef4ff;
  border: 1px solid #bcd3fb;
  border-radius: 8px;
  padding: 10px 14px;
  margin: 10px 0 14px;
  font-size: 13px;
}
.role-current { display: flex; align-items: center; gap: 8px; }
.role-tag { background: #1f6feb; color: #fff; border-radius: 4px; padding: 2px 8px; font-size: 12px; }
.role-scope { color: var(--muted); }
.role-switch select { margin-left: 6px; padding: 4px 6px; }
.role-perms { color: var(--muted); }
</style>
