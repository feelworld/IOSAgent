<script setup lang="ts">
import { ref, reactive, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import {
  getConfigs,
  updateConfigs,
  getDeviceGroups,
  getDevices,
  type ConfigItem,
} from '../api/config'

type Scope = 'global' | 'device_group' | 'device'

const PRESET_CONFIGS: Omit<ConfigItem, 'scope' | 'scope_id'>[] = [
  { key: 'heartbeat_interval', value: 30, description: '心跳间隔（秒）' },
  { key: 'heartbeat_timeout', value: 90, description: '心跳超时（秒）' },
  { key: 'script_timeout', value: 300, description: '脚本执行超时（秒）' },
  { key: 'max_retries', value: 3, description: '最大重试次数' },
  { key: 'command_expire_seconds', value: 3600, description: '指令过期时间（秒）' },
]

const activeScope = ref<Scope>('global')
const scopeId = ref('')
const loading = ref(false)
const saving = ref(false)
const configs = ref<ConfigItem[]>([])
const editingRow = ref<string | null>(null)
const editValue = ref<string | number>('')

const deviceGroups = ref<{ id: string; name: string }[]>([])
const deviceList = ref<{ id: string; device_uid: string; name: string }[]>([])

const addDialogVisible = ref(false)
const addForm = reactive<{ key: string; value: string; description: string }>({
  key: '',
  value: '',
  description: '',
})

function buildDefaults(): ConfigItem[] {
  return PRESET_CONFIGS.map((p) => ({
    ...p,
    scope: activeScope.value,
    scope_id: activeScope.value === 'global' ? undefined : scopeId.value,
  }))
}

async function loadConfigs() {
  loading.value = true
  try {
    const params: { scope: string; scope_id?: string } = { scope: activeScope.value }
    if (activeScope.value !== 'global' && scopeId.value) {
      params.scope_id = scopeId.value
    }
    if (activeScope.value !== 'global' && !scopeId.value) {
      configs.value = buildDefaults()
      return
    }
    const data = await getConfigs(params)
    if (data.length) {
      configs.value = data
    } else {
      configs.value = buildDefaults()
    }
  } catch {
    configs.value = buildDefaults()
  } finally {
    loading.value = false
  }
}

async function loadScopeOptions() {
  try {
    if (activeScope.value === 'device_group') {
      deviceGroups.value = await getDeviceGroups()
    } else if (activeScope.value === 'device') {
      deviceList.value = await getDevices()
    }
  } catch {
    ElMessage.warning('加载选项失败')
  }
}

function handleScopeChange(scope: Scope) {
  activeScope.value = scope
  scopeId.value = ''
  if (scope === 'global') {
    loadConfigs()
  } else {
    loadScopeOptions()
    configs.value = []
  }
}

function handleScopeIdChange() {
  if (scopeId.value) {
    loadConfigs()
  }
}

function startEdit(row: ConfigItem) {
  editingRow.value = row.key
  editValue.value = row.value
}

function cancelEdit() {
  editingRow.value = null
  editValue.value = ''
}

function confirmEdit(row: ConfigItem) {
  row.value = editValue.value
  editingRow.value = null
  editValue.value = ''
}

function openAddDialog() {
  addForm.key = ''
  addForm.value = ''
  addForm.description = ''
  addDialogVisible.value = true
}

function handleAdd() {
  if (!addForm.key.trim()) {
    ElMessage.warning('请输入配置键')
    return
  }
  if (configs.value.some((c) => c.key === addForm.key.trim())) {
    ElMessage.warning('配置键已存在')
    return
  }
  configs.value.push({
    key: addForm.key.trim(),
    value: addForm.value,
    description: addForm.description,
    scope: activeScope.value,
    scope_id: activeScope.value === 'global' ? undefined : scopeId.value,
  })
  addDialogVisible.value = false
  ElMessage.success('已添加，请点击保存提交')
}

async function handleDelete(row: ConfigItem) {
  try {
    await ElMessageBox.confirm(`确定删除配置「${row.key}」？`, '确认删除', {
      type: 'warning',
    })
    configs.value = configs.value.filter((c) => c.key !== row.key)
    ElMessage.success('已删除，请点击保存提交')
  } catch {
    // cancelled
  }
}

async function handleSave() {
  saving.value = true
  try {
    await updateConfigs(configs.value)
    ElMessage.success('配置已保存')
    await loadConfigs()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

function formatDate(val?: string) {
  if (!val) return '-'
  return new Date(val).toLocaleString()
}

watch(scopeId, handleScopeIdChange)

onMounted(() => {
  loadConfigs()
})
</script>

<template>
  <div class="config-panel">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>系统配置</span>
          <el-space>
            <el-button :icon="Plus" @click="openAddDialog">新增配置</el-button>
            <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
          </el-space>
        </div>
      </template>

      <div class="scope-bar">
        <el-tabs v-model="activeScope" @tab-change="handleScopeChange">
          <el-tab-pane label="全局配置" name="global" />
          <el-tab-pane label="设备组配置" name="device_group" />
          <el-tab-pane label="设备配置" name="device" />
        </el-tabs>

        <div v-if="activeScope === 'device_group'" class="scope-selector">
          <el-select v-model="scopeId" placeholder="选择设备组" clearable filterable style="width: 280px">
            <el-option
              v-for="g in deviceGroups"
              :key="g.id"
              :label="g.name"
              :value="g.id"
            />
          </el-select>
        </div>

        <div v-if="activeScope === 'device'" class="scope-selector">
          <el-select v-model="scopeId" placeholder="选择设备" clearable filterable style="width: 280px">
            <el-option
              v-for="d in deviceList"
              :key="d.id"
              :label="`${d.name || d.device_uid}`"
              :value="d.id"
            />
          </el-select>
        </div>
      </div>

      <el-table :data="configs" v-loading="loading" stripe style="width: 100%">
        <el-table-column prop="key" label="配置键" width="220" />
        <el-table-column label="值" min-width="200">
          <template #default="{ row }">
            <template v-if="editingRow === row.key">
              <el-space>
                <el-input v-model="editValue" size="small" style="width: 200px" @keyup.enter="confirmEdit(row)" />
                <el-button size="small" type="primary" @click="confirmEdit(row)">确定</el-button>
                <el-button size="small" @click="cancelEdit">取消</el-button>
              </el-space>
            </template>
            <template v-else>
              <span class="editable-cell" @click="startEdit(row)">{{ row.value }}</span>
            </template>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="说明" min-width="200" />
        <el-table-column label="更新时间" width="180">
          <template #default="{ row }">
            {{ formatDate(row.updated_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }">
            <el-button type="danger" link size="small" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="addDialogVisible" title="新增配置" width="480px" destroy-on-close>
      <el-form label-width="80px">
        <el-form-item label="配置键">
          <el-input v-model="addForm.key" placeholder="例如: heartbeat_interval" />
        </el-form-item>
        <el-form-item label="值">
          <el-input v-model="addForm.value" placeholder="配置值" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="addForm.description" placeholder="配置说明" />
        </el-form-item>
        <el-form-item label="作用域">
          <el-tag>{{ activeScope === 'global' ? '全局' : activeScope === 'device_group' ? '设备组' : '设备' }}</el-tag>
          <span v-if="scopeId" style="margin-left: 8px">
            <el-tag type="info">{{ scopeId }}</el-tag>
          </span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleAdd">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.config-panel {
  padding: 0;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.scope-bar {
  margin-bottom: 16px;
}
.scope-selector {
  margin-top: -8px;
  margin-bottom: 12px;
}
.editable-cell {
  cursor: pointer;
  padding: 2px 8px;
  border-radius: 4px;
  transition: background-color 0.2s;
}
.editable-cell:hover {
  background-color: var(--el-fill-color-light);
}
</style>
