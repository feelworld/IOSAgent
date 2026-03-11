<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useScriptStore } from '../stores/script'
import type { ScriptItem, ScriptStep } from '../stores/script'
import ScriptStepForm from '../components/ScriptStepForm.vue'

const store = useScriptStore()

const filterStatus = ref('')
const currentPage = ref(1)
const pageSize = ref(20)

const selectedScript = ref<ScriptItem | null>(null)
const editName = ref('')
const editDescription = ref('')
const editSteps = ref<ScriptStep[]>([])
const editChangelog = ref('')
const isCreating = ref(false)
const saving = ref(false)
const showJson = ref(false)

const rollbackVersion = ref<number>(1)
const showRollbackDialog = ref(false)

const statusOptions = [
  { label: '全部', value: '' },
  { label: '草稿', value: 'draft' },
  { label: '已发布', value: 'published' },
  { label: '已废弃', value: 'deprecated' },
]

const statusTagType = (status: string) => {
  const map: Record<string, string> = {
    draft: 'info',
    published: 'success',
    deprecated: 'danger',
  }
  return map[status] ?? 'info'
}

const statusLabel = (status: string) => {
  const map: Record<string, string> = {
    draft: '草稿',
    published: '已发布',
    deprecated: '已废弃',
  }
  return map[status] ?? status
}

const stepsJson = computed(() => JSON.stringify(editSteps.value, null, 2))

async function loadScripts() {
  await store.fetchScripts({
    status: filterStatus.value || undefined,
    page: currentPage.value,
    size: pageSize.value,
  })
}

function handleFilter() {
  currentPage.value = 1
  loadScripts()
}

function handlePageChange(page: number) {
  currentPage.value = page
  loadScripts()
}

function handleSelect(script: ScriptItem) {
  selectedScript.value = script
  isCreating.value = false
  editName.value = script.name
  editDescription.value = script.description ?? ''
  editChangelog.value = ''
  loadVersionsAndSteps(script.id)
}

async function loadVersionsAndSteps(scriptId: string) {
  await store.fetchVersions(scriptId)
  const current = store.versions.find(
    v => v.version === selectedScript.value?.current_version,
  )
  editSteps.value = current?.steps?.map(s => ({ ...s })) ?? []
}

function handleCreate() {
  isCreating.value = true
  selectedScript.value = null
  editName.value = ''
  editDescription.value = ''
  editSteps.value = [{ action: 'launch_app', target: '', timeout: 30 }]
  editChangelog.value = ''
  store.versions = []
}

function addStep() {
  editSteps.value.push({ action: 'tap', timeout: 30 })
}

function removeStep(idx: number) {
  editSteps.value.splice(idx, 1)
}

function updateStep(idx: number, step: ScriptStep) {
  editSteps.value[idx] = step
}

function moveStep(idx: number, dir: -1 | 1) {
  const target = idx + dir
  if (target < 0 || target >= editSteps.value.length) return
  const arr = editSteps.value
  ;[arr[idx], arr[target]] = [arr[target], arr[idx]]
}

async function handleSave() {
  if (!editName.value.trim()) {
    ElMessage.warning('请输入脚本名称')
    return
  }
  if (editSteps.value.length === 0) {
    ElMessage.warning('请至少添加一个步骤')
    return
  }

  saving.value = true
  try {
    if (isCreating.value) {
      const res = await store.createScript({
        name: editName.value,
        description: editDescription.value || undefined,
        steps: editSteps.value,
      })
      if (res.code === 0) {
        ElMessage.success('脚本创建成功')
        isCreating.value = false
        await loadScripts()
        const created = store.scripts.find(s => s.id === res.data.id)
        if (created) handleSelect(created)
      } else {
        ElMessage.error(res.message || '创建失败')
      }
    } else if (selectedScript.value) {
      const res = await store.updateScript(selectedScript.value.id, {
        steps: editSteps.value,
        changelog: editChangelog.value || undefined,
      })
      if (res.code === 0) {
        ElMessage.success('脚本已更新（新版本已创建）')
        editChangelog.value = ''
        await loadScripts()
        const updated = store.scripts.find(s => s.id === selectedScript.value!.id)
        if (updated) handleSelect(updated)
      } else {
        ElMessage.error(res.message || '更新失败')
      }
    }
  } finally {
    saving.value = false
  }
}

