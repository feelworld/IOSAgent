<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useStrategyStore } from '../stores/strategy'
import { useDeviceStore } from '../stores/device'
import ExploreAnalysis from '../components/ExploreAnalysis.vue'

const store = useStrategyStore()
const deviceStore = useDeviceStore()

const activeTab = ref('explore')

// --- Explore ---
const exploreForm = ref({
  script_id: '',
  script_version: 1,
  device_count: 3,
  rounds: 5,
  param_variations_json: '',
})
const exploreLoading = ref(false)
const analysisSessionId = ref('')

async function handleStartExplore() {
  if (!exploreForm.value.script_id) {
    ElMessage.warning('请输入脚本 ID')
    return
  }
  let variations: Record<string, any>[] = []
  if (exploreForm.value.param_variations_json.trim()) {
    try {
      variations = JSON.parse(exploreForm.value.param_variations_json)
      if (!Array.isArray(variations)) {
        ElMessage.error('参数变体必须为 JSON 数组')
        return
      }
    } catch {
      ElMessage.error('参数变体 JSON 格式不正确')
      return
    }
  }
  exploreLoading.value = true
  try {
    const res = await store.startExplore({
      script_id: exploreForm.value.script_id,
      script_version: exploreForm.value.script_version,
      device_count: exploreForm.value.device_count,
      rounds: exploreForm.value.rounds,
      param_variations: variations,
    })
    if (res.code === 0) {
      ElMessage.success('探索已启动')
      analysisSessionId.value = store.activeExploreSessionId || ''
    } else {
      ElMessage.error(res.message || '启动失败')
    }
  } catch (e: any) {
    ElMessage.error(e.message || '启动失败')
  } finally {
    exploreLoading.value = false
  }
}

async function handleStopExplore() {
  if (!store.activeExploreSessionId) return
  try {
    const res = await store.stopExplore(store.activeExploreSessionId)
    if (res.code === 0) {
      ElMessage.success('探索已停止')
    } else {
      ElMessage.error(res.message || '停止失败')
    }
  } catch (e: any) {
    ElMessage.error(e.message || '停止失败')
  }
}

async function handleLoadAnalysis() {
  if (!analysisSessionId.value) {
    ElMessage.warning('请输入或等待探索会话 ID')
    return
  }
  await store.getAnalysis(analysisSessionId.value)
}

// --- Execute ---
const selectedStrategyIds = ref<string[]>([])
const executeDeviceMode = ref<'all' | 'specific'>('all')
const selectedDeviceIds = ref<string[]>([])
const executeLoading = ref(false)

const exploreStrategies = computed(() => store.strategies.filter(s => s.phase === 'explore'))
const executeStrategies = computed(() => store.strategies.filter(s => s.phase === 'execute'))

const analysisStrategies = computed(() => store.analysis?.strategies || [])
const recommendedIds = computed(() => store.analysis?.recommended_strategies || [])

function handleStrategySelect(ids: string[]) {
  selectedStrategyIds.value = ids
}

async function handleStartExecute() {
  if (!selectedStrategyIds.value.length) {
    ElMessage.warning('请选择至少一个策略')
    return
  }
  executeLoading.value = true
  try {
    const payload: any = { strategy_ids: selectedStrategyIds.value }
    if (executeDeviceMode.value === 'all') {
      payload.all_devices = true
    } else {
      payload.device_ids = selectedDeviceIds.value
    }
    const res = await store.startExecute(payload)
    if (res.code === 0) {
      ElMessage.success('实施已启动')
      store.fetchStrategies({ phase: 'execute' })
    } else {
      ElMessage.error(res.message || '启动失败')
    }
  } catch (e: any) {
    ElMessage.error(e.message || '启动失败')
  } finally {
    executeLoading.value = false
  }
}

const currentPage = ref(1)
const pageSize = ref(20)

async function loadStrategies() {
  const phase = activeTab.value === 'explore' ? 'explore' : 'execute'
  await store.fetchStrategies({ phase, page: currentPage.value, size: pageSize.value })
}

function handleTabChange() {
  currentPage.value = 1
  loadStrategies()
}

function handlePageChange(page: number) {
  currentPage.value = page
  loadStrategies()
}

const statusTagType = (status: string) => {
  const map: Record<string, string> = {
    active: 'success',
    paused: 'warning',
    completed: 'info',
    abandoned: 'danger',
  }
  return map[status] || 'info'
}

