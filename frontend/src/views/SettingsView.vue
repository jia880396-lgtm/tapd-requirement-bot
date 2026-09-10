<template>
  <div class="page-container">
    <header class="workspace-page-header">
      <div>
        <h1 class="workspace-page-title">我的设置</h1>
        <p class="workspace-page-description">管理个人 TAPD、DeepSeek、评分标准及自动流程；个人修改仅对当前账号生效。</p>
      </div>
    </header>
    <el-tabs v-model="activeTab">
      <el-tab-pane label="我的业务配置" name="config">
        <el-card>
          <el-form :model="form" label-width="200px" v-loading="loading">
            <el-divider content-position="left">TAPD 配置</el-divider>
            <el-form-item label="API Endpoint">
              <el-input v-model="form.tapd_api_endpoint" />
            </el-form-item>
            <el-form-item label="Auth Token">
              <el-input v-model="form.tapd_auth_token" placeholder="40 位十六进制 token" show-password />
              <span class="hint">{{ form.tapd_auth_token_configured ? '(已配置)' : '(未配置)' }}</span>
            </el-form-item>
            <el-form-item label="Workspace IDs">
              <el-input v-model="form.tapd_workspace_ids" placeholder="多个用逗号分隔" />
            </el-form-item>
            <el-form-item label="API User (可选)">
              <el-input v-model="form.tapd_api_user" placeholder="Basic 认证用，可空" />
            </el-form-item>

            <el-divider content-position="left">模型方案（一键预设）</el-divider>
            <el-form-item label="模型方案">
              <el-select v-model="presetKey" placeholder="选择预设方案后点击保存生效" style="width: 100%">
                <el-option
                  v-for="p in MODEL_PRESETS"
                  :key="p.key"
                  :label="p.label"
                  :value="p.key"
                />
              </el-select>
              <span class="hint">选择后自动填充下方 Base URL / Model（API Key 走 .env 网关配置）</span>
            </el-form-item>

            <el-divider content-position="left">模型配置</el-divider>
            <el-form-item label="API Key">
              <el-input v-model="form.deepseek_api_key" show-password />
              <span class="hint">{{ form.deepseek_api_key_configured ? '(已配置)' : '(未配置)' }}</span>
            </el-form-item>
            <el-form-item label="Base URL">
              <el-input v-model="form.deepseek_base_url" />
            </el-form-item>
            <el-form-item label="Model">
              <el-input v-model="form.deepseek_model" />
            </el-form-item>

            <el-divider content-position="left">说明</el-divider>
            <el-alert
              title="以下 TAPD、DeepSeek 与评分参数为个人配置"
              type="info"
              :closable="false"
              description="保存后仅影响当前账号的拉取、AI 分析与评分结果；调度间隔和批量大小请在“自动流程”中单独设置。"
              style="margin-bottom: 18px"
            />
            <el-form-item>
              <el-button type="primary" @click="handleSave" :loading="saving">保存我的业务配置</el-button>
              <el-button @click="loadSettings">重新加载</el-button>
            </el-form-item>

            <template v-if="userStore.isAdmin">
              <el-divider content-position="left">系统级业务规则</el-divider>
              <el-form-item label="需求状态过滤">
                <el-input v-model="form.story_status_filter" placeholder="如 status_2（用户需求拉取用）" />
              </el-form-item>
              <el-form-item label="重复需求状态值">
                <el-input v-model="form.story_status_duplicate" placeholder="如 status_16" />
                <span class="hint">确认重复时写回 TAPD 用</span>
              </el-form-item>
              <el-form-item label="产品设计中状态值">
                <el-input v-model="form.story_status_product_designing" placeholder="如 status_21" />
                <span class="hint">手动更改 TAPD 状态用</span>
              </el-form-item>
              <el-form-item label="待评审状态值">
                <el-input v-model="form.story_status_prd_review" placeholder="如 status_8" />
                <span class="hint">PRD 分析界面拉取需求用</span>
              </el-form-item>

              <el-divider content-position="left">TAPD 自定义字段映射</el-divider>
            <el-form-item label="租户版本字段">
              <el-input v-model="form.custom_field_tenant_version" placeholder="custom_field_17" />
            </el-form-item>
            <el-form-item label="需求重要程度字段">
              <el-input v-model="form.custom_field_priority" placeholder="custom_field_18" />
            </el-form-item>
            <el-form-item label="PRD(需求方案)字段">
              <el-input v-model="form.custom_field_prd" placeholder="诊断脚本确认后填入" />
            </el-form-item>
            <el-form-item label="用户需求(客户问题描述)字段">
              <el-input v-model="form.custom_field_user_requirement" placeholder="诊断脚本确认后填入" />
            </el-form-item>

            <el-divider content-position="left">分类机器人配置</el-divider>
            <el-form-item label="自动分配处理人">
              <el-switch v-model="form.auto_assign_owner" />
              <span class="hint">开启后，分类完成会自动按模块映射分配处理人</span>
            </el-form-item>
            <el-form-item label="自动写回评论">
              <el-switch v-model="form.auto_write_comment" />
              <span class="hint">开启后，分类结果会自动写回 TAPD 评论</span>
            </el-form-item>
            <el-form-item label="评论含处理人信息">
              <el-switch v-model="form.owner_update_comment" />
              <span class="hint">写回评论时是否包含处理人信息</span>
            </el-form-item>

            <el-divider content-position="left">安全与限流配置</el-divider>
            <el-form-item label="登录失败锁定次数">
              <el-input-number v-model="form.login_max_attempts" :min="3" :max="10" />
              <span class="hint">连续登录失败达到此次数后锁定账号</span>
            </el-form-item>
            <el-form-item label="账号锁定时长(分钟)">
              <el-input-number v-model="form.login_lock_minutes" :min="5" :max="120" />
              <span class="hint">账号锁定后的解锁等待时间</span>
            </el-form-item>
            <el-form-item label="备份保留天数">
              <el-input-number v-model="form.backup_retention_days" :min="1" :max="90" />
              <span class="hint">数据库备份文件保留天数</span>
            </el-form-item>
            <el-form-item label="允许的跨域来源">
              <el-input v-model="form.allowed_origins" placeholder="多个用逗号分隔，留空表示不允许跨域" />
              <span class="hint">如需前端独立部署，请填入前端域名</span>
            </el-form-item>

              <el-form-item>
                <el-button type="primary" @click="handleSave('system')" :loading="saving">保存系统级配置</el-button>
                <el-button @click="loadSettings">重新加载</el-button>
              </el-form-item>
            </template>
          </el-form>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="自动流程" name="automation">
        <el-card v-loading="automationLoading" class="automation-card">
          <el-alert
            :title="automation.auto_flow_enabled ? '自动流程已启用' : '自动流程默认关闭'"
            :type="automation.auto_flow_enabled ? 'success' : 'info'"
            :closable="false"
            show-icon
            :description="automation.auto_flow_enabled ? '请在三个业务页面分别选择需要自动执行的任务；系统仅处理当前用户可见范围内的需求。' : '启用后，您可以在用户需求处理、需求分类和 PRD 分析页面分别开启个人定时任务。'"
          />
          <div class="automation-actions">
            <el-button v-if="!automation.auto_flow_enabled" type="primary" @click="confirmEnableAutomation">开启自动流程</el-button>
            <el-button v-else type="danger" plain @click="confirmDisableAutomation">关闭全部自动流程</el-button>
          </div>
          <el-divider content-position="left">执行参数</el-divider>
          <el-form label-width="180px" class="automation-form">
            <el-form-item label="调度间隔(分钟)">
              <el-input-number v-model="automationForm.schedule_interval_minutes" :min="5" :max="1440" :disabled="!automation.auto_flow_enabled" />
              <span class="hint">已启用任务按此间隔检查并执行</span>
            </el-form-item>
            <el-form-item label="单次批量大小">
              <el-input-number v-model="automationForm.batch_size" :min="1" :max="200" :disabled="!automation.auto_flow_enabled" />
              <span class="hint">每次自动拉取或分析的最大需求数量</span>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :disabled="!automation.auto_flow_enabled" :loading="automationSaving" @click="saveAutomationSettings">保存自动流程参数</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="修改密码" name="password">
        <el-card>
          <el-form :model="pwdForm" label-width="120px" style="max-width: 500px">
            <el-form-item label="原密码">
              <el-input v-model="pwdForm.old_password" type="password" show-password />
            </el-form-item>
            <el-form-item label="新密码">
              <el-input v-model="pwdForm.new_password" type="password" show-password />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="handleChangePwd" :loading="changingPwd">修改密码</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="我的评分标准" name="scoring">
        <el-card>
          <el-alert
            title="评分标准配置"
            type="info"
