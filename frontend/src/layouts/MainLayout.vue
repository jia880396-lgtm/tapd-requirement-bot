<template>
  <el-container class="main-layout">
    <el-header class="main-header">
      <div class="header-left">
        <div class="brand-mark">T</div>
        <div>
          <h3>{{ botName }}</h3>
          <span class="header-subtitle">需求智能处理工作台</span>
        </div>
      </div>
      <div class="header-right">
        <span class="connection-dot"></span>
        <span>服务连接正常</span>
        <span class="header-divider"></span>
        <span>{{ userStore.isAdmin ? '管理员工作区' : '个人工作区' }}</span>
      </div>
    </el-header>

    <el-container class="main-body">
      <el-aside width="220px" class="main-aside">
        <div class="menu-wrapper">
          <div class="menu-section-label">需求工作台</div>
          <el-menu
            :default-active="activeMenu"
            :default-openeds="['req-group', 'sys-group', 'dash-group']"
            @select="handleMenuSelect"
          >
            <!-- 需求处理模块 -->
            <el-sub-menu index="req-group">
              <template #title>
                <el-icon><Document /></el-icon>
                <span>需求处理</span>
              </template>
              <el-menu-item index="user-requirements">
                <el-icon><Document /></el-icon>
                <span>用户需求处理</span>
                <el-badge v-if="failPendingCount > 0" :value="failPendingCount" :max="99" class="menu-badge" />
              </el-menu-item>
              <el-menu-item index="duplicate-requirements">
                <el-icon><CopyDocument /></el-icon>
                <span>重复需求处理</span>
              </el-menu-item>
              <el-menu-item index="classification">
                <el-icon><Collection /></el-icon>
                <span>需求分类</span>
              </el-menu-item>
              <el-menu-item index="prd-analysis">
                <el-icon><Files /></el-icon>
                <span>PRD 分析</span>
              </el-menu-item>
            </el-sub-menu>

            <!-- 数据与统计模块 -->
            <div class="menu-section-label menu-section-label-inline">数据洞察</div>
            <el-sub-menu index="dash-group">
              <template #title>
                <el-icon><DataAnalysis /></el-icon>
                <span>仪表盘</span>
              </template>
              <el-menu-item index="dashboard|overview">数据概览</el-menu-item>
              <el-menu-item index="dashboard|reliability">可靠性分析</el-menu-item>
              <el-menu-item index="dashboard|owner">处理人分布</el-menu-item>
              <el-menu-item index="dashboard|classification">分类机器人看板</el-menu-item>
            </el-sub-menu>

            <!-- 系统管理模块：所有用户可管理自己的业务配置、评分标准、自动流程与密码；管理员额外管理全局配置 -->
            <div class="menu-section-label menu-section-label-inline">系统管理</div>
            <el-sub-menu index="sys-group">
              <template #title>
                <el-icon><Setting /></el-icon>
                <span>系统管理</span>
              </template>
              <el-menu-item index="settings|config">
                <el-icon><Setting /></el-icon>
                <span>我的业务配置</span>
              </el-menu-item>
              <el-menu-item index="settings|automation">
                <el-icon><Switch /></el-icon>
                <span>自动流程</span>
              </el-menu-item>
              <el-menu-item index="settings|password">
                <el-icon><Key /></el-icon>
                <span>修改密码</span>
              </el-menu-item>
              <el-menu-item index="settings|scoring">
                <el-icon><DataAnalysis /></el-icon>
                <span>我的评分标准</span>
              </el-menu-item>
              <el-menu-item v-if="userStore.isAdmin" index="user-management">
                <el-icon><User /></el-icon>
                <span>用户管理</span>
              </el-menu-item>
              <el-menu-item v-if="userStore.isAdmin" index="audit-logs">
                <el-icon><Tickets /></el-icon>
                <span>审计日志</span>
              </el-menu-item>
              <el-menu-item index="case-library">
                <el-icon><Files /></el-icon>
                <span>案例库</span>
              </el-menu-item>
              <el-menu-item v-if="userStore.isAdmin" index="skill-management">
                <el-icon><MagicStick /></el-icon>
                <span>模块技能</span>
              </el-menu-item>
            </el-sub-menu>
          </el-menu>
        </div>

        <!-- 用户信息区域（左下角） -->
        <div class="user-panel">
          <el-dropdown @command="handleCommand" placement="top-start" style="width: 100%">
            <div class="user-panel-content">
              <el-icon class="user-avatar"><UserFilled /></el-icon>
              <div class="user-text">
                <div class="user-name">{{ userStore.displayName || userStore.username }}</div>
                <el-tag size="small" :type="userStore.isAdmin ? 'danger' : 'info'">
                  {{ userStore.isAdmin ? '管理员' : '操作员' }}
                </el-tag>
              </div>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="dashboard">仪表盘</el-dropdown-item>
                <el-dropdown-item command="settings|config">我的业务配置</el-dropdown-item>
                <el-dropdown-item command="settings|automation">自动流程</el-dropdown-item>
                <el-dropdown-item command="settings|password">修改密码</el-dropdown-item>
                <el-dropdown-item command="settings|scoring">我的评分标准</el-dropdown-item>
                <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-aside>

      <el-main class="main-content">
        <router-view v-slot="{ Component }">
          <keep-alive>
            <component :is="Component" />
          </keep-alive>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  UserFilled, Document, Files, DataAnalysis, Setting, CopyDocument,
  Collection, User, Tickets, Switch, Key,
} from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import api from '@/api'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const botName = ref('TAPD需求处理辅助工具')
const failPendingCount = ref(0)
let notifyTimer = null