async function handlePublish() {
  if (!selectedScript.value) return
  try {
    await ElMessageBox.confirm('确认发布当前版本？发布后可被设备执行。', '发布脚本', { type: 'warning' })
    const res = await store.publishScript(selectedScript.value.id)
    if (res.code === 0) {
      ElMessage.success('脚本已发布')
      await loadScripts()
      const s = store.scripts.find(s => s.id === selectedScript.value!.id)
      if (s) {
        selectedScript.value = s
      }
    } else {
      ElMessage.error(res.message || '发布失败')
    }
  } catch {
    // dismissed
  }
}

function openRollback() {
  if (!selectedScript.value) return
  rollbackVersion.value = selectedScript.value.current_version
  showRollbackDialog.value = true
}

async function handleRollback() {
  if (!selectedScript.value) return
  try {
    const res = await store.rollbackScript(selectedScript.value.id, rollbackVersion.value)
    if (res.code === 0) {
      ElMessage.success(`已回滚到版本 ${rollbackVersion.value}`)
      showRollbackDialog.value = false
      await loadScripts()
      const s = store.scripts.find(s => s.id === selectedScript.value!.id)
      if (s) handleSelect(s)
    } else {
      ElMessage.error(res.message || '回滚失败')
    }
  } catch {
    // error
  }
}

function formatTime(val: string | null) {
  return val ? new Date(val).toLocaleString() : '-'
}

onMounted(() => {
  loadScripts()
})
</script>

