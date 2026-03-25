<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useDeviceStore, type DeviceItem } from '../stores/device'
import { useTaskStore } from '../stores/task'
import { useAccountStore, type AccountItem } from '../stores/account'

const store = useDeviceStore()
const taskStore = useTaskStore()
const accountStore = useAccountStore()
const filterStatus = ref('')
const currentPage = ref(1)
const pageSize = ref(20)
const selectedDevices = ref<DeviceItem[]>([])

// ── Dispatch dialog ──
const dispatchVisible = ref(false)
const dispatchForm = ref({
  action: 'login',
  app_name: '',
  app_names: '',
  apple_id: '',
  timeout: 300,
})
const dispatching = ref(false)
const deviceAccounts = ref<AccountItem[]>([])
const loadingAccounts = ref(false)

const actionOptions = [
  { label: '登录 Apple ID', value: 'login' },
  { label: '搜索下载 App', value: 'search_download' },
  { label: '删除 App', value: 'delete_app' },
  { label: '登录 + 下载 (完整流程)', value: 'full_flow' },
]

const needsLogin = computed(() =>
  ['login', 'full_flow'].includes(dispatchForm.value.action)
)
const needsAppName = computed(() =>
  ['search_download', 'full_flow'].includes(dispatchForm.value.action)
)
const needsAppNames = computed(() =>
  dispatchForm.value.action === 'delete_app'
)

function handleSelectionChange(rows: DeviceItem[]) {
  selectedDevices.value = rows
}

async function openDispatchDialog() {
  dispatchForm.value = { action: 'login', app_name: '', app_names: '', apple_id: '', timeout: 300 }
  deviceAccounts.value = []
  dispatchVisible.value = true
  await loadDispatchAccounts()
}

async function loadDispatchAccounts() {
  if (selectedDevices.value.length !== 1) {
    deviceAccounts.value = []
    return
  }
  loadingAccounts.value = true
  try {
    deviceAccounts.value = await accountStore.fetchDeviceAccounts(selectedDevices.value[0].id)
  } catch {
    deviceAccounts.value = []
  } finally {
    loadingAccounts.value = false
  }
}

