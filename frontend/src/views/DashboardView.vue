<template>
  <div class="page-container" v-loading="loading" element-loading-text="正在加载仪表盘数据…">
    <header class="workspace-page-header">
      <div>
        <h1 class="workspace-page-title">数据仪表盘</h1>
        <p class="workspace-page-description">汇总需求处理、可靠性评分与分类运行情况，点击可交互的指标卡可直接进入对应待办列表。</p>
      </div>
      <div class="workspace-page-meta">
        <span>实时概览</span>
        <el-tag size="small" type="success" effect="plain">数据已同步</el-tag>
      </div>
    </header>

    <nav class="dashboard-subnav">
      <button
        v-for="item in navItems"
        :key="item.key"
        class="subnav-item"
        :class="{ active: activeSection === item.key }"
        @click="scrollToSection(item.key)"
      >{{ item.label }}</button>
    </nav>

    <!-- 数据概览 -->
    <section ref="secOverview" data-section="overview" class="dash-section">
    <div class="section-title">数据概览</div>
    <!-- 顶部数据卡片 -->
    <div class="stat-grid stat-grid--5">
      <el-card shadow="hover" class="metric-card">
        <div class="metric-icon" :style="{ background: tint('primary'), color: token('primary') }">
          <el-icon><Tickets /></el-icon>
        </div>
        <div class="metric-body">
          <div class="metric-label">需求总数</div>
          <div class="metric-value" :style="{ color: token('primary') }">{{ stats.total || 0 }}</div>
          <div class="metric-hint"></div>
        </div>
      </el-card>

      <el-card shadow="hover" class="metric-card actionable" @click="goToRequirements({ status: 'pending' })">
        <div class="metric-icon" :style="{ background: tint('warning'), color: token('warning') }">
          <el-icon><Clock /></el-icon>
        </div>
        <div class="metric-body">
          <div class="metric-label">待处理</div>
          <div class="metric-value" :style="{ color: token('warning') }">{{ stats.pending || 0 }}</div>
          <div class="metric-hint">点击查看 →</div>
        </div>
      </el-card>

      <el-card shadow="hover" class="metric-card">
        <div class="metric-icon" :style="{ background: tint('primary'), color: token('primary') }">
          <el-icon><EditPen /></el-icon>
        </div>
        <div class="metric-body">
          <div class="metric-label">已打分</div>
          <div class="metric-value" :style="{ color: token('primary') }">{{ stats.scored || 0 }}</div>
          <div class="metric-hint"></div>
        </div>
      </el-card>

      <el-card shadow="hover" class="metric-card actionable" @click="goToDuplicates">
        <div class="metric-icon" :style="{ background: tint('info'), color: token('info') }">
          <el-icon><CopyDocument /></el-icon>
        </div>
        <div class="metric-body">
          <div class="metric-label">重复需求</div>
          <div class="metric-value" :style="{ color: token('info') }">{{ stats.duplicate || 0 }}</div>
          <div class="metric-hint">点击查看 →</div>
        </div>
      </el-card>

      <el-card shadow="hover" class="metric-card actionable" @click="goToRequirements({ low_score: '1' })">
        <div class="metric-icon" :style="{ background: tint('success'), color: token('success') }">
          <el-icon><TrendCharts /></el-icon>
        </div>
        <div class="metric-body">
          <div class="metric-label">合格率</div>
          <div class="metric-value" :style="{ color: token('success') }">{{ passRate }}%</div>
          <div class="metric-hint">点击查看 →</div>
        </div>
      </el-card>
    </div>
    </section>

    <!-- 可靠性分析 -->
    <section ref="secReliability" data-section="reliability" class="dash-section">
    <div class="section-title">可靠性分析</div>
    <!-- 第二行：分数分布 + 状态分布 -->
    <el-row :gutter="16">
      <el-col :span="12">
        <el-card>
          <template #header>
            <span>可靠性分数分布</span>
            <span class="card-sub">（按分数区间统计需求数）</span>
          </template>
          <v-chart class="chart" :option="scoreDistOption" autoresize />
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card>
          <template #header>处理状态分布</template>
          <v-chart class="chart" :option="statusOption" autoresize />
        </el-card>
      </el-col>
    </el-row>
    </section>

    <!-- 处理人需求状态分布 -->
    <section ref="secOwner" data-section="owner" class="dash-section">
    <div class="section-title">处理人需求状态分布</div>
    <el-card style="margin-top: 16px">
      <template #header>
        <span>处理人需求状态分布</span>
        <span class="card-sub">（按待处理数降序，最多展示前 15 名）</span>
      </template>
      <v-chart class="chart-tall" :option="ownerStackOption" autoresize />
    </el-card>
    </section>

    <!-- ============ 分类机器人看板 ============ -->
    <section ref="secClassification" data-section="classification" class="dash-section">
    <div class="section-title">分类机器人看板</div>

    <!-- 分类机器人统计卡片 -->
    <div class="stat-grid stat-grid--4">
      <el-card shadow="hover" class="metric-card actionable" @click="goToClassification">
        <div class="metric-icon" :style="{ background: tint('primary'), color: token('primary') }">
          <el-icon><Files /></el-icon>
        </div>
        <div class="metric-body">
          <div class="metric-label">已分类需求</div>
          <div class="metric-value" :style="{ color: token('primary') }">{{ clsStats.total_classified || 0 }}</div>
          <div class="metric-hint">点击查看 →</div>
        </div>
      </el-card>

      <el-card shadow="hover" class="metric-card">
        <div class="metric-icon" :style="{ background: tint('info'), color: token('info') }">
          <el-icon><ChatDotRound /></el-icon>
        </div>
        <div class="metric-body">
          <div class="metric-label">评论写回</div>
          <div class="metric-value" :style="{ color: token('info') }">{{ clsStats.total_comments_written || 0 }}</div>
          <div class="metric-hint"></div>
        </div>
      </el-card>

      <el-card shadow="hover" class="metric-card">
        <div class="metric-icon" :style="{ background: tint('success'), color: token('success') }">
          <el-icon><User /></el-icon>
        </div>
        <div class="metric-body">
          <div class="metric-label">处理人分配</div>
          <div class="metric-value" :style="{ color: token('success') }">{{ clsStats.total_owners_assigned || 0 }}</div>
          <div class="metric-hint"></div>
        </div>
      </el-card>

      <el-card shadow="hover" class="metric-card">
        <div class="metric-icon" :style="{ background: tint('primary'), color: token('primary') }">
          <el-icon><Promotion /></el-icon>
        </div>
        <div class="metric-body">
          <div class="metric-label">已写回 TAPD</div>
          <div class="metric-value" :style="{ color: token('primary') }">{{ clsStats.total_writebacked || 0 }}</div>
          <div class="metric-hint"></div>
        </div>
      </el-card>
    </div>

    <!-- 分类机器人图表 -->
    <el-row :gutter="16">
      <el-col :span="12">
        <el-card>
          <template #header>
            <span>一级分类分布</span>
            <span class="card-sub">（需求按一级模块分类）</span>
          </template>
          <v-chart class="chart" :option="clsL1Option" autoresize />
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card>
          <template #header>
            <span>处理人分配分布</span>
            <span class="card-sub">（按分配数量降序）</span>
          </template>
          <v-chart class="chart" :option="clsOwnerOption" autoresize />
        </el-card>
      </el-col>
    </el-row>

    <el-alert
      class="prd-shortcut"
      type="warning"
      :closable="false"
      show-icon
      title="待补充 PRD 的需求需要产品经理继续完善后才能分析"
    >
      <template #default>
        <el-button type="warning" link @click="goToPrdPending">查看待补充 PRD</el-button>
      </template>
    </el-alert>
    </section>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onActivated, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, PieChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, TitleComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import {
  Tickets, Clock, EditPen, CopyDocument, TrendCharts,
  Files, ChatDotRound, User, Promotion
} from '@element-plus/icons-vue'
import api from '@/api'

