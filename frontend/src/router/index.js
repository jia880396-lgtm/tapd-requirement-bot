import { createRouter, createWebHistory } from 'vue-router'
import { useUserStore } from '@/stores/user'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true }
  },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    redirect: '/user-requirements',
    children: [
      {
        path: 'user-requirements',
        name: 'user-requirements',
        component: () => import('@/views/UserRequirementView.vue'),
        meta: { title: '用户需求处理' }
      },
      {
        path: 'duplicate-requirements',
        name: 'duplicate-requirements',
        component: () => import('@/views/DuplicateRequirementView.vue'),
        meta: { title: '重复需求处理' }
      },
      {
        path: 'classification',
        name: 'classification',
        component: () => import('@/views/ClassificationView.vue'),
        meta: { title: '需求分类机器人' }
      },
      {
        path: 'prd-analysis',
        name: 'prd-analysis',
        component: () => import('@/views/PrdAnalysisView.vue'),
        meta: { title: 'PRD 分析' }
      },
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@/views/DashboardView.vue'),
        meta: { title: '仪表盘' }
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/views/SettingsView.vue'),
        meta: { title: '系统设置' }
      },
      {
        path: 'user-management',
        name: 'user-management',
        component: () => import('@/views/UserManagementView.vue'),
        meta: { title: '用户管理', requireAdmin: true }
      },
      {
        path: 'audit-logs',
        name: 'audit-logs',
        component: () => import('@/views/AuditLogView.vue'),
        meta: { title: '审计日志', requireAdmin: true }
      },
      {
        path: 'skill-management',
        name: 'skill-management',
        component: () => import('@/views/SkillManagementView.vue'),
        meta: { title: '模块技能', requireAdmin: true }
      },
      {
        path: 'case-library',
        name: 'case-library',
        component: () => import('@/views/CaseLibraryView.vue'),
        meta: { title: '案例库' }
      }
    ]
  },
  { path: '/:pathMatch(.*)*', redirect: '/' }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to, from, next) => {
  const userStore = useUserStore()
  if (to.meta.public) {
    next()
    return
  }
  if (!userStore.token) {
    next('/login')
    return
  }
  if (to.meta.requireAdmin && userStore.role !== 'admin') {
    next('/')
    return
  }
  next()
})

export default router
