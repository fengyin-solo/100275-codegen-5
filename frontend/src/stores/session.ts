import { defineStore } from 'pinia'

/** 污染物接收场景里的人员名册（与后端 app/services/pollutant.py 的 ROSTER 对应）。
 * id 是 ASCII 登录标识：HTTP 头只支持 latin-1，中文姓名不能直接放头里，由后端按 id 对出姓名/角色。
 */
export interface OperatorIdentity {
  id: string
  name: string
  role: string
  roleCode: string
  vessel: string
  voyage: string
}

export const OPERATORS: OperatorIdentity[] = [
  { id: 'chief_zhang', name: '张伟（大副）', role: '船上大副', roleCode: 'chief_mate', vessel: '远洋号', voyage: 'V-2409' },
  { id: 'chief_li', name: '李强（大副）', role: '船上大副', roleCode: 'chief_mate', vessel: '海运号', voyage: 'V-2409' },
  { id: 'supervisor_wang', name: '王磊（值班长）', role: '码头值班长', roleCode: 'supervisor', vessel: '', voyage: '' },
  { id: 'env_zhao', name: '赵敏（环保专责）', role: '环保专责', roleCode: 'env_officer', vessel: '', voyage: '' },
]

/** 各角色在污染物接收单据上的权限，按钮显隐只做体验收敛，真正拦截在后端。 */
export const ROLE_PERMISSIONS: Record<string, string[]> = {
  船上大副: ['接收单据查看', '接收单据填报', '接收量修改'],
  码头值班长: ['接收单据查看', '接收单据打回', '接收单确认', '上岸转运登记'],
  环保专责: ['接收单据查看'],
}

export const useSessionStore = defineStore('session', {
  state: () => {
    const first = OPERATORS[0]
    return {
      operatorId: first.id,
      operator: first.name,
      role: first.role,
      roleCode: first.roleCode,
      vessel: first.vessel,
      voyage: first.voyage,
      shiftLabel: '白班 08:00-20:00',
      scope: '船舶污染物接收',
    }
  },
  getters: {
    canOperate: (state) => state.operatorId.length > 0,
    permissions: (state): string[] => ROLE_PERMISSIONS[state.role] ?? [],
    can: (state) => (permission: string) =>
      (ROLE_PERMISSIONS[state.role] ?? []).includes(permission),
  },
  actions: {
    setOperator(id: string) {
      const found = OPERATORS.find((item) => item.id === id)
      if (!found) return
      this.operatorId = found.id
      this.operator = found.name
      this.role = found.role
      this.roleCode = found.roleCode
      this.vessel = found.vessel
      this.voyage = found.voyage
    },
    setShift(label: string) {
      this.shiftLabel = label
    },
  },
})