use([CanvasRenderer, BarChart, PieChart, GridComponent, TooltipComponent, LegendComponent, TitleComponent])

const router = useRouter()
const route = useRoute()
const stats = ref({})
const clsStats = ref({})
const loading = ref(true)

// 二级区块导航（吸顶 + 点击平滑跳转 + 滚动高亮）
const secOverview = ref(null)
const secReliability = ref(null)
const secOwner = ref(null)
const secClassification = ref(null)
const navItems = [
  { key: 'overview', label: '数据概览' },
  { key: 'reliability', label: '可靠性分析' },
  { key: 'owner', label: '处理人分布' },
  { key: 'classification', label: '分类机器人看板' },
]
const activeSection = ref('overview')

function scrollToSection(key) {
  const map = {
    overview: secOverview,
    reliability: secReliability,
    owner: secOwner,
    classification: secClassification,
  }
  const el = map[key]?.value
  if (!el) return
  const container = document.querySelector('.main-content')
  const cRect = container ? container.getBoundingClientRect() : { top: 0 }
  const rect = el.getBoundingClientRect()
  const offset = rect.top - cRect.top + (container ? container.scrollTop : window.scrollY) - 84
  if (container) container.scrollTo({ top: Math.max(offset, 0), behavior: 'smooth' })
  else window.scrollTo({ top: Math.max(offset, 0), behavior: 'smooth' })
  activeSection.value = key
}

