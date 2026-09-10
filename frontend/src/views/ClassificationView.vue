<template>
  <div class="page-container">
    <header class="workspace-page-header">
      <div>
        <h1 class="workspace-page-title">需求分类</h1>
        <p class="workspace-page-description">结合业务知识库自动识别需求模块，提供处理人建议与可控的 TAPD 写回能力。</p>
      </div>
      <div class="workspace-page-meta">
        <span>分类范围</span>
        <el-tag size="small" effect="plain">{{ userStore.isAdmin ? '全部可见需求' : '我的需求' }}</el-tag>
        <PageTutorial :tutorial="tutorials['classification']" />
      </div>
    </header>
    <el-tabs v-model="activeTab" @tab-change="onTabChange" class="workspace-tabs">
      <!-- ============ Tab 1: 分类处理 ============ -->
      <el-tab-pane label="分类处理" name="process">
        <!-- 机器人状态卡片 -->
        <el-row :gutter="12" class="stat-cards">
          <el-col :span="6">
            <el-card shadow="hover" class="metric-card">
              <div class="metric-label">机器人状态</div>
              <div class="metric-value" :class="botStateClass">{{ botStateText }}</div>
              <div class="metric-sub">{{ botStatus.scheduler_active === 'true' ? '定时任务运行中' : '定时任务已停止' }}</div>
            </el-card>
          </el-col>
          <el-col :span="6">
            <el-card shadow="hover" class="metric-card">
              <div class="metric-label">TAPD 连接</div>
              <div class="metric-value" :class="botStatus.tapd_connected ? 'ok' : 'err'">
                {{ botStatus.tapd_connected ? '正常' : '异常' }}
              </div>
              <div class="metric-sub">调度间隔：{{ botStatus.schedule_interval }}</div>
            </el-card>
          </el-col>
          <el-col :span="6">
            <el-card shadow="hover" class="metric-card">
              <div class="metric-label">已分类需求</div>
              <div class="metric-value">{{ stats.total_classified || 0 }}</div>
              <div class="metric-sub">评论写回 {{ stats.total_comments_written || 0 }} 条</div>
            </el-card>
          </el-col>
          <el-col :span="6">
            <el-card shadow="hover" class="metric-card">
              <div class="metric-label">处理人分配</div>
              <div class="metric-value">{{ stats.total_owners_assigned || 0 }}</div>
              <div class="metric-sub">已写回 TAPD {{ stats.total_writebacked || 0 }} 条</div>
            </el-card>
          </el-col>
        </el-row>

        <!-- 操作按钮 -->
        <el-card class="action-card">
          <div class="action-row">
            <el-button type="primary" :icon="VideoPlay" @click="handleRun" :loading="running" :disabled="running">
              {{ userStore.isAdmin ? '立即运行分类' : '运行我的分类' }}
            </el-button>
            <el-button type="danger" plain :icon="VideoPause" @click="handleStop" :disabled="botStatus.bot_state !== 'running'">
              停止执行
            </el-button>
            <el-button
              v-if="automation.auto_flow_enabled"
              :type="automation.classification_enabled ? 'warning' : 'default'"
              @click="togglePersonalAutomation"
              :loading="automationLoading"
            >
              {{ automation.classification_enabled ? '停止自动分类' : '开启自动分类' }}
            </el-button>
            <span v-if="automation.auto_flow_enabled && automation.classification_enabled" style="font-size:12px;color:#909399;margin-left:4px">
              每{{ automation.schedule_interval_minutes }}分钟，{{ automation.batch_size }}条/次
            </span>
            <template v-if="userStore.isAdmin">
              <el-divider direction="vertical" />
              <el-button :type="botStatus.auto_assign_owner ? 'warning' : 'success'"
                         @click="toggleOwnerAssign">
                {{ botStatus.auto_assign_owner ? '关闭自动分配' : '开启自动分配' }}
              </el-button>
              <el-button :type="botStatus.auto_write_comment ? 'warning' : 'success'"
                         @click="toggleCommentWrite">
                {{ botStatus.auto_write_comment ? '关闭自动评论' : '开启自动评论' }}
              </el-button>
            </template>
            <span class="last-run-info" v-if="botStatus.last_run_start">
              上次运行：{{ botStatus.last_run_start }}（{{ botStatus.last_run_duration }}）
            </span>
          </div>
          <el-alert v-if="botStatus.last_error" :title="`上次错误：${botStatus.last_error}`"
                    type="error" :closable="false" style="margin-top: 12px" />
        </el-card>

        <div class="view-context">
          <span class="view-context-title">当前视图</span>
          <el-tag size="small" effect="plain">{{ userStore.isAdmin ? '全部可见分类结果' : '我的名下分类结果' }}</el-tag>
          <el-tag v-if="listFilter.category_l1" size="small" closable @close="clearStoryFilter('category_l1')">一级分类：{{ listFilter.category_l1 }}</el-tag>
          <el-tag v-if="listFilter.confidence" size="small" closable @close="clearStoryFilter('confidence')">置信度：{{ confidenceLabel(listFilter.confidence) }}</el-tag>
          <el-tag v-if="listFilter.owner" size="small" closable @close="clearStoryFilter('owner')">预测处理人：{{ listFilter.owner }}</el-tag>
          <span class="view-context-count">共 {{ listTotal }} 条</span>
          <el-button v-if="hasStoryFilters" link type="primary" @click="clearAllStoryFilters">清空筛选</el-button>
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
          <div v-if="taskSummary.failed" class="task-summary-hint">存在失败项，请在“后台任务”或“运行日志”中查看详细原因。</div>
        </el-alert>

        <!-- 运行进度 -->
        <el-card v-if="runProgress.visible" class="run-progress-card">
          <div class="progress-header">
            <span class="progress-label">
              <el-icon v-if="runProgress.running" class="is-loading"><Loading /></el-icon>
              {{ runProgress.running ? '正在分类处理...' : (runProgress.status === 'completed' ? '处理完成' : '已停止') }}
            </span>
            <span class="progress-count">{{ runProgress.processed }} / {{ runProgress.total || '?' }}</span>
          </div>
          <el-progress
            :percentage="runProgress.percent"
            :status="runProgress.running ? '' : (runProgress.status === 'completed' ? 'success' : 'warning')"
            :stroke-width="18"
            text-inside
          />
          <div class="progress-stats">
            <el-tag type="success" size="small">已分类 {{ runProgress.succeeded }}</el-tag>
            <el-tag type="info" size="small">跳过 {{ runProgress.skipped }}</el-tag>
            <el-tag type="danger" size="small" v-if="runProgress.failed > 0">失败 {{ runProgress.failed }}</el-tag>
            <el-tag v-if="runProgress.status === 'interrupted'" type="warning" size="small">用户停止</el-tag>
          </div>
        </el-card>

        <!-- 分类结果列表 -->
        <el-card style="margin-top: 12px">
          <template #header>
            <span>分类结果列表</span>
            <span class="card-sub">（共 {{ listTotal }} 条）</span>
          </template>

          <div class="filter-bar">
            <el-select v-model="listFilter.category_l1" placeholder="一级分类" clearable filterable
                       style="width: 160px" @change="loadStories(1)">
              <el-option v-for="c in l1CategoryOptions" :key="c" :label="c" :value="c" />
            </el-select>
            <el-select v-model="listFilter.confidence" placeholder="置信度" clearable
                       style="width: 120px; margin-left: 8px" @change="loadStories(1)">
              <el-option label="高" value="high" />
              <el-option label="中" value="medium" />
              <el-option label="低" value="low" />
            </el-select>
            <el-select v-if="userStore.isAdmin" v-model="listFilter.owner" placeholder="处理人" clearable filterable
                       style="width: 180px; margin-left: 8px" @change="loadStories(1)">
              <el-option v-for="o in ownerOptions" :key="o.username" :label="o.display_name" :value="o.username" />
            </el-select>
            <el-button type="primary" :icon="Check" @click="prepareWriteback"
                       :disabled="!selectedRows.length" style="margin-left: 8px">
              批量写回处理人 ({{ selectedRows.length }})
            </el-button>
            <el-button v-if="userStore.isAdmin" :icon="Download" @click="openFetchByOwner" style="margin-left: 8px">
              按处理人拉取
            </el-button>
          </div>

          <el-table :data="stories" v-loading="listLoading" @selection-change="onSelectionChange"
                    @sort-change="onStorySortChange" stripe style="margin-top: 12px"
                    :default-sort="storyDefaultSort">
            <el-table-column type="selection" width="45" />
            <el-table-column label="需求ID" prop="story_id" width="130" />
            <el-table-column label="标题" min-width="220" show-overflow-tooltip>
              <template #default="{ row }">
                <el-link v-if="row.story_url" type="primary" :href="row.story_url" target="_blank" :underline="false">
                  {{ row.story_title }}
                </el-link>
                <span v-else>{{ row.story_title }}</span>
              </template>
            </el-table-column>
            <el-table-column label="版本" prop="tenant_version" width="90" show-overflow-tooltip />
            <el-table-column label="重要程度" prop="priority" width="90" show-overflow-tooltip />
            <el-table-column label="一级分类" prop="category_l1" width="100">
              <template #default="{ row }">
                <el-link v-if="row.category_l1" type="primary" :underline="false"
                         @click="filterByCategoryL1(row.category_l1)">
                  {{ row.category_l1 }}
                </el-link>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column label="二级分类" prop="category_l2" width="140" show-overflow-tooltip />
            <el-table-column label="置信度" prop="confidence_cn" width="80">
              <template #default="{ row }">
                <el-tag :type="confTagType(row.confidence)" size="small">{{ row.confidence_cn }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="原始处理人" prop="original_owner" width="120" show-overflow-tooltip />
            <el-table-column label="提交时间" prop="tapd_created" width="160" sortable="custom">
              <template #default="{ row }">{{ formatTime(row.tapd_created) || '-' }}</template>
            </el-table-column>
            <el-table-column label="更新时间" prop="tapd_updated" width="160" sortable="custom">
              <template #default="{ row }">{{ formatTime(row.tapd_updated) || '-' }}</template>
            </el-table-column>
            <el-table-column label="预测处理人" prop="assigned_owner" width="120" show-overflow-tooltip />
            <el-table-column label="写回状态" width="100">
              <template #default="{ row }">
                <el-tag v-if="row.writeback_completed" type="success" size="small">已写回</el-tag>
                <el-tag v-else type="info" size="small">未写回</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="260" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openEditOwner(row)">修改处理人</el-button>
                <el-button link type="primary" @click="openDetail(row)">详情</el-button>
                <el-button link type="success" @click="openAddCase(row)">加入案例库</el-button>
              </template>
            </el-table-column>
          </el-table>

          <el-pagination
            v-model:current-page="listPage"
            v-model:page-size="listSize"
            :total="listTotal"
            :page-sizes="[20, 50, 100]"
            layout="total, sizes, prev, pager, next"
            style="margin-top: 12px; justify-content: flex-end"
            @size-change="loadStories(1)"
            @current-change="loadStories()"
          />
        </el-card>
      </el-tab-pane>

      <!-- ============ Tab 2: 运行日志 ============ -->
      <el-tab-pane label="运行日志" name="runs">
        <el-card>
          <template #header>
            <span>分类运行日志</span>
            <span class="card-sub">（共 {{ runsTotal }} 条）</span>
          </template>
          <el-table :data="runs" v-loading="runsLoading" stripe>
            <el-table-column label="时间" prop="run_time" width="170" />
            <el-table-column label="拉取" prop="stories_fetched" width="70" />
            <el-table-column label="分类" prop="stories_classified" width="70" />
            <el-table-column label="跳过" prop="stories_skipped" width="70" />
            <el-table-column label="错误" prop="stories_errored" width="70" />
            <el-table-column label="评论" prop="comments_written" width="70" />
            <el-table-column label="分配" prop="owners_assigned" width="70" />
            <el-table-column label="状态" prop="status" width="100">
              <template #default="{ row }">
                <el-tag :type="runStatusType(row.status)" size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="错误信息" prop="error_message" min-width="200" show-overflow-tooltip />
          </el-table>
          <el-pagination
            v-model:current-page="runsPage"
            :total="runsTotal"
            :page-size="20"
            layout="total, prev, pager, next"
            style="margin-top: 12px; justify-content: flex-end"
            @current-change="loadRuns"
          />
        </el-card>
      </el-tab-pane>

      <!-- ============ Tab 3: 写回日志 ============ -->
      <el-tab-pane label="写回日志" name="writeback">
        <el-card>
          <template #header>
            <span>处理人写回日志</span>
            <span class="card-sub">（共 {{ wbTotal }} 条）</span>
          </template>
          <el-table :data="writebacks" v-loading="wbLoading" stripe>
            <el-table-column label="时间" prop="created_at" width="170" />
            <el-table-column label="需求ID" prop="story_id" width="130" />
            <el-table-column label="字段" prop="field" width="80" />
            <el-table-column label="原值" prop="before_value" width="120" show-overflow-tooltip />
            <el-table-column label="新值" prop="after_value" width="120" show-overflow-tooltip />
            <el-table-column label="操作人" prop="operator" width="100" />
            <el-table-column label="结果" width="100">
              <template #default="{ row }">
                <el-tag :type="row.result === 'success' ? 'success' : 'danger'" size="small">
                  {{ row.result === 'success' ? '成功' : '失败' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="错误" prop="error" min-width="200" show-overflow-tooltip />
          </el-table>
          <el-pagination
            v-model:current-page="wbPage"
            :total="wbTotal"
            :page-size="50"
            layout="total, prev, pager, next"
            style="margin-top: 12px; justify-content: flex-end"
            @current-change="loadWritebacks"
          />
        </el-card>
      </el-tab-pane>

      <!-- ============ Tab 4: 修正记录 ============ -->
      <el-tab-pane label="修正记录" name="modifications">
        <el-card>
          <template #header>
            <span>人工修正处理人记录</span>
            <span class="card-sub">（共 {{ modTotal }} 条）</span>
          </template>
          <el-table :data="modifications" v-loading="modLoading" stripe>
            <el-table-column label="时间" prop="modified_at" width="170" />
            <el-table-column label="需求ID" prop="story_id" width="130" />
            <el-table-column label="标题" prop="story_title" min-width="200" show-overflow-tooltip />
            <el-table-column label="一级分类" prop="predicted_l1" width="100" />
            <el-table-column label="原预测处理人" prop="original_predicted_owner" width="140" />
            <el-table-column label="修正后处理人" prop="modified_owner" width="140" />
            <el-table-column label="操作人" prop="modified_by" width="100" />
          </el-table>
          <el-pagination
            v-model:current-page="modPage"
            :total="modTotal"
            :page-size="50"
            layout="total, prev, pager, next"
            style="margin-top: 12px; justify-content: flex-end"
            @current-change="loadModifications"
          />
        </el-card>
      </el-tab-pane>

      <!-- ============ Tab 5: 后台任务 ============ -->
      <el-tab-pane label="后台任务" name="jobs">
        <el-card>
          <template #header>
            <div style="display: flex; justify-content: space-between; align-items: center">
              <span>后台任务列表</span>
              <el-button size="small" :icon="Refresh" @click="loadJobs">刷新</el-button>
            </div>
          </template>
          <el-table :data="jobs" v-loading="jobsLoading" stripe>
            <el-table-column label="任务ID" prop="job_id" width="200" show-overflow-tooltip />
            <el-table-column label="类型" prop="job_type" width="100" />
            <el-table-column label="状态" prop="status" width="100">
              <template #default="{ row }">
                <el-tag :type="jobStatusType(row.status)" size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="进度" width="150">
              <template #default="{ row }">
                {{ row.processed || 0 }} / {{ row.total || 0 }}
                （成功 {{ row.succeeded || 0 }} / 失败 {{ row.failed || 0 }}）
              </template>
            </el-table-column>
            <el-table-column label="创建人" prop="created_by" width="100" />
            <el-table-column label="开始时间" prop="started_at" width="170" />
            <el-table-column label="完成时间" prop="finished_at" width="170" />
            <el-table-column label="错误" prop="error_message" min-width="200" show-overflow-tooltip />
          </el-table>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <!-- ============ 修改处理人对话框 ============ -->
    <el-dialog v-model="editOwnerVisible" title="修改处理人" width="500px">
      <el-form :model="editForm" label-width="120px">
        <el-form-item label="需求ID">
          <span>{{ editForm.story_id }}</span>
        </el-form-item>
        <el-form-item label="标题">
          <span>{{ editForm.story_title }}</span>
        </el-form-item>
        <el-form-item label="分类">
          <span>{{ editForm.category_l1 }} / {{ editForm.category_l2 }}</span>
        </el-form-item>
        <el-form-item label="当前处理人">
          <span>{{ editForm.original_predicted_owner || '（未分配）' }}</span>
        </el-form-item>
        <el-form-item label="新处理人">
          <el-select v-model="editForm.modified_owner" placeholder="选择处理人" filterable>
            <el-option v-for="o in ownerOptions" :key="o.username" :label="o.display_name" :value="o.username" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editOwnerVisible = false">取消</el-button>
        <el-button type="primary" @click="saveOwnerModification" :loading="savingMod">保存</el-button>
      </template>
    </el-dialog>

    <!-- ============ 详情对话框 ============ -->
    <el-dialog v-model="detailVisible" title="分类详情" width="700px">
      <el-descriptions :column="1" border v-if="currentDetail">
        <el-descriptions-item label="需求ID">{{ currentDetail.story_id }}</el-descriptions-item>
        <el-descriptions-item label="标题">{{ currentDetail.story_title }}</el-descriptions-item>
        <el-descriptions-item label="一级分类">{{ currentDetail.category_l1 }}</el-descriptions-item>
        <el-descriptions-item label="二级分类">{{ currentDetail.category_l2 }}</el-descriptions-item>
        <el-descriptions-item label="置信度">{{ currentDetail.confidence_cn }}</el-descriptions-item>
        <el-descriptions-item label="原模块">{{ currentDetail.original_module }}</el-descriptions-item>
        <el-descriptions-item label="处理人">{{ currentDetail.assigned_owner || '（未分配）' }}</el-descriptions-item>
        <el-descriptions-item label="分类理由">{{ currentDetail.reason }}</el-descriptions-item>
        <el-descriptions-item label="需求描述">
          <div style="max-height: 200px; overflow-y: auto; white-space: pre-wrap;">{{ currentDetail.story_description || '（无）' }}</div>
        </el-descriptions-item>
        <el-descriptions-item label="评论ID">{{ currentDetail.comment_id || '（无）' }}</el-descriptions-item>
        <el-descriptions-item label="评论写回">
          <el-tag :type="currentDetail.comment_written ? 'success' : 'info'" size="small">
            {{ currentDetail.comment_written ? '已写回' : '未写回' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="处理人写回">
          <el-tag :type="currentDetail.writeback_completed ? 'success' : 'info'" size="small">
            {{ currentDetail.writeback_completed ? '已写回' : '未写回' }}
          </el-tag>
          <span v-if="currentDetail.writeback_completed_at" style="margin-left: 8px; color: #909399; font-size: 12px">
            {{ currentDetail.writeback_completed_at }}
          </span>
        </el-descriptions-item>
        <el-descriptions-item label="创建人">{{ currentDetail.created_by || '（未知）' }}</el-descriptions-item>
        <el-descriptions-item label="处理时间">{{ currentDetail.processed_at }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ currentDetail.updated_at }}</el-descriptions-item>
        <el-descriptions-item label="TAPD链接">
          <el-link type="primary" :href="currentDetail.story_url" target="_blank">{{ currentDetail.story_url }}</el-link>
        </el-descriptions-item>
      </el-descriptions>
    </el-dialog>

    <!-- ============ 写回确认对话框 ============ -->
    <el-dialog v-model="writebackConfirmVisible" title="确认写回处理人" width="600px">
      <el-alert type="warning" :closable="false" style="margin-bottom: 12px"
                title="即将把以下处理人写回到 TAPD，请仔细核对。" />
      <el-table :data="selectedRows" max-height="300" stripe>
        <el-table-column label="需求ID" prop="story_id" width="130" />
        <el-table-column label="标题" prop="story_title" min-width="180" show-overflow-tooltip />
        <el-table-column label="处理人" prop="assigned_owner" width="120" />
      </el-table>
      <div style="margin-top: 12px">
        <el-checkbox v-model="writeCommentAlso">同时写回评论</el-checkbox>
      </div>
      <template #footer>
        <el-button @click="writebackConfirmVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmWriteback" :loading="writingBack">确认写回</el-button>
      </template>
    </el-dialog>

    <!-- ============ 按处理人拉取对话框 ============ -->
    <el-dialog v-model="fetchByOwnerVisible" title="按处理人拉取需求" width="640px" :close-on-click-modal="!fetchingByOwner">
      <el-alert type="info" :closable="false" style="margin-bottom: 12px"
                :title="userStore.isAdmin ? '从 TAPD 拉取指定处理人名下『需求待评估』状态的需求，自动分类后进入分类结果列表。' : '拉取您自己名下『需求待评估』状态的需求，自动分类后进入分类结果列表。'" />
      <el-form :model="fetchByOwnerForm" label-width="100px">
        <el-form-item label="处理人">
          <el-select v-model="fetchByOwnerForm.owner" placeholder="选择处理人" filterable style="width: 240px" :disabled="fetchingByOwner || !userStore.isAdmin">
            <el-option v-for="o in fetchOwnerOptions" :key="o" :label="o" :value="o" />
          </el-select>
          <span v-if="!userStore.isAdmin" style="margin-left: 8px; color: #909399; font-size: 12px">仅能拉取自己名下的需求</span>
        </el-form-item>
        <el-form-item label="拉取数量">
          <el-input-number v-model="fetchByOwnerForm.limit" :min="1" :max="200" :disabled="fetchingByOwner" />
          <span style="margin-left: 8px; color: #909399; font-size: 12px">每条需求会调用 AI 分类，数量过多会耗时较长</span>
        </el-form-item>
      </el-form>

      <!-- 实时处理进度 -->
      <div v-if="fetchingByOwner || fetchByOwnerProgress.done" class="fetch-progress-section">
        <div class="progress-header">
          <span class="progress-label">
            <el-icon v-if="fetchingByOwner" class="is-loading"><Loading /></el-icon>
            {{ fetchingByOwner ? '正在拉取并分类...' : '处理完成' }}
          </span>
          <span class="progress-count">{{ fetchByOwnerProgress.processed }} / {{ fetchByOwnerProgress.total }}</span>
        </div>
        <el-progress
          :percentage="fetchByOwnerPercent"
          :status="fetchByOwnerProgress.done ? (fetchByOwnerProgress.errored > 0 ? 'warning' : 'success') : ''"
          :stroke-width="18"
          text-inside
        />
        <div class="progress-stats">
          <el-tag type="success" size="small">已分类 {{ fetchByOwnerProgress.classified }}</el-tag>
          <el-tag type="info" size="small">跳过 {{ fetchByOwnerProgress.skipped }}</el-tag>
          <el-tag type="danger" size="small" v-if="fetchByOwnerProgress.errored > 0">失败 {{ fetchByOwnerProgress.errored }}</el-tag>
        </div>
        <!-- 最近处理的需求 -->
        <div class="progress-latest" v-if="fetchByOwnerProgress.latestTitle">
          <span class="latest-label">最新：</span>
          <el-tag :type="fetchByOwnerProgress.latestStatus === 'error' ? 'danger' : fetchByOwnerProgress.latestStatus === 'skipped' ? 'info' : 'success'" size="small">
            {{ fetchByOwnerProgress.latestStatus === 'error' ? '失败' : fetchByOwnerProgress.latestStatus === 'skipped' ? '跳过' : '完成' }}
          </el-tag>
          <span class="latest-title">{{ fetchByOwnerProgress.latestTitle }}</span>
        </div>
      </div>

      <!-- 拉取结果汇总 -->
      <el-result v-if="fetchByOwnerResult" :icon="fetchByOwnerResult.errored > 0 ? 'warning' : 'success'"
                 :title="fetchByOwnerResult.message" style="padding: 16px 0">
        <template #extra>
          <el-descriptions :column="3" border size="small">
            <el-descriptions-item label="共拉取">{{ fetchByOwnerResult.total }}</el-descriptions-item>
            <el-descriptions-item label="新分类">
              <span style="color: #67c23a; font-weight: bold">{{ fetchByOwnerResult.classified }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="已存在跳过">{{ fetchByOwnerResult.skipped }}</el-descriptions-item>
          </el-descriptions>
        </template>
      </el-result>

      <template #footer>
        <el-button @click="fetchByOwnerVisible = false" :disabled="fetchingByOwner">关闭</el-button>
        <el-button type="primary" @click="confirmFetchByOwner" :loading="fetchingByOwner" :disabled="fetchingByOwner">
          {{ fetchingByOwner ? '正在拉取并分类...' : '开始拉取' }}
        </el-button>
      </template>
    </el-dialog>

    <AddCaseLibraryDialog ref="addCaseDialog" />
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { VideoPlay, VideoPause, Check, Refresh, Download, Loading } from '@element-plus/icons-vue'
import api from '@/api'
import { useUserStore } from '@/stores/user'
import PageTutorial from '@/components/PageTutorial.vue'
import AddCaseLibraryDialog from '@/components/AddCaseLibraryDialog.vue'
import { tutorials } from '@/tutorials'

const userStore = useUserStore()
const router = useRouter()
const automation = reactive({ auto_flow_enabled: false, classification_enabled: false, schedule_interval_minutes: 30, batch_size: 50, max_processing_minutes: 60 })
const automationLoading = ref(false)

const activeTab = ref('process')
const running = ref(false)
const taskSummary = ref(null)

// 运行进度
const runProgress = reactive({
  visible: false,
  running: false,
  jobId: '',
  status: '',
  total: 0,
  processed: 0,
  succeeded: 0,
  failed: 0,
  skipped: 0,
  percent: 0,
})
let runPollTimer = null

// 机器人状态
const botStatus = ref({})
const stats = ref({})
const ownerOptions = ref([])
const fetchOwnerOptions = ref([])  // 按处理人拉取用：TAPD 处理人显示名列表
const l1CategoryOptions = ref([])

// 列表
const stories = ref([])
const listLoading = ref(false)
const listPage = ref(1)
const listSize = ref(20)
const listTotal = ref(0)
const listFilter = reactive({ category_l1: '', confidence: '', owner: '' })
const storySortProp = ref('tapd_created')
const storySortOrder = ref('descending')
const storyDefaultSort = ref({ prop: 'tapd_created', order: 'descending' })
const selectedRows = ref([])

// 运行日志
const runs = ref([])
const runsLoading = ref(false)
const runsPage = ref(1)
const runsTotal = ref(0)

// 写回日志
const writebacks = ref([])
const wbLoading = ref(false)
const wbPage = ref(1)
const wbTotal = ref(0)

// 修正记录
const modifications = ref([])
const modLoading = ref(false)
const modPage = ref(1)
const modTotal = ref(0)

// 后台任务
const jobs = ref([])
const jobsLoading = ref(false)

// 修改处理人
const editOwnerVisible = ref(false)
const editForm = reactive({})
const savingMod = ref(false)

// 详情
const detailVisible = ref(false)
const currentDetail = ref(null)
const addCaseDialog = ref(null)

// 写回确认
const writebackConfirmVisible = ref(false)
const writeCommentAlso = ref(false)
const writingBack = ref(false)

// 按处理人拉取
const fetchByOwnerVisible = ref(false)
const fetchByOwnerForm = reactive({ owner: '', limit: 50 })
const fetchingByOwner = ref(false)
const fetchByOwnerResult = ref(null)
const fetchByOwnerProgress = reactive({
  total: 0, processed: 0, classified: 0, skipped: 0, errored: 0,
  done: false, latestTitle: '', latestStatus: '',
})
const fetchByOwnerPercent = computed(() => {
  if (!fetchByOwnerProgress.total) return 0
  return Math.round((fetchByOwnerProgress.processed / fetchByOwnerProgress.total) * 100)
})

let statusTimer = null

const botStateText = computed(() => {
  const s = botStatus.value.bot_state
  return { running: '运行中', idle: '空闲', error: '错误' }[s] || s || '空闲'
})
const botStateClass = computed(() => {
  const s = botStatus.value.bot_state
  if (s === 'running') return 'running'
  if (s === 'error') return 'err'
  return 'ok'
})

function confTagType(c) {
  return { high: 'success', medium: 'warning', low: 'danger' }[c] || 'info'
}
function runStatusType(s) {
  return { success: 'success', failed: 'danger', running: 'warning' }[s] || 'info'
}
function jobStatusType(s) {
  return { completed: 'success', failed: 'danger', running: 'warning', interrupted: 'info' }[s] || 'info'
}

async function loadBotStatus() {
  try {
    const data = await api.get('/classification/status')
    botStatus.value = data
  } catch (e) { /* ignore */ }
}

async function loadStats() {
  try {
    const data = await api.get('/classification/stats')
    stats.value = data
  } catch (e) { /* ignore */ }
}

async function loadOwners() {
  try {
    const data = await api.get('/classification/owners')
    ownerOptions.value = data.data || []
  } catch (e) { /* ignore */ }
}

async function loadFetchOwners() {
  try {
    const data = await api.get('/user-requirements/owners')
    fetchOwnerOptions.value = data.owners || []
  } catch (e) { /* ignore */ }
}

async function loadL1Categories() {
  try {
    const data = await api.get('/classification/categories')
    l1CategoryOptions.value = data.data || []
  } catch (e) { /* ignore */ }
}

// 点击一级分类直接筛选（与置信度一致）
const hasStoryFilters = computed(() => Boolean(listFilter.category_l1 || listFilter.confidence || listFilter.owner))

function confidenceLabel(value) {
  return { high: '高', medium: '中', low: '低' }[value] || value
}

function clearStoryFilter(type) {
  listFilter[type] = ''
  loadStories(1)
}

function clearAllStoryFilters() {
  listFilter.category_l1 = ''
  listFilter.confidence = ''
  listFilter.owner = ''
  loadStories(1)
}

function filterByCategoryL1(category) {
  listFilter.category_l1 = category
  loadStories(1)
}

function onStorySortChange({ prop, order }) {
  storySortProp.value = prop || 'tapd_created'
  storySortOrder.value = order || 'descending'
  loadStories(1)
}

function formatTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (num) => String(num).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

async function loadStories(page) {
  if (page) listPage.value = page
  listLoading.value = true
  try {
    const sortFieldMap = {
      tapd_created: 'tapd_created',
      tapd_updated: 'tapd_updated',
    }
    const sortOrderMap = { ascending: 'asc', descending: 'desc' }
    const params = {
      page: listPage.value,
      size: listSize.value,
      order_by: sortFieldMap[storySortProp.value] || 'tapd_created',
      order: sortOrderMap[storySortOrder.value] || 'desc',
    }
    if (listFilter.category_l1) params.category_l1 = listFilter.category_l1
    if (listFilter.confidence) params.confidence = listFilter.confidence
    if (listFilter.owner) params.owner = listFilter.owner
    const data = await api.get('/classification/stories', { params })
    stories.value = data.data || []
    listTotal.value = data.total || 0
  } finally {
    listLoading.value = false
  }
}

async function loadRuns() {
  runsLoading.value = true
  try {
    const data = await api.get('/classification/runs', { params: { page: runsPage.value, size: 20 } })
    runs.value = data.data || []
    runsTotal.value = data.total || 0
  } finally {
    runsLoading.value = false
  }
}

async function loadWritebacks() {
  wbLoading.value = true
  try {
    const data = await api.get('/classification/writeback/logs', { params: { page: wbPage.value, size: 50 } })
    writebacks.value = data.data || []
    wbTotal.value = data.total || 0
  } finally {
    wbLoading.value = false
  }
}

async function loadModifications() {
  modLoading.value = true
  try {
    const data = await api.get('/classification/owner-modifications', { params: { page: modPage.value, size: 50 } })
    modifications.value = data.data?.records || []
    modTotal.value = data.data?.total || 0
  } finally {
    modLoading.value = false
  }
}

async function loadJobs() {
  jobsLoading.value = true
  try {
    const data = await api.get('/classification/jobs', { params: { limit: 30 } })
    jobs.value = data.data || []
  } finally {
    jobsLoading.value = false
  }
}

function onSelectionChange(rows) {
  selectedRows.value = rows
}

function onTabChange(tab) {
  if (tab === 'runs') loadRuns()
  else if (tab === 'writeback') loadWritebacks()
  else if (tab === 'modifications') loadModifications()
  else if (tab === 'jobs') loadJobs()
}

async function loadAutomation() {
  try {
    Object.assign(automation, await api.get('/automation/status'))
  } catch (e) { /* handled globally */ }
}

async function togglePersonalAutomation() {
  if (!automation.auto_flow_enabled) {
    ElMessage.info('请先在“系统管理 - 自动流程设置”中确认开启自动流程功能')
    router.push({ name: 'settings' })
    return
  }
  automationLoading.value = true
  try {
    const enabled = !automation.classification_enabled
    const data = await api.post('/automation/modules/classification', { enabled })
    Object.assign(automation, data)
    ElMessage.success(`${data.message}：每 ${data.schedule_interval_minutes} 分钟分类最多 ${data.batch_size} 条需求`)
  } finally {
    automationLoading.value = false
  }
}

async function handleRun() {
  try {
    running.value = true
    const data = await api.post('/classification/run')
    ElMessage.success(data.message || '已启动分类处理')

    // 启动进度轮询
    runProgress.visible = true
    runProgress.running = true
    runProgress.jobId = data.job_id
    runProgress.status = ''
    runProgress.total = 0
    runProgress.processed = 0
    runProgress.succeeded = 0
    runProgress.failed = 0
    runProgress.skipped = 0
    runProgress.percent = 0
    startRunPolling(data.job_id)

    await loadBotStatus()
  } catch (e) { /* error already handled */ } finally {
    running.value = false
  }
}

function startRunPolling(jobId) {
  if (runPollTimer) clearInterval(runPollTimer)
  runPollTimer = setInterval(async () => {
    try {
      const job = await api.get(`/classification/jobs/${jobId}`)
      const d = job.data || job
      runProgress.status = d.status
      runProgress.total = d.total || 0
      runProgress.processed = d.processed || 0
      runProgress.succeeded = d.succeeded || 0
      runProgress.failed = d.failed || 0
      if (runProgress.total > 0) {
        runProgress.percent = Math.round((runProgress.processed / runProgress.total) * 100)
      } else if (d.status === 'completed') {
        runProgress.percent = 100
      }

      // 任务结束
      if (['completed', 'failed', 'interrupted'].includes(d.status)) {
        clearInterval(runPollTimer)
        runPollTimer = null
        runProgress.running = false

        // 从 result JSON 中提取 skipped
        if (d.result) {
          try {
            const r = JSON.parse(d.result)
            runProgress.skipped = r.skipped || 0
          } catch (e) { /* ignore */ }
        }

        // 刷新结果
        await loadBotStatus()
        await loadStories(1)
        await loadStats()

        if (d.status === 'completed') {
          taskSummary.value = {
            type: runProgress.failed ? 'warning' : 'success',
            title: '分类任务完成',
            detail: `共处理 ${runProgress.processed} 条；新分类 ${runProgress.succeeded} 条，跳过 ${runProgress.skipped} 条，失败 ${runProgress.failed} 条。`,
            failed: runProgress.failed,
          }
          ElMessage.success(`分类完成：共 ${runProgress.processed} 条，新分类 ${runProgress.succeeded} 条，跳过 ${runProgress.skipped} 条`)
        } else if (d.status === 'interrupted') {
          taskSummary.value = {
            type: 'warning',
            title: '分类任务已停止',
            detail: `已处理 ${runProgress.processed} 条；新分类 ${runProgress.succeeded} 条。`,
            failed: true,
          }
          ElMessage.warning(`分类已停止：已处理 ${runProgress.processed} 条，新分类 ${runProgress.succeeded} 条`)
        } else if (d.status === 'failed') {
          taskSummary.value = {
            type: 'error',
            title: '分类任务失败',
            detail: d.error_message || '未知错误，请查看后台任务或运行日志。',
            failed: true,
          }
          ElMessage.error('分类任务失败：' + (d.error_message || '未知错误'))
        }

        // 任务结果由结果卡片保留，进度卡片在结束后收起
        setTimeout(() => { runProgress.visible = false }, 5000)
      }
    } catch (e) { /* ignore polling errors */ }
  }, 2000)
}

async function handleStop() {
  try {
    await ElMessageBox.confirm('确认停止当前正在执行的分类任务？', '提示', { type: 'warning' })
    const data = await api.post('/classification/stop')
    ElMessage.success(data.message || '已请求停止')
    runProgress.running = false
    runProgress.status = 'interrupted'
    await loadBotStatus()
  } catch (e) { /* cancel */ }
}

async function toggleScheduler() {
  const action = botStatus.value.scheduler_active === 'true' ? 'stop' : 'start'
  try {
    const data = await api.post(`/classification/scheduler/${action}`)
    ElMessage.success(data.message)
    await loadBotStatus()
  } catch (e) { /* ignore */ }
}

async function toggleOwnerAssign() {
  const action = botStatus.value.auto_assign_owner ? 'disable' : 'enable'
  try {
    const data = await api.post(`/classification/owner/${action}`)
    ElMessage.success(data.message)
    await loadBotStatus()
  } catch (e) { /* ignore */ }
}

async function toggleCommentWrite() {
  const action = botStatus.value.auto_write_comment ? 'disable' : 'enable'
  try {
    const data = await api.post(`/classification/comment/${action}`)
    ElMessage.success(data.message)
    await loadBotStatus()
  } catch (e) { /* ignore */ }
}

function openEditOwner(row) {
  Object.assign(editForm, {
    story_id: row.story_id,
    story_title: row.story_title,
    category_l1: row.category_l1,
    category_l2: row.category_l2,
    workspace_id: row.workspace_id,
    original_predicted_owner: row.assigned_owner || '',
    modified_owner: row.assigned_owner || '',
    updated_at: row.updated_at,
  })
  editOwnerVisible.value = true
}

async function saveOwnerModification() {
  if (!editForm.modified_owner) {
    ElMessage.warning('请选择处理人')
    return
  }
  savingMod.value = true
  try {
    await api.post('/classification/owner-modifications', {
      items: [{
        story_id: editForm.story_id,
        story_title: editForm.story_title,
        workspace_id: editForm.workspace_id,
        original_predicted_owner: editForm.original_predicted_owner,
        modified_owner: editForm.modified_owner,
        predicted_l1: editForm.category_l1,
        predicted_l2: editForm.category_l2,
        updated_at: editForm.updated_at,
      }]
    })
    ElMessage.success('处理人已修正')
    editOwnerVisible.value = false
    await loadStories()
  } finally {
    savingMod.value = false
  }
}

function openDetail(row) {
  currentDetail.value = row
  detailVisible.value = true
}

function openAddCase(row) {
  const aiResult = {
    category_l1: row.category_l1,
    category_l2: row.category_l2,
    confidence: row.confidence,
    reason: row.reason,
  }
  addCaseDialog.value?.open({
    moduleKey: 'classification',
    requirement_title: row.story_title || '',
    requirement_desc: '',
    aiResult,
    is_mismatch: true,
  })
}

function prepareWriteback() {
  if (!selectedRows.value.length) {
    ElMessage.warning('请先选择需要写回的需求')
    return
  }
  const noOwner = selectedRows.value.filter(r => !r.assigned_owner)
  if (noOwner.length) {
    ElMessage.warning(`有 ${noOwner.length} 条需求未分配处理人，请先修正处理人`)
    return
  }
  writeCommentAlso.value = false
  writebackConfirmVisible.value = true
}

async function confirmWriteback() {
  writingBack.value = true
  try {
    const items = selectedRows.value.map(r => ({
      story_id: r.story_id,
      workspace_id: r.workspace_id,
      owner: r.assigned_owner,
      before_owner: r.assigned_owner,
    }))
    // 1. prepare
    const prepareResp = await api.post('/classification/writeback/prepare', { items })
    // 2. execute
    const execResp = await api.post('/classification/writeback', {
      items,
      write_comment: writeCommentAlso.value,
      confirm_token: prepareResp.confirm_token,
    })
    ElMessage.success(execResp.message || '写回完成')
    writebackConfirmVisible.value = false
    await loadStories()
    await loadStats()
    if (activeTab.value === 'writeback') loadWritebacks()
  } finally {
    writingBack.value = false
  }
}

function openFetchByOwner() {
  // 操作员默认锁定为自己的显示名，管理员可选
  fetchByOwnerForm.owner = userStore.isAdmin ? '' : userStore.displayName
  fetchByOwnerForm.limit = 50
  fetchByOwnerResult.value = null
  fetchByOwnerProgress.total = 0
  fetchByOwnerProgress.processed = 0
  fetchByOwnerProgress.classified = 0
  fetchByOwnerProgress.skipped = 0
  fetchByOwnerProgress.errored = 0
  fetchByOwnerProgress.done = false
  fetchByOwnerProgress.latestTitle = ''
  fetchByOwnerProgress.latestStatus = ''
  fetchByOwnerVisible.value = true
}

async function confirmFetchByOwner() {
  if (!fetchByOwnerForm.owner) {
    ElMessage.warning('请选择处理人')
    return
  }
  fetchingByOwner.value = true
  fetchByOwnerResult.value = null
  fetchByOwnerProgress.total = 0
  fetchByOwnerProgress.processed = 0
  fetchByOwnerProgress.classified = 0
  fetchByOwnerProgress.skipped = 0
  fetchByOwnerProgress.errored = 0
  fetchByOwnerProgress.done = false
  fetchByOwnerProgress.latestTitle = ''
  fetchByOwnerProgress.latestStatus = ''

  try {
    // 使用 fetch + ReadableStream 读取 SSE 流式响应
    const resp = await fetch('/api/classification/fetch-by-owner', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${localStorage.getItem('token') || ''}`,
      },
      credentials: 'include',
      body: JSON.stringify({
        owner: fetchByOwnerForm.owner,
        limit: fetchByOwnerForm.limit,
      }),
    })

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}))
      throw new Error(errData.detail || `HTTP ${resp.status}`)
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      // SSE 事件以 \n\n 分隔
      const lines = buffer.split('\n\n')
      buffer = lines.pop() || ''  // 保留最后不完整的一段
      for (const chunk of lines) {
        const line = chunk.trim()
        if (!line.startsWith('data: ')) continue
        const jsonStr = line.slice(6)
        try {
          const data = JSON.parse(jsonStr)
          if (data.type === 'start') {
            fetchByOwnerProgress.total = data.total
          } else if (data.type === 'progress') {
            fetchByOwnerProgress.processed = data.index
            fetchByOwnerProgress.classified = data.classified
            fetchByOwnerProgress.skipped = data.skipped
            fetchByOwnerProgress.errored = data.errored
            fetchByOwnerProgress.latestTitle = data.title || ''
            fetchByOwnerProgress.latestStatus = data.status || ''
          } else if (data.type === 'done') {
            fetchByOwnerProgress.done = true
            fetchByOwnerProgress.total = data.total
            fetchByOwnerProgress.classified = data.classified
            fetchByOwnerProgress.skipped = data.skipped
            fetchByOwnerProgress.errored = data.errored
            fetchByOwnerResult.value = data
          }
        } catch (parseErr) {
          // 忽略解析错误
        }
      }
    }

    // 刷新分类结果列表和统计
    await loadStories(1)
    await loadStats()
  } catch (e) {
    ElMessage.error('拉取分类失败：' + (e.message || e))
  } finally {
    fetchingByOwner.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadBotStatus(), loadAutomation(), loadStats(), loadOwners(), loadFetchOwners(), loadL1Categories(), loadStories()])
  // 每 15 秒刷新状态（降低频率避免超时）
  statusTimer = setInterval(loadBotStatus, 15000)
})

onUnmounted(() => {
  if (statusTimer) clearInterval(statusTimer)
  if (runPollTimer) clearInterval(runPollTimer)
})
</script>

<style scoped>
.stat-cards {
  margin-bottom: 12px;
}
.metric-card {
  text-align: left;
}
.metric-card :deep(.el-card__body) {
  padding: 16px;
}
.metric-label {
  font-size: 13px;
  color: #667085;
  margin-bottom: 6px;
}
.metric-value {
  font-size: 28px;
  font-weight: 720;
  color: #172033;
  letter-spacing: -0.4px;
}
.metric-value.ok { color: #67c23a; }
.metric-value.err { color: #f56c6c; }
.metric-value.running { color: #e6a23c; }
.metric-sub {
  font-size: 11px;
  color: #909399;
  margin-top: 4px;
}
.action-card {
  margin-bottom: 14px;
}
.workspace-tabs :deep(.el-tabs__header) {
  margin-bottom: 18px;
}
.workspace-tabs :deep(.el-tabs__item) {
  height: 38px;
  font-weight: 600;
}
.view-context {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin: -2px 0 12px;
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
.run-progress-card {
  margin-bottom: 12px;
}
.run-progress-card :deep(.el-card__body) {
  padding: 16px 20px;
}
.run-progress-card .progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.run-progress-card .progress-label {
  font-size: 14px;
  font-weight: 500;
  color: #303133;
  display: flex;
  align-items: center;
  gap: 6px;
}
.run-progress-card .progress-count {
  font-size: 13px;
  color: #606266;
  font-weight: 600;
}
.run-progress-card .progress-stats {
  margin-top: 10px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.last-run-info {
  margin-left: auto;
  padding-left: 12px;
  font-size: 12px;
  color: #667085;
}
.card-sub {
  font-size: 12px;
  color: #909399;
  margin-left: 8px;
  font-weight: normal;
}
.chart {
  height: 300px;
}
.filter-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
}
.fetch-progress-section {
  margin-top: 16px;
  padding: 16px;
  background: #f5f7fa;
  border-radius: 8px;
}
.progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.progress-label {
  font-size: 14px;
  font-weight: 500;
  color: #303133;
  display: flex;
  align-items: center;
  gap: 6px;
}
.progress-count {
  font-size: 13px;
  color: #606266;
  font-weight: 600;
}
.progress-stats {
  margin-top: 10px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.progress-latest {
  margin-top: 10px;
  font-size: 12px;
  color: #606266;
  display: flex;
  align-items: center;
  gap: 6px;
}
.latest-label {
  color: #909399;
  flex-shrink: 0;
}
.latest-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