const activeMenu = computed(() => {
  if (route.name === 'settings') {
    return `settings|${route.query.tab || 'config'}`
  }
  if (route.name === 'dashboard') {
    return `dashboard|${route.query.section || 'overview'}`
  }
  return route.name || 'user-requirements'
})

function handleMenuSelect(index) {
  if (typeof index === 'string' && index.startsWith('settings|')) {
    const tab = index.slice('settings|'.length)
    router.push({ name: 'settings', query: { tab } })
  } else if (typeof index === 'string' && index.startsWith('dashboard|')) {
    const section = index.slice('dashboard|'.length)
    router.push({ name: 'dashboard', query: { section } })
  } else {
    router.push({ name: index })
  }
}

async function handleCommand(command) {
  if (command === 'logout') {
    userStore.logout()
    router.push('/login')
  } else if (typeof command === 'string' && command.startsWith('settings|')) {
    const tab = command.slice('settings|'.length)
    router.push({ name: 'settings', query: { tab } })
  } else {
    router.push({ name: command })
  }
}

async function loadFailPending() {
  try {
    const data = await api.get('/user-requirements/statistics')
    failPendingCount.value = data.fail_pending || 0
  } catch (e) {
    // 忽略
  }
}

onMounted(async () => {
  try {
    const data = await api.get('/health')
    // 优先使用后端配置的名称，但保留默认标题
    if (data.bot_name) botName.value = data.bot_name
  } catch (e) {
    // 忽略
  }
  if (userStore.isLoggedIn) {
    try {
      await userStore.fetchMe()
    } catch (e) {
      // 忽略
    }
    loadFailPending()
    notifyTimer = setInterval(loadFailPending, 30000)
  }
})

onUnmounted(() => {
  if (notifyTimer) clearInterval(notifyTimer)
})
</script>

<style scoped>
.main-layout {
  height: 100vh;
  display: flex;
  flex-direction: column;
}
.main-header {
  height: 64px;
  background: rgba(255, 255, 255, 0.94);
  border-bottom: 1px solid #e4eaf3;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  flex-shrink: 0;
}
.header-left { display: flex; align-items: center; gap: 10px; }
.brand-mark { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 9px; background: linear-gradient(135deg, #2563eb, #60a5fa); color: #fff; font-size: 16px; font-weight: 750; box-shadow: 0 5px 12px rgba(37, 99, 235, 0.22); }
.header-left h3 { margin: 0; color: #172033; font-size: 16px; font-weight: 700; line-height: 20px; }
.header-subtitle { display: block; color: #98a2b3; font-size: 11px; line-height: 16px; }
.header-right { display: flex; align-items: center; gap: 8px; color: #667085; font-size: 12px; }
.connection-dot { width: 7px; height: 7px; border-radius: 50%; background: #22c55e; box-shadow: 0 0 0 3px #dcfce7; }
.header-divider { width: 1px; height: 16px; margin: 0 4px; background: #e4eaf3; }
.main-body { flex: 1; overflow: hidden; }
.main-aside { background: #fff; border-right: 1px solid #e4eaf3; display: flex; flex-direction: column; overflow: hidden; }
.menu-wrapper { flex: 1; padding: 12px 10px; overflow-y: auto; overflow-x: hidden; }
.menu-section-label { padding: 4px 10px 8px; color: #98a2b3; font-size: 11px; font-weight: 700; letter-spacing: 0.7px; text-transform: uppercase; }
.menu-section-label-inline { margin-top: 14px; }
.menu-wrapper :deep(.el-menu) { border-right: 0; background: transparent; }
.menu-wrapper :deep(.el-menu-item), .menu-wrapper :deep(.el-sub-menu__title) { height: 42px; line-height: 42px; margin: 2px 0; border-radius: 8px; color: #475467; }
.menu-wrapper :deep(.el-menu-item:hover), .menu-wrapper :deep(.el-sub-menu__title:hover) { background: #f4f7fb; color: #2563eb; }
.menu-wrapper :deep(.el-menu-item.is-active) { background: #eaf2ff; color: #1d4ed8; font-weight: 650; }
.menu-wrapper :deep(.el-menu--inline .el-menu-item) { min-width: 0; }
.user-panel { border-top: 1px solid #e4eaf3; padding: 10px; background: #fbfcfe; }
.user-panel-content { display: flex; align-items: center; cursor: pointer; padding: 8px; border-radius: 8px; transition: background 0.2s; }
.user-panel-content:hover { background: #eef4ff; }
.user-avatar { display: grid; place-items: center; width: 30px; height: 30px; padding: 6px; font-size: 18px; color: #2563eb; background: #eaf2ff; border-radius: 50%; margin-right: 10px; }
.user-text { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.user-name { font-size: 13px; color: #344054; font-weight: 650; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 120px; }
.main-content { background: #f4f7fb; padding: 0; overflow-y: auto; }
.menu-badge { margin-left: auto; margin-top: 2px; }
.menu-badge :deep(.el-badge__content) { font-size: 11px; }
@media (max-width: 900px) { .header-right { display: none; } }
</style>
