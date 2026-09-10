<template>
  <div class="page-container">
    <header class="workspace-page-header">
      <div>
        <h1 class="workspace-page-title">用户管理</h1>
        <p class="workspace-page-description">管理系统账号、角色与权限，重置密码或停用异常账号；登录日志请在「审计日志」中查看。</p>
      </div>
      <div class="workspace-page-meta">
        <el-button type="primary" :icon="Plus" @click="openCreate">新建用户</el-button>
      </div>
    </header>

    <el-card>
      <template #header>
        <span class="list-header">用户列表（共 {{ users.length }} 个账号）</span>
      </template>

      <el-table :data="users" v-loading="loading" stripe>
        <el-table-column label="ID" prop="id" width="60" />
        <el-table-column label="用户名" prop="username" width="140" />
        <el-table-column label="显示名" prop="display_name" width="140" />
        <el-table-column label="角色" width="100">
          <template #default="{ row }">
            <el-tag :type="row.role === 'admin' ? 'danger' : 'info'" size="small">
              {{ row.role === 'admin' ? '管理员' : '操作员' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'danger'" size="small">
              {{ row.is_active ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="需改密" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.must_change_password" type="warning" size="small">是</el-tag>
            <span v-else style="color: #909399">否</span>
          </template>
        </el-table-column>
        <el-table-column label="失败次数" prop="failed_login_count" width="90" />
        <el-table-column label="锁定至" width="170">
          <template #default="{ row }">
            <span v-if="row.locked_until" style="color: #f56c6c">{{ row.locked_until }}</span>
            <span v-else style="color: #909399">-</span>
          </template>
        </el-table-column>
        <el-table-column label="最后登录" prop="last_login_at" width="170">
          <template #default="{ row }">
            <span style="color: #909399">{{ row.last_login_at || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="创建人" prop="created_by" width="120" />
        <el-table-column label="创建时间" prop="created_at" width="170" />
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="warning" @click="openResetPwd(row)">重置密码</el-button>
            <el-button link type="danger" @click="handleDeactivate(row)"
                       :disabled="row.username === currentUsername">停用</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- ============ 新建/编辑用户对话框 ============ -->
    <el-dialog v-model="formVisible" :title="formMode === 'create' ? '新建用户' : '编辑用户'" width="500px">
      <el-form :model="userForm" label-width="120px">
        <el-form-item label="用户名" v-if="formMode === 'create'">
          <el-input v-model="userForm.username" placeholder="登录账号" />
        </el-form-item>
        <el-form-item label="用户名" v-else>
          <span>{{ userForm.username }}</span>
        </el-form-item>
        <el-form-item label="显示名">
          <el-input v-model="userForm.display_name" placeholder="中文显示名" />
        </el-form-item>
        <el-form-item label="密码" v-if="formMode === 'create'">
          <el-input v-model="userForm.password" type="password" show-password placeholder="至少 8 位" />
        </el-form-item>
        <el-form-item label="角色">
          <el-radio-group v-model="userForm.role">
            <el-radio value="admin">管理员</el-radio>
            <el-radio value="operator">操作员</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="启用状态" v-if="formMode === 'edit'">
          <el-switch v-model="userForm.is_active" />
        </el-form-item>
        <el-form-item label="登录后改密">
          <el-switch v-model="userForm.must_change_password" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formVisible = false">取消</el-button>
        <el-button type="primary" @click="saveUser" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- ============ 重置密码对话框 ============ -->
    <el-dialog v-model="pwdVisible" title="重置密码" width="450px">
      <el-form :model="pwdForm" label-width="120px">
        <el-form-item label="用户名">
          <span>{{ pwdForm.username }}</span>
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="pwdForm.new_password" type="password" show-password placeholder="至少 8 位" />
        </el-form-item>
        <el-form-item label="登录后改密">
          <el-switch v-model="pwdForm.must_change_password" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdVisible = false">取消</el-button>
        <el-button type="primary" @click="saveResetPwd" :loading="savingPwd">确认重置</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import api from '@/api'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()
const currentUsername = computed(() => userStore.username)

// 用户列表
const users = ref([])
const loading = ref(false)

// 表单
const formVisible = ref(false)
const formMode = ref('create')
const userForm = reactive({
  id: null, username: '', display_name: '', password: '',
  role: 'operator', is_active: true, must_change_password: true,
})
const saving = ref(false)

// 重置密码
const pwdVisible = ref(false)
const pwdForm = reactive({ id: null, username: '', new_password: '', must_change_password: true })
const savingPwd = ref(false)

async function loadUsers() {
  loading.value = true
  try {
    const data = await api.get('/users')
    users.value = data.data || []
  } finally {
    loading.value = false
  }
}

function openCreate() {
  formMode.value = 'create'
  Object.assign(userForm, {
    id: null, username: '', display_name: '', password: '',
    role: 'operator', is_active: true, must_change_password: true,
  })
  formVisible.value = true
}

function openEdit(row) {
  formMode.value = 'edit'
  Object.assign(userForm, {
    id: row.id, username: row.username, display_name: row.display_name,
    password: '', role: row.role, is_active: row.is_active,
    must_change_password: row.must_change_password,
  })
  formVisible.value = true
}

async function saveUser() {
  if (formMode.value === 'create') {
    if (!userForm.username || !userForm.password) {
      ElMessage.warning('用户名和密码不能为空')
      return
    }
    if (userForm.password.length < 8) {
      ElMessage.warning('密码长度不少于 8 位')
      return
    }
  }
  saving.value = true
  try {
    if (formMode.value === 'create') {
      const data = await api.post('/users', {
        username: userForm.username,
        display_name: userForm.display_name,
        password: userForm.password,
        role: userForm.role,
        must_change_password: userForm.must_change_password,
      })
      ElMessage.success(data.message || '用户创建成功')
    } else {
      await api.put(`/users/${userForm.id}`, {
        display_name: userForm.display_name,
        role: userForm.role,
        is_active: userForm.is_active,
        must_change_password: userForm.must_change_password,
      })
      ElMessage.success('用户已更新')
    }
    formVisible.value = false
    await loadUsers()
  } finally {
    saving.value = false
  }
}

function openResetPwd(row) {
  Object.assign(pwdForm, {
    id: row.id, username: row.username,
    new_password: '', must_change_password: true,
  })
  pwdVisible.value = true
}

async function saveResetPwd() {
  if (!pwdForm.new_password) {
    ElMessage.warning('请输入新密码')
    return
  }
  if (pwdForm.new_password.length < 8) {
    ElMessage.warning('密码长度不少于 8 位')
    return
  }
  savingPwd.value = true
  try {
    const data = await api.post(`/users/${pwdForm.id}/reset-password`, {
      new_password: pwdForm.new_password,
      must_change_password: pwdForm.must_change_password,
    })
    ElMessage.success(data.message || '密码已重置')
    pwdVisible.value = false
    await loadUsers()
  } finally {
    savingPwd.value = false
  }
}

async function handleDeactivate(row) {
  try {
    await ElMessageBox.confirm(`确认停用账号 "${row.username}"？停用后该用户将无法登录`, '提示', { type: 'warning' })
    const data = await api.delete(`/users/${row.id}`)
    ElMessage.success(data.message || '账号已停用')
    await loadUsers()
  } catch (e) { /* cancel */ }
}

onMounted(async () => {
  await loadUsers()
})
</script>

<style scoped>
.list-header {
  font-weight: 600;
}
</style>