async function handleDispatch() {
  if (!selectedDevices.value.length) {
    ElMessage.warning('请先选择设备')
    return
  }
  if (needsAppName.value && !dispatchForm.value.app_name.trim()) {
    ElMessage.warning('请输入 App 名称')
    return
  }
  if (needsAppNames.value && !dispatchForm.value.app_names.trim()) {
    ElMessage.warning('请输入要删除的 App 名称')
    return
  }

  dispatching.value = true
  try {
    const payload: Record<string, any> = {
      device_ids: selectedDevices.value.map(d => d.id),
      action: dispatchForm.value.action,
      timeout_seconds: dispatchForm.value.timeout,
    }
    if (dispatchForm.value.app_name) payload.app_name = dispatchForm.value.app_name
    if (dispatchForm.value.app_names) payload.app_names = dispatchForm.value.app_names
    if (dispatchForm.value.apple_id) {
      payload.params = { apple_id: dispatchForm.value.apple_id }
    }

    const res = await taskStore.dispatchTask(payload)
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

// ── Device account management dialog ──
const accountDialogVisible = ref(false)
const accountDialogDevice = ref<DeviceItem | null>(null)
const managedAccounts = ref<AccountItem[]>([])
const loadingManaged = ref(false)

async function openAccountDialog(device: DeviceItem) {
  accountDialogDevice.value = device
  accountDialogVisible.value = true
  await refreshManagedAccounts()
}

async function refreshManagedAccounts() {
  if (!accountDialogDevice.value) return
  loadingManaged.value = true
  try {
    managedAccounts.value = await accountStore.fetchDeviceAccounts(accountDialogDevice.value.id)
  } catch {
    managedAccounts.value = []
  } finally {
    loadingManaged.value = false
  }
}

async function handleRemoveAccount(acc: AccountItem) {
  try {
    await ElMessageBox.confirm(
      `确定要从该设备移除账号 ${acc.email} 吗？\n系统会自动从账号池补充新账号（如有可用）。`,
      '移除账号',
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await accountStore.unbindAndRefill(acc.id)
    ElMessage.success('已移除，系统自动补充中...')
    await refreshManagedAccounts()
    loadDevices()
  } catch (e: any) {
    ElMessage.error(e.message || '操作失败')
  }
}

// ── Device list ──
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

const accountStatusTag = (status: string) => {
  const map: Record<string, string> = {
    active: 'success',
    banned: 'danger',
    suspended: 'warning',
    unknown: 'info',
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
          下发任务
        </el-button>
      </el-space>
    </el-card>

    <el-table :data="store.devices" v-loading="store.loading" stripe style="width: 100%" @selection-change="handleSelectionChange">
      <el-table-column type="selection" width="50" fixed />
      <el-table-column prop="name" label="名称" width="120" fixed />
      <el-table-column label="状态" width="90" fixed>
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)" size="small">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="model" label="型号" width="120" />
      <el-table-column prop="ios_version" label="iOS" width="80" />
      <el-table-column label="当前账号" min-width="180">
        <template #default="{ row }">
          <div style="display: flex; align-items: center; gap: 6px">
            <span v-if="row.current_apple_id" style="font-size: 12px">{{ row.current_apple_id }}</span>
            <el-tag v-else type="info" size="small">未分配</el-tag>
            <el-button link type="primary" size="small" @click.stop="openAccountDialog(row)">管理</el-button>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="电量" width="70">
        <template #default="{ row }">
          {{ row.battery_level != null ? `${row.battery_level}%` : '-' }}
        </template>
      </el-table-column>
      <el-table-column label="越狱" width="90">
        <template #default="{ row }">
          <el-tag v-if="row.jailbroken === true" type="warning" size="small">{{ row.jailbreak_type || '是' }}</el-tag>
          <el-tag v-else-if="row.jailbroken === false" type="info" size="small">否</el-tag>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column prop="udid" label="UDID" width="160" show-overflow-tooltip />
      <el-table-column prop="serial_number" label="序列号" width="130" show-overflow-tooltip />
      <el-table-column prop="imei" label="IMEI" width="160" show-overflow-tooltip />
      <el-table-column prop="product_type" label="产品型号" width="120" />
      <el-table-column prop="cpu_architecture" label="CPU" width="100" />
      <el-table-column prop="wifi_mac" label="WiFi MAC" width="150" show-overflow-tooltip />
      <el-table-column prop="companion_id" label="伴生机" width="140" show-overflow-tooltip />
      <el-table-column prop="device_uid" label="设备 UID" width="160" show-overflow-tooltip />
      <el-table-column label="最后心跳" min-width="170">
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

    <!-- ── Dispatch dialog ── -->
    <el-dialog v-model="dispatchVisible" title="下发任务" width="560px" destroy-on-close>
      <el-form label-width="100px">
        <el-form-item label="已选设备">
          <el-tag v-for="d in selectedDevices" :key="d.id" size="small" style="margin-right: 6px">
            {{ d.name || d.device_uid.slice(0, 8) }}
          </el-tag>
        </el-form-item>
        <el-form-item label="任务类型">
          <el-select v-model="dispatchForm.action" style="width: 100%">
            <el-option v-for="opt in actionOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="needsLogin" label="选择账号">
          <el-select v-model="dispatchForm.apple_id" placeholder="系统自动分配" clearable style="width: 100%"
            :loading="loadingAccounts">
            <el-option label="系统自动分配" value="" />
            <el-option
              v-for="acc in deviceAccounts.filter(a => a.status === 'active')"
              :key="acc.id"
              :label="acc.email + (acc.is_primary ? ' (主)' : '')"
              :value="acc.email"
            />
          </el-select>
          <div v-if="selectedDevices.length > 1" style="font-size: 12px; color: var(--el-text-color-secondary); margin-top: 4px">
            多台设备下发时使用系统自动分配
          </div>
        </el-form-item>
        <el-form-item v-if="needsAppName" label="App 名称">
          <el-input v-model="dispatchForm.app_name" placeholder="例如: 微信" />
        </el-form-item>
        <el-form-item v-if="needsAppNames" label="App 名称">
          <el-input v-model="dispatchForm.app_names" placeholder="多个用逗号分隔，例如: VLC, 微信" />
          <div style="font-size: 12px; color: var(--el-text-color-secondary); margin-top: 4px">
            支持多个 App，用逗号分隔
          </div>
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

    <!-- ── Device account management dialog ── -->
    <el-dialog
      v-model="accountDialogVisible"
      :title="`设备账号管理 - ${accountDialogDevice?.name || accountDialogDevice?.device_uid?.slice(0, 12) || ''}`"
      width="600px"
      destroy-on-close
    >
      <el-table :data="managedAccounts" v-loading="loadingManaged" stripe size="small">
        <el-table-column prop="email" label="Apple ID" min-width="200" />
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="accountStatusTag(row.status)" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="主账号" width="70" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.is_primary" type="warning" size="small">主</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最后使用" width="160">
          <template #default="{ row }">
            {{ row.last_used_at ? new Date(row.last_used_at).toLocaleString() : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80" align="center">
          <template #default="{ row }">
            <el-button link type="danger" size="small" @click="handleRemoveAccount(row)">移除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="!loadingManaged && !managedAccounts.length" style="text-align: center; padding: 20px; color: var(--el-text-color-secondary)">
        该设备暂无绑定账号，系统将在下发任务时自动从账号池分配
      </div>
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