description="调整后仅影响当前账号后续生成的评分与 PRD 分析；历史记录需手动重新处理。"
            :closable="false"
            style="margin-bottom: 16px"
          />

          <el-form :model="form" label-width="180px" v-loading="loading">
            <el-divider content-position="left">核心参数</el-divider>
            <el-form-item label="可靠性达标阈值">
              <el-input-number v-model="form.reliability_threshold" :min="0" :max="100" />
              <span class="hint">低于此分数的需求将生成补充问题并写回评论</span>
            </el-form-item>
            <el-form-item label="补充问题数量上限">
              <el-input-number v-model="form.question_max_count" :min="1" :max="10" />
              <span class="hint">未达标时生成的补充问题数量上限</span>
            </el-form-item>

            <el-divider content-position="left">评分松紧度</el-divider>
            <el-form-item label="评分松紧度">
              <el-radio-group v-model="form.scoring_strictness">
                <el-radio value="loose">宽松</el-radio>
                <el-radio value="standard">标准</el-radio>
                <el-radio value="strict">严格</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item>
              <div class="strictness-desc">
                <div v-if="form.scoring_strictness === 'loose'">
                  <strong>宽松评分</strong>：目标是判断需求"是否足以进入下一步产品评估"，而非判断需求是否完美。
                  只要需求能让人理解"谁、在什么场景、遇到了什么问题、希望达到什么效果"，就应给及格以上分数。
                  不因缺少截图、量化数据而扣分。
                </div>
                <div v-else-if="form.scoring_strictness === 'standard'">
                  <strong>标准评分</strong>：综合判断需求的信息完整度、描述清晰度、可实现性和业务价值。
                  不因缺少截图扣分，但缺少关键业务信息时应适当扣分。
                </div>
                <div v-else>
                  <strong>严格评分</strong>：需求必须信息完整、描述清晰、有明确业务价值和技术可行性。
                  缺少具体单号、量化数据等关键定位信息时应适当扣分。
                </div>
              </div>
            </el-form-item>

            <el-divider content-position="left">补充问题聚焦方向</el-divider>
            <el-form-item label="问题聚焦方向">
              <el-radio-group v-model="form.question_focus">
                <el-radio value="problem_scenario">仅问题场景（推荐）</el-radio>
                <el-radio value="all">全部方面</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item>
              <div class="strictness-desc">
                <div v-if="form.question_focus === 'problem_scenario'">
                  <strong>仅问题场景</strong>：只追问客户在什么场景下遇到了什么问题，禁止追问技术实现、产品方案、量化数据。
                </div>
                <div v-else>
                  <strong>全部方面</strong>：可追问问题场景、技术实现、产品方案等各方面。
                </div>
              </div>
            </el-form-item>

            <el-divider content-position="left">评分维度参考（只读）</el-divider>
            <el-form-item>
              <div class="dim-reference">
                <table class="dim-table">
                  <thead>
                    <tr>
                      <th>维度</th>
                      <th>权重</th>
                      <th>说明</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td>信息完整度</td>
                      <td>30分</td>
                      <td>需求是否包含客户标识、业务场景、问题描述、期望效果</td>
                    </tr>
                    <tr>
                      <td>描述清晰度</td>
                      <td>30分</td>
                      <td>描述是否清晰、能让人理解问题所在</td>
                    </tr>
                    <tr>
                      <td>可实现性</td>
                      <td>20分</td>
                      <td>需求是否明确到可以进入产品评估阶段</td>
                    </tr>
                    <tr>
                      <td>业务价值</td>
                      <td>20分</td>
                      <td>需求是否有合理的业务动机</td>
                    </tr>
                  </tbody>
                </table>
                <div class="dim-note">
                  注：需求完整度维度权重目前为固定值，如需调整请联系开发修改 prompts.py。
                </div>
              </div>
            </el-form-item>

            <el-divider content-position="left">PRD 评分标准</el-divider>
            <el-alert
              title="PRD 评分标准配置"
              type="info"
              description="以下配置作用于 PRD 分析界面的完整度打分。调整后新分析的 PRD 将按新标准执行（历史已分析需手动重新分析）。保存后热更新，无需重启。"
              :closable="false"
              style="margin-bottom: 16px"
            />
            <el-form-item label="PRD 评分松紧度">
              <el-radio-group v-model="form.prd_strictness">
                <el-radio value="loose">宽松</el-radio>
                <el-radio value="standard">标准（推荐）</el-radio>
                <el-radio value="strict">严格</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item>
              <div class="strictness-desc">
                <div v-if="form.prd_strictness === 'loose'">
                  <strong>宽松评分</strong>：目标是判断 PRD 是否足以进入开发评估，而非追求完美。
                  只要能让开发理解"要做什么、为谁做、解决什么问题"，就应给及格以上分数。
                  不因缺少蓝湖链接、埋点监控而扣分；模板结构缺失不严重时不扣分。
                </div>
                <div v-else-if="form.prd_strictness === 'standard'">
                  <strong>标准评分</strong>：综合判断 PRD 的覆盖度、详细度和可测试性。
                  核心诉求必须覆盖，功能描述需有路径，验收标准需可测试。
                  缺少蓝湖链接、埋点监控等非核心项时适当扣分但不严重扣分。
                </div>
                <div v-else>
                  <strong>严格评分</strong>：PRD 必须结构完整、信息详尽、可测试可验证。
                  必须包含背景、场景分析、功能价值、蓝湖链接、功能描述、验收标准、埋点监控等完整模板结构，缺失任一项均扣分。
                </div>
              </div>
            </el-form-item>

            <el-form-item label="PRD 合格阈值">
              <el-input-number v-model="form.prd_pass_threshold" :min="0" :max="100" />
              <span class="hint">完整度分数 ≥ 此阈值视为合格；低于此值生成补充建议</span>
            </el-form-item>

            <el-divider content-position="left">PRD 维度权重（总和需 = 100）</el-divider>
            <el-form-item label="需求覆盖度">
              <el-input-number v-model="form.prd_weight_coverage" :min="0" :max="100" />
              <span class="hint">PRD 是否覆盖用户需求所有要点</span>
            </el-form-item>
            <el-form-item label="功能详细度">
              <el-input-number v-model="form.prd_weight_functional" :min="0" :max="100" />
              <span class="hint">功能描述是否详细到可开发（功能路径、调整点）</span>
            </el-form-item>
            <el-form-item label="交互完整度">
              <el-input-number v-model="form.prd_weight_interaction" :min="0" :max="100" />
              <span class="hint">是否描述异常流程、边界条件、数据校验</span>
            </el-form-item>
            <el-form-item label="验收标准">
              <el-input-number v-model="form.prd_weight_acceptance" :min="0" :max="100" />
              <span class="hint">是否有明确的验收标准（可测试的断言）</span>
            </el-form-item>
            <el-form-item>
              <div class="weight-sum" :class="{ 'weight-error': prdWeightSum !== 100 }">
                当前权重总和：{{ prdWeightSum }} / 100
                <span v-if="prdWeightSum !== 100" class="weight-warn">（必须等于 100，否则保存将被拒绝）</span>
                <span v-else class="weight-ok">✓</span>
              </div>
            </el-form-item>

            <el-form-item>
              <el-button type="primary" @click="handleSave" :loading="saving">保存我的评分标准</el-button>
              <el-button @click="loadSettings">重新加载</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/api'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()
