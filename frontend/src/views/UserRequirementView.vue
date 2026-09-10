<template>
  <div class="page-container">
    <header class="workspace-page-header">
      <div>
        <h1 class="workspace-page-title">用户需求处理</h1>
        <p class="workspace-page-description">拉取待评估需求，完成重复识别与可靠性打分，并将需要补充的信息写回 TAPD。</p>
      </div>
      <div class="workspace-page-meta">
        <span>数据范围</span>
        <el-tag size="small" effect="plain">{{ userStore.isAdmin ? '全部需求' : '我的需求' }}</el-tag>
        <PageTutorial :tutorial="tutorials['user-requirements']" />
      </div>
    </header>

    <!-- 统计卡片 -->
    <el-row :gutter="16" class="stat-row">
      <el-col :span="6">
        <el-card class="stat-card">
          <div class="stat-value">{{ stats.total }}</div>
          <div class="stat-label">总需求数</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card">
          <div class="stat-value" style="color: #e6a23c">{{ stats.pending }}</div>
          <div class="stat-label">待处理</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card">
          <div class="stat-value" style="color: #f56c6c">{{ stats.duplicate }}</div>
          <div class="stat-label">重复需求</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card">
          <div class="stat-value" style="color: #67c23a">{{ stats.avg_score }}</div>
          <div class="stat-label">平均可靠性分</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 拉取区 + 操作按钮 -->
    <el-card class="action-card">
      <!-- 第一行：拉取 + 批量操作按钮 -->
      <div class="action-row">
        <el-button
          type="primary"
          :icon="Download"
          @click="handleFetch"
          :loading="fetching"
          :disabled="processing"
        >
          {{ userStore.isAdmin ? '拉取需求' : '拉取我的需求' }}
        </el-button>
        <el-button
          v-if="userStore.isAdmin"
          :icon="Download"
          @click="openFetchByOwner"
          :disabled="processing"
        >
          按处理人拉取
        </el-button>
        <el-button
          v-if="automation.auto_flow_enabled"
          :type="automation.requirements_enabled ? 'warning' : 'default'"
          @click="toggleAutomation"
          :loading="automationLoading"
        >
          {{ automation.requirements_enabled ? '停止自动处理' : '开启自动处理' }}
        </el-button>
        <el-button
          v-if="automation.auto_flow_enabled"
          :icon="Setting"
          circle
          size="small"
          @click="openAutoSettings"
          title="自动处理设置"
        />
        <span v-if="automation.auto_flow_enabled && automation.requirements_enabled" class="auto-config-hint">
          每{{ automation.schedule_interval_minutes }}分钟，{{ automation.batch_size }}条/次，超时{{ automation.max_processing_minutes }}分钟
        </span>
        <el-tag
          v-if="automation.auto_flow_enabled && automation.requirements_enabled && automation.current_job_status === 'running'"
          type="warning"
          size="small"
          effect="dark"
          style="margin-left:4px"
        >运行中</el-tag>
        <el-tag
          v-else-if="automation.auto_flow_enabled && automation.requirements_enabled && automation.current_job_status !== 'running'"
          type="info"
          size="small"
          style="margin-left:4px"
        >{{ automation.requirements_last_run_at ? '上次: ' + formatRelTime(automation.requirements_last_run_at) : '等待首次调度' }}</el-tag>

      <el-divider direction="vertical" />

      <el-button
        type="success"
        :icon="Check"
        @click="handleScore"
        :loading="scoring"
        :disabled="!selected.length || processing || scoring"
      >
        启动打分 ({{ selected.length }})
      </el-button>
      <el-dropdown trigger="click" :disabled="!selected.length">
        <el-button :icon="MoreFilled" :disabled="!selected.length">
          更多操作 ({{ selected.length }})
        </el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item :icon="Promotion" @click="handleChangeTapdStatus">
              更改 TAPD 状态
            </el-dropdown-item>
            <el-dropdown-item :icon="CopyDocument" divided @click="handleMarkDuplicate">
              标记为重复
            </el-dropdown-item>
            <el-dropdown-item :icon="ChatDotRound" @click="handleWriteComment">
              写回补充评论
            </el-dropdown-item>
            <el-dropdown-item :icon="UploadFilled" divided @click="handleWritebackScore">
              写回AI打分
            </el-dropdown-item>
            <el-dropdown-item :icon="EditPen" @click="handleWritebackReason">
              写回打分理由
            </el-dropdown-item>
            <el-dropdown-item :icon="DataLine" divided @click="handleWritebackClassification">
              写回AI分类
            </el-dropdown-item>
            <el-dropdown-item :icon="DocumentCopy" @click="handleWritebackDuplicate">
              写回重复需求
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
      </div>

      <el-divider style="margin: 12px 0 8px" />

      <!-- 第二行：筛选条件 -->
      <div class="filter-row">
        <el-input
          v-model="keyword"
          placeholder="搜索标题"
          style="width: 180px"
          clearable
          @keyup.enter="loadList"
          @clear="loadList"
        />
        <el-select v-model="filterStatus" placeholder="状态筛选" style="width: 130px" clearable @change="loadList">
          <el-option label="待评估" value="pending" />
          <el-option label="已打分" value="scored" />
          <el-option label="已确认" value="confirmed" />
        </el-select>
        <el-select v-if="userStore.isAdmin" v-model="filterOwner" placeholder="处理人筛选" style="width: 150px" clearable filterable @change="loadList">
          <el-option v-for="o in ownerOptions" :key="o" :label="o" :value="o" />
        </el-select>
        <el-button
          :type="onlyFail ? 'danger' : 'default'"
          @click="toggleOnlyFail"
        >
          {{ onlyFail ? '✓ 仅未达标(<60分)' : '仅未达标(<60分)' }}
        </el-button>
      </div>
    </el-card>

    <div class="view-context">
      <span class="view-context-title">当前视图</span>
      <el-tag size="small" effect="plain">{{ userStore.isAdmin ? '全部可见需求' : '我的名下需求' }}</el-tag>
      <el-tag v-if="filterStatus" size="small" closable @close="clearFilter('status')">{{ statusLabel(filterStatus) }}</el-tag>
      <el-tag v-if="filterOwner" size="small" closable @close="clearFilter('owner')">处理人：{{ filterOwner }}</el-tag>
      <el-tag v-if="onlyFail" type="danger" size="small" closable @close="clearFilter('onlyFail')">仅未达标（低于 60 分）</el-tag>
      <el-tag v-if="keyword" type="info" size="small" closable @close="clearFilter('keyword')">标题：{{ keyword }}</el-tag>
      <span class="view-context-count">共 {{ total }} 条</span>
      <el-button v-if="hasActiveFilters" link type="primary" @click="clearAllFilters">清空筛选</el-button>
    </div>

    <el-alert
      v-if="taskSummary"
      class="task-summary"
      :type="taskSummary.type"
      :closable="true"
      @close="taskSummary = null"
    >
      <template #title>{{ taskSummary.title }}</template>
      <div>{{ taskSummary.detail }}</div>
      <div v-if="taskSummary.failed" class="task-summary-hint">存在失败项，请在后台任务或处理日志中查看详细原因。</div>
    </el-alert>

    <!-- 拉取后自动处理进度条 -->
    <el-card v-if="processing" class="progress-card">
      <div class="progress-title">
        <el-icon class="is-loading"><Loading /></el-icon>
        {{ phase === 'fetching' ? '正在拉取需求...' : '自动处理中（重复识别 → 打分 → 分类）' }}
      </div>
      <!-- 拉取阶段：不确定进度条 -->
      <div v-if="phase === 'fetching'" class="progress-phase">
        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px">
          <span style="color: #606266; font-size: 13px">正在从 TAPD 拉取需求并入库...</span>
        </div>
        <el-progress :percentage="100" status="active" :indeterminate="true" :duration="3" />
        <div v-if="fetchInfo.total" style="margin-top: 8px; font-size: 12px; color: #909399">
          已拉取 {{ fetchInfo.total }} 条，新增 {{ fetchInfo.newCount }} 条，更新 {{ fetchInfo.updatedCount }} 条
        </div>
      </div>
      <div v-if="phase !== 'fetching'" class="progress-phase">
        <span>阶段一：重复识别</span>
        <el-progress
          :percentage="dupPercent"
          :status="phase === 'score' || phase === 'classify' || phase === 'done' ? 'success' : ''"
        />
        <span class="progress-detail">{{ dupProcessed }} / {{ dupTotal }}（成功 {{ dupSuccess }}，失败 {{ dupFail }}）</span>
      </div>
      <div v-if="phase !== 'fetching'" class="progress-phase">
        <span>阶段二：可靠性打分</span>
        <el-progress
          v-if="phase === 'score' || phase === 'classify' || phase === 'done'"
          :percentage="scorePercent"
          :status="phase === 'classify' || phase === 'done' ? 'success' : ''"
        />
        <el-progress v-else :percentage="0" status="warning" />
        <span class="progress-detail" v-if="phase === 'score' || phase === 'classify' || phase === 'done'">{{ scoreProcessed }} / {{ scoreTotal }}（成功 {{ scoreSuccess }}，失败 {{ scoreFail }}）</span>
        <span class="progress-detail" v-else>等待重复识别完成...</span>
      </div>
      <div v-if="phase === 'classify' || phase === 'done'" class="progress-phase">
        <span>阶段三：AI模块分类</span>
        <el-progress
          :percentage="classifyPercent"
          :status="phase === 'done' ? 'success' : ''"
        />
        <span class="progress-detail">{{ classifyProcessed }} / {{ classifyTotal }}（成功 {{ classifySuccess }}，失败 {{ classifyFail }}）</span>
      </div>
    </el-card>

    <!-- 手动打分进度条 -->
    <el-card v-if="scoring" class="progress-card">
      <div class="progress-title">
        <el-icon class="is-loading"><Loading /></el-icon>
        可靠性打分中（{{ scoringProcessed }} / {{ scoringTotal }}）
      </div>
      <el-progress
        :percentage="scoringPercent"
        :status="scoringPercent >= 100 ? 'success' : ''"
      />
      <span class="progress-detail">
        成功 {{ scoringSuccess }}，失败 {{ scoringFail }}
        <span v-if="scoringFail > 0">，失败项请在处理日志中查看</span>
      </span>
    </el-card>

    <!-- 需求列表 -->
    <el-card>
      <el-table
        :data="list"
        @selection-change="onSelectionChange"
        @sort-change="onSortChange"
        v-loading="loading"
        stripe
        :default-sort="defaultSort"
      >
        <el-table-column type="selection" width="40" />
        <el-table-column prop="story_id" label="需求ID" width="120" />
        <el-table-column label="标题" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">
            <el-link v-if="row.tapd_url" type="primary" :href="row.tapd_url" target="_blank">
              {{ row.title }}
            </el-link>
            <span v-else>{{ row.title }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="owner" label="处理人" width="120" show-overflow-tooltip />
        <el-table-column prop="tenant_version" label="版本" width="120" show-overflow-tooltip />
        <el-table-column prop="priority" label="重要程度" width="100" show-overflow-tooltip />
        <el-table-column label="可靠性分" width="150" sortable="custom" prop="reliability_score">
          <template #default="{ row }">
            <el-tag v-if="row.reliability_score !== null && row.reliability_score !== undefined" :type="scoreTagType(row.reliability_score)">
              {{ row.reliability_score }}
            </el-tag>
            <span v-else>-</span>
            <el-tooltip
              v-if="row.manual_score !== null && row.manual_score !== undefined"
              :content="`人工打分 ${row.manual_score}/10（${row.manual_score_by || '未知'}${row.manual_score_comment ? '：' + row.manual_score_comment : ''}）`"
            >
              <el-tag size="small" type="warning" effect="plain" style="margin-left: 4px">
                人工{{ row.manual_score }}
              </el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="AI打分(10)" width="100" sortable="custom" prop="ai_score_10">
          <template #default="{ row }">
            <el-tag v-if="row.ai_score_10 !== null && row.ai_score_10 !== undefined" 
              :type="row.ai_score_10 >= 6 ? 'success' : row.ai_score_10 >= 4 ? 'warning' : 'danger'"
              effect="dark"
              size="small"
              round>
              {{ row.ai_score_10 }}
            </el-tag>
            <span v-else style="color: #c0c4cc">-</span>
          </template>
        </el-table-column>
        <el-table-column label="提交时间" width="160" sortable="custom" prop="tapd_created">
          <template #default="{ row }">
            <span>{{ formatTime(row.tapd_created) || formatTime(row.created_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="更新时间" width="160" sortable="custom" prop="updated_at">
          <template #default="{ row }">
            <span>{{ formatTime(row.updated_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="重复需求" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.is_duplicate" type="danger" effect="plain" size="small">
              是
            </el-tag>
            <el-tag v-else type="success" effect="plain" size="small">否</el-tag>
            <el-tooltip v-if="row.is_duplicate && row.duplicate_with?.length" 
              :content="'疑似重复: ' + row.duplicate_with.join(', ')" placement="top">
              <el-icon style="margin-left: 2px; cursor: help; color: #909399"><InfoFilled /></el-icon>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="AI模块分类" width="140">
          <template #default="{ row }">
            <el-tag v-if="row.ai_module" size="small" effect="plain" type="info">
              {{ row.ai_module }}
            </el-tag>
            <span v-else style="color: #c0c4cc">-</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="320" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="showDetail(row)">详情</el-button>
            <el-button link type="warning" @click="openCommentEditor(row)"
              :disabled="!row.reliability_score || row.reliability_score >= 60">
              编辑评论
            </el-button>
            <el-button link type="primary" @click="writeCommentSingle(row)"
              :disabled="!row.reliability_score || row.reliability_score >= 60">
              写评论
            </el-button>
            <el-button link type="success" @click="openAddCase(row)">加入案例库</el-button>
            <el-button link type="warning" @click="openManualScore(row)">人工打分</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        layout="total, prev, pager, next"
        style="margin-top: 16px"
        @current-change="loadList"
      />
    </el-card>

    <!-- 详情抽屉 -->
    <el-drawer v-model="detailVisible" title="需求详情" size="50%">
      <div v-if="currentDetail" class="detail-content">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="需求ID">{{ currentDetail.story_id }}</el-descriptions-item>
          <el-descriptions-item label="标题">
            <el-link v-if="currentDetail.tapd_url" type="primary" :href="currentDetail.tapd_url" target="_blank">
              {{ currentDetail.title }}
            </el-link>
            <span v-else>{{ currentDetail.title }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="处理人">{{ currentDetail.owner || '-' }}</el-descriptions-item>
          <el-descriptions-item label="租户版本">{{ currentDetail.tenant_version || '-' }}</el-descriptions-item>
          <el-descriptions-item label="需求重要程度">{{ currentDetail.priority || '-' }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusTagType(currentDetail.status)">{{ statusLabel(currentDetail.status) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="可靠性分">{{ currentDetail.reliability_score ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="AI打分(10)">
            <el-tag v-if="currentDetail.ai_score_10 !== null && currentDetail.ai_score_10 !== undefined" 
              :type="currentDetail.ai_score_10 >= 6 ? 'success' : currentDetail.ai_score_10 >= 4 ? 'warning' : 'danger'"
              effect="dark" size="small" round>
              {{ currentDetail.ai_score_10 }}
            </el-tag>
            <span v-else>-</span>
          </el-descriptions-item>
          <el-descriptions-item label="AI打分理由">
            <el-tag v-if="currentDetail.ai_score_reason" size="small" effect="plain" type="info">
              {{ currentDetail.ai_score_reason }}
            </el-tag>
            <span v-else>-</span>
          </el-descriptions-item>
          <el-descriptions-item label="用户需求描述">
            <div class="desc-text">{{ currentDetail.description || '(空)' }}</div>
          </el-descriptions-item>
          <el-descriptions-item label="补充问题" v-if="currentDetail.supplemental_questions?.length">
            <ol>
              <li v-for="(q, i) in currentDetail.supplemental_questions" :key="i">{{ q }}</li>
            </ol>
          </el-descriptions-item>
          <el-descriptions-item label="重复需求">
            <template v-if="currentDetail.is_duplicate">
              <el-tag type="danger" size="small">是</el-tag>
              <div v-if="currentDetail.duplicate_detail?.length" style="margin-top: 4px">
                <div v-for="(d, i) in currentDetail.duplicate_detail" :key="i" class="dup-item">
                  <el-link type="primary" :href="tapdUrl(d.story_id)" target="_blank">
                    {{ d.story_id }} - {{ d.title || '(无标题)' }}
                  </el-link>
                  <el-tag size="small" style="margin-left: 8px">相似度 {{ (d.similarity * 100).toFixed(0) }}%</el-tag>
                </div>
              </div>
              <div v-else-if="currentDetail.duplicate_with?.length" style="margin-top: 4px">
                {{ currentDetail.duplicate_with.join(', ') }}
              </div>
              <div v-if="currentDetail.duplicate_tapd_value" style="margin-top: 4px; color: #909399; font-size: 12px">
                TAPD写回值: {{ currentDetail.duplicate_tapd_value }}
              </div>
            </template>
            <el-tag v-else type="success" size="small">否</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="AI模块分类">
            <el-tag v-if="currentDetail.ai_module" size="small" effect="plain" type="info">
              {{ currentDetail.ai_module }}
            </el-tag>
            <span v-else style="color: #c0c4cc">未分类</span>
          </el-descriptions-item>
        </el-descriptions>

        <!-- 处理时间线 -->
        <el-divider content-position="left">处理时间线</el-divider>
        <div v-loading="timelineLoading" class="timeline-container">
          <el-timeline v-if="timelineEvents.length">
            <el-timeline-item
              v-for="(ev, i) in timelineEvents"
              :key="i"
              :timestamp="ev.time"
              :type="timelineTagType(ev.level)"
              placement="top"
            >
              <div class="timeline-event">
                <el-tag :type="timelineTagType(ev.level)" size="small" effect="plain">{{ ev.type }}</el-tag>
                <span class="timeline-title">{{ ev.title }}</span>
                <div class="timeline-desc" v-if="ev.desc">{{ ev.desc }}</div>
              </div>
            </el-timeline-item>
          </el-timeline>
          <el-empty v-else description="暂无处理记录" :image-size="60" />
        </div>
      </div>
    </el-drawer>

    <!-- 评论编辑弹窗 -->
    <el-dialog
      v-model="commentEditorVisible"
      title="编辑待返回评论"
      width="1000px"
      :close-on-click-modal="false"
      top="5vh"
    >
      <div v-if="commentEditorRow" class="comment-editor">
        <el-descriptions :column="3" border size="small" style="margin-bottom: 12px">
          <el-descriptions-item label="需求ID">{{ commentEditorRow.story_id }}</el-descriptions-item>
          <el-descriptions-item label="可靠性分">
            <el-tag type="danger">{{ commentEditorRow.reliability_score }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="处理人">{{ commentEditorRow.owner || '-' }}</el-descriptions-item>
          <el-descriptions-item label="标题" :span="3">
            <el-link v-if="commentEditorRow.tapd_url" type="primary" :href="commentEditorRow.tapd_url" target="_blank">
              {{ commentEditorRow.title }}
            </el-link>
            <span v-else>{{ commentEditorRow.title }}</span>
          </el-descriptions-item>
        </el-descriptions>

        <el-row :gutter="16">
          <!-- 左侧：需求原文 + AI 评分详情 -->
          <el-col :span="12">
            <div class="editor-left-panel">
              <div class="panel-section">
                <div class="panel-title">需求原文</div>
                <div class="panel-content desc-text">{{ commentEditorRow.description || '(空)' }}</div>
              </div>

              <div class="panel-section" v-if="commentEditorRow.reliability_detail">
                <div class="panel-title">AI 评分详情</div>
                <div class="panel-content">
                  <div class="score-reason" v-if="commentEditorRow.reliability_detail.reason">
                    <el-tag type="warning" size="small">评估总结</el-tag>
                    <span style="margin-left: 8px">{{ commentEditorRow.reliability_detail.reason }}</span>
                  </div>
                  <div class="score-dims" v-if="commentEditorRow.reliability_detail.dimensions">
                    <div v-for="(d, key) in commentEditorRow.reliability_detail.dimensions" :key="key" class="score-dim-item">
                      <span class="dim-label">{{ dimLabelMap[key] || key }}</span>
                      <el-tag size="small" :type="scoreTagType(d.score)">{{ d.score }}</el-tag>
                      <span class="dim-comment">{{ d.comment }}</span>
                    </div>
                  </div>
                </div>
              </div>

              <div class="panel-section" v-if="commentEditorRow.supplemental_questions?.length">
                <div class="panel-title">AI 生成的补充问题</div>
                <div class="panel-content">
                  <ol class="questions-list">
                    <li v-for="(q, i) in commentEditorRow.supplemental_questions" :key="i">{{ q }}</li>
                  </ol>
                </div>
              </div>
            </div>
          </el-col>

          <!-- 右侧：评论编辑区 -->
          <el-col :span="12">
            <div class="editor-right-panel">
              <div class="comment-editor-toolbar">
                <el-button size="small" @click="resetComment" :loading="commentLoading">重新加载AI生成内容</el-button>
                <span class="comment-hint">可在此修改评论，写回TAPD</span>
              </div>
              <el-input
                v-model="commentContent"
                type="textarea"
                :rows="22"
                placeholder="评论内容"
                style="margin-top: 8px"
              />
            </div>
          </el-col>
        </el-row>
      </div>
      <template #footer>
        <el-button @click="commentEditorVisible = false">取消</el-button>
        <el-button type="primary" @click="submitCustomComment" :loading="commentSubmitting">
          写回评论
        </el-button>
      </template>
    </el-dialog>

    <!-- 按处理人拉取对话框 -->
    <el-dialog v-model="fetchByOwnerVisible" title="按处理人拉取需求" width="600px" :close-on-click-modal="!fetchingByOwner">
      <el-alert type="info" :closable="false" style="margin-bottom: 12px"
                :title="userStore.isAdmin ? '从 TAPD 拉取指定处理人名下的需求，自动进行重复识别和打分处理。' : '拉取您自己名下的需求，自动进行重复识别和打分处理。'" />
      <el-form :model="fetchByOwnerForm" label-width="100px">
        <el-form-item label="处理人">
          <el-select v-model="fetchByOwnerForm.owner" placeholder="选择处理人" filterable style="width: 240px" :disabled="fetchingByOwner || !userStore.isAdmin">
            <el-option v-for="o in ownerOptions" :key="o" :label="o" :value="o" />
          </el-select>
          <span v-if="!userStore.isAdmin" style="margin-left: 8px; color: #909399; font-size: 12px">仅能拉取自己名下的需求</span>
        </el-form-item>
        <el-form-item label="拉取数量">
          <el-input-number v-model="fetchByOwnerForm.limit" :min="1" :max="200" :disabled="fetchingByOwner" />
          <span style="margin-left: 8px; color: #909399; font-size: 12px">每条需求会自动进行重复识别和打分，数量过多会耗时较长</span>
        </el-form-item>
      </el-form>

      <!-- 拉取结果汇总 -->
      <el-result v-if="fetchByOwnerResult" :icon="fetchByOwnerResult.errored > 0 ? 'warning' : 'success'"
                 :title="fetchByOwnerResult.message" style="padding: 16px 0">
        <template #extra>
          <el-descriptions :column="3" border size="small">
            <el-descriptions-item label="共拉取">{{ fetchByOwnerResult.total }}</el-descriptions-item>
            <el-descriptions-item label="新增">
              <span style="color: #67c23a; font-weight: bold">{{ fetchByOwnerResult.new }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="更新">{{ fetchByOwnerResult.updated }}</el-descriptions-item>
          </el-descriptions>
        </template>
      </el-result>

      <template #footer>
        <el-button @click="fetchByOwnerVisible = false">关闭</el-button>
        <el-button type="primary" @click="confirmFetchByOwner" :loading="fetchingByOwner">
          {{ fetchingByOwner ? '正在拉取...' : '开始拉取' }}
        </el-button>
      </template>
    </el-dialog>

    <AddCaseLibraryDialog ref="addCaseDialog" />

    <!-- 人工打分弹窗（1-10 分，0.5 步进） -->
    <el-dialog v-model="manualScoreVisible" title="人工打分（修正 AI 评估）" width="560px">
      <div v-if="manualScoreRow" class="manual-score-panel">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="需求">
            {{ manualScoreRow.story_id }} · {{ manualScoreRow.title }}
          </el-descriptions-item>
          <el-descriptions-item label="AI 打分">
            <el-tag :type="scoreTagType(manualScoreRow.reliability_score)">{{ manualScoreRow.reliability_score }}</el-tag>
            <span class="hint" style="margin-left: 8px">{{ manualScoreRow.reliability_detail?.reason || '（无理由）' }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="需求描述">
            <div class="desc-text" style="max-height: 120px; overflow: auto">{{ manualScoreRow.description || '(空)' }}</div>
          </el-descriptions-item>
        </el-descriptions>
        <div class="manual-score-slider">
          <div class="manual-score-label">
            人工打分：<strong>{{ manualScoreValue }} / 10</strong>
            <span class="hint">（1 分=完全不合格，10 分=信息完整可直接评估）</span>
          </div>
          <el-slider v-model="manualScoreValue" :min="1" :max="10" :step="0.5" show-stops />
        </div>
        <el-input
          v-model="manualScoreComment"
          type="textarea"
          :rows="2"
          maxlength="500"
          show-word-limit
          placeholder="修正备注（可选）：说明与 AI 打分不一致的原因"
        />
      </div>
      <template #footer>
        <el-button @click="manualScoreVisible = false">取消</el-button>
        <el-button type="primary" :loading="manualScoreSaving" @click="submitManualScore">保存打分</el-button>
      </template>
    </el-dialog>

    <!-- 自动处理参数设置弹窗 -->
    <el-dialog v-model="autoSettingsVisible" title="自动处理设置" width="420px" :close-on-click-modal="false">
      <el-form label-width="120px" :model="autoSettingsForm">
        <el-form-item label="调度间隔（分钟）">
          <el-input-number v-model="autoSettingsForm.schedule_interval_minutes" :min="5" :max="1440" :step="5" />
          <div class="form-tip">每隔多少分钟检查一次是否需要自动处理</div>
        </el-form-item>
        <el-form-item label="批量大小">
          <el-input-number v-model="autoSettingsForm.batch_size" :min="1" :max="200" :step="10" />
          <div class="form-tip">每次自动处理最多拉取/处理的需求数量</div>
        </el-form-item>
        <el-form-item label="最大时长（分钟）">
          <el-input-number v-model="autoSettingsForm.max_processing_minutes" :min="5" :max="480" :step="5" />
          <div class="form-tip">单次自动处理超过此时长则自动终止</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="autoSettingsVisible = false">取消</el-button>
        <el-button type="primary" :loading="autoSettingsSaving" @click="saveAutoSettings">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, onActivated } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  Download, Check, ChatDotRound, Promotion, CopyDocument, Loading, MoreFilled, Close, UploadFilled, DataLine, DocumentCopy, EditPen, Setting
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/api'
import { useUserStore } from '@/stores/user'
import PageTutorial from '@/components/PageTutorial.vue'
import AddCaseLibraryDialog from '@/components/AddCaseLibraryDialog.vue'
import { tutorials } from '@/tutorials'

const userStore = useUserStore()
const automation = reactive({ auto_flow_enabled: false, requirements_enabled: false, schedule_interval_minutes: 30, batch_size: 50, max_processing_minutes: 60 })
const automationLoading = ref(false)
const autoStatusTimer = ref(null)   // 自动处理心跳轮询 timer
const autoSettingsVisible = ref(false)
const autoSettingsSaving = ref(false)
const autoSettingsForm = reactive({ schedule_interval_minutes: 30, batch_size: 50, max_processing_minutes: 60 })
const router = useRouter()
const route = useRoute()

const list = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const keyword = ref('')
const filterStatus = ref('')
const filterOwner = ref('')
const onlyFail = ref(false)
const loading = ref(false)
const selected = ref([])

// 排序状态
const sortProp = ref('tapd_created')
const sortOrder = ref('descending')  // ascending / descending / null
const defaultSort = ref({ prop: 'tapd_created', order: 'descending' })

const ownerOptions = ref([])

// 评论编辑相关状态
const commentEditorVisible = ref(false)
const commentEditorRow = ref(null)
const commentContent = ref('')
const commentLoading = ref(false)
const commentSubmitting = ref(false)

// 评分维度中文映射
const dimLabelMap = {
  completeness: '信息完整度(30)',
  clarity: '描述清晰度(30)',
  feasibility: '可实现性(20)',
  business_value: '业务价值(20)',
}

// 时间线相关状态
const timelineEvents = ref([])
const timelineLoading = ref(false)

const stats = ref({ total: 0, pending: 0, duplicate: 0, avg_score: 0 })

const fetching = ref(false)
const scoring = ref(false)
const scoringTotal = ref(0)
const scoringProcessed = ref(0)
const scoringSuccess = ref(0)
const scoringFail = ref(0)
const taskSummary = ref(null)

// 自动处理进度状态
const processing = ref(false)
const phase = ref('')
const fetchInfo = reactive({ total: 0, newCount: 0, updatedCount: 0 })
const dupTotal = ref(0)
const dupProcessed = ref(0)
const dupSuccess = ref(0)
const dupFail = ref(0)
const scoreTotal = ref(0)
const scoreProcessed = ref(0)
const scoreSuccess = ref(0)
const scoreFail = ref(0)
const classifyTotal = ref(0)
const classifyProcessed = ref(0)
const classifySuccess = ref(0)
const classifyFail = ref(0)

const dupPercent = computed(() => {
  if (!dupTotal.value) return 0
  return Math.round((dupProcessed.value / dupTotal.value) * 100)
})
const scorePercent = computed(() => {
  if (!scoreTotal.value) return 0
  return Math.round((scoreProcessed.value / scoreTotal.value) * 100)
})
const classifyPercent = computed(() => {
  if (!classifyTotal.value) return 0
  return Math.round((classifyProcessed.value / classifyTotal.value) * 100)
})
const scoringPercent = computed(() => {
  if (!scoringTotal.value) return 0
  return Math.round((scoringProcessed.value / scoringTotal.value) * 100)
})

const detailVisible = ref(false)
const currentDetail = ref(null)
const addCaseDialog = ref(null)

let statsTimer = null
let processTimer = null

async function loadList() {
  loading.value = true
  try {
    // 后端排序字段映射
    const orderFieldMap = {
      'reliability_score': 'score',
      'tapd_created': 'tapd_created',
      'updated_at': 'updated',
      'created_at': 'created',
    }
    const orderDirMap = {
      'ascending': 'asc',
      'descending': 'desc',
    }
    const data = await api.get('/user-requirements/list', {
      params: {
        page: page.value,
        page_size: pageSize.value,
        status: filterStatus.value || undefined,
        keyword: keyword.value || undefined,
        owner: filterOwner.value || undefined,
        max_score: onlyFail.value ? 60 : undefined,
        order_by: orderFieldMap[sortProp.value] || undefined,
        order: orderDirMap[sortOrder.value] || undefined,
      }
    })
    list.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function onSortChange({ prop, order }) {
  sortProp.value = prop
  sortOrder.value = order
  page.value = 1
  loadList()
}

function formatTime(t) {
  if (!t) return ''
  try {
    const d = new Date(t)
    if (isNaN(d.getTime())) return t
    const pad = (n) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  } catch {
    return t
  }
}

const hasActiveFilters = computed(() => Boolean(keyword.value || filterStatus.value || filterOwner.value || onlyFail.value))

function clearFilter(type) {
  if (type === 'keyword') keyword.value = ''
  if (type === 'status') filterStatus.value = ''
  if (type === 'owner') filterOwner.value = ''
  if (type === 'onlyFail') onlyFail.value = false
  page.value = 1
  loadList()
}

function clearAllFilters() {
  keyword.value = ''
  filterStatus.value = ''
  filterOwner.value = ''
  onlyFail.value = false
  page.value = 1
  loadList()
}

function applyRouteFilters() {
  if (route.query.status) filterStatus.value = String(route.query.status)
  if (route.query.low_score === '1') onlyFail.value = true
}

function toggleOnlyFail() {
  onlyFail.value = !onlyFail.value
  page.value = 1
  loadList()
}

async function loadStats() {
  try {
    stats.value = await api.get('/user-requirements/statistics')
  } catch (e) {
    // 忽略
  }
}

async function loadOwners() {
  try {
    const data = await api.get('/user-requirements/owners')
    ownerOptions.value = data.owners || []
  } catch (e) {
    // 忽略
  }
}

function onSelectionChange(rows) {
  selected.value = rows
}

function tapdUrl(storyId) {
  const ws = list.value[0]?.workspace_id || currentDetail.value?.workspace_id
  return ws ? `https://www.tapd.cn/${ws}/prong/stories/view/${storyId}` : '#'
}

async function loadAutomation() {
  try {
    const data = await api.get('/automation/status')
    Object.assign(automation, data)
    // 若自动处理开启，启动心跳轮询感知任务状态
    if (data.requirements_enabled) {
      startAutoStatusPolling()
      // 若后端报告有正在运行的任务，且前端当前未在轮询，则自动接入进度展示
      if (data.current_job_id && (data.current_job_status === 'running' || data.current_job_status === 'pending') && !processTimer) {
        processing.value = true
        const r = data.current_job_result || {}
        if (r.phase) phase.value = r.phase
        startProcessPolling(data.current_job_id)
      }
    } else {
      stopAutoStatusPolling()
    }
  } catch (e) { /* handled globally */ }
}

function startAutoStatusPolling(fastMode = false) {
  // fastMode: 刚开启时用 1s 间隔快速等待任务出现，出现后自动降为 10s 心跳
  if (autoStatusTimer.value) clearInterval(autoStatusTimer.value)
  let interval = fastMode ? 1000 : 10000
  let fastCount = 0
  const poll = async () => {
    try {
      const data = await api.get('/automation/status')
      Object.assign(automation, data)
      // 新任务开始：自动接入进度展示
      if (data.current_job_id && (data.current_job_status === 'running' || data.current_job_status === 'pending') && !processTimer) {
        processing.value = true
        const r = data.current_job_result || {}
        if (r.phase) phase.value = r.phase
        startProcessPolling(data.current_job_id)
        // 任务已接管，降回 10s 心跳
        if (interval === 1000) {
          clearInterval(autoStatusTimer.value)
          autoStatusTimer.value = setInterval(poll, 10000)
        }
      } else if (fastMode && interval === 1000) {
        // 快速模式最多等 30s（30次），还未出现任务则降回 10s
        fastCount++
        if (fastCount >= 30) {
          clearInterval(autoStatusTimer.value)
          autoStatusTimer.value = setInterval(poll, 10000)
        }
      }
    } catch (e) { /* ignore */ }
  }
  autoStatusTimer.value = setInterval(poll, interval)
}

function stopAutoStatusPolling() {
  if (autoStatusTimer.value) {
    clearInterval(autoStatusTimer.value)
    autoStatusTimer.value = null
  }
}

function formatRelTime(isoStr) {
  if (!isoStr) return ''
  const diff = Math.floor((Date.now() - new Date(isoStr).getTime()) / 1000)
  if (diff < 60) return `${diff}秒前`
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
  return `${Math.floor(diff / 86400)}天前`
}

async function toggleAutomation() {
  if (!automation.auto_flow_enabled) {
    ElMessage.info('请先在“系统管理 - 自动流程设置”中确认开启自动流程功能')
    router.push({ name: 'settings' })
    return
  }
  automationLoading.value = true
  try {
    const enabled = !automation.requirements_enabled
    const data = await api.post('/automation/modules/requirements', { enabled })
    Object.assign(automation, data)
    if (enabled) {
      ElMessage.success(`${data.message}`)
      // 立刻显示进度面板，用户看到有响应；快速轮询等待后台 job_id 出现
      processing.value = true
      phase.value = 'fetching'
      dupTotal.value = 0; dupProcessed.value = 0; dupSuccess.value = 0; dupFail.value = 0
      scoreTotal.value = 0; scoreProcessed.value = 0; scoreSuccess.value = 0; scoreFail.value = 0
      classifyTotal.value = 0; classifyProcessed.value = 0; classifySuccess.value = 0; classifyFail.value = 0
      fetchInfo.total = 0; fetchInfo.newCount = 0; fetchInfo.updatedCount = 0
      startAutoStatusPolling(true)  // fastMode: 每1秒轮询直到任务出现
    } else {
      ElMessage.info(data.message)
      stopAutoStatusPolling()
      processing.value = false
    }
  } finally {
    automationLoading.value = false
  }
}

function openAutoSettings() {
  autoSettingsForm.schedule_interval_minutes = automation.schedule_interval_minutes || 30
  autoSettingsForm.batch_size = automation.batch_size || 50
  autoSettingsForm.max_processing_minutes = automation.max_processing_minutes || 60
  autoSettingsVisible.value = true
}

async function saveAutoSettings() {
  autoSettingsSaving.value = true
  try {
    const data = await api.post('/automation/settings', autoSettingsForm)
    Object.assign(automation, data)
    ElMessage.success(data.message || '设置已保存')
    autoSettingsVisible.value = false
  } catch (e) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    autoSettingsSaving.value = false
  }
}

async function handleFetch() {
  // 立即显示进度面板（不等 API 返回）
  processing.value = true
  phase.value = 'fetching'
  dupTotal.value = 0
  dupProcessed.value = 0
  dupSuccess.value = 0
  dupFail.value = 0
  scoreTotal.value = 0
  scoreProcessed.value = 0
  scoreSuccess.value = 0
  scoreFail.value = 0
  fetchInfo.total = 0
  fetchInfo.newCount = 0
  fetchInfo.updatedCount = 0
  fetching.value = true
  try {
    const data = await api.get('/user-requirements/fetch')
    taskSummary.value = {
      type: 'info',
      title: '需求拉取已启动',
      detail: '正在后台处理中，请查看下方进度面板',
    }
    if (data.job_id) {
      startProcessPolling(data.job_id)
    } else {
      // 无新需求时直接关闭进度面板
      processing.value = false
      taskSummary.value = { type: 'info', title: '无新增需求', detail: '' }
      await loadList()
      await loadStats()
      await loadOwners()
    }
  } finally {
    fetching.value = false
  }
}

// 按处理人拉取
const fetchByOwnerVisible = ref(false)
const fetchByOwnerForm = reactive({ owner: '', limit: 50 })
const fetchingByOwner = ref(false)
const fetchByOwnerResult = ref(null)

function openFetchByOwner() {
  // 操作员默认锁定为自己的显示名，管理员可选
  fetchByOwnerForm.owner = userStore.isAdmin ? '' : userStore.displayName
  fetchByOwnerForm.limit = 50
  fetchByOwnerResult.value = null
  fetchByOwnerVisible.value = true
}

async function confirmFetchByOwner() {
  if (!fetchByOwnerForm.owner) {
    ElMessage.warning('请选择处理人')
    return
  }
  fetchingByOwner.value = true
  fetchByOwnerResult.value = null
  // 立即显示进度面板
  processing.value = true
  phase.value = 'fetching'
  dupTotal.value = 0; dupProcessed.value = 0; dupSuccess.value = 0; dupFail.value = 0
  scoreTotal.value = 0; scoreProcessed.value = 0; scoreSuccess.value = 0; scoreFail.value = 0
  fetchInfo.total = 0; fetchInfo.newCount = 0; fetchInfo.updatedCount = 0
  try {
    const data = await api.get('/user-requirements/fetch', {
      params: { owner: fetchByOwnerForm.owner, limit: fetchByOwnerForm.limit },
    }, { timeout: 300000 })
    fetchByOwnerResult.value = {
      ...data,
      errored: 0,
      message: `处理人 ${fetchByOwnerForm.owner}：任务已启动，请查看进度面板`,
    }
    await loadOwners()
    // 启动自动处理进度轮询
    if (data.job_id) {
      startProcessPolling(data.job_id)
    }
  } catch (e) {
    ElMessage.error('拉取失败：' + (e.response?.data?.detail || e.message))
  } finally {
    fetchingByOwner.value = false
  }
}

function startProcessPolling(jobId) {
  processing.value = true
  // phase 由调用方设置（handleFetch 设为 'fetching'），轮询响应会更新
  dupTotal.value = 0
  dupProcessed.value = 0
  dupSuccess.value = 0
  dupFail.value = 0
  scoreTotal.value = 0
  scoreProcessed.value = 0
  scoreSuccess.value = 0
  scoreFail.value = 0

  let count = 0
  processTimer = setInterval(async () => {
    count++
    try {
      const data = await api.get(`/user-requirements/jobs/${jobId}/result`)
      const r = data.result || {}
      if (r.phase) phase.value = r.phase
      if (r.duplicate_total !== undefined) dupTotal.value = r.duplicate_total
      if (r.duplicate_processed !== undefined) dupProcessed.value = r.duplicate_processed
      if (r.duplicate_succeeded !== undefined) dupSuccess.value = r.duplicate_succeeded
      if (r.duplicate_failed !== undefined) dupFail.value = r.duplicate_failed
      if (r.score_total !== undefined) scoreTotal.value = r.score_total
      if (r.score_processed !== undefined) scoreProcessed.value = r.score_processed
      if (r.score_succeeded !== undefined) scoreSuccess.value = r.score_succeeded
      if (r.score_failed !== undefined) scoreFail.value = r.score_failed
      if (r.classify_total !== undefined) classifyTotal.value = r.classify_total
      if (r.classify_processed !== undefined) classifyProcessed.value = r.classify_processed
      if (r.classify_succeeded !== undefined) classifySuccess.value = r.classify_succeeded
      if (r.classify_failed !== undefined) classifyFail.value = r.classify_failed
      // 更新拉取阶段统计
      if (r.fetch_total !== undefined) fetchInfo.total = r.fetch_total
      if (r.fetch_new !== undefined) fetchInfo.newCount = r.fetch_new
      if (r.fetch_updated !== undefined) fetchInfo.updatedCount = r.fetch_updated

      if (data.status === 'completed' || data.status === 'failed' || data.status === 'interrupted') {
        clearInterval(processTimer)
        processTimer = null
        processing.value = false
        const failed = dupFail.value + scoreFail.value + classifyFail.value
        if (data.status === 'completed') {
          // 没有新增/待处理需求时，直接提示无新需求
          if (fetchInfo.total > 0 && fetchInfo.newCount === 0 && dupTotal.value === 0 && scoreTotal.value === 0) {
            taskSummary.value = {
              type: 'info',
              title: '无新需求',
              detail: `从 TAPD 拉取 ${fetchInfo.total} 条，均已处理过，无新增待处理需求。`,
              failed: 0,
            }
            ElMessage.info(`已同步：拉取 ${fetchInfo.total} 条，均已处理，无新需求`)
          } else {
          taskSummary.value = {
            type: failed ? 'warning' : 'success',
            title: '自动处理完成',
            detail: `拉取 ${fetchInfo.total} 条（新增 ${fetchInfo.newCount}）；重复识别 ${dupSuccess.value}/${dupTotal.value}；打分 ${scoreSuccess.value}/${scoreTotal.value}；分类 ${classifySuccess.value}/${classifyTotal.value}。`,
            failed,
          }
          ElMessage.success(`处理完成：拉取 ${fetchInfo.total} 条，重复识别 ${dupSuccess.value}/${dupTotal.value}，打分 ${scoreSuccess.value}/${scoreTotal.value}，分类 ${classifySuccess.value}/${classifyTotal.value}`)
          }
          // 刷新列表和统计
          await loadList()
          await loadStats()
        } else {
          taskSummary.value = {
            type: 'warning',
            title: '自动处理未正常完成',
            detail: `任务状态：${data.status}；重复识别已完成 ${dupProcessed.value}/${dupTotal.value}，打分已完成 ${scoreProcessed.value}/${scoreTotal.value}。`,
            failed: true,
          }
          ElMessage.warning(`任务状态：${data.status}`)
        }
        await loadList()
        await loadStats()
      }
    } catch (e) {
      clearInterval(processTimer)
      processTimer = null
      processing.value = false
    }
    if (count > 900) {
      clearInterval(processTimer)
      processTimer = null
      processing.value = false
    }
  }, 2000)
}

async function handleScore() {
  const ids = selected.value.map(r => r.id)
  if (!ids.length) {
    ElMessage.warning('请先选择需求')
    return
  }
  scoring.value = true
  scoringTotal.value = ids.length
  scoringProcessed.value = 0
  scoringSuccess.value = 0
  scoringFail.value = 0
  try {
    const data = await api.post('/user-requirements/score', { record_ids: ids })
    ElMessage.success(`打分任务已启动，共 ${data.total} 条`)
    pollScoreJob(data.job_id)
  } catch (e) {
    scoring.value = false
    ElMessage.error('启动打分失败：' + (e.response?.data?.detail || e.message))
  }
}

function pollScoreJob(jobId) {
  let count = 0
  const timer = setInterval(async () => {
    count++
    try {
      const data = await api.get(`/user-requirements/jobs/${jobId}/result`)
      if (data.total !== undefined) scoringTotal.value = data.total
      if (data.processed !== undefined) scoringProcessed.value = data.processed
      if (data.succeeded !== undefined) scoringSuccess.value = data.succeeded
      if (data.failed !== undefined) scoringFail.value = data.failed

      if (data.status === 'completed' || data.status === 'failed' || data.status === 'interrupted') {
        clearInterval(timer)
        scoring.value = false
        const failed = scoringFail.value
        if (data.status === 'completed') {
          taskSummary.value = {
            type: failed ? 'warning' : 'success',
            title: '打分任务完成',
            detail: `成功 ${scoringSuccess.value} 条，失败 ${scoringFail.value} 条。`,
            failed,
          }
          ElMessage.success(`打分完成：成功 ${scoringSuccess.value}，失败 ${scoringFail.value}`)
        } else {
          taskSummary.value = {
            type: 'warning',
            title: '打分任务未正常完成',
            detail: `任务状态：${data.status}；已完成 ${scoringProcessed.value}/${scoringTotal.value}。`,
            failed: true,
          }
          ElMessage.warning(`打分任务状态：${data.status}`)
        }
        await loadList()
        await loadStats()
      }
    } catch (e) {
      clearInterval(timer)
      scoring.value = false
    }
    if (count > 1200) {
      clearInterval(timer)
      scoring.value = false
    }
  }, 1500)
}

async function handleChangeTapdStatus() {
  const ids = selected.value.map(r => r.id)
  if (!ids.length) {
    ElMessage.warning('请先选择需求')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认将选中的 ${ids.length} 条需求的 TAPD 状态更改为「产品设计中」？`,
      '更改 TAPD 状态',
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    const data = await api.post('/user-requirements/change-tapd-status', { record_ids: ids })
    if (data.success) {
      ElMessage.success(data.message)
    } else {
      ElMessage.warning(data.message)
    }
    await loadList()
    await loadStats()
  } catch (e) {
    // 错误已处理
  }
}

async function handleMarkDuplicate() {
  const ids = selected.value.map(r => r.id)
  if (!ids.length) {
    ElMessage.warning('请先选择需求')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认将选中的 ${ids.length} 条需求标记为重复？\n标记后将自动转入「重复需求处理」页面，按确认重复流程处理（写回 TAPD 状态为重复需求）。`,
      '标记为重复',
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    const data = await api.post('/user-requirements/mark-duplicate', { record_ids: ids })
    ElMessage.success(data.message)
    // 跳转到重复需求处理页面
    router.push({ name: 'duplicate-requirements' })
  } catch (e) {
    // 错误已处理
  }
}

async function writeCommentSingle(row) {
  // 通过的需求不写回评论
  if (row.reliability_score >= 60) {
    ElMessage.info('该需求已通过评估，无需写回评论')
    return
  }
  try {
    await ElMessageBox.confirm(`确认为需求 ${row.story_id} 写回可靠性评论？`, '确认')
    await api.post(`/user-requirements/${row.story_id}/write-comment`, null, {
      params: { action: 'reliability_comment' }
    })
    ElMessage.success('评论已写回')
    await loadList()
  } catch (e) {
    // 取消或错误
  }
}

async function handleWriteComment() {
  // 仅对未达标的需求写回评论
  const targets = selected.value.filter(r => r.reliability_score && r.reliability_score < 60)
  const skipped = selected.value.length - targets.length
  if (!targets.length) {
    ElMessage.warning('选中需求中没有未达标的需写回评论')
    return
  }
  const skipHint = skipped > 0 ? `\n（已跳过 ${skipped} 条已通过评估的需求）` : ''
  try {
    await ElMessageBox.confirm(`确认为选中的 ${targets.length} 条未达标需求写回评论？${skipHint}`, '确认')
    let success = 0
    for (const row of targets) {
      try {
        await api.post(`/user-requirements/${row.story_id}/write-comment`, null, {
          params: { action: 'reliability_comment' }
        })
        success++
      } catch (e) {
        // 单条失败继续
      }
    }
    ElMessage.success(`批量写回完成：成功 ${success}/${targets.length}`)
    await loadList()
  } catch (e) {
    // 取消
  }
}

async function handleWritebackScore() {
  // 批量写回AI打分到TAPD
  const targets = selected.value.filter(r => r.reliability_score !== null && r.reliability_score !== undefined)
  if (!targets.length) {
    ElMessage.warning('选中需求中暂无已打分的记录')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认将 ${targets.length} 条已打分需求的AI分数（10分制）写回TAPD？\n此操作会在每条需求的变更历史中留下一条记录。`,
      '写回AI打分',
      { type: 'warning' }
    )
    const ids = targets.map(r => r.story_id)
    try {
      const data = await api.post('/user-requirements/batch-writeback-score', ids)
      ElMessage.success(`写回完成：成功 ${data.success} 条，失败 ${data.failed} 条`)
    } catch (e) {
      console.error('批量写回失败：', e)
    }
  } catch {
    // 取消
  }
}

async function handleWritebackReason() {
  // 批量写回AI打分理由到TAPD
  const targets = selected.value.filter(r => r.reliability_score !== null && r.reliability_score !== undefined)
  if (!targets.length) {
    ElMessage.warning('选中需求中暂无已打分的记录')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认将 ${targets.length} 条已打分需求的AI打分理由写回TAPD？\n此操作会在每条需求的变更历史中留下一条记录。`,
      '写回打分理由',
      { type: 'warning' }
    )
    const ids = targets.map(r => r.story_id)
    try {
      const data = await api.post('/user-requirements/batch-writeback-reason', ids)
      ElMessage.success(`写回完成：成功 ${data.success} 条，失败 ${data.failed} 条`)
    } catch (e) {
      console.error('批量写回理由失败：', e)
    }
  } catch {
    // 取消
  }
}

async function handleWritebackClassification() {
  // 批量写回AI模块分类到TAPD
  const targets = selected.value.filter(r => r.ai_module)
  if (!targets.length) {
    ElMessage.warning('选中需求中暂无已分类的记录')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认将 ${targets.length} 条已分类需求的AI模块分类写回TAPD？\n此操作会在每条需求的变更历史中留下一条记录。`,
      '写回AI分类',
      { type: 'warning' }
    )
    const ids = targets.map(r => r.story_id)
    try {
      const data = await api.post('/user-requirements/batch-writeback-classification', ids)
      ElMessage.success(`写回完成：成功 ${data.success} 条，失败 ${data.failed} 条`)
    } catch (e) {
      console.error('批量写回分类失败：', e)
    }
  } catch {
    // 取消
  }
}

async function handleWritebackDuplicate() {
  // 批量写回重复需求到TAPD
  const targets = selected.value
  if (!targets.length) {
    ElMessage.warning('请先选择需求')
    return
  }
  const dupCount = targets.filter(r => r.is_duplicate).length
  const normalCount = targets.length - dupCount
  try {
    await ElMessageBox.confirm(
      `确认将选中的 ${targets.length} 条需求的重复状态写回TAPD？\n其中 ${dupCount} 条为重复，${normalCount} 条为正常。\n此操作会在每条需求的变更历史中留下一条记录。`,
      '写回重复需求',
      { type: 'warning' }
    )
    const ids = targets.map(r => r.story_id)
    try {
      const data = await api.post('/user-requirements/batch-writeback-duplicate', ids)
      ElMessage.success(`写回完成：成功 ${data.success} 条，失败 ${data.failed} 条`)
    } catch (e) {
      console.error('批量写回重复需求失败：', e)
    }
  } catch {
    // 取消
  }
}

function showDetail(row) {
  currentDetail.value = row
  detailVisible.value = true
  loadTimeline(row.story_id)
}

// 将当前需求作为「误判案例」加入案例库（预填 AI 可靠性打分结果）
// ---------- 人工打分（1-10 分，0.5 步进） ----------
const manualScoreVisible = ref(false)
const manualScoreSaving = ref(false)
const manualScoreRow = ref(null)
const manualScoreValue = ref(7)
const manualScoreComment = ref('')

function openManualScore(row) {
  manualScoreRow.value = row
  manualScoreValue.value = row.manual_score ?? (row.reliability_score != null ? Math.round(row.reliability_score / 5) / 2 : 7)
  manualScoreComment.value = row.manual_score_comment || ''
  manualScoreVisible.value = true
}

async function submitManualScore() {
  if (!manualScoreRow.value) return
  const row = manualScoreRow.value
  manualScoreSaving.value = true
  try {
    await api.post(`/user-requirements/record/${row.id}/manual-score`, {
      score: manualScoreValue.value,
      comment: manualScoreComment.value,
    })
    ElMessage.success(`人工打分已保存：${manualScoreValue.value}/10`)
    manualScoreVisible.value = false
    manualScoreRow.value = null
    loadList()

    // 人工与 AI 差异大（≥2 分，即 20 百分制）时引导加入案例库，供后续优化
    if (row.reliability_score != null && Math.abs(manualScoreValue.value * 10 - row.reliability_score) >= 20) {
      try {
        await ElMessageBox.confirm(
          `人工打分 ${manualScoreValue.value}/10 与 AI 打分 ${row.reliability_score} 差异较大，是否将本条加入案例库，用于后续提示词优化？`,
          '建议加入案例库',
          { confirmButtonText: '加入案例库', cancelButtonText: '暂不', type: 'warning' },
        )
        openAddCase(row)
      } catch (e) { /* 用户选择暂不 */ }
    }
  } catch (e) {
    // 拦截器已提示
  } finally {
    manualScoreSaving.value = false
  }
}

function openAddCase(row) {
  const aiResult = {
    total_score: row.reliability_score,
    pass: row.reliability_score != null ? row.reliability_score >= 60 : null,
    reason: row.reliability_detail?.reason ?? null,
    dimensions: row.reliability_detail?.dimensions ?? null,
    supplemental_questions: row.supplemental_questions ?? null,
  }
  addCaseDialog.value?.open({
    moduleKey: 'reliability',
    requirement_title: row.title || '',
    requirement_desc: row.description || '',
    aiResult,
    is_mismatch: true,
  })
}

async function loadTimeline(storyId) {
  timelineLoading.value = true
  timelineEvents.value = []
  try {
    const data = await api.get(`/user-requirements/${storyId}/timeline`)
    timelineEvents.value = data.events || []
  } catch (e) {
    // 忽略
  } finally {
    timelineLoading.value = false
  }
}

function timelineTagType(level) {
  const map = { success: 'success', warning: 'warning', error: 'danger', info: 'info' }
  return map[level] || 'info'
}

// ---------- 评论编辑相关 ----------
async function openCommentEditor(row) {
  if (!row.reliability_score || row.reliability_score >= 60) {
    ElMessage.info('该需求已通过评估，无需写回评论')
    return
  }
  commentEditorRow.value = row
  commentContent.value = ''
  commentEditorVisible.value = true
  await loadCommentPreview(row)
}

async function loadCommentPreview(row) {
  commentLoading.value = true
  try {
    const data = await api.get(`/user-requirements/${row.story_id}/comment-preview`, {
      params: { action: 'reliability_comment' }
    })
    commentContent.value = data.content
  } catch (e) {
    // 错误已处理
  } finally {
    commentLoading.value = false
  }
}

function resetComment() {
  if (commentEditorRow.value) {
    loadCommentPreview(commentEditorRow.value)
  }
}

async function submitCustomComment() {
  if (!commentContent.value.trim()) {
    ElMessage.warning('评论内容不能为空')
    return
  }
  const row = commentEditorRow.value
  try {
    await ElMessageBox.confirm(
      `确认将修改后的评论写回到需求 ${row.story_id} 的 TAPD 评论？`,
      '确认写回',
      { type: 'warning' }
    )
  } catch {
    return
  }
  commentSubmitting.value = true
  try {
    await api.post(`/user-requirements/${row.story_id}/write-comment-custom`, {
      content: commentContent.value,
      action: 'reliability_comment',
    })
    ElMessage.success('评论已写回')
    commentEditorVisible.value = false
    await loadList()
  } catch (e) {
    // 错误已处理
  } finally {
    commentSubmitting.value = false
  }
}

function scoreTagType(score) {
  if (score >= 80) return 'success'
  if (score >= 60) return ''
  if (score >= 40) return 'warning'
  return 'danger'
}

function statusTagType(status) {
  return { pending: 'info', scored: '', duplicate: 'danger', confirmed: 'success', rejected: 'warning' }[status] || ''
}

function statusLabel(status) {
  return { pending: '待评估', scored: '已打分', duplicate: '重复', confirmed: '已确认', rejected: '已拒绝' }[status] || status
}

onMounted(() => {
  applyRouteFilters()
  loadList()
  loadStats()
  loadOwners()
  loadAutomation()
  statsTimer = setInterval(loadStats, 10000)
})

// keep-alive 下切换回来时刷新列表（进度条状态由组件保留，无需重置）
onActivated(() => {
  applyRouteFilters()
  loadList()
  loadStats()
  loadOwners()
  loadAutomation()
})

onUnmounted(() => {
  if (statsTimer) clearInterval(statsTimer)
  if (processTimer) clearInterval(processTimer)
  stopAutoStatusPolling()
})
</script>

<style scoped>
.stat-row {
  margin-bottom: 18px;
}
.stat-card :deep(.el-card__body) {
  padding: 16px 18px;
}
.action-card {
  margin-bottom: 14px;
}
.action-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.filter-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.action-label {
  color: #606266;
  font-size: 14px;
}
.view-context {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin: -4px 0 12px;
  padding: 10px 12px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  background: #fff;
}
.view-context-title {
  font-size: 13px;
  color: #606266;
  font-weight: 600;
}
.view-context-count {
  margin-left: auto;
  color: #909399;
  font-size: 13px;
}
.task-summary {
  margin-bottom: 12px;
}
.task-summary-hint {
  margin-top: 4px;
  font-size: 12px;
  color: #909399;
}
.progress-card {
  margin-bottom: 16px;
}
.progress-title {
  font-weight: 600;
  margin-bottom: 12px;
  color: #409eff;
  display: flex;
  align-items: center;
  gap: 6px;
}
.progress-phase {
  margin-bottom: 16px;
}
.progress-phase span:first-child {
  display: block;
  margin-bottom: 6px;
  color: #303133;
  font-size: 13px;
}
.progress-detail {
  display: block;
  margin-top: 4px;
  color: #909399;
  font-size: 12px;
}
.detail-content {
  padding: 0 8px;
}
.desc-text {
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 300px;
  overflow-y: auto;
}
.dup-item {
  margin-bottom: 6px;
}
.comment-editor-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 8px;
}
.comment-hint {
  color: #909399;
  font-size: 12px;
}
.editor-left-panel {
  border-right: 1px solid #e4e7ed;
  padding-right: 8px;
  max-height: 560px;
  overflow-y: auto;
}
.editor-right-panel {
  padding-left: 8px;
}
.panel-section {
  margin-bottom: 14px;
}
.panel-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 6px;
  padding-left: 8px;
  border-left: 3px solid #409eff;
}
.panel-content {
  font-size: 12px;
  color: #606266;
  line-height: 1.6;
}
.panel-content.desc-text {
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 180px;
  overflow-y: auto;
  background: #f5f7fa;
  padding: 8px;
  border-radius: 4px;
}
.score-reason {
  margin-bottom: 8px;
  font-size: 12px;
  line-height: 1.6;
}
.score-dims {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.score-dim-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  padding: 4px 0;
  border-bottom: 1px dashed #ebeef5;
}
.dim-label {
  min-width: 130px;
  color: #303133;
  font-weight: 500;
}
.dim-comment {
  color: #909399;
  flex: 1;
}
.questions-list {
  padding-left: 20px;
  margin: 0;
}
.questions-list li {
  margin-bottom: 4px;
}
.timeline-container {
  max-height: 400px;
  overflow-y: auto;
  padding: 8px 0;
}
.timeline-event {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.timeline-title {
  font-size: 13px;
  color: #303133;
  margin-left: 8px;
}
.timeline-desc {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}
.auto-config-hint {
  font-size: 12px;
  color: #909399;
  margin-left: 4px;
}
.form-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}
</style>