let scrollHandler = null
function setupScrollSpy() {
  const container = document.querySelector('.main-content')
  const target = container || window
  const sections = [
    { key: 'overview', el: secOverview.value },
    { key: 'reliability', el: secReliability.value },
    { key: 'owner', el: secOwner.value },
    { key: 'classification', el: secClassification.value },
  ].filter(s => s.el)
  if (scrollHandler) target.removeEventListener('scroll', scrollHandler)
  scrollHandler = () => {
    const cTop = container ? container.getBoundingClientRect().top : 0
    const scrollTop = container ? container.scrollTop : window.scrollY
    const probe = scrollTop + 120
    // 触底判定：滚动到底部时强制高亮最后一个区块，
    // 避免末项（分类机器人看板）因内容不足无法越过探测线而错高亮上一区块（处理人分布）
    const atBottom = container
      ? scrollTop + container.clientHeight >= container.scrollHeight - 4
      : (window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 4)
    let current = sections[0]?.key
    for (const s of sections) {
      const top = s.el.getBoundingClientRect().top - cTop + scrollTop
      if (top <= probe) current = s.key
    }
    if (atBottom && sections.length) current = sections[sections.length - 1].key
    if (current) activeSection.value = current
  }
  target.addEventListener('scroll', scrollHandler, { passive: true })
}

// 语义化配色（与设计令牌对齐）
const PALETTE = {
  primary: '#2563eb',
  warning: '#e6a23c',
  info: '#909399',
  success: '#16a34a'
}
function token(name) {
  return PALETTE[name] || PALETTE.primary
}
// 浅色底（用于图标圆形背景）
function tint(name) {
  const map = {
    primary: '#e8f0fe',
    warning: '#fdf3e7',
    info: '#f1f2f4',
    success: '#e7f6ec'
  }
  return map[name] || map.primary
}

const passRate = computed(() => {
  const s = stats.value
  if (!s || !s.scored) return 0
  const passCount = s.pass_count || 0
  return Math.round(passCount / s.scored * 100)
})

const scoreDistOption = ref({})
const statusOption = ref({})
const ownerStackOption = ref({})
const clsL1Option = ref({})
const clsOwnerOption = ref({})

// 空数据占位
function emptyTitle(text) {
  return {
    title: {
      text,
      left: 'center',
      top: 'center',
      textStyle: { color: '#98a2b3', fontSize: 13, fontWeight: 'normal' }
    }
  }
}

function goToRequirements(query = {}) {
  router.push({ name: 'user-requirements', query })
}

function goToDuplicates() {
  router.push({ name: 'duplicate-requirements' })
}

function goToPrdPending() {
  router.push({ name: 'prd-analysis', query: { status: '待补充PRD' } })
}

function goToClassification() {
  router.push({ name: 'classification' })
}

