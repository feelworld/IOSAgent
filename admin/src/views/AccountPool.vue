<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAccountStore, type AccountItem } from '../stores/account'
import client from '../api/client'

const store = useAccountStore()
const filterStatus = ref('')
const filterBound = ref('')
const currentPage = ref(1)
const pageSize = ref(20)

const importVisible = ref(false)
const importForm = ref({ text: '', pool_group: 'default' })
const importing = ref(false)

const maxAccountsPerDevice = ref(3)
const savingConfig = ref(false)

async function loadMaxAccounts() {
  try {
    const { data: resp } = await client.get('/configs', { params: { scope: 'global' } })
    const list = resp?.data || resp || []
    const found = Array.isArray(list) ? list.find((c: any) => c.key === 'max_accounts_per_device') : null
    if (found) maxAccountsPerDevice.value = Number(found.value) || 3
  } catch { /* use default */ }
}

async function saveMaxAccounts() {
  savingConfig.value = true
  try {
    await client.put('/configs', {
      key: 'max_accounts_per_device',
      value: maxAccountsPerDevice.value,
      scope: 'global',
    })
    ElMessage.success('保存成功')
  } catch {
    ElMessage.error('保存失败')
  } finally {
    savingConfig.value = false
  }
}

const statusTagType = (status: string) => {
  const map: Record<string, string> = {
    active: 'success',
    banned: 'danger',
    suspended: 'warning',
    unknown: 'info',
  }
  return map[status] || 'info'
}

const statusLabel = (status: string) => {
  const map: Record<string, string> = {
    active: '正常',
    banned: '已封号',
    suspended: '已禁用',
    unknown: '未知',
  }
  return map[status] || status
}

async function loadAccounts() {
  await store.fetchAccounts({
    status: filterStatus.value || undefined,
    bound: filterBound.value || undefined,
    page: currentPage.value,
    size: pageSize.value,
  })
}

function handleFilter() {
  currentPage.value = 1
  loadAccounts()
}

function handlePageChange(page: number) {
  currentPage.value = page
  loadAccounts()
}

async function handleImport() {
  if (!importForm.value.text.trim()) {
    ElMessage.warning('请输入账号信息')
    return
  }
  importing.value = true
  try {
    const result = await store.batchImport(importForm.value.text, importForm.value.pool_group)
    ElMessage.success(`导入成功 ${result.imported} 个，跳过 ${result.skipped} 个`)
    if (result.errors?.length) {
      ElMessage.warning(`${result.errors.length} 行格式错误`)
    }
    importVisible.value = false
    importForm.value.text = ''
    await loadAccounts()
    await store.fetchStats()
  } catch (e: any) {
    ElMessage.error(e.message || '导入失败')
  } finally {
    importing.value = false
  }
}

async function handleDisable(acc: AccountItem) {
  try {
    await ElMessageBox.confirm(`确定禁用账号 ${acc.email}？`, '确认')
    await store.disableAccount(acc.id)
    ElMessage.success('已禁用')
    await loadAccounts()
    await store.fetchStats()
  } catch { /* cancelled */ }
}

async function handleEnable(acc: AccountItem) {
  await store.enableAccount(acc.id)
  ElMessage.success('已启用')
  await loadAccounts()
  await store.fetchStats()
}

async function handleUnbind(acc: AccountItem) {
  try {
    await ElMessageBox.confirm(`确定解绑账号 ${acc.email}？`, '确认')
    await store.unbindAccount(acc.id)
    ElMessage.success('已解绑')
    await loadAccounts()
    await store.fetchStats()
  } catch { /* cancelled */ }
}

const distributing = ref(false)
async function handleDistributeAll() {
  try {
    await ElMessageBox.confirm('将未分配的账号自动分配给所有在线设备，确定？', '一键分配')
    distributing.value = true
    const result = await store.distributeAll()
    const devices = result.devices || []
    ElMessage.success(`已分配 ${devices.length} 台设备`)
    await loadAccounts()
    await store.fetchStats()
  } catch { /* cancelled */ } finally {
    distributing.value = false
  }
}

onMounted(() => {
  loadAccounts()
  store.fetchStats()
  loadMaxAccounts()
})
</script>