onMounted(() => {
  loadStrategies()
  deviceStore.fetchDevices({ size: 200 })
  store.setupWsHandlers()
})
</script>

<template>
  <div class="strategy-manager">
    <el-tabs v-model="activeTab" @tab-change="handleTabChange">
      <!-- 探索阶段 -->
      <el-tab-pane label="探索阶段" name="explore">
        <el-row :gutter="20">
          <el-col :span="10">
            <el-card shadow="never">
              <template #header><span>探索配置</span></template>
              <el-form label-width="110px" size="default">
                <el-form-item label="脚本 ID">
                  <el-input v-model="exploreForm.script_id" placeholder="输入脚本 ID" />
                </el-form-item>
                <el-form-item label="脚本版本">
                  <el-input-number v-model="exploreForm.script_version" :min="1" />
                </el-form-item>
                <el-form-item label="设备数量">
                  <el-input-number v-model="exploreForm.device_count" :min="1" :max="50" />
                </el-form-item>
                <el-form-item label="探索轮次">
                  <el-input-number v-model="exploreForm.rounds" :min="1" :max="100" />
                </el-form-item>
                <el-form-item label="参数变体 (JSON)">
                  <el-input
                    v-model="exploreForm.param_variations_json"
                    type="textarea"
                    :rows="5"
                    placeholder='[{"keyword":"app1"},{"keyword":"app2"}]'
                  />
                </el-form-item>
                <el-form-item>
                  <el-space>
                    <el-button
                      type="primary"
                      :loading="exploreLoading"
                      :disabled="!!store.activeExploreSessionId"
                      @click="handleStartExplore"
                    >
                      启动探索
                    </el-button>
                    <el-button
                      type="danger"
                      :disabled="!store.activeExploreSessionId"
                      @click="handleStopExplore"
                    >
                      停止探索
                    </el-button>
                  </el-space>
                </el-form-item>
              </el-form>
              <el-alert
                v-if="store.activeExploreSessionId"
                :title="`探索会话: ${store.activeExploreSessionId}`"
                type="info"
                show-icon
                :closable="false"
                style="margin-top: 8px"
              />
            </el-card>
          </el-col>

          <el-col :span="14">
            <el-card shadow="never">
              <template #header>
                <div style="display: flex; align-items: center; justify-content: space-between">
                  <span>分析结果</span>
                  <el-space>
                    <el-input
                      v-model="analysisSessionId"
                      placeholder="探索会话 ID"
                      style="width: 220px"
                      size="small"
                    />
                    <el-button size="small" type="primary" :loading="store.analysisLoading" @click="handleLoadAnalysis">
                      加载分析
                    </el-button>
                  </el-space>
                </div>
              </template>

              <template v-if="store.analysis">
                <p style="margin-bottom: 12px; color: var(--el-text-color-secondary)">
                  总执行次数: {{ store.analysis.total_executions }}
                  &nbsp;|&nbsp;策略数: {{ store.analysis.strategies.length }}
                  &nbsp;|&nbsp;推荐: {{ store.analysis.recommended_strategies.length }}
                </p>
                <ExploreAnalysis
                  :strategies="analysisStrategies"
                  :recommended="recommendedIds"
                />
                <el-table :data="analysisStrategies" stripe style="margin-top: 16px" size="small">
                  <el-table-column label="#" width="50">
                    <template #default="{ $index }">{{ $index + 1 }}</template>
                  </el-table-column>
                  <el-table-column label="参数" min-width="160">
                    <template #default="{ row }">
                      <code>{{ JSON.stringify(row.params) }}</code>
                    </template>
                  </el-table-column>
                  <el-table-column prop="executions" label="执行次数" width="100" />
                  <el-table-column label="成功率" width="100">
                    <template #default="{ row }">
                      {{ (row.success_rate * 100).toFixed(1) }}%
                    </template>
                  </el-table-column>
                  <el-table-column prop="total_downloads" label="下载量" width="90" />
                  <el-table-column label="效果评分" width="100">
                    <template #default="{ row }">
                      <el-tag :type="recommendedIds.includes(row.id) ? 'success' : 'info'" size="small">
                        {{ row.effectiveness_score.toFixed(2) }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="推荐" width="70" align="center">
                    <template #default="{ row }">
                      <el-icon v-if="recommendedIds.includes(row.id)" color="#67C23A"><i class="el-icon-check" /></el-icon>
                    </template>
                  </el-table-column>
                </el-table>
              </template>
              <el-empty v-else description="暂无分析数据" />
            </el-card>
          </el-col>
        </el-row>

        <el-card shadow="never" style="margin-top: 16px">
          <template #header><span>探索阶段策略列表</span></template>
          <el-table :data="exploreStrategies" v-loading="store.loading" stripe>
            <el-table-column prop="name" label="名称" width="140" />
            <el-table-column prop="script_id" label="脚本 ID" width="140" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="statusTagType(row.status)" size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="effectiveness_score" label="效果评分" width="110">
              <template #default="{ row }">{{ row.effectiveness_score.toFixed(2) }}</template>
            </el-table-column>
            <el-table-column prop="total_executions" label="总执行" width="90" />
            <el-table-column prop="successful_executions" label="成功" width="80" />
            <el-table-column prop="total_downloads" label="下载量" width="90" />
            <el-table-column label="创建时间" min-width="170">
              <template #default="{ row }">{{ new Date(row.created_at).toLocaleString() }}</template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- 实施阶段 -->
      <el-tab-pane label="实施阶段" name="execute">
        <el-row :gutter="20">
          <el-col :span="16">
            <el-card shadow="never">
              <template #header><span>选择策略并实施</span></template>
              <template v-if="analysisStrategies.length">
                <el-checkbox-group v-model="selectedStrategyIds" @change="handleStrategySelect">
                  <el-table :data="analysisStrategies" stripe size="small">
                    <el-table-column width="50">
                      <template #default="{ row }">
                        <el-checkbox :value="row.id" />
                      </template>
                    </el-table-column>
                    <el-table-column label="参数" min-width="160">
                      <template #default="{ row }">
                        <code>{{ JSON.stringify(row.params) }}</code>
                      </template>
                    </el-table-column>
                    <el-table-column prop="effectiveness_score" label="效果评分" width="110">
                      <template #default="{ row }">{{ row.effectiveness_score.toFixed(2) }}</template>
                    </el-table-column>
                    <el-table-column label="成功率" width="100">
                      <template #default="{ row }">{{ (row.success_rate * 100).toFixed(1) }}%</template>
                    </el-table-column>
                    <el-table-column prop="total_downloads" label="下载量" width="90" />
                  </el-table>
                </el-checkbox-group>
              </template>
              <el-empty v-else description="请先在探索阶段获取分析结果" />
            </el-card>
          </el-col>

          <el-col :span="8">
            <el-card shadow="never">
              <template #header><span>设备选择</span></template>
              <el-radio-group v-model="executeDeviceMode" style="margin-bottom: 12px">
                <el-radio value="all">全部设备</el-radio>
                <el-radio value="specific">指定设备</el-radio>
              </el-radio-group>
              <template v-if="executeDeviceMode === 'specific'">
                <el-checkbox-group v-model="selectedDeviceIds">
                  <div v-for="d in deviceStore.devices" :key="d.id" style="margin-bottom: 4px">
                    <el-checkbox :value="d.id">
                      {{ d.device_uid.slice(0, 12) }} ({{ d.status }})
                    </el-checkbox>
                  </div>
                </el-checkbox-group>
              </template>
              <el-button
                type="primary"
                :loading="executeLoading"
                :disabled="!selectedStrategyIds.length"
                style="margin-top: 16px; width: 100%"
                @click="handleStartExecute"
              >
                启动实施
              </el-button>
            </el-card>
          </el-col>
        </el-row>

        <el-card shadow="never" style="margin-top: 16px">
          <template #header><span>实施阶段策略列表</span></template>
          <el-table :data="executeStrategies" v-loading="store.loading" stripe>
            <el-table-column prop="name" label="名称" width="140" />
            <el-table-column prop="script_id" label="脚本 ID" width="140" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="statusTagType(row.status)" size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="effectiveness_score" label="效果评分" width="110">
              <template #default="{ row }">{{ row.effectiveness_score.toFixed(2) }}</template>
            </el-table-column>
            <el-table-column prop="total_executions" label="总执行" width="90" />
            <el-table-column prop="successful_executions" label="成功" width="80" />
            <el-table-column prop="total_downloads" label="下载量" width="90" />
            <el-table-column label="创建时间" min-width="170">
              <template #default="{ row }">{{ new Date(row.created_at).toLocaleString() }}</template>
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
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.strategy-manager {
  padding: 0;
}
.pagination {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
</style>
