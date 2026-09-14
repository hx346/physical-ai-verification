<template>
  <div>
    <a-typography-title :level="4">实验引擎 Experiment</a-typography-title>
    <a-alert type="info" show-icon style="margin-bottom: 16px"
             message="LHS / 蒙特卡洛采样 × 解析内核逐样本求值；敏感性为一阶 Sobol（SALib）" />

    <a-space style="margin-bottom: 16px" wrap>
      <a-select v-model:value="projectId" style="width: 240px" placeholder="选择项目" :options="projectOptions"
                @change="loadSystems" />
      <a-select v-model:value="systemConfigId" style="width: 240px" placeholder="选择系统配置"
                :options="systemOptions" :disabled="!projectId" />
      <a-input-number v-model:value="n" :min="100" :max="10000" :step="100" style="width: 120px" />
      <a-button type="primary" :loading="creating" :disabled="!projectId || !systemConfigId" @click="create">
        运行实验
      </a-button>
    </a-space>

    <a-spin :spinning="polling">
      <template v-if="jobStatus">
        <a-tag :color="jobColor(jobStatus)">{{ jobStatus }}</a-tag>
        <span style="margin-left: 8px; color: #888">{{ jobKey }}</span>
      </template>

      <template v-if="aggregates">
        <a-row :gutter="16" style="margin-top: 16px">
          <a-col v-for="card in aggCards" :key="card.label" :span="6">
            <a-card size="small">
              <a-statistic :title="card.label" :value="card.value" :precision="4" />
            </a-card>
          </a-col>
        </a-row>

        <a-typography-paragraph style="margin-top: 20px"><b>敏感性排名（一阶 Sobol / 主导失败因子）</b></a-typography-paragraph>
        <div v-for="s in sensitivity" :key="s.name" style="margin: 4px 0; max-width: 560px">
          <span style="display: inline-block; width: 160px">{{ s.name }}</span>
          <a-progress :percent="Math.round((s.share ?? 0) * 100)" size="small"
                      style="display: inline-block; width: 340px" />
        </div>
        <a-typography-text type="secondary">
          证据：{{ evidenceId }}（type=experiment，已入 Evidence Store）
        </a-typography-text>
      </template>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { message } from 'ant-design-vue'
import { http } from '../api/http'

interface Project { id: string; name: string }
interface SystemConf { id: string; name?: string; ir?: { name?: string } }

const projects = ref<Project[]>([])
const systems = ref<SystemConf[]>([])
const projectId = ref('')
const systemConfigId = ref('')
const n = ref(1000)
const creating = ref(false)
const polling = ref(false)
const jobKey = ref('')
const jobStatus = ref('')
const evidenceId = ref('')
const result = ref<Record<string, number> | null>(null)

const projectOptions = computed(() => projects.value.map((p) => ({ value: p.id, label: p.name })))
const systemOptions = computed(() =>
  systems.value.map((s, i) => ({ value: s.id, label: s.ir?.name || s.name || `system-${i + 1}` })))

const aggregates = computed(() => result.value)
const sensitivity = computed<{ name: string; share: number }[]>(() => sensList.value)
const sensList = ref<{ name: string; share: number }[]>([])

const aggCards = computed(() => {
  const a = result.value ?? {}
  return [
    { label: '成功率均值', value: a.success_rate_mean ?? 0 },
    { label: '成功率 P5', value: a.success_rate_P5 ?? 0 },
    { label: '定位精度 P95 均值 (mm)', value: a.accuracy_p95_mean_mm ?? 0 },
    { label: '样本数', value: a.samples ?? 0 },
  ]
})

let timer: number | undefined

onMounted(async () => {
  projects.value = await http.get<Project[]>('/api/projects')
})

onUnmounted(() => clearInterval(timer))

async function loadSystems() {
  systemConfigId.value = ''
  if (!projectId.value) return
  systems.value = await http.get<SystemConf[]>(`/api/projects/${projectId.value}/systems`)
}

async function create() {
  creating.value = true
  try {
    const r = await http.post<{ jobKey: string }>('/api/experiments', {
      projectId: projectId.value, systemConfigId: systemConfigId.value, n: n.value, method: 'lhs',
    })
    jobKey.value = r.jobKey
    jobStatus.value = 'QUEUED'
    result.value = null
    sensList.value = []
    evidenceId.value = ''
    polling.value = true
    timer = window.setInterval(poll, 3000)
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    creating.value = false
  }
}

async function poll() {
  try {
    const r = await http.get<{ jobKey: string; status: string; result?: { aggregates?: Record<string, number>; sensitivity?: { name: string; share: number }[] }; evidenceId?: string; lastError?: string }>(
      `/api/experiments/${jobKey.value}`)
    jobStatus.value = r.status
    if (r.status === 'FAILED') {
      polling.value = false
      clearInterval(timer)
      message.error(`实验失败：${r.lastError ?? ''}`)
      return
    }
    if (r.result?.aggregates) {
      result.value = r.result.aggregates
      sensList.value = r.result.sensitivity ?? []
      evidenceId.value = r.evidenceId ?? ''
      polling.value = false
      clearInterval(timer)
    }
  } catch (e) {
    polling.value = false
    clearInterval(timer)
    message.error((e as Error).message)
  }
}

function jobColor(s: string): string {
  if (s === 'SUCCEEDED') return 'green'
  if (s === 'FAILED') return 'red'
  return 'blue'
}
</script>
