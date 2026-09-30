import { defineStore } from 'pinia'

import { getOperatorId, request, setOperatorId } from '@/api/client'

type OperatorInfo = {
  id: string
  name: string
  role: string
  roleLabel: string
  ship: string | null
  voyage: string | null
  active: boolean
  permissions: string[]
}

/**
 * 会话：保存当前操作身份（模拟切换登录）。
 * 单据归属只由后端按 X-Operator-Id 判定，前端角色只用于按钮显隐，绝不参与授权。
 */
export const useSessionStore = defineStore('session', {
  state: () => ({
    operators: [] as OperatorInfo[],
    operatorId: getOperatorId(),
    current: null as OperatorInfo | null,
    shiftLabel: '白班 08:00-20:00',
    scope: '港口集装箱作业管理平台',
  }),
  getters: {
    operator: (state) => state.current?.name ?? '未选择身份',
    roleLabel: (state) => state.current?.roleLabel ?? '无身份',
    permissions: (state) => new Set(state.current?.permissions ?? []),
    can(): (permission: string) => boolean {
      return (permission: string) => this.permissions.has(permission)
    },
  },
  actions: {
    async loadOperators() {
      const response = await request('/api/pollutant/operators')
      if (response.ok) {
        const payload = await response.json()
        this.operators = payload.operators ?? []
        if (!this.operatorId || !this.operators.some((item) => item.id === this.operatorId)) {
          const firstActive = this.operators.find((item) => item.active)
          this.operatorId = firstActive?.id ?? ''
          setOperatorId(this.operatorId)
        }
        await this.refreshMe()
      }
    },
    async refreshMe() {
      if (!this.operatorId) {
        this.current = null
        return
      }
      const response = await request('/api/pollutant/me')
      if (response.ok) {
        this.current = await response.json()
      } else {
        this.current = this.operators.find((item) => item.id === this.operatorId) ?? null
      }
    },
    async switchOperator(id: string) {
      this.operatorId = id
      setOperatorId(id)
      await this.refreshMe()
    },
    setShift(label: string) {
      this.shiftLabel = label
    },
  },
})
