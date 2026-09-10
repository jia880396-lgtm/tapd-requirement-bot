<template>
  <div class="page-container">
    <header class="workspace-page-header">
      <div>
        <h1 class="workspace-page-title">重复需求处理</h1>
        <p class="workspace-page-description">对系统识别的疑似重复需求进行人工裁定，确认重复写回 TAPD，或确认不重复后自动打分。</p>
      </div>
      <div class="workspace-page-meta">
        <PageTutorial :tutorial="tutorials['duplicate-requirements']" />
      </div>
    </header>

    <!-- 统计卡片 -->
    <el-row :gutter="16" class="stat-row">
      <el-col :span="8">
        <el-card class="stat-card">
          <div class="stat-value" style="color: #f56c6c">{{ stats.total }}</div>
          <div class="stat-label">重复需求总数</div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card class="stat-card">
          <div class="stat-value" style="color: #e6a23c">{{ selected.length }}</div>
          <div class="stat-label">已选中</div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card class="stat-card">
          <div class="stat-value" style="color: #67c23a">{{ confirmedCount }}</div>
          <div class="stat-label">本次已确认重复</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 操作区 -->
    <el-card class="action-card">
      <el-button
        type="danger"
        :icon="Check"
        @click="handleConfirmDuplicate"
        :disabled="!selected.length"
        :loading="confirming"
      >
        确认重复（{{ selected.length }}）
      </el-button>
      <el-button
        type="success"
        :icon="RefreshLeft"
        @click="handleRejectDuplicate"
        :disabled="!selected.length"
        :loading="rejecting"
      >
        确认不重复（{{ selected.length }}）
      </el-button>
      <el-button :icon="Refresh" @click="loadList">刷新</el-button>

      <el-input
        v-model="keyword"
        placeholder="搜索标题"
        style="width: 200px; margin-left: 12px"
        clearable
        @keyup.enter="loadList"
        @clear="loadList"
      />
    </el-card>

    <!-- 打分进度（确认不重复后触发） -->
    <el-card v-if="scoring" class="progress-card">
      <div class="progress-title">
        <el-icon class="is-loading"><Loading /></el-icon>
        确认不重复，正在打分...
      </div>
      <el-progress :percentage="scorePercent" />
      <span class="progress-detail">{{ scoreProcessed }} / {{ scoreTotal }}（成功 {{ scoreSuccess }}，失败 {{ scoreFail }}）</span>
    </el-card>

    <!-- 重复需求列表 -->
    <el-card>
      <el-table
        :data="list"
        @selection-change="onSelectionChange"
        v-loading="loading"
        stripe
      >
        <el-table-column type="selection" width="40" />
        <el-table-column prop="story_id" label="需求ID" width="120" />
        <el-table-column label="标题" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <el-link v-if="row.tapd_url" type="primary" :href="row.tapd_url" target="_blank">
              {{ row.title }}
            </el-link>
            <span v-else>{{ row.title }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="owner" label="处理人" width="120" show-overflow-tooltip />
        <el-table-column prop="tenant_version" label="版本" width="120" show-overflow-tooltip />
        <el-table-column prop="priority" label="重要程度" width="100" show-overflow-tooltip />
        <el-table-column label="相似度" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.similarity !== null && row.similarity !== undefined" :type="similarityTagType(row.similarity)">
              {{ (row.similarity * 100).toFixed(0) }}%
            </el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="重复的Top3需求" min-width="320">
          <template #default="{ row }">
            <div v-if="row.duplicate_detail?.length" class="dup-list">
              <div v-for="(d, i) in row.duplicate_detail" :key="i" class="dup-item">
                <span class="dup-index">{{ i + 1 }}.</span>
                <el-link type="primary" :href="tapdUrl(row.workspace_id, d.story_id)" target="_blank">
                  {{ d.story_id }} - {{ d.title || '(无标题)' }}
                </el-link>
              </div>
            </div>
            <span v-else class="no-detail">{{ row.duplicate_with?.join(', ') || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="showDetail(row)">详情</el-button>
            <el-button size="small" type="success" link @click="openAddCase(row)">加入案例库</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        layout="total, prev, pager, next"
        style="margin-top: 16px"
        @current-change="loadList"
      />
    </el-card>

    <!-- 详情抽屉 -->
    <el-drawer v-model="detailVisible" title="重复需求详情" size="50%">
      <div v-if="currentDetail" class="detail-content">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="需求ID">{{ currentDetail.story_id }}</el-descriptions-item>
          <el-descriptions-item label="标题">
            <el-link v-if="currentDetail.tapd_url" type="primary" :href="currentDetail.tapd_url" target="_blank">
              {{ currentDetail.title }}
            </el-link>
            <span v-else>{{ currentDetail.title }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="处理人">{{ currentDetail.owner || '-' }}</el-descriptions-item>
          <el-descriptions-item label="版本">{{ currentDetail.tenant_version || '-' }}</el-descriptions-item>
          <el-descriptions-item label="重要程度">{{ currentDetail.priority || '-' }}</el-descriptions-item>
          <el-descriptions-item label="相似度">
            <el-tag v-if="currentDetail.similarity !== null && currentDetail.similarity !== undefined" :type="similarityTagType(currentDetail.similarity)">
              {{ (currentDetail.similarity * 100).toFixed(0) }}%
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag type="danger">重复</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="用户需求描述">
            <div class="desc-text">{{ currentDetail.description || '(空)' }}</div>
          </el-descriptions-item>
          <el-descriptions-item label="重复的Top3需求">
            <div v-if="currentDetail.duplicate_detail?.length" class="dup-list">
              <div v-for="(d, i) in currentDetail.duplicate_detail" :key="i" class="dup-item">
                <span class="dup-index">{{ i + 1 }}.</span>
                <el-link type="primary" :href="tapdUrl(currentDetail.workspace_id, d.story_id)" target="_blank">
                  {{ d.story_id }} - {{ d.title || '(无标题)' }}
                </el-link>
                <el-tag size="small" style="margin-left: 8px">相似度 {{ (d.similarity * 100).toFixed(0) }}%</el-tag>
              </div>
            </div>
            <span v-else>{{ currentDetail.duplicate_with?.join(', ') }}</span>
          </el-descriptions-item>
        </el-descriptions>
      </div>
    </el-drawer>

    <AddCaseLibraryDialog ref="addCaseDialog" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { Check, RefreshLeft, Refresh, Loading } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/api'
import PageTutorial from '@/components/PageTutorial.vue'
import AddCaseLibraryDialog from '@/components/AddCaseLibraryDialog.vue'
import { tutorials } from '@/tutorials'

const list = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const keyword = ref('')
const loading = ref(false)
const selected = ref([])

const stats = ref({ total: 0 })
const confirmedCount = ref(0)

const confirming = ref(false)
const rejecting = ref(false)

// 打分进度（确认不重复后）
const scoring = ref(false)
const scoreTotal = ref(0)
const scoreProcessed = ref(0)
const scoreSuccess = ref(0)
const scoreFail = ref(0)
const scorePercent = computed(() => {
  if (!scoreTotal.value) return 0
  return Math.round((scoreProcessed.value / scoreTotal.value) * 100)
})

const detailVisible = ref(false)
const currentDetail = ref(null)
const addCaseDialog = ref(null)

let scoreTimer = null

async function loadList() {
  loading.value = true
  try {
    const data = await api.get('/user-requirements/duplicate/list', {
      params: {
        page: page.value,
        page_size: pageSize.value,
        keyword: keyword.value || undefined
      }
    })
    list.value = data.items
    total.value = data.total
    stats.value.total = data.total
  } finally {
    loading.value = false
  }
}

function onSelectionChange(rows) {
  selected.value = rows
}

function tapdUrl(workspaceId, storyId) {
  if (!workspaceId || !storyId) return '#'
  return `https://www.tapd.cn/${workspaceId}/prong/stories/view/${storyId}`
}

async function handleConfirmDuplicate() {
  const count = selected.value.length
  try {
    await ElMessageBox.confirm(
      `即将把 ${count} 条重复需求写回 TAPD，并将 TAPD 需求状态更改为"重复需求"。确认操作？`,
      '确认重复',
      { type: 'warning' }
    )
    confirming.value = true
    const ids = selected.value.map(r => r.id)
    const data = await api.post('/user-requirements/duplicate/confirm', { record_ids: ids })
    confirmedCount.value += data.succeeded
    if (data.failed > 0) {
      ElMessage.warning(`完成：成功 ${data.succeeded} 条，失败 ${data.failed} 条`)
    } else {
      ElMessage.success(`已成功将 ${data.succeeded} 条需求在 TAPD 标记为重复需求`)
    }
    await loadList()
  } catch (e) {
    if (e !== 'cancel' && e?.response) {
      // 错误已由拦截器处理
    }
  } finally {
    confirming.value = false
  }
}

async function handleRejectDuplicate() {
  const count = selected.value.length
  try {
    await ElMessageBox.confirm(
      `即将把 ${count} 条需求标记为不重复，清除重复标记并发回打分处理。确认操作？`,
      '确认不重复',
      { type: 'warning' }
    )
    rejecting.value = true
    const ids = selected.value.map(r => r.id)
    const data = await api.post('/user-requirements/duplicate/reject', { record_ids: ids })
    ElMessage.success(`已将 ${data.cleared} 条需求标记为不重复，开始打分...`)
    rejecting.value = false
    await loadList()
    // 轮询打分进度
    if (data.job_id) {
      startScorePolling(data.job_id)
    }
  } catch (e) {
    if (e !== 'cancel') {
      // 错误已由拦截器处理
    }
  } finally {
    rejecting.value = false
  }
}

function startScorePolling(jobId) {
  scoring.value = true
  scoreTotal.value = 0
  scoreProcessed.value = 0
  scoreSuccess.value = 0
  scoreFail.value = 0

  let count = 0
  scoreTimer = setInterval(async () => {
    count++
    try {
      const data = await api.get(`/user-requirements/jobs/${jobId}/result`)
      if (data.total !== undefined) scoreTotal.value = data.total
      if (data.processed !== undefined) scoreProcessed.value = data.processed
      if (data.succeeded !== undefined) scoreSuccess.value = data.succeeded
      if (data.failed !== undefined) scoreFail.value = data.failed

      if (data.status === 'completed' || data.status === 'failed' || data.status === 'interrupted') {
        clearInterval(scoreTimer)
        scoreTimer = null
        scoring.value = false
        if (data.status === 'completed') {
          ElMessage.success(`打分完成：成功 ${scoreSuccess.value}，失败 ${scoreFail.value}`)
        } else {
          ElMessage.warning(`打分任务状态：${data.status}`)
        }
        await loadList()
      }
    } catch (e) {
      clearInterval(scoreTimer)
      scoreTimer = null
      scoring.value = false
    }
    if (count > 1200) {
      clearInterval(scoreTimer)
      scoreTimer = null
      scoring.value = false
    }
  }, 2000)
}

function showDetail(row) {
  currentDetail.value = row
  detailVisible.value = true
}

// 将当前需求作为「误判案例」加入案例库（预填 AI 重复识别结果）
function openAddCase(row) {
  const aiResult = {
    is_duplicate: row.is_duplicate,
    similarity: row.similarity,
    duplicate_detail: row.duplicate_detail ?? null,
  }
  addCaseDialog.value?.open({
    moduleKey: 'duplicate',
    requirement_title: row.title || '',
    requirement_desc: row.description || '',
    aiResult,
    is_mismatch: true,
  })
}

function similarityTagType(sim) {
  if (sim >= 0.8) return 'danger'
  if (sim >= 0.6) return 'warning'
  return 'info'
}

onMounted(() => {
  loadList()
})

onUnmounted(() => {
  if (scoreTimer) clearInterval(scoreTimer)
})
</script>

<style scoped>
.stat-row {
  margin-bottom: 16px;
}
.action-card {
  margin-bottom: 16px;
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
  display: block;
  margin-top: 4px;
  color: #909399;
  font-size: 12px;
}
.dup-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.dup-item {
  display: flex;
  align-items: center;
  gap: 4px;
}
.dup-index {
  color: #909399;
  font-size: 12px;
  min-width: 18px;
}
.no-detail {
  color: #c0c4cc;
}
.detail-content {
  padding: 0 8px;
}
.desc-text {
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 300px;
  overflow-y: auto;
}
</style>