<template>
  <div class="script-editor">
    <el-row :gutter="16">
      <!-- Left: Script List -->
      <el-col :span="9">
        <el-card class="list-card">
          <template #header>
            <div class="list-header">
              <span class="list-title">脚本列表</span>
              <el-button type="primary" size="small" @click="handleCreate">新建脚本</el-button>
            </div>
          </template>

          <el-space style="margin-bottom: 12px">
            <el-select v-model="filterStatus" placeholder="按状态筛选" clearable @change="handleFilter" style="width: 140px" size="small">
              <el-option v-for="opt in statusOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
            </el-select>
          </el-space>

          <el-table
            :data="store.scripts"
            v-loading="store.loading"
            stripe
            highlight-current-row
            size="small"
            @row-click="handleSelect"
            style="width: 100%"
          >
            <el-table-column label="名称" prop="name" min-width="120" show-overflow-tooltip />
            <el-table-column label="状态" width="80">
              <template #default="{ row }">
                <el-tag :type="statusTagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="版本" width="60" align="center">
              <template #default="{ row }">v{{ row.current_version }}</template>
            </el-table-column>
            <el-table-column label="更新时间" width="155">
              <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
            </el-table-column>
          </el-table>

          <div class="pagination">
            <el-pagination
              v-model:current-page="currentPage"
              :page-size="pageSize"
              :total="store.total"
              layout="total, prev, pager, next"
              small
              @current-change="handlePageChange"
            />
          </div>
        </el-card>
      </el-col>

      <!-- Right: Editor -->
      <el-col :span="15">
        <el-card v-if="selectedScript || isCreating" class="editor-card">
          <template #header>
            <div class="editor-header">
              <span>{{ isCreating ? '新建脚本' : `编辑脚本 - ${selectedScript?.name}` }}</span>
              <el-tag v-if="selectedScript" :type="statusTagType(selectedScript.status)" size="small">
                {{ statusLabel(selectedScript.status) }}
              </el-tag>
            </div>
          </template>

          <el-form label-width="80px">
            <el-form-item label="脚本名称">
              <el-input v-model="editName" placeholder="请输入脚本名称" :disabled="!isCreating" />
            </el-form-item>
            <el-form-item label="描述">
              <el-input v-model="editDescription" type="textarea" :rows="2" placeholder="脚本描述（可选）" :disabled="!isCreating" />
            </el-form-item>
            <el-form-item v-if="!isCreating" label="变更说明">
              <el-input v-model="editChangelog" placeholder="本次修改说明（可选，保存时创建新版本）" />
            </el-form-item>
          </el-form>

          <!-- Steps -->
          <div class="steps-section">
            <div class="steps-header">
              <span class="section-title">步骤列表 ({{ editSteps.length }})</span>
              <el-space>
                <el-button size="small" @click="showJson = !showJson">
                  {{ showJson ? '隐藏 JSON' : '查看 JSON' }}
                </el-button>
                <el-button type="primary" size="small" @click="addStep">添加步骤</el-button>
              </el-space>
            </div>

            <div v-if="showJson" class="json-preview">
              <el-input type="textarea" :model-value="stepsJson" :rows="10" readonly />
            </div>

            <div class="steps-list">
              <div v-for="(step, idx) in editSteps" :key="idx" class="step-wrapper">
                <div class="step-move">
                  <el-button size="small" link :disabled="idx === 0" @click="moveStep(idx, -1)">↑</el-button>
                  <el-button size="small" link :disabled="idx === editSteps.length - 1" @click="moveStep(idx, 1)">↓</el-button>
                </div>
                <div class="step-form-wrap">
                  <ScriptStepForm
                    :step="step"
                    :index="idx"
                    @update:step="(v) => updateStep(idx, v)"
                    @remove="removeStep(idx)"
                  />
                </div>
              </div>
            </div>
          </div>

          <!-- Actions -->
          <div class="editor-actions">
            <el-button type="primary" :loading="saving" @click="handleSave">
              {{ isCreating ? '创建' : '保存（创建新版本）' }}
            </el-button>
            <el-button
              v-if="selectedScript && selectedScript.status !== 'published'"
              type="success"
              @click="handlePublish"
            >
              发布
            </el-button>
            <el-button v-if="selectedScript" @click="openRollback">回滚版本</el-button>
          </div>

          <!-- Version History -->
          <div v-if="!isCreating && store.versions.length > 0" class="version-section">
            <div class="section-title" style="margin-bottom: 12px">版本历史</div>
            <el-timeline>
              <el-timeline-item
                v-for="v in store.versions"
                :key="v.id"
                :timestamp="formatTime(v.created_at)"
                placement="top"
                :type="v.version === selectedScript?.current_version ? 'primary' : undefined"
              >
                <div class="version-item">
                  <strong>v{{ v.version }}</strong>
                  <el-tag v-if="v.version === selectedScript?.current_version" type="primary" size="small" style="margin-left: 8px">当前</el-tag>
                  <el-tag v-if="v.published_at" type="success" size="small" style="margin-left: 4px">已发布</el-tag>
                </div>
                <div v-if="v.changelog" class="version-changelog">{{ v.changelog }}</div>
                <div class="version-meta">{{ v.steps.length }} 个步骤</div>
              </el-timeline-item>
            </el-timeline>
          </div>
        </el-card>

        <el-empty v-else description="请选择或新建一个脚本" />
      </el-col>
    </el-row>

    <!-- Rollback Dialog -->
    <el-dialog v-model="showRollbackDialog" title="回滚脚本版本" width="400px">
      <el-form label-width="80px">
        <el-form-item label="目标版本">
          <el-select v-model="rollbackVersion" style="width: 100%">
            <el-option
              v-for="v in store.versions"
              :key="v.version"
              :label="`v${v.version}${v.changelog ? ' - ' + v.changelog : ''}`"
              :value="v.version"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showRollbackDialog = false">取消</el-button>
        <el-button type="primary" @click="handleRollback">确认回滚</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.script-editor {
  padding: 0;
}
.list-card, .editor-card {
  height: calc(100vh - 120px);
  overflow-y: auto;
}
.list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.list-title {
  font-weight: 600;
  font-size: 15px;
}
.editor-header {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 600;
  font-size: 15px;
}
.pagination {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
.steps-section {
  margin-top: 16px;
}
.steps-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.section-title {
  font-weight: 600;
  font-size: 14px;
}
.json-preview {
  margin-bottom: 12px;
}
.steps-list {
  max-height: 400px;
  overflow-y: auto;
}
.step-wrapper {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}
.step-move {
  display: flex;
  flex-direction: column;
  padding-top: 36px;
}
.step-form-wrap {
  flex: 1;
}
.editor-actions {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--el-border-color-lighter);
}
.version-section {
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid var(--el-border-color-lighter);
}
.version-item {
  display: flex;
  align-items: center;
}
.version-changelog {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  margin-top: 4px;
}
.version-meta {
  color: var(--el-text-color-placeholder);
  font-size: 12px;
  margin-top: 2px;
}
</style>
