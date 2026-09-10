<template>
  <span class="tutorial-trigger" @click="open = true">
    <slot>
      <el-button link type="primary" :icon="QuestionFilled">使用教程</el-button>
    </slot>
  </span>

  <el-dialog
    v-model="open"
    :title="tutorial.title"
    width="860px"
    top="4vh"
    class="tutorial-dialog"
    append-to-body
    destroy-on-close
  >
    <div class="tutorial-body">
      <!-- 1. 页面处理逻辑图 -->
      <section class="tut-section">
        <h3 class="tut-h3"><span class="tut-num">1</span>页面处理逻辑图</h3>
        <p class="tut-lead">{{ tutorial.flowTitle }}</p>
        <div class="flow">
          <template v-for="(step, i) in tutorial.flow" :key="i">
            <FlowNode v-if="!step.branches" :node="{ ...step, index: i + 1 }" />
            <div v-else class="flow-branches">
              <div v-for="(b, bi) in step.branches" :key="bi" class="flow-branch-col">
                <div class="flow-branch-label">{{ b.label }}</div>
                <FlowNode :node="b.node" />
              </div>
            </div>
            <div v-if="i < tutorial.flow.length - 1" class="flow-arrow" aria-hidden="true">↓</div>
          </template>
        </div>
      </section>

      <el-divider />

      <!-- 2. 操作流程 + 按钮作用 -->
      <section class="tut-section">
        <h3 class="tut-h3"><span class="tut-num">2</span>操作流程与各按钮作用</h3>
        <el-steps :active="tutorial.steps.length" align-center finish-status="success" class="tut-steps">
          <el-step v-for="(s, i) in tutorial.steps" :key="i" :title="s.title" :description="s.desc" />
        </el-steps>

        <div class="tut-subtitle">各按钮主要作用</div>
        <el-table :data="tutorial.buttons" class="tut-btn-table" size="small" border>
          <el-table-column label="按钮" width="200">
            <template #default="{ row }">
              <el-tag :type="row.type || 'primary'" effect="light" disable-transitions>{{ row.name }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="desc" label="主要作用" min-width="380" />
        </el-table>
      </section>

      <el-divider />

      <!-- 3. 常见问题与提醒 -->
      <section class="tut-section">
        <h3 class="tut-h3"><span class="tut-num">3</span>常见问题与提醒</h3>
        <el-collapse v-model="activeFaq">
          <el-collapse-item v-for="(f, i) in tutorial.faqs" :key="i" :name="i">
            <template #title>
              <span class="tut-faq-q"><el-icon class="tut-faq-icon"><ChatLineSquare /></el-icon>Q：{{ f.q }}</span>
            </template>
            <div class="tut-faq-a">A：{{ f.a }}</div>
          </el-collapse-item>
        </el-collapse>
      </section>
    </div>

    <template #footer>
      <el-button type="primary" @click="open = false">我知道了</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { QuestionFilled, ChatLineSquare } from '@element-plus/icons-vue'
import FlowNode from './FlowNode.vue'

const props = defineProps({
  tutorial: { type: Object, required: true },
})

// 组件自行管理弹窗开关（触发按钮由组件内部渲染，父组件无需 v-model）
const open = ref(false)
const activeFaq = ref([])
</script>

<style scoped>
.tutorial-trigger { display: inline-flex; }
.tutorial-body { padding: 0 4px; }
.tut-section { margin-bottom: 4px; }
.tut-h3 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 14px;
  font-size: 15px;
  font-weight: 700;
  color: #172033;
}
.tut-num {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #2563eb;
  color: #fff;
  font-size: 12px;
  font-weight: 700;
}
.tut-lead { margin: 0 0 16px; color: #667085; font-size: 13px; }

/* 逻辑图 */
.flow {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 8px 0 4px;
}
.flow-arrow {
  font-size: 18px;
  line-height: 22px;
  color: #94a3b8;
  font-weight: 700;
}
.flow-branches {
  display: flex;
  gap: 28px;
  flex-wrap: wrap;
  justify-content: center;
  width: 100%;
  padding: 4px 0;
}
.flow-branch-col {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}
.flow-branch-label {
  font-size: 12px;
  font-weight: 650;
  color: #2563eb;
  background: #eaf2ff;
  border-radius: 6px;
  padding: 2px 10px;
}

/* 步骤与按钮表 */
.tut-steps { margin-bottom: 20px; }
.tut-steps :deep(.el-step__title) { font-size: 13px; }
.tut-steps :deep(.el-step__description) { font-size: 12px; }
.tut-subtitle {
  font-size: 13px;
  font-weight: 650;
  color: #344054;
  margin: 4px 0 10px;
}
.tut-btn-table :deep(.el-table__cell) { padding: 7px 0; }
.tut-btn-table :deep(.cell) { line-height: 18px; }

/* FAQ */
.tut-faq-q {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  color: #1d4ed8;
  font-size: 13px;
}
.tut-faq-icon { font-size: 15px; color: #2563eb; }
.tut-faq-a {
  font-size: 13px;
  color: #475467;
  line-height: 21px;
  padding: 4px 2px 8px;
}
</style>
