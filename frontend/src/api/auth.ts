/**
 * 登录态与权限能力单一来源（reactive 单例，项目无 pinia）。
 * token 落 localStorage（try/catch 兜底，隐私模式不崩）。
 * 与 client.ts 解耦：client 通过 setAuthProvider 注册取令牌/未授权回调，避免 auth↔client 循环 import。
 */
import { reactive } from 'vue'
import { api, setAuthProvider } from './client'

export interface MeUser {
  id: number
  username: string
  real_name?: string
  status?: string
  security_level?: string
  roles?: string[]
  [k: string]: unknown
}

interface AuthState {
  token: string
  user: MeUser | null
  roles: string[]
  caps: string[]
  ready: boolean // loadMe 成功过一次
  grants: Record<string, string[]> // 页面可见性矩阵：page_name → role_codes（含 '*'=所有已登录）
  grantsReady: boolean // grants 拉取成功过；false 时页面判定走静态 fallback
}

const TOKEN_KEY = 'ark_token'

const state = reactive<AuthState>({
  token: '',
  user: null,
  roles: [],
  caps: [],
  ready: false,
  grants: {},
  grantsReady: false,
})

function lsGet(k: string): string {
  try {
    return localStorage.getItem(k) ?? ''
  } catch {
    return ''
  }
}
function lsSet(k: string, v: string): void {
  try {
    if (v) localStorage.setItem(k, v)
    else localStorage.removeItem(k)
  } catch {
    /* 忽略：隐私模式/无 localStorage */
  }
}

// —— 能力容错匹配 ——
function withPrefix(p: string): string {
  if (p.startsWith('/api/v1')) return p
  return '/api/v1' + (p.startsWith('/') ? p : '/' + p)
}
function pathMatch(grantPath: string, wantPath: string): boolean {
  const g = withPrefix(grantPath)
  const w = withPrefix(wantPath)
  if (g === w) return true
  if (g.endsWith('/*')) return w.startsWith(g.slice(0, -1)) // "/api/v1/*" -> "/api/v1/"
  if (g.endsWith('*')) return w.startsWith(g.slice(0, -1))
  return false
}
// cap 形如 "<obj> <METHOD>"；拆最后一段为动作
function splitCap(cap: string): [string, string] {
  const i = cap.lastIndexOf(' ')
  if (i < 0) return [cap, '']
  return [cap.slice(0, i), cap.slice(i + 1)]
}
function matchAnyCap(caps: string[], want: string): boolean {
  const [wp, wa] = splitCap(want)
  const wantAct = wa.toUpperCase()
  for (const c of caps) {
    const [gp, ga] = splitCap(c)
    if (ga.toUpperCase() !== wantAct) continue
    if (pathMatch(gp, wp)) return true
  }
  return false
}

export const auth = {
  get token(): string {
    return state.token
  },
  get user(): MeUser | null {
    return state.user
  },
  get roles(): string[] {
    return state.roles
  },
  get caps(): string[] {
    return state.caps
  },
  get isAuthed(): boolean {
    return !!state.token
  },
  get isReady(): boolean {
    return state.ready
  },

  /** 应用启动时同步恢复令牌（角色/能力待 loadMe）。须在挂载 router 前调用。 */
  init(): void {
    state.token = lsGet(TOKEN_KEY)
    // 注册给 client：请求自动带 Bearer；401 触发登出
    setAuthProvider(
      () => state.token,
      () => auth.logout(),
    )
  },

  async login(username: string, password: string): Promise<void> {
    const res = await api.post<{ access_token: string; token_type?: string; expires_in?: number }>(
      '/auth/login',
      { username, password },
    )
    state.token = res.access_token
    lsSet(TOKEN_KEY, state.token)
    await this.loadMe()
  },

  async loadMe(): Promise<void> {
    if (!state.token) return
    const me = await api.get<{ user: MeUser; roles: string[]; caps: string[] }>('/auth/me')
    state.user = me.user
    state.roles = me.roles ?? []
    state.caps = me.caps ?? []
    state.ready = true
    // 页面可见性矩阵并行拉取（PRD 2.9）：失败不阻塞登录，走静态 fallback（canSeePage）
    try {
      const g = await api.get<{ grants: Array<{ page_name: string; role_code: string }> }>('/page-grants')
      this.applyGrants(g?.grants ?? [])
    } catch {
      state.grants = {}
      state.grantsReady = false
    }
  },

  /** 把后端授权行写入本地矩阵（登录加载与矩阵保存后共用）。 */
  applyGrants(list: Array<{ page_name: string; role_code: string }>): void {
    const m: Record<string, string[]> = {}
    for (const g of list) {
      ;(m[g.page_name] ??= []).push(g.role_code)
    }
    state.grants = m
    state.grantsReady = true
  },

  logout(): void {
    state.token = ''
    state.user = null
    state.roles = []
    state.caps = []
    state.ready = false
    state.grants = {}
    state.grantsReady = false
    lsSet(TOKEN_KEY, '')
  },

  /** 页面/菜单可见性判定：roles 为空视为「所有已登录可见」。 */
  hasAnyRole(roles: string[] | undefined): boolean {
    if (!roles || roles.length === 0) return true
    return roles.some((r) => state.roles.includes(r))
  },

  /**
   * 页面可见性统一判定（PRD 2.9 矩阵在线配置）：
   * 1) R-ADMIN 恒可见（前端硬编码兜底，防管理员把自己关门外）；
   * 2) 矩阵可用时白名单制——命中 '*' 或自身任一角色才可见（未配置 = 不可见）；
   * 3) 矩阵不可用（grantsReady=false）时退回静态 meta.roles（hasAnyRole），防全站锁死。
   * staticRoles 传路由 meta.roles / 菜单项 roles（仅作 fallback 数据源）。
   */
  canSeePage(name: string, staticRoles?: string[]): boolean {
    if (state.roles.includes('R-ADMIN')) return true
    if (state.grantsReady) {
      const rows = state.grants[name]
      if (!rows || rows.length === 0) return false
      return rows.includes('*') || rows.some((r) => state.roles.includes(r))
    }
    return this.hasAnyRole(staticRoles)
  },

  /** 按钮/操作级门控：want 可用简写 "/admin/users POST"。 */
  can(want: string): boolean {
    return matchAnyCap(state.caps, want)
  },
}
