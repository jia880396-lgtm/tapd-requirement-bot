<template>
  <div class="login-page">
    <!-- 左侧品牌叙事面板 -->
    <aside class="login-brand">
      <div class="brand-blob brand-blob--1"></div>
      <div class="brand-blob brand-blob--2"></div>

      <div class="brand-inner">
        <div class="brand-logo">
          <el-icon :size="30"><Cpu /></el-icon>
        </div>
        <h1 class="brand-title">TAPD 需求智能处理 Agent</h1>
        <p class="brand-subtitle">需求可靠性评估 · PRD 打分 · 重复识别 · 智能分类</p>

        <div class="brand-desc">
          基于大模型自动完成需求可靠性评估、重复识别与智能分类，让产品经理从重复劳动中解放出来。
        </div>

        <ul class="brand-features">
          <li>
            <span class="feature-ico"><el-icon><DataAnalysis /></el-icon></span>
            <div>
              <div class="feature-title">需求可靠性智能打分</div>
              <div class="feature-text">多维度评估需求完整度与可实现性</div>
            </div>
          </li>
          <li>
            <span class="feature-ico"><el-icon><Document /></el-icon></span>
            <div>
              <div class="feature-title">PRD 有效性打分</div>
              <div class="feature-text">评估 PRD 完整度并生成补充建议</div>
            </div>
          </li>
          <li>
            <span class="feature-ico"><el-icon><Connection /></el-icon></span>
            <div>
              <div class="feature-title">重复需求自动识别</div>
              <div class="feature-text">聚类历史需求，规避重复建设</div>
            </div>
          </li>
          <li>
            <span class="feature-ico"><el-icon><Files /></el-icon></span>
            <div>
              <div class="feature-title">分类机器人自动归类</div>
              <div class="feature-text">一键将需求分配至对应处理人</div>
            </div>
          </li>
        </ul>
      </div>

      <div class="brand-footer">© 2026 TAPD 需求智能处理平台</div>
    </aside>

    <!-- 右侧登录表单 -->
    <main class="login-form-panel">
      <div class="form-deco form-deco--1"></div>
      <div class="form-deco form-deco--2"></div>
      <div class="login-form-box">
        <div class="form-header">
          <div class="form-badge">
            <el-icon :size="22"><Cpu /></el-icon>
          </div>
          <h2 class="form-title">欢迎登录</h2>
          <p class="form-sub">请输入账号信息以进入工作台</p>
        </div>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          label-width="0"
          @submit.prevent="handleLogin"
        >
          <el-form-item prop="username">
            <el-input
              v-model="form.username"
              placeholder="用户名"
              size="large"
              :prefix-icon="User"
            />
          </el-form-item>
          <el-form-item prop="password">
            <el-input
              v-model="form.password"
              type="password"
              placeholder="密码"
              size="large"
              show-password
              :prefix-icon="Lock"
              @keyup.enter="handleLogin"
            />
          </el-form-item>
          <el-form-item>
            <el-button
              type="primary"
              size="large"
              class="login-btn"
              :loading="loading"
              @click="handleLogin"
            >
              登 录
            </el-button>
          </el-form-item>
        </el-form>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { User, Lock, Cpu, DataAnalysis, Connection, Files, Document } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const userStore = useUserStore()

const formRef = ref(null)
const loading = ref(false)

const form = reactive({
  username: '',
  password: ''
})

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

async function handleLogin() {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    try {
      await userStore.login(form.username, form.password)
      ElMessage.success('登录成功')
      router.push('/')
    } catch (e) {
      // 错误已由 axios 拦截器处理
    } finally {
      loading.value = false
    }
  })
}
</script>

<style scoped>
.login-page {
  position: relative;
  min-height: 100vh;
  overflow: hidden;
  background: #F3F7FF;
}

