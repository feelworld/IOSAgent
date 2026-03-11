<script setup lang="ts">
import { computed } from 'vue'
import type { ScriptStep } from '../stores/script'

const props = defineProps<{
  step: ScriptStep
  index: number
}>()

const emit = defineEmits<{
  'update:step': [value: ScriptStep]
  remove: []
}>()

const actionOptions = [
  { label: '启动应用', value: 'launch_app' },
  { label: '点击', value: 'tap' },
  { label: '输入文字', value: 'type' },
  { label: '滑动', value: 'swipe' },
  { label: '等待', value: 'wait' },
  { label: '搜索', value: 'search' },
  { label: '滚动', value: 'scroll' },
  { label: '截图', value: 'screenshot' },
  { label: '返回', value: 'back' },
  { label: '回到桌面', value: 'home' },
  { label: '查找元素', value: 'find_element' },
  { label: '断言存在', value: 'assert_exists' },
  { label: '断言不存在', value: 'assert_not_exists' },
  { label: '条件判断', value: 'conditional' },
]

const needsTarget = computed(() => {
  return ['tap', 'type', 'swipe', 'search', 'find_element',
    'assert_exists', 'assert_not_exists', 'launch_app'].includes(props.step.action)
})

const paramsJson = computed({
  get: () => props.step.params ? JSON.stringify(props.step.params, null, 2) : '',
  set: (val: string) => {
    try {
      const parsed = val.trim() ? JSON.parse(val) : undefined
      update({ params: parsed })
    } catch {
      // invalid JSON, ignore
    }
  },
})

function update(partial: Partial<ScriptStep>) {
  emit('update:step', { ...props.step, ...partial })
}
</script>

<template>
  <el-card shadow="never" class="step-card">
    <template #header>
      <div class="step-header">
        <span class="step-index">步骤 {{ index + 1 }}</span>
        <el-button type="danger" link size="small" @click="emit('remove')">
          删除
        </el-button>
      </div>
    </template>

    <el-form label-width="80px" size="default">
      <el-form-item label="动作">
        <el-select
          :model-value="step.action"
          placeholder="选择动作类型"
          style="width: 100%"
          @update:model-value="(v: string) => update({ action: v })"
        >
          <el-option
            v-for="opt in actionOptions"
            :key="opt.value"
            :label="opt.label"
            :value="opt.value"
          />
        </el-select>
      </el-form-item>

      <el-form-item v-if="needsTarget" label="目标">
        <el-input
          :model-value="step.target ?? ''"
          placeholder="元素定位 / 应用标识"
          @update:model-value="(v: string) => update({ target: v || undefined })"
        />
      </el-form-item>

      <el-form-item label="超时(秒)">
        <el-input-number
          :model-value="step.timeout ?? 30"
          :min="1"
          :max="600"
          @update:model-value="(v: number) => update({ timeout: v })"
        />
      </el-form-item>

      <el-form-item label="参数">
        <el-input
          v-model="paramsJson"
          type="textarea"
          :rows="3"
          placeholder='JSON 格式参数，如 {"key": "value"}'
        />
      </el-form-item>
    </el-form>
  </el-card>
</template>

<style scoped>
.step-card {
  margin-bottom: 12px;
}
.step-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.step-index {
  font-weight: 600;
  font-size: 14px;
}
</style>
