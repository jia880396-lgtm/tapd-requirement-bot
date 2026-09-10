<template>
  <div class="page-container">
    <header class="workspace-page-header">
      <div>
        <h1 class="workspace-page-title">PRD 分析</h1>
        <p class="workspace-page-description">对比用户原始需求与 PRD 内容，识别完整度缺口并生成可执行的补充建议。</p>
      </div>
      <div class="workspace-page-meta">
        <span>分析范围</span>
        <el-tag size="small" effect="plain">{{ userStore.isAdmin ? '全部可见 PRD' : '我的 PRD' }}</el-tag>
        <PageTutorial :tutorial="tutorials['prd-analysis']" />
      </div>
    </header>
    <el-card class="action-card">
      <div class="action-row">
        <el-button type="primary" :icon="Download" @click="handleFetch" :loading="fetching">
          {{ userStore.isAdmin ? '拉取 PRD（待评审）' : '拉取我的PRD' }}
        </el-button>
        <el-button
          type="success"
          :icon="Check"
          @click="handleAnalyze"
          :disabled="!selected.length"
          :loading="analyzing"
        >
          启动分析 ({{ selected.length }})
        </el-button>
        <el-button
          v-if="automation.auto_flow_enabled"
          :type="automation.prd_enabled ? 'warning' : 'default'"
          @click="toggleAutomation"
          :loading="automationLoading"
        >
          {{ automation.prd_enabled ? '停止自动分析' : '开启自动分析' }}
        </el-button>
        <span v-if="automation.auto_flow_enabled && automation.prd_enabled" style="font-size:12px;color:#909399;margin-left:4px">
          每{{ automation.schedule_interval_minutes }}分钟，{{ automation.batch_size }}条/次
        </span>
      </div>
      <el-divider />
      <div class="filter-row">
        <el-input
          v-model="keyword"
          placeholder="搜索需求 ID"
          style="width: 180px"
          clearable
          @keyup.enter="loadList"
          @clear="loadList"
        />
        <el-select v-if="userStore.isAdmin" v-model="filterOwner" placeholder="处理人筛选" style="width: 150px" clearable filterable @change="loadList">
          <el-option v-for="o in ownerOptions" :key="o" :label="o" :value="o" />
        </el-select>
        <el-select v-model="filterStatus" placeholder="分析状态" style="width: 130px" clearable @change="loadList">
          <el-option label="待分析" value="pending" />
          <el-option label="待补充PRD" value="待补充PRD" />
          <el-option label="已分析" value="analyzed" />
          <el-option label="已评审" value="reviewed" />
        </el-select>
      </div>
    </el-card>

    <div class="view-context">
      <span class="view-context-title">当前视图</span>
      <el-tag size="small" effect="plain">{{ userStore.isAdmin ? '全部可见 PRD' : '我的名下 PRD' }}</el-tag>
      <el-tag v-if="filterStatus" size="small" closable @close="clearFilter('status')">{{ statusLabel(filterStatus) }}</el-tag>
      <el-tag v-if="filterOwner" size="small" closable @close="clearFilter('owner')">处理人：{{ filterOwner }}</el-tag>
      <el-tag v-if="keyword" type="info" size="small" closable @close="clearFilter('keyword')">需求 ID：{{ keyword }}</el-tag>
      <span class="view-context-count">共 {{ total }} 条</span>
      <el-button v-if="hasActiveFilters" link type="primary" @click="clearAllFilters">清空筛选</el-button>
    </div>

    <el-alert
      v-if="taskSummary"
      class="task-summary"
      :type="taskSummary.type"
      :closable="true"
      @close="taskSummary = null"
    >
      <template #title>{{ taskSummary.title }}</template>
      <div>{{ taskSummary.detail }}</div>
      <div v-if="taskSummary.failed" class="task-summary-hint">存在失败项，请在任务状态或处理日志中查看详细原因。</div>
    </el-alert>

    <!-- 分析进度条 -->
    <el-card v-if="jobStatus" class="progress-card">
      <div class="progress-title">
        <el-icon v-if="jobStatus === 'running'" class="is-loading"><Loading /></el-icon>
        <span>PRD 分析进度</span>
        <el-tag v-if="jobStatus !== 'running'" size="small" :type="jobStatusTagType(jobStatus)">{{ jobStatusLabel(jobStatus) }}</el-tag>
      </div>
      <el-progress
        :percentage="jobPercent"
        :status="jobProgressStatus"
        :stroke-width="18"
        text-inside
      />
      <div class="progress-detail">
        已处理 {{ jobProcessed }} / {{ jobTotal }}（成功 {{ jobSucceeded }}，失败 {{ jobFailed }}）
      </div>
    </el-card>

    <el-row :gutter="16">
      <!-- 左侧 PRD 列表 -->
      <el-col :span="14">
        <el-card>
          <template #header>
            <div class="card-header">
              <span>PRD 列表</span>
              <el-tag size="small" type="info">共 {{ total }} 条</el-tag>
            </div>
          </template>
          <el-table
            :data="list"
            @selection-change="onSelectionChange"
            @row-click="showDetail"
            @sort-change="onSortChange"
            highlight-current-row
            v-loading="loading"
            stripe
            height="560"
            :default-sort="defaultSort"
          >
            <el-table-column type="selection" width="40" :selectable="canSelectRow" />
            <el-table-column prop="story_id" label="需求ID" width="120" />
            <el-table-column label="标题" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">
                <el-link v-if="row.tapd_url" type="primary" :href="row.tapd_url" target="_blank" @click.stop>
                  {{ row.title || '(无标题)' }}
                </el-link>
                <span v-else>{{ row.title || '(无标题)' }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="owner" label="处理人" width="110" show-overflow-tooltip />
            <el-table-column prop="tenant_version" label="版本" width="100" show-overflow-tooltip />
            <el-table-column prop="priority" label="重要程度" width="90" show-overflow-tooltip />
            <el-table-column label="完整度" width="140" sortable="custom" prop="completeness_score">
              <template #default="{ row }">
                <el-tag v-if="row.completeness_score !== null && row.completeness_score !== undefined" :type="scoreTagType(row.completeness_score)">
                  {{ row.completeness_score }}
                </el-tag>
                <span v-else>-</span>
                <el-tooltip
                  v-if="row.manual_score !== null && row.manual_score !== undefined"
                  :content="`人工打分 ${row.manual_score}/10（${row.manual_score_by || '未知'}${row.manual_score_comment ? '：' + row.manual_score_comment : ''}）`"
                >
                  <el-tag size="small" type="warning" effect="plain" style="margin-left: 4px">
                    人工{{ row.manual_score }}
                  </el-tag>
                </el-tooltip>
              </template>
            </el-table-column>
            <el-table-column label="提交时间" width="150" sortable="custom" prop="tapd_created">
              <template #default="{ row }">
                <span>{{ formatTime(row.tapd_created) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="更新时间" width="150" sortable="custom" prop="tapd_updated">
              <template #default="{ row }">
                <span>{{ formatTime(row.tapd_updated) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="分析状态" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="statusTagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="260" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click.stop="showDetail(row)">详情</el-button>
                <el-button link type="success" @click.stop="openAddCase(row)">加入案例库</el-button>
                <el-button link type="warning" @click.stop="openManualScore(row)">人工打分</el-button>
              </template>
            </el-table-column>
          </el-table>

          <el-pagination
            v-model:current-page="page"
            v-model:page-size="pageSize"
            :total="total"
            :page-sizes="[20, 50, 100]"
            layout="total, sizes, prev, pager, next"
            style="margin-top: 12px; justify-content: end"
            @current-change="loadList"
            @size-change="loadList"
          />
        </el-card>
      </el-col>

      <!-- 右侧详情 -->
      <el-col :span="10">
        <el-card>
          <template #header>
            <span>分析详情</span>
          </template>
          <div v-if="currentDetail" class="detail-content">
            <el-descriptions :column="1" border size="small">
              <el-descriptions-item label="需求ID">{{ currentDetail.story_id }}</el-descriptions-item>
              <el-descriptions-item label="标题">
                <el-link v-if="currentDetail.tapd_url" type="primary" :href="currentDetail.tapd_url" target="_blank">
                  {{ currentDetail.title || '(无标题)' }}
                </el-link>
                <span v-else>{{ currentDetail.title || '(无标题)' }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="处理人">{{ currentDetail.owner || '-' }}</el-descriptions-item>
              <el-descriptions-item label="提交人">{{ currentDetail.creator || '-' }}</el-descriptions-item>
              <el-descriptions-item label="租户版本">{{ currentDetail.tenant_version || '-' }}</el-descriptions-item>
              <el-descriptions-item label="重要程度">{{ currentDetail.priority || '-' }}</el-descriptions-item>
              <el-descriptions-item label="提交时间">{{ formatTime(currentDetail.tapd_created) || '-' }}</el-descriptions-item>
              <el-descriptions-item label="更新时间">{{ formatTime(currentDetail.tapd_updated) || '-' }}</el-descriptions-item>
              <el-descriptions-item label="完整度评分">
                <el-tag :type="scoreTagType(currentDetail.completeness_score)" size="large">
                  {{ currentDetail.completeness_score ?? '-' }} / 100
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="用户原始需求">
                <div class="desc-text">{{ currentDetail.original_requirement || '(空)' }}</div>
              </el-descriptions-item>
              <el-descriptions-item label="PRD 内容">
                <div class="desc-text">{{ currentDetail.prd_content || '(空)' }}</div>
              </el-descriptions-item>
            </el-descriptions>

            <template v-if="currentDetail.coverage_detail">
              <h4 style="margin-top: 16px">覆盖度</h4>
              <div v-if="currentDetail.coverage_detail.covered_points?.length">
                <strong>✓ 已覆盖：</strong>
                <ul>
                  <li v-for="(p, i) in currentDetail.coverage_detail.covered_points" :key="i">{{ p }}</li>
                </ul>
              </div>
              <div v-if="currentDetail.coverage_detail.missing_points?.length">
                <strong style="color: #f56c6c">✗ 遗漏：</strong>
                <ul>
                  <li v-for="(p, i) in currentDetail.coverage_detail.missing_points" :key="i">{{ p }}</li>
                </ul>
              </div>
            </template>

            <template v-if="currentDetail.suggestions?.length">
              <h4 style="margin-top: 16px">补充建议</h4>
              <el-table :data="currentDetail.suggestions" size="small" border>
                <el-table-column prop="category" label="类别" width="80" />
                <el-table-column label="优先级" width="80">
                  <template #default="{ row }">
                    <el-tag size="small" :type="priorityType(row.priority)">{{ row.priority }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="suggestion" label="建议" />
              </el-table>
            </template>
          </div>
          <el-empty v-else description="请选择左侧 PRD 查看详情" />
        </el-card>
      </el-col>
    </el-row>

    <AddCaseLibraryDialog ref="addCaseDialog" />

    <!-- 人工打分弹窗（1-10 分，0.5 步进） -->
    <el-dialog v-model="manualScoreVisible" title="人工打分（修正 AI 完整度评估）" width="560px">
      <div v-if="manualScoreRow" class="manual-score-panel">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="需求">
            {{ manualScoreRow.story_id }} · {{ manualScoreRow.title }}
          </el-descriptions-item>
          <el-descriptions-item label="AI 完整度">
            <el-tag :type="scoreTagType(manualScoreRow.completeness_score)">{{ manualScoreRow.completeness_score }}</el-tag>
            <span class="hint" style="margin-left: 8px">{{ manualScoreRow.coverage_detail?.missing_points?.length ? `遗漏 ${manualScoreRow.coverage_detail.missing_points.length} 个要点` : '（无遗漏信息）' }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="用户原始需求">
            <div class="desc-text" style="max-height: 100px; overflow: auto">{{ manualScoreRow.original_requirement || '(空)' }}</div>
          </el-descriptions-item>
        </el-descriptions>
        <div class="manual-score-slider">
          <div class="manual-score-label">
            人工打分：<strong>{{ manualScoreValue }} / 10</strong>
            <span class="hint">（1 分=PRD 完全不合格，10 分=完整可直接开发）</span>
          </div>
          <el-slider v-model="manualScoreValue" :min="1" :max="10" :step="0.5" show-stops />
        </div>
        <el-input
          v-model="manualScoreComment"
          type="textarea"
          :rows="2"
          maxlength="500"
          show-word-limit
          placeholder="修正备注（可选）：说明与 AI 打分不一致的原因"
        />
      </div>
      <template #footer>
        <el-button @click="manualScoreVisible = false">取消</el-button>
        <el-button type="primary" :loading="manualScoreSaving" @click="submitManualScore">保存打分</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onActivated } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Download, Check, Loading } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/api'
import { useUserStore } from '@/stores/user'
import PageTutorial from '@/components/PageTutorial.vue'
import AddCaseLibraryDialog from '@/components/AddCaseLibraryDialog.vue'
import { tutorials } from '@/tutorials'

const userStore = useUserStore()
const route = useRoute()
const router = useRouter()
const automation = reactive({ auto_flow_enabled: false, prd_enabled: false, schedule_interval_minutes: 30, batch_size: 50, max_processing_minutes: 60 })
const automationLoading = ref(false)

const list = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const keyword = ref('')
const filterOwner = ref('')
const filterStatus = ref('')
const loading = ref(false)
const selected = ref([])
const currentDetail = ref(null)
const addCaseDialog = ref(null)

const fetching = ref(false)
const analyzing = ref(false)
const taskSummary = ref(null)

// 分析任务进度状态
const jobStatus = ref('')        // running/completed/failed/interrupted
const jobTotal = ref(0)
const jobProcessed = ref(0)
const jobSucceeded = ref(0)
const jobFailed = ref(0)

const jobPercent = computed(() => {
  if (!jobTotal.value) return 0
  return Math.min(100, Math.round((jobProcessed.value / jobTotal.value) * 100))
})

const jobProgressStatus = computed(() => {
  if (jobStatus.value === 'completed') return 'success'
  if (jobStatus.value === 'failed' || jobStatus.value === 'interrupted') return 'exception'
  return ''
})

function jobStatusLabel(s) {
  return { running: '进行中', completed: '已完成', failed: '失败', interrupted: '已中断' }[s] || s
}

function jobStatusTagType(s) {
  return { running: 'warning', completed: 'success', failed: 'danger', interrupted: 'info' }[s] || ''
}

function resetJobProgress() {
  jobStatus.value = ''
  jobTotal.value = 0
  jobProcessed.value = 0
  jobSucceeded.value = 0
  jobFailed.value = 0
}

const ownerOptions = ref([])

// 排序状态
const sortProp = ref('tapd_created')
const sortOrder = ref('descending')
const defaultSort = ref({ prop: 'tapd_created', order: 'descending' })

async function loadList() {
  loading.value = true
  try {
    const orderFieldMap = {
      'completeness_score': 'score',
      'tapd_created': 'tapd_created',
      'tapd_updated': 'updated',
    }
    const orderDirMap = {
      'ascending': 'asc',
      'descending': 'desc',
    }
    const data = await api.get('/prd/list', {
      params: {
        page: page.value,
        page_size: pageSize.value,
        status: filterStatus.value || undefined,
        keyword: keyword.value || undefined,
        owner: filterOwner.value || undefined,
        order_by: orderFieldMap[sortProp.value] || undefined,
        order: orderDirMap[sortOrder.value] || undefined,
      }
    })
    list.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

async function loadOwners() {
  try {
    // 与用户需求处理页使用相同的处理人列表源
    const data = await api.get('/user-requirements/owners')
    ownerOptions.value = data.owners || []
  } catch (e) {
    // 忽略
  }
}

const hasActiveFilters = computed(() => Boolean(keyword.value || filterOwner.value || filterStatus.value))

function clearFilter(type) {
  if (type === 'keyword') keyword.value = ''
  if (type === 'owner') filterOwner.value = ''
  if (type === 'status') filterStatus.value = ''
  page.value = 1
  loadList()
}

function clearAllFilters() {
  keyword.value = ''
  filterOwner.value = ''
  filterStatus.value = ''
  page.value = 1
  loadList()
}

function applyRouteFilters() {
  if (route.query.status) filterStatus.value = String(route.query.status)
}

function onSelectionChange(rows) {
  selected.value = rows
}

function onSortChange({ prop, order }) {
  sortProp.value = prop
  sortOrder.value = order
  page.value = 1
  loadList()
}

function showDetail(row) {
  currentDetail.value = row
}

// ---------- 人工打分（1-10 分，0.5 步进） ----------
const manualScoreVisible = ref(false)
const manualScoreSaving = ref(false)
const manualScoreRow = ref(null)
const manualScoreValue = ref(7)
const manualScoreComment = ref('')

function openManualScore(row) {
  manualScoreRow.value = row
  manualScoreValue.value = row.manual_score ?? (row.completeness_score != null ? Math.round(row.completeness_score / 5) / 2 : 7)
  manualScoreComment.value = row.manual_score_comment || ''
  manualScoreVisible.value = true
}

async function submitManualScore() {
  if (!manualScoreRow.value) return
  const row = manualScoreRow.value
  manualScoreSaving.value = true
  try {
    await api.post(`/prd/record/${row.id}/manual-score`, {
      score: manualScoreValue.value,
      comment: manualScoreComment.value,
    })
    ElMessage.success(`人工打分已保存：${manualScoreValue.value}/10`)
    manualScoreVisible.value = false
    manualScoreRow.value = null
    loadList()

    // 人工与 AI 差异大（≥2 分，即 20 百分制）时引导加入案例库，供后续优化
    if (row.completeness_score != null && Math.abs(manualScoreValue.value * 10 - row.completeness_score) >= 20) {
      try {
        await ElMessageBox.confirm(
          `人工打分 ${manualScoreValue.value}/10 与 AI 打分 ${row.completeness_score} 差异较大，是否将本条加入案例库，用于后续提示词优化？`,
          '建议加入案例库',
          { confirmButtonText: '加入案例库', cancelButtonText: '暂不', type: 'warning' },
        )
        openAddCase(row)
      } catch (e) { /* 用户选择暂不 */ }
    }
  } catch (e) {
    // 拦截器已提示
  } finally {
    manualScoreSaving.value = false
  }
}

function openAddCase(row) {
  const aiResult = {
    completeness_score: row.completeness_score,
    coverage_detail: row.coverage_detail,
    suggestions: row.suggestions,
  }
  addCaseDialog.value?.open({
    moduleKey: 'prd',
    requirement_title: row.title || '',
    requirement_desc: row.original_requirement || '',
    aiResult,
    is_mismatch: true,
  })
}

async function loadAutomation() {
  try {
    Object.assign(automation, await api.get('/automation/status'))
  } catch (e) { /* handled globally */ }
}

async function toggleAutomation() {
  if (!automation.auto_flow_enabled) {
    ElMessage.info('请先在“系统管理 - 自动流程设置”中确认开启自动流程功能')
    router.push({ name: 'settings' })
    return
  }
  automationLoading.value = true
  try {
    const enabled = !automation.prd_enabled
    const data = await api.post('/automation/modules/prd', { enabled })
    Object.assign(automation, data)
    ElMessage.success(`${data.message}：每 ${data.schedule_interval_minutes} 分钟拉取并分析最多 ${data.batch_size} 条 PRD`)
  } finally {
    automationLoading.value = false
  }
}

async function handleFetch() {
  fetching.value = true
  try {
    // 操作员自动传入自己的 owner，管理员不传 owner 拉取全量
    const payload = { limit: 200 }
    if (!userStore.isAdmin) {
      payload.owner = userStore.displayName
    }
    const data = await api.post('/prd/fetch', payload)
    const ownerHint = userStore.isAdmin ? '' : `（处理人：${userStore.displayName}）`
    taskSummary.value = {
      type: 'success',
      title: 'PRD 拉取完成',
      detail: `新增 ${data.new} 条，更新 ${data.updated} 条，跳过 ${data.skipped} 条；待补充 PRD ${data.pending_prd || 0} 条。${ownerHint}`,
      failed: false,
    }
    ElMessage.success(`拉取成功${ownerHint}（状态：${data.status_filter}）：新增 ${data.new}，更新 ${data.updated}，跳过 ${data.skipped}，待补充PRD ${data.pending_prd || 0}`)
    await loadList()
    await loadOwners()
  } finally {
    fetching.value = false
  }
}

async function handleAnalyze() {
  const ids = selected.value.map(r => r.id)
  if (!ids.length) {
    ElMessage.warning('请先选择 PRD')
    return
  }
  analyzing.value = true
  resetJobProgress()
  try {
    const data = await api.post('/prd/analyze', { record_ids: ids })
    jobTotal.value = data.total
    jobStatus.value = 'running'
    ElMessage.success(`分析任务已启动，共 ${data.total} 条`)
    pollJob(data.job_id)
  } finally {
    analyzing.value = false
  }
}

function pollJob(jobId) {
  let count = 0
  const timer = setInterval(async () => {
    count++
    try {
      const data = await api.get(`/prd/jobs/${jobId}/result`)
      jobStatus.value = data.status
      if (data.total != null) jobTotal.value = data.total
      if (data.processed != null) jobProcessed.value = data.processed
      if (data.succeeded != null) jobSucceeded.value = data.succeeded
      if (data.failed != null) jobFailed.value = data.failed
      if (['completed', 'failed', 'interrupted'].includes(data.status)) {
        clearInterval(timer)
        if (data.status === 'completed') {
          taskSummary.value = {
            type: data.failed ? 'warning' : 'success',
            title: 'PRD 分析完成',
            detail: `成功 ${data.succeeded} 条，失败 ${data.failed} 条。`,
            failed: data.failed,
          }
          ElMessage.success(`分析完成：成功 ${data.succeeded}，失败 ${data.failed}`)
        } else {
          taskSummary.value = {
            type: 'warning',
            title: 'PRD 分析未正常完成',
            detail: `任务状态：${jobStatusLabel(data.status)}。`,
            failed: true,
          }
          ElMessage.warning(`任务状态：${jobStatusLabel(data.status)}`)
        }
        await loadList()
      }
    } catch (e) {
      clearInterval(timer)
    }
    if (count > 1200) clearInterval(timer)
  }, 2000)
}

function formatTime(t) {
  if (!t) return ''
  try {
    const d = new Date(t)
    if (isNaN(d.getTime())) return t
    const pad = (n) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  } catch {
    return t
  }
}

function scoreTagType(score) {
  if (score === null || score === undefined) return 'info'
  if (score >= 80) return 'success'
  if (score >= 60) return ''
  if (score >= 40) return 'warning'
  return 'danger'
}

function statusLabel(status) {
  return { pending: '待分析', '待补充PRD': '待补充PRD', analyzed: '已分析', reviewed: '已评审' }[status] || status
}

function canSelectRow(row) {
  // "待补充PRD"状态（PRD为空）的记录不允许勾选分析
  return row.status !== '待补充PRD'
}

function statusTagType(status) {
  return { pending: 'info', '待补充PRD': 'danger', analyzed: 'success', reviewed: 'warning' }[status] || ''
}

function priorityType(p) {
  return { high: 'danger', medium: 'warning', low: 'info' }[p] || ''
}

onMounted(() => {
  applyRouteFilters()
  loadList()
  loadOwners()
  loadAutomation()
})

onActivated(() => {
  applyRouteFilters()
  loadList()
  loadAutomation()
})
</script>

<style scoped>
.action-card {
  margin-bottom: 14px;
}
.action-card :deep(.el-divider--horizontal) {
  margin: 14px 0;
}
.view-context {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin: -4px 0 12px;
  padding: 10px 12px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  background: #fff;
}
.view-context-title {
  font-size: 13px;
  color: #606266;
  font-weight: 600;
}
.view-context-count {
  margin-left: auto;
  color: #909399;
  font-size: 13px;
}
.task-summary {
  margin-bottom: 12px;
}
.task-summary-hint {
  margin-top: 4px;
  font-size: 12px;
  color: #909399;
}
.progress-card {
  margin-bottom: 16px;
}
.progress-title {
  font-weight: 600;
  margin-bottom: 12px;
  color: #409eff;
  display: flex;
  align-items: center;
  gap: 6px;
}
.progress-detail {
  margin-top: 8px;
  font-size: 13px;
  color: #606266;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.detail-content {
  max-height: 600px;
  overflow-y: auto;
}
.desc-text {
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow-y: auto;
  background: #f5f7fa;
  padding: 8px;
  border-radius: 4px;
}
</style>
