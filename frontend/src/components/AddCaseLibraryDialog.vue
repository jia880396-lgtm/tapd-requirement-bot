<template>
  <el-dialog v-model="visible" title="加入案例库" width="700px" top="5vh">
    <el-alert type="info" :closable="false" class="intro">
      记录「AI 结果与人工正确结果不一致」的样本。这些案例会用于各模块 Skill 的
      <b>一键优化</b>与<b>评测</b>，并自动以 few-shot 形式注入推理提示词。
    </el-alert>
    <el-form :model="form" label-width="130px" style="margin-top: 14px">
      <el-form-item label="所属模块">
        <el-select v-model="form.moduleKey" style="width: 100%">
          <el-option v-for="k in MODULE_KEYS" :key="k" :label="MODULE_LABELS[k]" :value="k" />
        </el-select>
      </el-form-item>
      <el-form-item label="需求标题">
        <el-input v-model="form.requirement_title" placeholder="需求标题" />
      </el-form-item>
      <el-form-item label="需求描述">
        <el-input v-model="form.requirement_desc" type="textarea" :rows="3" placeholder="需求描述（可选）" />
      </el-form-item>
      <el-form-item label="AI 结果 (JSON)">
        <el-input v-model="form.ai_result_json" type="textarea" :rows="4" placeholder='系统给出的结果，如 {"category_l1":"订单"}' class="mono" />
      </el-form-item>
      <el-form-item label="人工正确结果 (JSON)">
        <el-input v-model="form.human_result_json" type="textarea" :rows="4" placeholder='你认为正确的结果，如 {"category_l1":"售后"}' class="mono" />
      </el-form-item>
      <el-form-item label="是否误判">
        <el-switch v-model="form.is_mismatch" />
        <span class="form-hint">关闭表示这是「正确样本」，仍可作为评测基准</span>
      </el-form-item>
      <el-form-item label="误判原因">
        <el-input v-model="form.mismatch_reason" type="textarea" :rows="2" placeholder="为何判错（误判时填写）" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" @click="save" :loading="saving">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { MODULE_KEYS, MODULE_LABELS, addSkillCase } from '@/api/skills'

const visible = ref(false)
const saving = ref(false)
const form = reactive({
  moduleKey: 'reliability',
  requirement_title: '',
  requirement_desc: '',
  ai_result_json: '{}',
  human_result_json: '{}',
  is_mismatch: true,
  mismatch_reason: '',
  source: 'module-page',
})

// 由父组件调用：open({ moduleKey, requirement_title, requirement_desc, aiResult, humanResult, is_mismatch, mismatch_reason })
function open(prefill = {}) {
  form.moduleKey = prefill.moduleKey || 'reliability'
  form.requirement_title = prefill.requirement_title || ''
  form.requirement_desc = prefill.requirement_desc || ''
  form.ai_result_json = prefill.aiResult ? JSON.stringify(prefill.aiResult, null, 2) : '{}'
  form.human_result_json = prefill.humanResult ? JSON.stringify(prefill.humanResult, null, 2) : '{}'
  form.is_mismatch = prefill.is_mismatch ?? true
  form.mismatch_reason = prefill.mismatch_reason || ''
  form.source = 'module-page'
  visible.value = true
}

async function save() {
  if (!form.requirement_title.trim()) {
    ElMessage.warning('需求标题不能为空')
    return
  }
  try {
    JSON.parse(form.ai_result_json)
  } catch (e) {
    ElMessage.error('AI 结果不是合法 JSON')
    return
  }
  try {
    JSON.parse(form.human_result_json)
  } catch (e) {
    ElMessage.error('人工正确结果不是合法 JSON')
    return
  }
  saving.value = true
  try {
    await addSkillCase(form.moduleKey, {
      requirement_title: form.requirement_title,
      requirement_desc: form.requirement_desc,
      ai_result_json: form.ai_result_json,
      human_result_json: form.human_result_json,
      is_mismatch: form.is_mismatch,
      mismatch_reason: form.mismatch_reason,
      source: form.source,
    })
    ElMessage.success('已加入案例库')
    visible.value = false
  } catch (e) {
    // 拦截器已提示
  } finally {
    saving.value = false
  }
}

defineExpose({ open })
</script>

<style scoped>
.intro { line-height: 1.7; }
.form-hint { color: #909399; font-size: 12px; margin-left: 10px; }
.mono :deep(textarea) { font-family: 'SFMono-Regular', Consolas, monospace; }
</style>
