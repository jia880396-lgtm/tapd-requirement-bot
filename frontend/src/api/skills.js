// 模块技能（四流程内化）+ 案例库 的前端 API 封装
// 后端路由前缀 /api/skills；响应拦截器已 return response.data，故下列函数拿到的即是后端 JSON 响应体。
import api from '@/api'

// 四个模块的 module_key（务必与后端 skill_store.MODULE_KEYS 一致）
export const MODULE_KEYS = ['reliability', 'duplicate', 'classification', 'prd']
export const MODULE_LABELS = {
  reliability: '需求可靠性打分',
  duplicate: '重复需求识别',
  classification: '需求分类',
  prd: 'PRD 分析',
}

// 列表 4 个 skill（已登录） -> { data: [skill] }
export const listSkills = () => api.get('/skills')

// 详情 + 生效版本全文（已登录） -> skill 对象
export const getSkill = (moduleKey) => api.get(`/skills/${moduleKey}`)

// 版本历史（已登录） -> { data: [version] }
export const listSkillVersions = (moduleKey) =>
  api.get(`/skills/${moduleKey}/versions`)

// 创建草稿版本（admin）。rules_json / params_json 必须是 JSON 字符串
export const createSkillVersion = (moduleKey, payload) =>
  api.post(`/skills/${moduleKey}/versions`, {
    prompt_text: payload.prompt_text ?? '',
    rules_json: payload.rules_json ?? '{}',
    params_json: payload.params_json ?? '{}',
    kb_context: payload.kb_context ?? '',
  })

// 激活版本（admin） -> { status, data: version }
export const activateSkillVersion = (moduleKey, vid) =>
  api.post(`/skills/${moduleKey}/versions/${vid}/activate`)

// 案例列表（已登录） -> { total, page, size, data: [case] }
export const listSkillCases = (moduleKey, { is_mismatch, page = 1, size = 20 } = {}) => {
  const params = { page, size }
  if (is_mismatch !== undefined && is_mismatch !== null) params.is_mismatch = is_mismatch
  return api.get(`/skills/${moduleKey}/cases`, { params })
}

// 新增案例（已登录）。ai_result_json / human_result_json 必须是 JSON 字符串
export const addSkillCase = (moduleKey, payload) =>
  api.post(`/skills/${moduleKey}/cases`, {
    requirement_id: payload.requirement_id ?? null,
    requirement_title: payload.requirement_title,
    requirement_desc: payload.requirement_desc ?? '',
    ai_result_json:
      typeof payload.ai_result_json === 'string'
        ? payload.ai_result_json
        : JSON.stringify(payload.ai_result_json ?? {}),
    human_result_json:
      typeof payload.human_result_json === 'string'
        ? payload.human_result_json
        : JSON.stringify(payload.human_result_json ?? {}),
    is_mismatch: payload.is_mismatch ?? true,
    mismatch_reason: payload.mismatch_reason ?? '',
    source: payload.source ?? 'manual',
  })

// 删除案例（已登录）
export const deleteSkillCase = (moduleKey, cid) =>
  api.delete(`/skills/${moduleKey}/cases/${cid}`)

// 长耗时接口（评测 / 优化 / A/B 对比内部会批量调用 LLM）单独放宽超时：
// 全局 axios timeout 为 60s，这些接口并发化后仍需 1~5 分钟，避免前端先于后端超时。
const LONG_TIMEOUT = { timeout: 10 * 60 * 1000 }

// 优化（admin） -> { status, data: { version_id, version_no, changes, rationale } }
export const optimizeSkill = (moduleKey, maxCases = 50) =>
  api.post(`/skills/${moduleKey}/optimize`, { max_cases: maxCases }, LONG_TIMEOUT)

// 评测（admin） -> { status, data: { module_key, total_cases, active, draft, delta } }
export const evaluateSkill = (moduleKey, draftVersionId = null) =>
  api.post(`/skills/${moduleKey}/evaluate`, { draft_version_id: draftVersionId }, LONG_TIMEOUT)

// 回滚（admin）：回滚到当前生效版本的父版本，旧生效版本置 archived
// -> { status, data: { reverted_version_id, active_version_id, parent_version_id } }
export const rollbackSkill = (moduleKey) =>
  api.post(`/skills/${moduleKey}/rollback`)

// 立即复盘（admin）：对全部模块触发一次复盘（仅产出草稿，不自动激活）
// -> { status, data: [ { module_key, status, ... } ] }
export const runReview = () => api.post('/skills/review/run', {}, LONG_TIMEOUT)

// 复盘记录（已登录） -> { data: [ { module_key, run_at, new_case_count, total_cases,
//   draft_version_id, active_accuracy, draft_accuracy, delta, recommendation, note, created_by } ] }
export const getReviewLogs = () => api.get('/skills/review/logs')

// A/B 影子对比（admin）：对比 生效版本 vs 候选版本 在近期线上数据上的决策变化率（只读）
// -> { status, data: { module_key, candidate_version_id, sample_size, compared, disagreements,
//      change_rate, per_sample } }
export const abCompareSkill = (moduleKey, candidateVersionId, sampleSize = 20) =>
  api.post(`/skills/${moduleKey}/ab-compare`, {
    candidate_version_id: candidateVersionId,
    sample_size: sampleSize,
  }, LONG_TIMEOUT)
