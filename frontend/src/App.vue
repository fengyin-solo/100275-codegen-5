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
          <label class="role-switch">
            当前身份：
            <select :value="store.operatorId" @change="switchIdentity(($event.target as HTMLSelectElement).value)">
              <optgroup v-for="role in roleGroups" :key="role" :label="role">
                <option v-for="person in byRole(role)" :key="person.id" :value="person.id" :disabled="!person.active">
                  {{ person.name }}（{{ person.roleLabel }}<template v-if="person.ship"> · {{ person.ship }} {{ person.voyage }}</template><template v-if="!person.active"> · 已调班</template>）
                </option>
              </optgroup>
            </select>
          </label>
          <span class="head-meta">{{ store.shiftLabel }}</span>
        </span>
      </header>
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'

import { useSessionStore } from '@/stores/session'

const store = useSessionStore()

const navItems = [{ label: "运营概览", path: "/" }, { label: "泊位计划", path: "/berth" }, { label: "船舶作业", path: "/vessel" }, { label: "岸桥调度", path: "/quaycrane" }, { label: "堆场策划", path: "/yardplan" }, { label: "场桥调度", path: "/rtg" }, { label: "内集卡调度", path: "/truck" }, { label: "集装箱信息", path: "/container" }, { label: "闸口管理", path: "/gate" }, { label: "危险品申报", path: "/dangerous" }, { label: "冷藏箱监控", path: "/coldchain" }, { label: "绑扎加固", path: "/lashing" }, { label: "工班管理", path: "/shift" }, { label: "箱体修洗", path: "/repair" }, { label: "理货记录", path: "/tally" }, { label: "海关查验", path: "/customs" }, { label: "支线驳船", path: "/feeder" }, { label: "超限箱管理", path: "/oog" }, { label: "空箱堆存", path: "/emptystack" }, { label: "能耗监测", path: "/energy" }, { label: "安全巡检", path: "/safetycheck" }, { label: "船舶污染物接收", path: "/pollutant" }]

const roleGroups = ['船上大副', '码头值班长', '环保专责']
const byRole = (role: string) => store.operators.filter((person) => person.roleLabel === role)

async function switchIdentity(id: string) {
  await store.switchOperator(id)
}

onMounted(() => {
  void store.loadOperators()
})
</script>

<style scoped>
.role-switch { font-size: 13px; color: #344054; }
.role-switch select { padding: 2px 6px; border-radius: 6px; border: 1px solid #d0d5dd; }
.head-meta { margin-left: 12px; color: #667085; }
</style>
