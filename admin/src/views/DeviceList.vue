<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useDeviceStore, type DeviceItem } from '../stores/device'
import { useTaskStore } from '../stores/task'
import { useScriptStore, type ScriptItem } from '../stores/script'

const store = useDeviceStore()
const taskStore = useTaskStore()
const scriptStore = useScriptStore()
const filterStatus = ref('')
const currentPage = ref(1)
const pageSize = ref(20)
const selectedDevices = ref<DeviceItem[]>([])

const dispatchVisible = ref(false)
const dispatchForm = ref({
  script_id: '',
  script_version: 1,
  params_json: '',
  timeout: 300,
})
const dispatching = ref(false)
const scriptList = ref<ScriptItem[]>([])
const selectedScriptName = ref('')

function handleSelectionChange(rows: DeviceItem[]) {
  selectedDevices.value = rows
}

async function openDispatchDialog() {
  dispatchForm.value = { script_id: '', script_version: 1, params_json: '', timeout: 300 }
  selectedScriptName.value = ''
  dispatchVisible.value = true
  await scriptStore.fetchScripts({ size: 100 })
  scriptList.value = scriptStore.scripts
}

function handleScriptSelect(scriptId: string) {
  const script = scriptList.value.find(s => s.id === scriptId)
  if (script) {
    dispatchForm.value.script_version = script.current_version
    selectedScriptName.value = script.name
  }
}

async function handleDispatch() {
  if (!selectedDevices.value.length) {
    ElMessage.warning('请先选择设备')
    return
  }
  if (!dispatchForm.value.script_id) {
    ElMessage.warning('请选择脚本')
    return
  }

  let params: Record<string, any> | undefined
  if (dispatchForm.value.params_json.trim()) {
    try {
      params = JSON.parse(dispatchForm.value.params_json)
    } catch {
      ElMessage.error('参数 JSON 格式不正确')
      return
    }
  }

  dispatching.value = true
  try {
    const res = await taskStore.dispatchTask({
      device_ids: selectedDevices.value.map(d => d.id),
      script_id: dispatchForm.value.script_id,
      script_version: dispatchForm.value.script_version,
      params,
      timeout: dispatchForm.value.timeout,
    })
    if (res.code === 0) {
      ElMessage.success(`已下发 ${selectedDevices.value.length} 台设备`)
      dispatchVisible.value = false
    } else {
      ElMessage.error(res.message || '下发失败')
    }
  } catch (e: any) {
    ElMessage.error(e.message || '下发失败')
  } finally {
    dispatching.value = false
  }
}

const statusOptions = [
  { label: '全部', value: '' },
  { label: '在线', value: 'online' },
  { label: '离线', value: 'offline' },
  { label: '忙碌', value: 'busy' },
  { label: '错误', value: 'error' },
  { label: '维护', value: 'maintenance' },
]

const statusTagType = (status: string) => {
  const map: Record<string, string> = {
    online: 'success',
    offline: 'info',
    busy: 'warning',
    error: 'danger',
    maintenance: '',
  }
  return map[status] || 'info'
}

async function loadDevices() {
  await store.fetchDevices({
    status: filterStatus.value || undefined,
    page: currentPage.value,
    size: pageSize.value,
    sort: 'last_heartbeat:desc',
  })
}

function handleFilter() {
  currentPage.value = 1
  loadDevices()
}

function handlePageChange(page: number) {
  currentPage.value = page
  loadDevices()
}

onMounted(() => {
  loadDevices()
  store.fetchStats()
  store.setupWsHandlers()
})
</script>

<template>
  <div class="device-list">
    <div class="stats-row">
      <el-row :gutter="16">
        <el-col :span="4">
          <el-statistic title="总设备" :value="store.stats.total" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="在线" :value="store.stats.online" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="离线" :value="store.stats.offline" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="忙碌" :value="store.stats.busy" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="错误" :value="store.stats.error" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="在线率" :value="`${(store.stats.online_rate * 100).toFixed(1)}%`" />
        </el-col>
      </el-row>
    </div>

    <el-card class="filter-card">
      <el-space>
        <el-select v-model="filterStatus" placeholder="按状态筛选" clearable @change="handleFilter" style="width: 200px">
          <el-option v-for="opt in statusOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
        </el-select>
        <el-button type="primary" @click="openDispatchDialog" :disabled="!selectedDevices.length">
          下发脚本
        </el-button>
      </el-space>
    </el-card>

    <el-table :data="store.devices" v-loading="store.loading" stripe style="width: 100%" @selection-change="handleSelectionChange">
      <el-table-column type="selection" width="50" />
      <el-table-column prop="device_uid" label="设备 UID" width="160" />
      <el-table-column prop="name" label="名称" width="120" />
      <el-table-column prop="model" label="型号" width="120" />
      <el-table-column prop="ios_version" label="iOS 版本" width="100" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)" size="small">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="电量" width="80">
        <template #default="{ row }">
          {{ row.battery_level != null ? `${row.battery_level}%` : '-' }}
        </template>
      </el-table-column>
      <el-table-column prop="companion_id" label="伴生机" width="140" />
      <el-table-column label="最后心跳" min-width="180">
        <template #default="{ row }">
          {{ row.last_heartbeat ? new Date(row.last_heartbeat).toLocaleString() : '-' }}
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

    <el-dialog v-model="dispatchVisible" title="下发脚本" width="520px" destroy-on-close>
      <el-form label-width="100px">
        <el-form-item label="已选设备">
          <el-tag v-for="d in selectedDevices" :key="d.id" size="small" style="margin-right: 6px">
            {{ d.device_uid.slice(0, 8) }}…
          </el-tag>
          <span v-if="!selectedDevices.length" style="color: var(--el-text-color-placeholder)">请在表格中勾选设备</span>
        </el-form-item>
        <el-form-item label="选择脚本">
          <el-select
            v-model="dispatchForm.script_id"
            placeholder="请选择脚本"
            filterable
            style="width: 100%"
            @change="handleScriptSelect"
          >
            <el-option
              v-for="s in scriptList"
              :key="s.id"
              :label="`${s.name} (v${s.current_version}) ${s.script_type === 'python' ? '[Py]' : ''}`"
              :value="s.id"
            >
              <span>{{ s.name }}</span>
              <el-tag :type="s.script_type === 'python' ? 'warning' : 'primary'" size="small" style="margin-left: 8px">
                {{ s.script_type === 'python' ? 'Python' : '步骤' }}
              </el-tag>
              <span style="float: right; color: var(--el-text-color-secondary); font-size: 12px">v{{ s.current_version }}</span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="脚本版本">
          <el-input-number v-model="dispatchForm.script_version" :min="1" />
          <span style="margin-left: 8px; color: var(--el-text-color-secondary); font-size: 12px">默认使用最新版本</span>
        </el-form-item>
        <el-form-item label="参数 (JSON)">
          <el-input
            v-model="dispatchForm.params_json"
            type="textarea"
            :rows="4"
            placeholder='{"keyword": "example"}'
          />
        </el-form-item>
        <el-form-item label="超时 (秒)">
          <el-input-number v-model="dispatchForm.timeout" :min="30" :max="3600" :step="30" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dispatchVisible = false">取消</el-button>
        <el-button type="primary" :loading="dispatching" @click="handleDispatch">下发</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.device-list {
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