async function loadData() {
  const data = await api.get('/user-requirements/statistics')
  stats.value = data

  // 分数分布柱状图
  const scoreKeys = Object.keys(data.score_distribution || {})
  const scoreVals = Object.values(data.score_distribution || {})
  scoreDistOption.value = scoreKeys.length
    ? {
        tooltip: { trigger: 'axis' },
        grid: { left: '3%', right: '4%', bottom: '3%', top: '12%', containLabel: true },
        xAxis: {
          type: 'category',
          data: scoreKeys,
          name: '分数区间',
          nameLocation: 'middle',
          nameGap: 30,
          axisLabel: { color: '#667085' },
          axisLine: { lineStyle: { color: '#d6deea' } }
        },
        yAxis: {
          type: 'value',
          name: '需求数',
          nameTextStyle: { color: '#98a2b3' },
          axisLabel: { color: '#667085' },
          splitLine: { lineStyle: { color: '#eef2f7' } }
        },
        series: [{
          type: 'bar',
          data: scoreVals,
          barWidth: '52%',
          itemStyle: {
            borderRadius: [6, 6, 0, 0],
            color: {
              type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: '#3b82f6' },
                { offset: 1, color: '#93c5fd' }
              ]
            }
          },
          label: { show: true, position: 'top', color: '#475467', fontSize: 12 }
        }]
      }
    : emptyTitle('暂无分数分布数据')

  // 状态分布饼图
  const statusData = [
    { name: '待处理', value: data.pending, itemStyle: { color: '#e6a23c' } },
    { name: '已打分', value: data.scored, itemStyle: { color: '#2563eb' } },
    { name: '重复', value: data.duplicate, itemStyle: { color: '#909399' } },
    { name: '已确认', value: data.confirmed, itemStyle: { color: '#16a34a' } },
    { name: '已拒绝', value: data.rejected, itemStyle: { color: '#f56c6c' } }
  ].filter(d => d.value > 0)
  statusOption.value = statusData.length
    ? {
        tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
        legend: { bottom: 0 },
        series: [{
          type: 'pie',
          radius: ['42%', '70%'],
          center: ['50%', '45%'],
          avoidLabelOverlap: true,
          itemStyle: { borderColor: '#fff', borderWidth: 2 },
          label: { formatter: '{b}\n{d}%', color: '#475467' },
          data: statusData
        }]
      }
    : emptyTitle('暂无状态分布数据')

  // 处理人堆叠柱状图（过滤掉"未分配"，只显示具体人名，取前 15 名）
  const topOwners = (data.by_owner || []).filter(o => o.owner && o.owner !== '未分配').slice(0, 15)
  const ownerNames = topOwners.map(o => o.owner)
  ownerStackOption.value = ownerNames.length
    ? {
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
        legend: { bottom: 0, data: ['待处理', '已打分', '重复', '已确认', '已拒绝'] },
        grid: { left: '3%', right: '4%', bottom: '15%', containLabel: true },
        xAxis: { type: 'category', data: ownerNames, axisLabel: { interval: 0, rotate: ownerNames.length > 8 ? 30 : 0, color: '#667085' } },
        yAxis: { type: 'value', axisLabel: { color: '#667085' }, splitLine: { lineStyle: { color: '#eef2f7' } } },
        series: [
          { name: '待处理', type: 'bar', stack: 'total', data: topOwners.map(o => o.pending), itemStyle: { color: '#e6a23c' } },
          { name: '已打分', type: 'bar', stack: 'total', data: topOwners.map(o => o.scored), itemStyle: { color: '#2563eb' } },
          { name: '重复', type: 'bar', stack: 'total', data: topOwners.map(o => o.duplicate), itemStyle: { color: '#909399' } },
          { name: '已确认', type: 'bar', stack: 'total', data: topOwners.map(o => o.confirmed), itemStyle: { color: '#16a34a' } },
          { name: '已拒绝', type: 'bar', stack: 'total', data: topOwners.map(o => o.rejected), itemStyle: { color: '#f56c6c' } }
        ]
      }
    : emptyTitle('暂无处理人数据')
}

async function loadClsStats() {
  const data = await api.get('/classification/stats')
  clsStats.value = data

  // 一级分类分布饼图
  const l1 = data.category_l1_distribution || []
  clsL1Option.value = l1.length
    ? {
        tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
        legend: { bottom: 0, type: 'scroll' },
        color: ['#2563eb', '#16a34a', '#e6a23c', '#909399', '#f56c6c', '#8b5cf6', '#0ea5e9'],
        series: [{
          type: 'pie',
          radius: ['42%', '70%'],
          center: ['50%', '45%'],
          avoidLabelOverlap: true,
          itemStyle: { borderColor: '#fff', borderWidth: 2 },
          label: { formatter: '{b}\n{d}%', color: '#475467' },
          data: l1.map(d => ({ name: d.name || '未分类', value: d.count }))
        }]
      }
    : emptyTitle('暂无分类数据')

  // 处理人分布柱状图
  const ownerDist = data.owner_distribution || []
  clsOwnerOption.value = ownerDist.length
    ? {
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
        grid: { left: '3%', right: '4%', bottom: '15%', containLabel: true },
        xAxis: {
          type: 'category',
          data: ownerDist.map(d => d.name),
          axisLabel: { interval: 0, rotate: ownerDist.length > 6 ? 30 : 0, color: '#667085' }
        },
        yAxis: { type: 'value', axisLabel: { color: '#667085' }, splitLine: { lineStyle: { color: '#eef2f7' } } },
        series: [{
          type: 'bar',
          data: ownerDist.map(d => d.count),
          barWidth: '52%',
          itemStyle: {
            borderRadius: [6, 6, 0, 0],
            color: {
              type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: '#22c55e' },
                { offset: 1, color: '#86efac' }
              ]
            }
          },
          label: { show: true, position: 'top', color: '#475467', fontSize: 12 }
        }]
      }
    : emptyTitle('暂无处理人分配数据')
}

