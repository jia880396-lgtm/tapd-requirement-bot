<template>
  <div class="page-container">
    <header class="workspace-page-header">
      <div>
        <h1 class="workspace-page-title">模块技能</h1>
        <p class="workspace-page-description">
          将需求处理的四个流程（可靠性打分 / 重复识别 / 需求分类 / PRD 分析）内化为可配置的 Skill。
          管理员可查看并编辑生效版本、基于误判案例一键优化、评测对比、并激活新版本。
        </p>
      </div>
      <div class="workspace-page-meta">
        <PageTutorial :tutorial="tutorials['skill-management']" />
      </div>
    </header>

    <el-row :gutter="16">
      <!-- 左侧：4 个 Skill 卡片 -->
      <el-col :span="8">
        <el-card shadow="never" class="skill-list">
          <template #header><span class="list-header">模块列表</span></template>
          <div
            v-for="sk in skills"
            :key="sk.module_key"
            class="skill-item"
            :class="{ active: selectedKey === sk.module_key }"
            @click="selectSkill(sk.module_key)"
          >
            <div class="skill-item-main">
              <span class="skill-item-name">{{ sk.name }}</span>
              <el-tag size="small" :type="sk.active_version ? 'success' : 'info'">
                v{{ sk.active_version ? sk.active_version.version_no : '-' }}
              </el-tag>
            </div>
            <div class="skill-item-desc">{{ sk.description }}</div>
          </div>
          <el-empty v-if="!skills.length" description="暂无 Skill" />
        </el-card>
      </el-col>

      <!-- 右侧：选中 Skill 的管理面板 -->
      <el-col :span="16" v-loading="loading">
        <template v-if="selected">
          <el-card shadow="never" class="toolbar-card">
            <div class="toolbar">
              <div>
                <strong>{{ selected.name }}</strong>
                <span class="toolbar-sub">（模块标识：{{ selected.module_key }}）</span>
              </div>
              <div class="toolbar-actions">
                <el-button type="primary" :icon="Edit" @click="openEdit">编辑为新草稿</el-button>
                <el-button type="warning" :icon="MagicStick" @click="runOptimize" :loading="optimizing">
                  一键优化
                </el-button>
                <el-button :icon="DataAnalysis" @click="runEvaluate" :loading="evaluating">
                  运行评测
                </el-button>
                <el-button :icon="Refresh" @click="runReviewAll" :loading="reviewing">
                  立即复盘
                </el-button>
                <el-button :icon="Switch" @click="openAbDialog" :disabled="versions.length < 2">
                  A/B 对比
                </el-button>
              </div>
            </div>
          </el-card>

          <el-card shadow="never" class="detail-card">
            <el-tabs v-model="activeTab">
              <!-- 当前生效版本 -->
              <el-tab-pane label="当前生效版本" name="active">
                <div v-if="selected.active_version" class="version-view">
                  <el-descriptions :column="2" border size="small">
                    <el-descriptions-item label="版本号">v{{ selected.active_version.version_no }}</el-descriptions-item>
                    <el-descriptions-item label="状态">
                      <el-tag size="small" type="success">生效中</el-tag>
                    </el-descriptions-item>
                    <el-descriptions-item label="更新时间" :span="2">
                      {{ selected.active_version.created_at || '-' }}
                    </el-descriptions-item>
                  </el-descriptions>

                  <h4 class="block-title">主提示词 (prompt_text)</h4>
                  <pre class="code-block">{{ selected.active_version.prompt_text || '（空）' }}</pre>

                  <h4 class="block-title">结构化规则 (rules_json)</h4>
                  <pre class="code-block">{{ prettyJson(selected.active_version.rules_json) }}</pre>

                  <h4 class="block-title">参数 (params_json)</h4>
                  <pre class="code-block">{{ prettyJson(selected.active_version.params_json) }}</pre>

                  <h4 class="block-title">知识库上下文 (kb_context)</h4>
                  <pre class="code-block">{{ selected.active_version.kb_context || '（空）' }}</pre>
                </div>
                <el-empty v-else description="该模块暂无生效版本" />
              </el-tab-pane>

              <!-- 版本历史 -->
              <el-tab-pane label="版本历史" name="versions">
                <el-table :data="versions" v-loading="versionsLoading" stripe>
                  <el-table-column label="版本" width="80">
                    <template #default="{ row }">v{{ row.version_no }}</template>
                  </el-table-column>
                  <el-table-column label="状态" width="100">
                    <template #default="{ row }">
                      <el-tag size="small" :type="row.status === 'active' ? 'success' : row.status === 'draft' ? 'warning' : 'info'">
                        {{ { active: '生效', draft: '草稿', archived: '归档' }[row.status] || row.status }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="来源" prop="created_by" width="120" />
                  <el-table-column label="创建时间" prop="created_at" min-width="160" />
                  <el-table-column label="操作" width="140" fixed="right">
                    <template #default="{ row }">
                      <el-button
                        v-if="row.status !== 'active'"
                        link type="primary"
                        @click="activate(row)"
                        :loading="activatingId === row.id"
                      >激活</el-button>
                      <template v-else>
                        <span style="color:#67c23a">生效中</span>
                        <el-button
                          v-if="row.parent_version_id"
                          link type="danger"
                          @click="rollback(row)"
                          :loading="rollingBackId === row.id"
                        >回滚</el-button>
                      </template>
                    </template>
                  </el-table-column>
                </el-table>
              </el-tab-pane>

              <!-- 评测结果 -->
              <el-tab-pane label="评测结果" name="evaluate">
                <div v-if="evalResult" class="eval-view">
                  <p class="eval-note">案例库共 {{ evalResult.total_cases }} 条样本（temperature=0 复现）。</p>
                  <el-row :gutter="16">
                    <el-col :span="11">
                      <el-card shadow="never" class="eval-box">
                        <template #header>生效版本准确率</template>
                        <div class="eval-score">{{ pct(evalResult.active?.accuracy) }}</div>
                        <div class="eval-sub">样本 {{ evalResult.active?.evaluated || 0 }} / 正确 {{ evalResult.active?.correct || 0 }}</div>
                        <div v-if="evalResult.active?.l1_accuracy !== null && evalResult.active?.l1_accuracy !== undefined" class="eval-sub">
                          一级分类准确率：{{ pct(evalResult.active.l1_accuracy) }}
                        </div>
                      </el-card>
                    </el-col>
                    <el-col :span="11">
                      <el-card shadow="never" class="eval-box">
                        <template #header>最新草稿准确率</template>
                        <template v-if="evalResult.draft">
                          <div class="eval-score">{{ pct(evalResult.draft.accuracy) }}</div>
                          <div class="eval-sub">样本 {{ evalResult.draft.evaluated }} / 正确 {{ evalResult.draft.correct }}</div>
                          <div v-if="evalResult.draft.l1_accuracy !== null && evalResult.draft.l1_accuracy !== undefined" class="eval-sub">
                            一级分类准确率：{{ pct(evalResult.draft.l1_accuracy) }}
                          </div>
                        </template>
                        <div v-else class="eval-sub">无草稿版本（先「一键优化」生成草稿）</div>
                      </el-card>
                    </el-col>
                  </el-row>
                  <el-alert
                    v-if="evalResult.delta !== null && evalResult.delta !== undefined"
                    class="eval-delta"
                    :title="`准确率变化（草稿 - 生效）：${deltaText}`"
                    :type="evalResult.delta >= 0 ? 'success' : 'error'"
                    :closable="false"
                  />
                </div>
                <el-empty v-else description="点击上方「运行评测」查看准确率对比" />
              </el-tab-pane>

              <!-- 复盘记录 -->
              <el-tab-pane label="复盘记录" name="review">
                <div v-if="reviewLogs.length" class="review-view">
                  <p class="eval-note">定期复盘会自动统计新增误判案例、优化产出草稿并评测对比（<strong>不自动激活</strong>），是否采纳由管理员决定。下表为各模块复盘历史。</p>
                  <el-table :data="reviewLogs" stripe size="small">
                    <el-table-column label="模块" width="120">
                      <template #default="{ row }">{{ moduleLabel(row.module_key) }}</template>
                    </el-table-column>
                    <el-table-column label="复盘时间" prop="run_at" min-width="150" />
                    <el-table-column label="新增案例" prop="new_case_count" width="90" />
                    <el-table-column label="案例总数" prop="total_cases" width="90" />
                    <el-table-column label="草稿版本" width="90">
                      <template #default="{ row }">{{ row.draft_version_id ? 'v' + row.draft_version_no : '-' }}</template>
                    </el-table-column>
                    <el-table-column label="生效准确率" width="110">
                      <template #default="{ row }">{{ row.active_accuracy != null ? pct(row.active_accuracy) : '-' }}</template>
                    </el-table-column>
                    <el-table-column label="草稿准确率" width="110">
                      <template #default="{ row }">{{ row.draft_accuracy != null ? pct(row.draft_accuracy) : '-' }}</template>
                    </el-table-column>
                    <el-table-column label="Δ" width="90">
                      <template #default="{ row }">
                        <span :class="row.delta > 0 ? 'up' : row.delta < 0 ? 'down' : ''">
                          {{ row.delta != null ? (row.delta >= 0 ? '+' : '') + (row.delta * 100).toFixed(1) + '%' : '-' }}
                        </span>
                      </template>
                    </el-table-column>
                    <el-table-column label="建议" width="90">
                      <template #default="{ row }">
                        <el-tag size="small" :type="recoType(row.recommendation)">{{ recoLabel(row.recommendation) }}</el-tag>
                      </template>
                    </el-table-column>
                    <el-table-column label="说明" prop="note" min-width="200" show-overflow-tooltip />
                  </el-table>
                </div>
                <el-empty v-else description="暂无复盘记录，点击上方「立即复盘」开始" />
              </el-tab-pane>
            </el-tabs>
          </el-card>
        </template>

        <el-empty v-else description="请选择左侧模块" />
      </el-col>
    </el-row>

    <!-- 编辑为新草稿对话框 -->
    <el-dialog v-model="editVisible" :title="`编辑「${selected?.name || ''}」为新草稿`" width="760px" top="5vh">
      <el-form label-width="120px">
        <el-form-item label="主提示词">
          <el-input v-model="editForm.prompt_text" type="textarea" :rows="8" placeholder="prompt_text" />
        </el-form-item>
        <el-form-item label="结构化规则">
          <el-input v-model="editForm.rules_json" type="textarea" :rows="6" placeholder='rules_json（合法 JSON 字符串）' class="mono" />
        </el-form-item>
        <el-form-item label="参数">
          <el-input v-model="editForm.params_json" type="textarea" :rows="4" placeholder='params_json（合法 JSON 字符串）' class="mono" />
        </el-form-item>
        <el-form-item label="知识库上下文">
          <el-input v-model="editForm.kb_context" type="textarea" :rows="3" placeholder="kb_context（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" @click="saveDraft" :loading="saving">保存为草稿</el-button>
      </template>
    </el-dialog>

    <!-- 优化结果对话框 -->
    <el-dialog v-model="optimizeVisible" title="一键优化结果" width="640px">
      <template v-if="optimizeResult">
        <el-alert
          :title="`已生成草稿版本 v${optimizeResult.version_no}`"
          type="success" :closable="false" class="opt-alert"
        />
        <h4 class="block-title">优化理由</h4>
        <p class="opt-rationale">{{ optimizeResult.rationale || '（无）' }}</p>
        <h4 class="block-title">改动点</h4>
        <ul class="opt-changes">
          <li v-for="(c, i) in optimizeResult.changes || []" :key="i">{{ c }}</li>
          <li v-if="!(optimizeResult.changes || []).length">（无明确改动点）</li>
        </ul>
        <p class="opt-hint">草稿已生成，请到「版本历史」中确认并激活。</p>
      </template>
      <template #footer>
        <el-button @click="optimizeVisible = false">关闭</el-button>
        <el-button type="primary" @click="afterOptimize">查看版本历史</el-button>
      </template>
    </el-dialog>

    <!-- A/B 影子对比对话框 -->
    <el-dialog v-model="abVisible" :title="`A/B 影子对比 —— ${selected?.name || ''}`" width="820px" top="4vh">
      <el-alert type="info" :closable="false" class="ab-hint">
        在近期线上数据上，把<strong>候选版本</strong>重跑一遍，与<strong>当前生效版本</strong>的生产结果比对，量化「若采纳候选会改变多少决策」。只读、不写回生产。
      </el-alert>
      <el-form inline class="ab-form">
        <el-form-item label="候选版本">
          <el-select v-model="abCandidateId" placeholder="选择非生效版本" style="width:320px">
            <el-option
              v-for="v in candidateVersions"
              :key="v.id"
              :label="`v${v.version_no}（${v.status === 'draft' ? '草稿' : '归档'}）· ${v.optimizer_note || '（无版本说明）'}`"
              :value="v.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="样本量">
          <el-input-number v-model="abSampleSize" :min="1" :max="50" :step="5" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Switch" @click="runAb" :loading="abLoading" :disabled="!abCandidateId">
            运行对比
          </el-button>
        </el-form-item>
      </el-form>

      <div v-if="abResult" v-loading="abLoading" class="ab-result">
        <el-row :gutter="16">
          <el-col :span="8">
            <el-card shadow="never" class="ab-box"><template #header>对比样本</template><div class="ab-num">{{ abResult.compared }}</div></el-card>
          </el-col>
          <el-col :span="8">
            <el-card shadow="never" class="ab-box"><template #header>决策变化</template><div class="ab-num danger">{{ abResult.disagreements }}</div></el-card>
          </el-col>
          <el-col :span="8">
            <el-card shadow="never" class="ab-box"><template #header>变化率</template><div class="ab-num" :class="abResult.change_rate > 0 ? 'danger' : ''">{{ pct(abResult.change_rate) }}</div></el-card>
          </el-col>
        </el-row>
        <el-alert
          class="ab-delta"
          :title="abChangeText"
          :type="abResult.change_rate > 0.05 ? 'warning' : 'success'"
          :closable="false"
        />
        <el-table :data="abResult.per_sample" max-height="280" size="small" class="ab-table">
          <el-table-column label="ID" prop="id" width="80" />
          <el-table-column label="标题" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">
              <el-link
                v-if="tapdUrl(row)"
                :href="tapdUrl(row)"
                target="_blank"
                type="primary"
                :underline="true"
              >{{ row.title || row.story_id }}</el-link>
              <span v-else>{{ row.title || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="旧版（当前生效）" min-width="160">
            <template #default="{ row }">{{ sampleText(row.production) }}</template>
          </el-table-column>
          <el-table-column label="新版（草稿）" min-width="160">
            <template #default="{ row }">{{ sampleText(row.candidate) }}</template>
          </el-table-column>
          <el-table-column label="是否一致" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.error ? 'info' : (isSame(row) ? 'success' : 'danger')">
                {{ row.error ? '错误' : (isSame(row) ? '一致' : '变化') }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Edit, MagicStick, DataAnalysis, Refresh, Switch } from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import {
  listSkills, getSkill, listSkillVersions, createSkillVersion,
  activateSkillVersion, optimizeSkill, evaluateSkill,
  rollbackSkill, runReview, getReviewLogs, abCompareSkill,
  MODULE_LABELS,
} from '@/api/skills'
import PageTutorial from '@/components/PageTutorial.vue'
import { tutorials } from '@/tutorials'

const userStore = useUserStore()

const skills = ref([])
const loading = ref(false)
const selectedKey = ref(null)
const activeTab = ref('active')

const versions = ref([])
const versionsLoading = ref(false)
const activatingId = ref(null)

const editVisible = ref(false)
const saving = ref(false)
const editForm = reactive({ prompt_text: '', rules_json: '{}', params_json: '{}', kb_context: '' })

const optimizeVisible = ref(false)
const optimizing = ref(false)
const optimizeResult = ref(null)

const evaluating = ref(false)
const evalResult = ref(null)

const reviewing = ref(false)
const reviewLogs = ref([])

const rollingBackId = ref(null)

const abVisible = ref(false)
const abCandidateId = ref(null)
const abSampleSize = ref(20)
const abLoading = ref(false)
const abResult = ref(null)
const candidateVersions = computed(() =>
  versions.value.filter(v => v.status !== 'active')
)

const selected = computed(() => skills.value.find(s => s.module_key === selectedKey.value) || null)

function prettyJson(str) {
  if (!str) return '（空）'
  try {
    return JSON.stringify(JSON.parse(str), null, 2)
  } catch (e) {
    return str
  }
}
function pct(v) {
  if (v === null || v === undefined) return '-'
  return (v * 100).toFixed(1) + '%'
}
const deltaText = computed(() => {
  if (evalResult.value?.delta === null || evalResult.value?.delta === undefined) return '-'
  const d = evalResult.value.delta
  return (d >= 0 ? '+' : '') + (d * 100).toFixed(1) + '%'
})

function moduleLabel(key) {
  return MODULE_LABELS[key] || key
}
function recoType(r) {
  return { adopt: 'success', review: 'warning', skip: 'info', none: 'info', error: 'danger' }[r] || 'info'
}
function recoLabel(r) {
  return { adopt: '建议采纳', review: '建议人工复核', skip: '暂不采纳', none: '无', error: '失败' }[r] || r || '-'
}

async function loadSkills() {
  loading.value = true
  try {
    const data = await listSkills()
    skills.value = data.data || []
    if (!selectedKey.value && skills.value.length) {
      selectedKey.value = skills.value[0].module_key
    }
  } finally {
    loading.value = false
  }
}

async function selectSkill(key) {
  selectedKey.value = key
  activeTab.value = 'active'
  evalResult.value = null
  await loadVersions(key)
}

async function loadVersions(key) {
  if (!key) return
  versionsLoading.value = true
  try {
    const data = await listSkillVersions(key)
    versions.value = data.data || []
  } finally {
    versionsLoading.value = false
  }
}

function openEdit() {
  if (!selected.value?.active_version) {
    ElMessage.warning('该模块暂无生效版本可编辑')
    return
  }
  const av = selected.value.active_version
  editForm.prompt_text = av.prompt_text || ''
  editForm.rules_json = prettyJson(av.rules_json)
  editForm.params_json = prettyJson(av.params_json)
  editForm.kb_context = av.kb_context || ''
  editVisible.value = true
}

async function saveDraft() {
  // 校验 JSON 合法性
  try {
    JSON.parse(editForm.rules_json)
  } catch (e) {
    ElMessage.error('rules_json 不是合法 JSON')
    return
  }
  try {
    JSON.parse(editForm.params_json)
  } catch (e) {
    ElMessage.error('params_json 不是合法 JSON')
    return
  }
  saving.value = true
  try {
    const res = await createSkillVersion(selectedKey.value, {
      prompt_text: editForm.prompt_text,
      rules_json: editForm.rules_json,
      params_json: editForm.params_json,
      kb_context: editForm.kb_context,
    })
    ElMessage.success(`草稿 v${res.data.version_no} 已创建`)
    editVisible.value = false
    await loadVersions(selectedKey.value)
    activeTab.value = 'versions'
  } catch (e) {
    // 拦截器已提示
  } finally {
    saving.value = false
  }
}

async function activate(row) {
  try {
    await new Promise((resolve, reject) => {
      // ElMessageBox.confirm 返回 Promise
      import('element-plus').then(({ ElMessageBox }) => {
        ElMessageBox.confirm(`确认将 v${row.version_no} 设为生效版本？旧生效版本将归档。`, '激活版本', { type: 'warning' })
          .then(resolve).catch(reject)
      })
    })
  } catch (e) {
    return
  }
  activatingId.value = row.id
  try {
    await activateSkillVersion(selectedKey.value, row.id)
    ElMessage.success(`v${row.version_no} 已生效`)
    await loadSkills()
    await loadVersions(selectedKey.value)
  } catch (e) {
    // 拦截器已提示
  } finally {
    activatingId.value = null
  }
}

async function runOptimize() {
  optimizing.value = true
  try {
    const res = await optimizeSkill(selectedKey.value)
    optimizeResult.value = res.data
    optimizeVisible.value = true
    await loadVersions(selectedKey.value)
  } catch (e) {
    // 拦截器已提示（如案例不足 3 条）
  } finally {
    optimizing.value = false
  }
}

function afterOptimize() {
  optimizeVisible.value = false
  activeTab.value = 'versions'
}

async function runEvaluate() {
  evaluating.value = true
  try {
    const res = await evaluateSkill(selectedKey.value)
    evalResult.value = res.data
    activeTab.value = 'evaluate'
  } catch (e) {
    // 拦截器已提示
  } finally {
    evaluating.value = false
  }
}

// 复盘记录：进入标签页时加载（全模块）
async function loadReviewLogs() {
  try {
    const data = await getReviewLogs()
    reviewLogs.value = data.data || []
  } catch (e) {
    // 拦截器已提示
  }
}

// 立即复盘（管理员触发全模块一次）
async function runReviewAll() {
  reviewing.value = true
  try {
    const res = await runReview()
    const results = Array.isArray(res.data) ? res.data : (res.data?.results || [])
    const reviewed = results.filter(r => r.status === 'reviewed').length
    const skipped = results.filter(r => r.status === 'skipped').length
    ElMessage.success(`复盘完成：生成草稿 ${reviewed} 个模块，跳过 ${skipped} 个（案例不足）`)
    await loadReviewLogs()
    if (activeTab.value === 'review') await loadReviewLogs()
  } catch (e) {
    // 拦截器已提示
  } finally {
    reviewing.value = false
  }
}

// 回滚到当前生效版本的父版本
async function rollback(row) {
  try {
    await new Promise((resolve, reject) => {
      import('element-plus').then(({ ElMessageBox }) => {
        ElMessageBox.confirm(
          `确认将「${selected.value.name}」回滚到父版本 v${row.parent_version_id}？当前生效版本将归档。`,
          '回滚版本', { type: 'warning' }
        ).then(resolve).catch(reject)
      })
    })
  } catch (e) {
    return
  }
  rollingBackId.value = row.id
  try {
    const res = await rollbackSkill(selectedKey.value)
    ElMessage.success(`已回滚到 v${res.data.version_no}`)
    await loadSkills()
    await loadVersions(selectedKey.value)
  } catch (e) {
    // 拦截器已提示
  } finally {
    rollingBackId.value = null
  }
}

// A/B 影子对比
function openAbDialog() {
  abCandidateId.value = candidateVersions.value.length ? candidateVersions.value[0].id : null
  abResult.value = null
  abVisible.value = true
}
async function runAb() {
  if (!abCandidateId.value) return
  abLoading.value = true
  abResult.value = null
  try {
    const res = await abCompareSkill(selectedKey.value, abCandidateId.value, abSampleSize.value)
    abResult.value = res.data
  } catch (e) {
    // 拦截器已提示
  } finally {
    abLoading.value = false
  }
}
function sampleText(obj) {
  if (!obj) return '-'
  if (obj.l1 !== undefined) return `${obj.l1} / ${obj.l2 || ''}`
  if (obj.pass !== undefined) {
    const score = obj.score !== undefined && obj.score !== null ? `（${obj.score}分）` : ''
    return `${obj.pass ? '采纳' : '不采纳'}${score}`
  }
  return '-'
}
// 拼接 TAPD 需求详情页链接（格式与知识库中历史需求链接一致）
function tapdUrl(row) {
  if (!row || !row.story_id || !row.workspace_id) return ''
  return `https://www.tapd.cn/tapd_fe/${row.workspace_id}/story/detail/${row.story_id}`
}
function isSame(row) {
  if (row.error) return true
  const p = row.production, c = row.candidate
  if (!p || !c) return true
  if (p.l1 !== undefined && c.l1 !== undefined) return p.l1 === c.l1 && (p.l2 || '') === (c.l2 || '')
  if (p.pass !== undefined && c.pass !== undefined) return p.pass === c.pass
  return true
}
const abChangeText = computed(() => {
  if (!abResult.value) return ''
  const cr = abResult.value.change_rate || 0
  return `在 ${abResult.value.compared} 个对比样本中，有 ${abResult.value.disagreements} 个决策发生变化（变化率 ${pct(cr)}）`
})

// 进入「复盘记录」标签页时加载
watch(activeTab, (v) => {
  if (v === 'review') loadReviewLogs()
})

onMounted(async () => {
  if (!userStore.isAdmin) {
    ElMessage.error('需要管理员权限')
    return
  }
  await loadSkills()
  if (selectedKey.value) await loadVersions(selectedKey.value)
})
</script>

<style scoped>
.list-header { font-weight: 600; }
.skill-list { height: calc(100vh - 180px); overflow-y: auto; }
.skill-item {
  padding: 12px 14px; border: 1px solid #e4eaf3; border-radius: 10px; margin-bottom: 10px; cursor: pointer; transition: all .15s;
}
.skill-item:hover { border-color: #2563eb; background: #f4f8ff; }
.skill-item.active { border-color: #2563eb; background: #eaf2ff; box-shadow: 0 0 0 2px rgba(37,99,235,.12); }
.skill-item-main { display: flex; align-items: center; justify-content: space-between; }
.skill-item-name { font-weight: 650; color: #1d2939; }
.skill-item-desc { color: #667085; font-size: 12px; margin-top: 4px; line-height: 18px; }
.toolbar-card { margin-bottom: 14px; }
.toolbar { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; }
.toolbar-sub { color: #98a2b3; font-size: 12px; }
.toolbar-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.detail-card { min-height: 400px; }
.block-title { margin: 16px 0 6px; font-size: 13px; color: #344054; font-weight: 650; }
.code-block {
  background: #0f172a; color: #e2e8f0; padding: 12px 14px; border-radius: 8px;
  font-size: 12px; line-height: 1.6; white-space: pre-wrap; word-break: break-all; max-height: 320px; overflow: auto;
}
.mono :deep(textarea) { font-family: 'SFMono-Regular', Consolas, monospace; }
.eval-note { color: #667085; font-size: 13px; margin-bottom: 12px; }
.eval-box { text-align: center; }
.eval-score { font-size: 30px; font-weight: 750; color: #2563eb; }
.eval-sub { color: #667085; font-size: 12px; margin-top: 4px; }
.eval-delta { margin-top: 16px; }
.opt-alert { margin-bottom: 12px; }
.opt-rationale { color: #344054; line-height: 1.7; background: #f8fafc; padding: 10px 12px; border-radius: 8px; }
.opt-changes { margin: 6px 0 0; padding-left: 20px; color: #475467; line-height: 1.8; }
.opt-hint { color: #98a2b3; font-size: 12px; margin-top: 12px; }
.ab-hint { margin-bottom: 14px; line-height: 1.7; }
.ab-form { margin-bottom: 8px; }
.ab-box { text-align: center; }
.ab-num { font-size: 26px; font-weight: 750; color: #2563eb; }
.ab-num.danger { color: #d92d20; }
.ab-delta { margin: 14px 0; }
.ab-table { margin-top: 8px; }
.up { color: #d92d20; font-weight: 650; }
.down { color: #16a34a; font-weight: 650; }
.review-view .el-table { margin-top: 8px; }
</style>