const route = useRoute()
const router = useRouter()
const activeTab = ref(String(route.query.tab || 'config'))

// 左侧导航通过 ?tab= 跳转，这里与路由保持双向同步
watch(
  () => route.query.tab,
  (t) => {
    if (t) activeTab.value = String(t)
  },
)
watch(activeTab, (t) => {
  if (String(route.query.tab || '') !== t) {
    router.replace({ name: 'settings', query: { ...route.query, tab: t } })
  }
})
const loading = ref(false)
const saving = ref(false)
const changingPwd = ref(false)
const automationLoading = ref(false)
const automationSaving = ref(false)
const automation = reactive({ auto_flow_enabled: false })
const automationForm = reactive({ schedule_interval_minutes: 30, batch_size: 50 })

const form = reactive({})
const pwdForm = reactive({ old_password: '', new_password: '' })

// 模型方案预设：一键填充 Base URL / Model（API Key 走 .env 网关配置，无需在页面填写）
const MODEL_PRESETS = [
  {
    key: 'llm-gateway',
    label: 'AI 网关（推荐）— 文字+图片一个模型',
    fields: {
      deepseek_base_url: 'https://your-llm-gateway.example.com/v1',
      deepseek_model: 'qwen3.8-flash',
    },
  },
]
const presetKey = ref('')
watch(presetKey, (k) => {
  const preset = MODEL_PRESETS.find((p) => p.key === k)
  if (!preset) return
  form.deepseek_base_url = preset.fields.deepseek_base_url
  form.deepseek_model = preset.fields.deepseek_model
  ElMessage.info(`已填充「${preset.label.split('—')[0].trim()}」的地址与模型名，直接点击保存生效`)
})