/* ---------- 左侧品牌面板（斜切分割） ---------- */
.login-brand {
  position: relative;
  z-index: 2;
  width: 56%;
  min-height: 100vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 56px 64px;
  color: #fff;
  background: radial-gradient(circle at 72% 18%, #245ce8 0%, #0c42b8 100%);
  /* 斜向切割：右上角到右下角形成一条对角线，替代竖直分割线 */
  clip-path: polygon(0 0, 100% 0, 80% 100%, 0 100%);
  /* drop-shadow 会贴合 clip-path 轮廓，沿斜线投出柔和蓝光 */
  filter: drop-shadow(12px 0 26px rgba(22, 93, 255, 0.22));
}
/* 沿斜切边缘的高光描边，强化“设计感切割” */
.login-brand::after {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.50), rgba(255, 255, 255, 0.10));
  clip-path: polygon(100% 0, 80% 100%, 78.6% 100%, 98.6% 0);
}
.brand-blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(10px);
  opacity: 0.30;
  pointer-events: none;
}
.brand-blob--1 {
  width: 300px;
  height: 300px;
  top: -110px;
  right: -90px;
  background: radial-gradient(circle at 30% 30%, #4f8bff, transparent 70%);
}
.brand-blob--2 {
  width: 340px;
  height: 340px;
  bottom: -130px;
  left: -110px;
  background: radial-gradient(circle at 60% 40%, #2f6bff, transparent 70%);
}
.brand-inner {
  position: relative;
  z-index: 1;
}
.brand-logo {
  width: 56px;
  height: 56px;
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.18);
  border: 1px solid rgba(255, 255, 255, 0.25);
  backdrop-filter: blur(4px);
  color: #fff;
  margin-bottom: 18px;
}
.brand-title {
  margin: 0 0 6px;
  font-size: 34px;
  font-weight: 800;
  letter-spacing: -0.5px;
  line-height: 1.25;
}
.brand-subtitle {
  margin: 0;
  font-size: 15px;
  color: rgba(255, 255, 255, 0.72);
  letter-spacing: 0.3px;
}
.brand-desc {
  margin: 16px 0 22px;
  font-size: 12px;
  line-height: 21px;
  color: rgba(255, 255, 255, 0.55);
  max-width: 440px;
}
.brand-features {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.brand-features li {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: rgba(255, 255, 255, 0.16);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 12px;
  transition: background 0.2s ease, transform 0.2s ease;
}
.brand-features li:hover {
  background: rgba(255, 255, 255, 0.22);
  transform: translateY(-2px);
}
.feature-ico {
  flex-shrink: 0;
  width: 34px;
  height: 34px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  color: #fff;
  background: rgba(255, 255, 255, 0.16);
}
.feature-title {
  font-size: 15px;
  font-weight: 600;
  color: #fff;
  line-height: 20px;
}
.feature-text {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.72);
  line-height: 18px;
}
.brand-footer {
  position: absolute;
  left: 60px;
  bottom: 28px;
  z-index: 1;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.55);
}

/* ---------- 右侧表单面板（铺满整屏，置于斜切之下） ---------- */
.login-form-panel {
  position: absolute;
  z-index: 1;
  inset: 0;
  display: flex;
  align-items: flex-start;
  justify-content: flex-end;
  padding: 26vh 7% 24px 0;
  overflow: hidden;
  background: #F3F7FF;
}
.form-deco {
  display: none; /* 隐藏右侧悬浮装饰元素，保持登录区整洁 */
}
.form-deco--1 {
  width: 240px;
  height: 240px;
  top: -80px;
  right: -70px;
  background: radial-gradient(circle at 30% 30%, #bfdbfe, transparent 70%);
}
.form-deco--2 {
  width: 280px;
  height: 280px;
  bottom: -110px;
  left: -90px;
  background: radial-gradient(circle at 60% 40%, #bae6fd, transparent 70%);
}
.login-form-box {
  position: relative;
  z-index: 1;
  width: 400px;
  max-width: 100%;
  background: #fff;
  border-radius: 16px;
  box-shadow: 0 10px 32px rgba(22, 93, 255, 0.13);
  padding: 32px 30px;
}
.form-header {
  text-align: center;
  margin-bottom: 18px;
}
.form-badge {
  width: 52px;
  height: 52px;
  margin: 0 auto 12px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  background: linear-gradient(135deg, #165DFF, #4080ff);
  box-shadow: 0 8px 20px rgba(22, 93, 255, 0.28);
}
.form-title {
  margin: 0 0 6px;
  font-size: 24px;
  font-weight: 700;
  color: var(--app-text);
  letter-spacing: -0.3px;
}
.form-sub {
  margin: 0;
  font-size: 13px;
  color: var(--app-text-secondary);
}
.login-btn {
  width: 100%;
  --el-color-primary: #165DFF;
  --el-color-primary-light-3: #4080ff;
  --el-color-primary-light-5: #6ea2ff;
  --el-color-primary-dark-2: #0e4ad6;
  height: 44px;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 2px;
  box-shadow: 0 6px 16px rgba(22, 93, 255, 0.25);
}

.login-form-box :deep(.el-input__wrapper) {
  height: 44px;
  border-radius: 10px;
  padding: 0 14px;
}
.login-form-box :deep(.el-form-item) {
  margin-bottom: 12px;
}

/* ---------- 响应式 ---------- */
@media (max-width: 860px) {
  .login-brand {
    display: none;
  }
  .login-form-panel {
    justify-content: center;
    padding: 24px;
    background: radial-gradient(circle at 72% 18%, #245ce8 0%, #0c42b8 100%);
  }
  .login-form-box {
    background: #fff;
    padding: 30px 22px;
    border-radius: 16px;
    box-shadow: 0 10px 32px rgba(22, 93, 255, 0.13);
  }
}
</style>
