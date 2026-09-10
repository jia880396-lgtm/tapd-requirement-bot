<template>
  <div class="page-container">
    <header class="workspace-page-header">
      <div>
        <h1 class="workspace-page-title">审计日志</h1>
        <p class="workspace-page-description">查看系统操作审计与账号登录记录，排查异常操作与登录风险。</p>
      </div>
    </header>
    <el-tabs v-model="activeTab" @tab-change="onTabChange">
      <!-- ============ Tab 1: 操作审计日志 ============ -->
      <el-tab-pane label="操作审计日志" name="audit">
        <el-card>
          <template #header>
            <div class="filter-bar">
              <span class="header-title">操作审计日志（共 {{ auditTotal }} 条）</span>
              <div class="filter-controls">
                <el-select v-model="auditFilter.module" placeholder="模块筛选" clearable
                           style="width: 160px" @change="loadAuditLogs(1)">
                  <el-option v-for="m in modules" :key="m.key" :label="m.label" :value="m.key" />
                </el-select>
                <el-input v-model="auditFilter.actor" placeholder="操作人筛选" clearable
                          style="width: 160px; margin-left: 8px" @change="loadAuditLogs(1)" />
                <el-input v-model="auditFilter.action" placeholder="操作类型筛选" clearable
                          style="width: 200px; margin-left: 8px" @change="loadAuditLogs(1)" />
                <el-button size="small" :icon="Refresh" @click="loadAuditLogs()" style="margin-left: 8px">刷新</el-button>
              </div>
            </div>
          </template>

          <el-table :data="auditLogs" v-loading="auditLoading" stripe>
            <el-table-column label="时间" prop="created_at" width="170" />
            <el-table-column label="操作人" prop="actor" width="120" />
            <el-table-column label="IP" prop="actor_ip" width="140" />
            <el-table-column label="操作类型" prop="action" width="220" show-overflow-tooltip>
              <template #default="{ row }">
                <el-tag :type="actionTagType(row.action)" size="small">{{ row.action }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="目标" prop="target" width="200" show-overflow-tooltip />
            <el-table-column label="详情" prop="detail" min-width="240" show-overflow-tooltip />
            <el-table-column label="结果" width="90">
              <template #default="{ row }">
                <el-tag :type="row.result === 'success' ? 'success' : 'danger'" size="small">
                  {{ row.result === 'success' ? '成功' : '失败' }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>

          <el-pagination
            v-model:current-page="auditPage"
            :total="auditTotal"
            :page-size="50"
            layout="total, prev, pager, next"
            style="margin-top: 12px; justify-content: flex-end"
            @current-change="loadAuditLogs"
          />
        </el-card>
      </el-tab-pane>

      <!-- ============ Tab 2: 登录日志 ============ -->
      <el-tab-pane label="登录日志" name="login-logs">
        <el-card>
          <template #header>
            <div class="filter-bar">
              <span class="header-title">登录日志（共 {{ loginTotal }} 条）</span>
              <div class="filter-controls">
                <el-input v-model="loginFilter.username" placeholder="用户名筛选" clearable
                          style="width: 200px" @change="loadLoginLogs(1)" />
                <el-button size="small" :icon="Refresh" @click="loadLoginLogs()" style="margin-left: 8px">刷新</el-button>
              </div>
            </div>
          </template>
          <el-table :data="loginLogs" v-loading="loginLoading" stripe>
            <el-table-column label="时间" prop="login_time" width="170" />
            <el-table-column label="用户名" prop="username" width="140" />
            <el-table-column label="IP" prop="ip" width="140" />
            <el-table-column label="结果" width="90">
              <template #default="{ row }">
                <el-tag :type="row.success ? 'success' : 'danger'" size="small">
                  {{ row.success ? '成功' : '失败' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="原因" prop="reason" width="180" show-overflow-tooltip />
            <el-table-column label="User-Agent" prop="user_agent" min-width="240" show-overflow-tooltip />
          </el-table>
          <el-pagination
            v-model:current-page="loginPage"
            :total="loginTotal"
            :page-size="50"
            layout="total, prev, pager, next"
            style="margin-top: 12px; justify-content: flex-end"
            @current-change="loadLoginLogs"
          />
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import api from '@/api'

const activeTab = ref('audit')

// 审计日志
const auditLogs = ref([])
const auditLoading = ref(false)
const auditPage = ref(1)
const auditTotal = ref(0)
const auditFilter = reactive({ module: '', actor: '', action: '' })
const modules = ref([])

// 登录日志
const loginLogs = ref([])
const loginLoading = ref(false)
const loginPage = ref(1)
const loginTotal = ref(0)
const loginFilter = reactive({ username: '' })

function actionTagType(action) {
  if (!action) return 'info'
  if (action.includes('create')) return 'success'
  if (action.includes('delete') || action.includes('deactivate')) return 'danger'
  if (action.includes('update') || action.includes('reset')) return 'warning'
  if (action.includes('run') || action.includes('execute')) return 'primary'
  return 'info'
}

async function loadModules() {
  try {
    const data = await api.get('/audit-logs/modules')
    modules.value = data.data || []
  } catch (e) { /* ignore */ }
}

async function loadAuditLogs(page) {
  if (page) auditPage.value = page
  auditLoading.value = true
  try {
    const params = { page: auditPage.value, size: 50 }
    if (auditFilter.module && auditFilter.module !== 'all') params.module = auditFilter.module
    if (auditFilter.actor) params.actor = auditFilter.actor
    if (auditFilter.action) params.action = auditFilter.action
    const data = await api.get('/audit-logs', { params })
    auditLogs.value = data.data || []
    auditTotal.value = data.total || 0
  } finally {
    auditLoading.value = false
  }
}

async function loadLoginLogs(page) {
  if (page) loginPage.value = page
  loginLoading.value = true
  try {
    const params = { page: loginPage.value, size: 50 }
    if (loginFilter.username) params.username = loginFilter.username
    const data = await api.get('/audit-logs/login-logs', { params })
    loginLogs.value = data.data || []
    loginTotal.value = data.total || 0
  } finally {
    loginLoading.value = false
  }
}

function onTabChange(tab) {
  if (tab === 'login-logs') loadLoginLogs()
}

onMounted(async () => {
  await Promise.all([loadModules(), loadAuditLogs()])
})
</script>

<style scoped>
.filter-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.header-title {
  font-weight: 600;
}
.filter-controls {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
}
</style>