// PRD 维度权重总和（必须 = 100）
const prdWeightSum = computed(() => {
  return (Number(form.prd_weight_coverage) || 0)
    + (Number(form.prd_weight_functional) || 0)
    + (Number(form.prd_weight_interaction) || 0)
    + (Number(form.prd_weight_acceptance) || 0)
})

async function loadSettings() {
  loading.value = true
  try {
    const data = await api.get('/settings')
    Object.assign(form, data)
  } finally {
    loading.value = false
  }
}

async function handleSave(scope = 'personal') {
  // PRD 维度权重校验：必须总和 = 100
  if (prdWeightSum.value !== 100) {
    ElMessage.error(`PRD 维度权重总和必须等于 100，当前为 ${prdWeightSum.value}，请调整后再保存`)
    return
  }
  saving.value = true
  try {
    await api.post('/settings', { ...form, scope })
    ElMessage.success(scope === 'system' ? '系统级配置已保存' : '个人配置已保存，仅对当前账号生效')
    await loadSettings()
  } finally {
    saving.value = false
  }
}

async function loadAutomation() {
  automationLoading.value = true
  try {
    const data = await api.get('/automation/status')
    Object.assign(automation, data)
    automationForm.schedule_interval_minutes = data.schedule_interval_minutes
    automationForm.batch_size = data.batch_size
  } finally {
    automationLoading.value = false
  }
}

