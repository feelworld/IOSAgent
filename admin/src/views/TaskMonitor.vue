<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useTaskStore } from '../stores/task'

const store = useTaskStore()
const filterStatus = ref('')
const filterSource = ref('')
const currentPage = ref(1)
const pageSize = ref(20)

const statusOptions = [
  { label: '全部', value: '' },
  { label: '待处理', value: 'pending' },
  { label: '已下发', value: 'dispatched' },
  { label: '运行中', value: 'running' },
  { label: '成功', value: 'success' },
  { label: '失败', value: 'failed' },
  { label: '超时', value: 'timeout' },
  { label: '已取消', value: 'cancelled' },
]

const sourceOptions = [
  { label: '全部', value: '' },
  { label: '手动', value: 'manual' },
  { label: '探索', value: 'explore' },
  { label: '执行', value: 'execute' },
]

const statusTagType = (status: string) => {
  const map: Record<string, string> = {
    pending: 'info',
    dispatched: 'warning',
    running: '',
    success: 'success',
    failed: 'danger',
    timeout: 'danger',
    cancelled: 'info',
  }
  return map[status] ?? 'info'
}

const statusLabel = (status: string) => {
  const map: Record<string, string> = {
    pending: '待处理',
    dispatched: '已下发',
    running: '运行中',
    success: '成功',
    failed: '失败',
    timeout: '超时',
    cancelled: '已取消',
  }
  return map[status] ?? status
}

function shortenId(id: string) {
  return id ? id.slice(0, 8) + '…' : '-'
}

function formatDuration(row: any) {
  if (row.result?.duration_seconds != null) {
    return `${row.result.duration_seconds.toFixed(1)}s`
  }
  if (row.started_at && row.completed_at) {
    const dur = (new Date(row.completed_at).getTime() - new Date(row.started_at).getTime()) / 1000
    return `${dur.toFixed(1)}s`
  }
  return '-'
}

function formatTime(val: string | null) {
  return val ? new Date(val).toLocaleString() : '-'
}

async function loadTasks() {
  await store.fetchTasks({
    status: filterStatus.value || undefined,
    source: filterSource.value || undefined,
    page: currentPage.value,
    size: pageSize.value,
  })
}

function handleFilter() {
  currentPage.value = 1
  loadTasks()
}

function handlePageChange(page: number) {
  currentPage.value = page
  loadTasks()
}

function isActive(status: string) {
  return ['pending', 'dispatched', 'running'].includes(status)
}

async function handleCancel(taskId: string) {
  try {
    await ElMessageBox.confirm('确认取消该任务？', '取消任务', { type: 'warning' })
    const res = await store.cancelTask(taskId)
    if (res.code === 0) {
      ElMessage.success('任务已取消')
      loadTasks()
    } else {
      ElMessage.error(res.message || '取消失败')
    }
  } catch {
    // user dismissed
  }
}

onMounted(() => {
  loadTasks()
  store.fetchStats()
  store.setupWsHandlers()
})
</script>

<template>
  <div class="task-monitor">
    <div class="stats-row">
      <el-row :gutter="16">
        <el-col :span="4">
          <el-statistic title="总任务" :value="store.stats.total" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="运行中" :value="store.stats.running" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="成功" :value="store.stats.success" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="失败" :value="store.stats.failed" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="超时" :value="store.stats.timeout" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="成功率" :value="`${(store.stats.success_rate * 100).toFixed(1)}%`" />
        </el-col>
      </el-row>
    </div>

    <el-card class="filter-card">
      <el-space>
        <el-select v-model="filterStatus" placeholder="按状态筛选" clearable @change="handleFilter" style="width: 160px">
          <el-option v-for="opt in statusOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
        </el-select>
        <el-select v-model="filterSource" placeholder="按来源筛选" clearable @change="handleFilter" style="width: 160px">
          <el-option v-for="opt in sourceOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
        </el-select>
      </el-space>
    </el-card>

    <el-table :data="store.tasks" v-loading="store.loading" stripe style="width: 100%">
      <el-table-column label="任务 UID" width="130">
        <template #default="{ row }">
          <el-tooltip :content="row.task_uid" placement="top">
            <span>{{ shortenId(row.task_uid) }}</span>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column label="设备 ID" width="130">
        <template #default="{ row }">
          <el-tooltip :content="row.device_id" placement="top">
            <span>{{ shortenId(row.device_id) }}</span>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="来源" width="80">
        <template #default="{ row }">
          {{ row.source }}
        </template>
      </el-table-column>
      <el-table-column label="下发时间" min-width="170">
        <template #default="{ row }">
          {{ formatTime(row.dispatched_at) }}
        </template>
      </el-table-column>
      <el-table-column label="完成时间" min-width="170">
        <template #default="{ row }">
          {{ formatTime(row.completed_at) }}
        </template>
      </el-table-column>
      <el-table-column label="耗时" width="90">
        <template #default="{ row }">
          {{ formatDuration(row) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="isActive(row.status)"
            type="danger"
            size="small"
            link
            @click="handleCancel(row.id)"
          >
            取消
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pagination">
      <el-pagination
        v-model:current-page="currentPage"
        :page-size="pageSize"
        :total="store.total"
        layout="total, prev, pager, next"
        @current-change="handlePageChange"
      />
    </div>
  </div>
</template>

<style scoped>
.task-monitor {
  padding: 0;
}
.stats-row {
  margin-bottom: 20px;
  padding: 16px;
  background: var(--el-bg-color);
  border-radius: 8px;
}
.filter-card {
  margin-bottom: 16px;
}
.pagination {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
</style>
