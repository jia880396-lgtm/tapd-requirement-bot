<template>
  <div class="page-container">
    <header class="workspace-page-header">
      <div>
        <h1 class="workspace-page-title">案例库</h1>
        <p class="workspace-page-description">
          沉淀「AI 结果与人工正确结果不一致」的样本，作为各模块 Skill 优化与评测的基准集。
          标记误判的案例会被自动注入推理提示词（few-shot），并用于「一键优化」生成更好的 Skill 版本。
        </p>
      </div>
      <div class="workspace-page-meta">
        <el-button type="primary" :icon="Plus" @click="openAdd">新增案例</el-button>
      </div>
    </header>

    <el-card shadow="never">
      <div class="filter-bar">
        <el-radio-group v-model="currentModule" @change="reload">
          <el-radio-button v-for="k in MODULE_KEYS" :key="k" :value="k">{{ MODULE_LABELS[k] }}</el-radio-button>
        </el-radio-group>
        <div class="filter-right">
          <el-switch v-model="onlyMismatch" @change="reload" active-text="仅看误判案例" />
        </div>
      </div>

      <el-table :data="cases" v-loading="loading" stripe>
        <el-table-column label="需求标题" prop="requirement_title" min-width="200" show-overflow-tooltip />
        <el-table-column label="是否误判" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.is_mismatch ? 'danger' : 'success'">
              {{ row.is_mismatch ? '误判' : '正确' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="来源" prop="source" width="100" />
        <el-table-column label="误判原因" prop="mismatch_reason" min-width="160" show-overflow-tooltip />
        <el-table-column label="创建人" prop="created_by" width="110" />
        <el-table-column label="创建时间" prop="created_at" width="170" show-overflow-tooltip />
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">详情</el-button>
            <el-button link type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          :total="total"
          :page-size="size"
          layout="total, prev, pager, next"
          @current-change="reload"
        />
      </div>
    </el-card>

    <!-- 新增案例对话框 -->
    <el-dialog v-model="addVisible" title="新增案例" width="680px" top="5vh">
      <el-form :model="addForm" label-width="120px">
        <el-form-item label="所属模块">
          <el-select v-model="addForm.moduleKey" style="width: 100%">
            <el-option v-for="k in MODULE_KEYS" :key="k" :label="MODULE_LABELS[k]" :value="k" />
          </el-select>
        </el-form-item>
        <el-form-item label="需求标题">
          <el-input v-model="addForm.requirement_title" placeholder="需求标题" />
        </el-form-item>
        <el-form-item label="需求描述">
          <el-input v-model="addForm.requirement_desc" type="textarea" :rows="3" placeholder="需求描述（可选）" />
        </el-form-item>
        <el-form-item label="AI 结果 (JSON)">
          <el-input v-model="addForm.ai_result_json" type="textarea" :rows="4" placeholder='如 {"category_l1":"订单"}' class="mono" />
        </el-form-item>
        <el-form-item label="人工正确结果 (JSON)">
          <el-input v-model="addForm.human_result_json" type="textarea" :rows="4" placeholder='如 {"category_l1":"售后"}' class="mono" />
        </el-form-item>
        <el-form-item label="是否误判">
          <el-switch v-model="addForm.is_mismatch" />
        </el-form-item>
        <el-form-item label="误判原因">
          <el-input v-model="addForm.mismatch_reason" type="textarea" :rows="2" placeholder="为何判错（误判时填写）" />
        </el-form-item>
        <el-form-item label="来源">
          <el-input v-model="addForm.source" placeholder="来源标识，如 manual" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addVisible = false">取消</el-button>
        <el-button type="primary" @click="saveAdd" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- 案例详情对话框 -->
    <el-dialog v-model="detailVisible" title="案例详情" width="640px">
      <template v-if="current">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="所属模块">{{ MODULE_LABELS[currentModule] }}</el-descriptions-item>
          <el-descriptions-item label="需求标题">{{ current.requirement_title }}</el-descriptions-item>
          <el-descriptions-item label="是否误判">
            <el-tag size="small" :type="current.is_mismatch ? 'danger' : 'success'">
              {{ current.is_mismatch ? '误判' : '正确' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="误判原因">{{ current.mismatch_reason || '（无）' }}</el-descriptions-item>
        </el-descriptions>
        <h4 class="block-title">AI 结果</h4>
        <pre class="code-block">{{ prettyJson(current.ai_result_json) }}</pre>
        <h4 class="block-title">人工正确结果</h4>
        <pre class="code-block">{{ prettyJson(current.human_result_json) }}</pre>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import {
  MODULE_KEYS, MODULE_LABELS, listSkillCases, addSkillCase, deleteSkillCase,
} from '@/api/skills'

const currentModule = ref(MODULE_KEYS[0])
const onlyMismatch = ref(false)
const cases = ref([])
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const size = ref(20)

const addVisible = ref(false)
const saving = ref(false)
const addForm = reactive({
  moduleKey: MODULE_KEYS[0],
  requirement_title: '', requirement_desc: '',
  ai_result_json: '{}', human_result_json: '{}',
  is_mismatch: true, mismatch_reason: '', source: 'manual',
})

const detailVisible = ref(false)
const current = ref(null)

function prettyJson(str) {
  if (!str) return '（空）'
  try {
    return JSON.stringify(JSON.parse(str), null, 2)
  } catch (e) {
    return str
  }
}

async function reload() {
  loading.value = true
  try {
    const res = await listSkillCases(currentModule.value, {
      is_mismatch: onlyMismatch.value ? true : null,
      page: page.value, size: size.value,
    })
    cases.value = res.data || []
    total.value = res.total || 0
  } finally {
    loading.value = false
  }
}

function openAdd() {
  Object.assign(addForm, {
    moduleKey: currentModule.value,
    requirement_title: '', requirement_desc: '',
    ai_result_json: '{}', human_result_json: '{}',
    is_mismatch: true, mismatch_reason: '', source: 'manual',
  })
  addVisible.value = true
}

async function saveAdd() {
  if (!addForm.requirement_title.trim()) {
    ElMessage.warning('需求标题不能为空')
    return
  }
  try {
    JSON.parse(addForm.ai_result_json)
  } catch (e) {
    ElMessage.error('AI 结果不是合法 JSON')
    return
  }
  try {
    JSON.parse(addForm.human_result_json)
  } catch (e) {
    ElMessage.error('人工正确结果不是合法 JSON')
    return
  }
  saving.value = true
  try {
    await addSkillCase(addForm.moduleKey, {
      requirement_title: addForm.requirement_title,
      requirement_desc: addForm.requirement_desc,
      ai_result_json: addForm.ai_result_json,
      human_result_json: addForm.human_result_json,
      is_mismatch: addForm.is_mismatch,
      mismatch_reason: addForm.mismatch_reason,
      source: addForm.source,
    })
    ElMessage.success('案例已添加')
    addVisible.value = false
    await reload()
  } catch (e) {
    // 拦截器已提示
  } finally {
    saving.value = false
  }
}

function openDetail(row) {
  current.value = row
  detailVisible.value = true
}

async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(`确认删除案例「${row.requirement_title}」？`, '删除案例', { type: 'warning' })
  } catch (e) {
    return
  }
  try {
    await deleteSkillCase(currentModule.value, row.id)
    ElMessage.success('已删除')
    await reload()
  } catch (e) {
    // 拦截器已提示
  }
}

onMounted(reload)
</script>

<style scoped>
.filter-bar {
  display: flex; align-items: center; justify-content: space-between;
  flex-wrap: wrap; gap: 12px; margin-bottom: 14px;
}
.pager { margin-top: 14px; display: flex; justify-content: flex-end; }
.block-title { margin: 14px 0 6px; font-size: 13px; color: #344054; font-weight: 650; }
.code-block {
  background: #0f172a; color: #e2e8f0; padding: 12px 14px; border-radius: 8px;
  font-size: 12px; line-height: 1.6; white-space: pre-wrap; word-break: break-all; max-height: 280px; overflow: auto;
}
.mono :deep(textarea) { font-family: 'SFMono-Regular', Consolas, monospace; }
</style>