async function confirmEnableAutomation() {
  try {
    await ElMessageBox.confirm(
      '开启后，您可以在三个业务页面分别开启个人定时任务。任务将按调度间隔和批量大小自动执行，且操作员仅处理自己名下需求。是否继续？',
      '确认开启自动流程',
      { type: 'warning', confirmButtonText: '确认开启', cancelButtonText: '暂不开启' },
    )
    const data = await api.post('/automation/enable')
    Object.assign(automation, data)
    ElMessage.success(data.message)
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') { /* request errors handled globally */ }
  }
}

async function confirmDisableAutomation() {
  try {
    await ElMessageBox.confirm('关闭后，当前账号在三个业务页面已开启的自动任务都会停止。是否继续？', '确认关闭自动流程', { type: 'warning' })
    const data = await api.post('/automation/disable')
    Object.assign(automation, data)
    ElMessage.success(data.message)
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') { /* request errors handled globally */ }
  }
}

async function saveAutomationSettings() {
  automationSaving.value = true
  try {
    const data = await api.post('/automation/settings', automationForm)
    automationForm.schedule_interval_minutes = data.schedule_interval_minutes
    automationForm.batch_size = data.batch_size
    ElMessage.success(data.message)
  } finally {
    automationSaving.value = false
  }
}

async function handleChangePwd() {
  if (!pwdForm.old_password || !pwdForm.new_password) {
    ElMessage.warning('请填写完整')
    return
  }
  changingPwd.value = true
  try {
    await api.post('/auth/change-password', pwdForm)
    ElMessage.success('密码已修改')
    pwdForm.old_password = ''
    pwdForm.new_password = ''
  } finally {
    changingPwd.value = false
  }
}

onMounted(() => {
  loadAutomation()
  loadSettings()
})
</script>

<style scoped>
.automation-card :deep(.el-alert) {
  margin-bottom: 18px;
}
.automation-actions {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.automation-form {
  max-width: 640px;
}
.hint {
  margin-left: 12px;
  color: #909399;
  font-size: 12px;
}
.strictness-desc {
  color: #606266;
  font-size: 12px;
  line-height: 1.7;
  padding: 10px 14px;
  background: #f5f7fa;
  border-radius: 4px;
  border-left: 3px solid #409eff;
}
.dim-reference {
  width: 100%;
}
.dim-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.dim-table th,
.dim-table td {
  border: 1px solid #ebeef5;
  padding: 8px 12px;
  text-align: left;
}
.dim-table th {
  background: #f5f7fa;
  color: #303133;
  font-weight: 600;
}
.dim-note {
  color: #909399;
  font-size: 12px;
  margin-top: 8px;
}
.weight-sum {
  display: inline-block;
  padding: 8px 14px;
  background: #f5f7fa;
  border-radius: 4px;
  border-left: 3px solid #67c23a;
  font-size: 13px;
  color: #606266;
}
.weight-sum.weight-error {
  border-left-color: #f56c6c;
  background: #fef0f0;
}
.weight-warn {
  color: #f56c6c;
  font-weight: 600;
  margin-left: 6px;
}
.weight-ok {
  color: #67c23a;
  font-weight: 600;
  margin-left: 6px;
}
</style>