onMounted(() => {
  loading.value = true
  Promise.allSettled([loadData(), loadClsStats()]).finally(() => {
    loading.value = false
    setupScrollSpy()
    const s = route.query.section
    if (s) scrollToSection(s)
  })
})

onActivated(() => {
  const s = route.query.section
  if (s) scrollToSection(s)
})

// 左侧导航点击下属区块时，URL 携带 ?section=xxx，监听并平滑跳转
watch(() => route.query.section, (s) => {
  if (s) scrollToSection(s)
})
</script>

<style scoped>
.stat-grid {
  display: grid;
  gap: 12px;
  margin-bottom: 0;
}
.stat-grid--5 { grid-template-columns: repeat(5, minmax(0, 1fr)); }
.stat-grid--4 { grid-template-columns: repeat(4, minmax(0, 1fr)); margin-bottom: 16px; }

.metric-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px;
  border-radius: var(--app-radius-md);
  height: 100%;
}
.metric-card :deep(.el-card__body) {
  display: flex;
  align-items: center;
  gap: 14px;
  width: 100%;
  padding: 0;
}
.metric-icon {
  width: 46px;
  height: 46px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  flex-shrink: 0;
}
.metric-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.metric-label {
  font-size: 13px;
  color: var(--app-text-secondary);
  margin-bottom: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.metric-value {
  font-size: 28px;
  font-weight: 720;
  line-height: 34px;
  letter-spacing: -0.5px;
}
/* 预留提示行，保证所有卡片等高 */
.metric-hint {
  min-height: 18px;
  margin-top: 2px;
  font-size: 12px;
  line-height: 18px;
  color: var(--app-primary);
}
.metric-card.actionable {
  cursor: pointer;
  transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
}
.metric-card.actionable:hover {
  transform: translateY(-3px);
  border-color: #a7c5fb;
  box-shadow: 0 6px 18px rgba(37, 99, 235, 0.12);
}

.chart {
  height: 320px;
}
.chart-tall {
  height: 420px;
}
.prd-shortcut {
  margin: 16px 0;
}

/* 二级区块导航（吸顶，参考系统管理子项模式） */
.dashboard-subnav {
  position: sticky;
  top: 0;
  z-index: 5;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 4px 0 0;
  padding: 12px 0;
  background: #f4f7fb;
  border-bottom: 1px solid #e4eaf3;
}
.subnav-item {
  border: 1px solid #d6deea;
  background: #fff;
  color: #475467;
  font-size: 13px;
  padding: 6px 18px;
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.18s ease;
}
.subnav-item:hover {
  border-color: #a7c5fb;
  color: #1d4ed8;
}
.subnav-item.active {
  background: var(--app-primary, #2563eb);
  border-color: var(--app-primary, #2563eb);
  color: #fff;
  font-weight: 600;
}
.dash-section {
  scroll-margin-top: 80px;
}
.section-title {
  font-size: 15px;
  font-weight: 650;
  color: var(--app-text, #172033);
  margin: 24px 0 16px;
  padding-left: 11px;
  border-left: 3px solid var(--app-primary, #2563eb);
}
.card-sub {
  font-size: 12px;
  color: var(--app-text-muted);
  margin-left: 8px;
  font-weight: normal;
}

@media (max-width: 1200px) {
  .stat-grid--5 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .stat-grid--4 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 768px) {
  .stat-grid--5, .stat-grid--4 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 520px) {
  .stat-grid--5, .stat-grid--4 { grid-template-columns: 1fr; }
}
</style>