<template>
  <div class="account-pool">
    <div class="stats-row">
      <el-row :gutter="16">
        <el-col :span="4">
          <el-statistic title="总账号" :value="store.stats.total" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="正常" :value="store.stats.active" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="已分配" :value="store.stats.assigned" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="待分配" :value="store.stats.unassigned" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="已封号" :value="store.stats.banned" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="已禁用" :value="store.stats.suspended" />
        </el-col>
      </el-row>
    </div>

    <el-card class="setting-card">
      <el-space>
        <span style="font-size: 14px; color: #606266">单台设备账号上限：</span>
        <el-input-number v-model="maxAccountsPerDevice" :min="1" :max="50" size="small" style="width: 120px" />
        <el-button type="primary" size="small" :loading="savingConfig" @click="saveMaxAccounts">保存</el-button>
      </el-space>
    </el-card>

    <el-card class="filter-card">
      <el-space>
        <el-select v-model="filterStatus" placeholder="按状态筛选" clearable @change="handleFilter" style="width: 140px">
          <el-option label="全部" value="" />
          <el-option label="正常" value="active" />
          <el-option label="已封号" value="banned" />
          <el-option label="已禁用" value="suspended" />
          <el-option label="未知" value="unknown" />
        </el-select>
        <el-select v-model="filterBound" placeholder="分配状态" clearable @change="handleFilter" style="width: 140px">
          <el-option label="全部" value="" />
          <el-option label="已分配" value="yes" />
          <el-option label="未分配" value="no" />
        </el-select>
        <el-button type="primary" @click="importVisible = true">批量导入</el-button>
        <el-button type="success" :loading="distributing" @click="handleDistributeAll">一键分配</el-button>
      </el-space>
    </el-card>

    <el-table :data="store.accounts" v-loading="store.loading" stripe style="width: 100%">
      <el-table-column prop="email" label="邮箱" min-width="220" show-overflow-tooltip />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="绑定设备" min-width="180">
        <template #default="{ row }">
          <template v-if="row.bound_device_uid">
            <span style="font-family: monospace; font-size: 12px">{{ row.bound_device_uid }}</span>
          </template>
          <span v-else-if="row.bound_device_id" style="color: #999">{{ row.bound_device_id.slice(0, 8) }}…</span>
          <el-tag v-else type="info" size="small">未分配</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="主账号" width="80" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.is_primary" type="success" size="small">是</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="pool_group" label="分组" width="100" />
      <el-table-column label="最后使用" width="170">
        <template #default="{ row }">
          {{ row.last_used_at ? new Date(row.last_used_at).toLocaleString() : '-' }}
        </template>
      </el-table-column>
      <el-table-column label="封号时间" width="170">
        <template #default="{ row }">
          {{ row.banned_at ? new Date(row.banned_at).toLocaleString() : '-' }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="row.status === 'active' || row.status === 'unknown'"
            type="warning"
            size="small"
            text
            @click="handleDisable(row)"
          >禁用</el-button>
          <el-button
            v-if="row.status === 'suspended' || row.status === 'banned'"
            type="success"
            size="small"
            text
            @click="handleEnable(row)"
          >启用</el-button>
          <el-button
            v-if="row.bound_device_id"
            type="danger"
            size="small"
            text
            @click="handleUnbind(row)"
          >解绑</el-button>
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

    <!-- Batch Import Dialog -->
    <el-dialog v-model="importVisible" title="批量导入账号" width="600px" destroy-on-close>
      <el-form label-width="80px">
        <el-form-item label="分组">
          <el-input v-model="importForm.pool_group" placeholder="default" style="width: 200px" />
        </el-form-item>
        <el-form-item label="账号列表">
          <el-input
            v-model="importForm.text"
            type="textarea"
            :rows="12"
            placeholder="每行一个，格式：邮箱----密码&#10;&#10;例如：&#10;user1@example.com----password123&#10;user2@example.com----pass456"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="importVisible = false">取消</el-button>
        <el-button type="primary" :loading="importing" @click="handleImport">导入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.account-pool {
  padding: 0;
}
.stats-row {
  margin-bottom: 20px;
  padding: 16px;
  background: var(--el-bg-color);
  border-radius: 8px;
}
.setting-card {
  margin-bottom: 12px;
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
