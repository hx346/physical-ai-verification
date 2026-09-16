<template>
  <div>
    <a-typography-title :level="4">实验平台 Experiment</a-typography-title>

    <a-space style="margin-bottom: 16px" wrap>
      <a-select v-model:value="projectId" style="width: 260px" placeholder="选择项目"
                :options="projectOptions" @change="onProjectChange" />
      <a-button :disabled="!projectId" @click="refresh">刷新</a-button>
    </a-space>

    <a-tabs v-model:activeKey="tab">
      <!-- ==================== 批次 ==================== -->
      <a-tab-pane key="batches" tab="批次">
        <a-space style="margin-bottom: 12px" wrap>
          <a-select v-model:value="newBackend" style="width: 120px"
                    :options="[{ value: 'analytic', label: '解析' }, { value: 'simulator', label: '仿真' }]" />
          <a-select v-model:value="newSystemId" style="width: 260px" placeholder="系统配置"
                    :options="systemOptions" :disabled="!projectId" />
          <a-input-number v-model:value="newN" :min="1" :max="10000" :step="50" style="width: 110px" />
          <a-button type="primary" :loading="creating" :disabled="!projectId || !newSystemId" @click="createBatch">
            发起批次
          </a-button>
          <a-typography-text type="secondary">
            仿真批次并行编排（sim-worker × N），进度实时可见
          </a-typography-text>
        </a-space>

        <a-table :data-source="batches" row-key="jobKey" size="small" :pagination="{ pageSize: 10 }">
          <a-table-column title="批次" data-index="jobKey" :width="300">
            <template #default="{ text }"><code style="font-size: 12px">{{ text }}</code></template>
          </a-table-column>
          <a-table-column title="后端" data-index="backend" :width="80">
            <template #default="{ text }">
              <a-tag :color="text === 'simulator' ? 'purple' : 'blue'">{{ text === 'simulator' ? '仿真' : '解析' }}</a-tag>
            </template>
          </a-table-column>
          <a-table-column title="n" data-index="n" :width="60" />
          <a-table-column title="状态" data-index="status" :width="170">
            <template #default="{ record }">
              <a-space size="small">
                <a-tag :color="statusColor(record.status)">{{ record.status }}</a-tag>
                <a-progress v-if="record.progress && record.status === 'RUNNING'"
                            :percent="Math.round((record.progress.done / record.progress.total) * 100)"
                            size="small" style="width: 80px" />
              </a-space>
            </template>
          </a-table-column>
          <a-table-column title="证据" data-index="evidenceId" :width="90" />
          <a-table-column title="创建" data-index="createdAt" :width="180">
            <template #default="{ text }">{{ (text ?? '').slice(0, 19) }}</template>
          </a-table-column>
          <a-table-column :width="90">
            <template #default="{ record }">
              <a @click="openBatch(record)">查看</a>
            </template>
          </a-table-column>
        </a-table>
      </a-tab-pane>

      <!-- ==================== 对照 ==================== -->
      <a-tab-pane key="comparisons" tab="对照">
        <a-space style="margin-bottom: 12px" wrap>
          <a-select v-model:value="cmpSystems" mode="multiple" style="min-width: 380px"
                    placeholder="选择 2-5 个系统配置（首项为基准臂）" :options="systemOptions" :disabled="!projectId" />
          <a-select v-model:value="cmpBackend" style="width: 120px"
                    :options="[{ value: 'analytic', label: '解析' }, { value: 'simulator', label: '仿真' }]" />
          <a-input-number v-model:value="cmpN" :min="10" :max="10000" :step="50" style="width: 110px" />
          <a-button type="primary" :loading="cmpCreating"
                    :disabled="!projectId || cmpSystems.length < 2" @click="createComparison">
            发起对照
          </a-button>
          <a-typography-text type="secondary">同 seed 配对采样：run i 各臂参数相同，差异归因系统配置</a-typography-text>
        </a-space>

        <a-table :data-source="comparisons" row-key="comparisonKey" size="small" :pagination="{ pageSize: 10 }">
          <a-table-column title="对照" data-index="comparisonKey" :width="240">
            <template #default="{ text }"><code style="font-size: 12px">{{ text }}</code></template>
          </a-table-column>
          <a-table-column title="标签" data-index="label" :width="160" />
          <a-table-column title="后端" data-index="backend" :width="80">
            <template #default="{ text }">
              <a-tag :color="text === 'simulator' ? 'purple' : 'blue'">{{ text === 'simulator' ? '仿真' : '解析' }}</a-tag>
            </template>
          </a-table-column>
          <a-table-column title="臂数" data-index="armCount" :width="70" />
          <a-table-column title="证据" data-index="evidenceId" :width="90" />
          <a-table-column title="创建" data-index="createdAt" :width="180">
            <template #default="{ text }">{{ (text ?? '').slice(0, 19) }}</template>
          </a-table-column>
          <a-table-column :width="90">
            <template #default="{ record }">
              <a @click="openComparison(record)">查看</a>
            </template>
          </a-table-column>
        </a-table>
      </a-tab-pane>
    </a-tabs>

    <!-- 批次下钻 -->
    <a-drawer v-model:open="batchDrawer" width="620" :title="`批次 ${drawerBatch?.jobKey ?? ''}`">
      <template v-if="drawerBatch">
        <a-space style="margin-bottom: 12px">
          <a-tag :color="statusColor(drawerBatch.status)">{{ drawerBatch.status }}</a-tag>
          <a-tag v-if="drawerBatch.progress">
            进度 {{ drawerBatch.progress.done }}/{{ drawerBatch.progress.total }}
          </a-tag>
        </a-space>
        <a-row v-if="batchAgg" :gutter="12">
          <a-col v-for="card in batchCards" :key="card.label" :span="8">
            <a-card size="small"><a-statistic :title="card.label" :value="card.value" :precision="4" /></a-card>
          </a-col>
        </a-row>
        <template v-if="batchSens.length">
          <a-typography-paragraph style="margin-top: 16px"><b>敏感性排名</b></a-typography-paragraph>
          <div v-for="s in batchSens" :key="s.name" style="margin: 4px 0">
            <span style="display: inline-block; width: 170px; font-size: 12px">{{ s.name }}</span>
            <a-progress :percent="Math.round((s.share ?? 0) * 100)" size="small"
                        style="display: inline-block; width: 360px" />
          </div>
        </template>
        <a-typography-text v-if="drawerBatch.evidenceId" type="secondary" style="display: block; margin-top: 12px">
          证据：{{ drawerBatch.evidenceId }}（已入 Evidence Store）
        </a-typography-text>
      </template>
    </a-drawer>

    <!-- 对照下钻 -->
    <a-drawer v-model:open="cmpDrawer" width="760" :title="`对照 ${drawerCmp?.comparisonKey ?? ''}`">
      <template v-if="drawerCmp">
        <a-space style="margin-bottom: 12px" wrap>
          <a-tag :color="statusColor(drawerCmp.status)">{{ drawerCmp.status }}</a-tag>
          <a-tag>{{ drawerCmp.backend }}</a-tag>
          <a v-if="drawerCmp.evidenceId">证据 {{ drawerCmp.evidenceId }}</a>
        </a-space>
        <a-table v-if="cmpArms.length" :data-source="cmpArms" row-key="jobKey" size="small"
                 :pagination="false" style="margin-bottom: 12px">
          <a-table-column title="臂" data-index="systemConfigId" :width="200" />
          <a-table-column title="状态" :width="120">
            <template #default="{ record }">
              <a-space size="small">
                <a-tag :color="statusColor(record.status)">{{ record.status }}</a-tag>
                <span v-if="record.progress" style="color: #888; font-size: 12px">
                  {{ record.progress.done }}/{{ record.progress.total }}</span>
              </a-space>
            </template>
          </a-table-column>
          <a-table-column title="任务" data-index="jobKey" :width="280">
            <template #default="{ text }"><code style="font-size: 11px">{{ text }}</code></template>
          </a-table-column>
        </a-table>

        <template v-if="cmpResult">
          <a-typography-paragraph><b>指标并列（首臂为基准）</b></a-typography-paragraph>
          <table class="cmp-table">
            <thead>
              <tr>
                <th>指标</th>
                <th v-for="arm in cmpResult.arms" :key="String(arm.systemConfigId)">
                  {{ arm.systemConfigId }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="key in cmpResult.metricKeys" :key="key">
                <td>{{ cmpResult.metricLabels?.[key] ?? key }}</td>
                <td v-for="arm in cmpResult.arms" :key="String(arm.systemConfigId)">
                  {{ fmtNum(arm[key]) }}
                  <div v-if="key === 'pick_success_rate'" class="ci">CI {{ fmtCI(arm) }}</div>
                </td>
              </tr>
            </tbody>
          </table>

          <a-typography-paragraph style="margin-top: 12px"><b>差值（相对基准臂）</b></a-typography-paragraph>
          <table class="cmp-table" v-if="cmpResult.deltas?.length">
            <thead>
              <tr><th>臂</th><th>vs</th><th>指标</th><th>Δ</th><th>更优</th></tr>
            </thead>
            <tbody>
              <template v-for="d in cmpResult.deltas" :key="String(d.systemConfigId)">
                <tr v-for="key in cmpResult.metricKeys" :key="String(d.systemConfigId) + key">
                  <td v-if="d[key] !== undefined" :rowspan="cmpResult.metricKeys.length">{{ d.systemConfigId }}</td>
                  <td v-if="d[key] !== undefined">vs {{ d.vs }}</td>
                  <td v-if="d[key] !== undefined">{{ cmpResult.metricLabels?.[key] ?? key }}</td>
                  <td v-if="d[key] !== undefined" :class="{ good: d[key + '__better'] === d.systemConfigId }">
                    {{ d[key] !== undefined ? fmtNum(d[key]) : '-' }}
                  </td>
                  <td v-if="d[key] !== undefined">{{ d[key + '__better'] ?? '-' }}</td>
                </tr>
              </template>
            </tbody>
          </table>

          <a-typography-paragraph style="margin-top: 12px"><b>对照假设</b></a-typography-paragraph>
          <ul style="font-size: 12px; color: #666">
            <li v-for="a in cmpResult.assumptions" :key="a.name">[{{ a.provenance }}] {{ a.name }}：{{ a.note }}</li>
          </ul>
        </template>
      </template>
    </a-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { message } from 'ant-design-vue'
import { http } from '../api/http'

interface Project { id: string; name: string }
interface SystemConf { id: string; name?: string; ir?: { name?: string } }
interface Progress { done: number; total: number }
interface Batch {
  jobKey: string; status: string; backend?: string; n?: number
  progress?: Progress; evidenceId?: string; createdAt?: string
}
interface ComparisonRow {
  comparisonKey: string; label?: string; backend?: string
  armCount?: number; evidenceId?: string; createdAt?: string
}
interface Arm {
  systemConfigId: string; jobKey: string; status: string
  progress?: Progress; evidenceId?: string; lastError?: string
  result?: { aggregates?: Record<string, number>; sensitivity?: { name: string; share: number }[] }
}
interface ComparisonDetail {
  comparisonKey: string; label?: string; backend?: string; status: string
  evidenceId?: string; arms: Arm[]
  comparison?: {
    metricKeys: string[]
    metricLabels?: Record<string, string>
    arms: Record<string, unknown>[]
    deltas: Record<string, unknown>[]
    assumptions: { name: string; provenance: string; note: string }[]
  }
}

const projects = ref<Project[]>([])
const systems = ref<SystemConf[]>([])
const projectId = ref('')
const tab = ref('batches')

// —— 批次 ——
const newBackend = ref<'analytic' | 'simulator'>('analytic')
const newSystemId = ref('')
const newN = ref(1000)
const creating = ref(false)
const batches = ref<Batch[]>([])

// —— 对照 ——
const cmpSystems = ref<string[]>([])
const cmpBackend = ref<'analytic' | 'simulator'>('analytic')
const cmpN = ref(1000)
const cmpCreating = ref(false)
const comparisons = ref<ComparisonRow[]>([])

const batchDrawer = ref(false)
const drawerBatch = ref<Batch | null>(null)
const batchDetail = ref<{ result?: { aggregates?: Record<string, number>; sensitivity?: { name: string; share: number }[] } } | null>(null)

const cmpDrawer = ref(false)
const drawerCmp = ref<ComparisonDetail | null>(null)

const projectOptions = computed(() => projects.value.map((p) => ({ value: p.id, label: p.name })))
const systemOptions = computed(() =>
  systems.value.map((s, i) => ({ value: s.id, label: s.ir?.name || s.name || `system-${i + 1}` })))

const batchAgg = computed(() => batchDetail.value?.result?.aggregates ?? null)
const batchSens = computed(() => batchDetail.value?.result?.sensitivity ?? [])
const batchCards = computed(() => {
  const a = batchAgg.value ?? {}
  const sim = drawerBatch.value?.backend === 'simulator'
  return sim
    ? [
        { label: '抓取成功率', value: a.pick_success_rate ?? 0 },
        { label: '样本数', value: a.samples ?? 0 },
        { label: '失败数', value: a.failed ?? 0 },
      ]
    : [
        { label: '成功率均值', value: a.success_rate_mean ?? 0 },
        { label: '成功率 P5', value: a.success_rate_P5 ?? 0 },
        { label: '定位精度 P95 均值', value: a.accuracy_p95_mean_mm ?? 0 },
      ]
})
const cmpArms = computed(() => drawerCmp.value?.arms ?? [])
const cmpResult = computed(() => drawerCmp.value?.comparison ?? null)

let timer: number | undefined

onMounted(async () => {
  projects.value = await http.get<Project[]>('/api/projects')
  refresh()
  timer = window.setInterval(() => {
    // 有进行中的批次/对照时自动刷新列表
    if (batches.value.some((b) => b.status === 'QUEUED' || b.status === 'RUNNING') && projectId.value) {
      loadBatches()
    }
  }, 5000)
})
onUnmounted(() => clearInterval(timer))

async function onProjectChange() {
  systems.value = []
  cmpSystems.value = []
  newSystemId.value = ''
  if (!projectId.value) return
  systems.value = await http.get<SystemConf[]>(`/api/projects/${projectId.value}/systems`)
  refresh()
}

async function refresh() {
  if (!projectId.value) return
  await Promise.all([loadBatches(), loadComparisons()])
}

async function loadBatches() {
  batches.value = await http.get<Batch[]>(`/api/experiments/batches?projectId=${projectId.value}`)
}

async function loadComparisons() {
  comparisons.value = await http.get<ComparisonRow[]>(
    `/api/experiments/comparisons/projects/${projectId.value}`)
}

async function createBatch() {
  creating.value = true
  try {
    const r = await http.post<{ jobKey: string }>('/api/experiments', {
      projectId: projectId.value, systemConfigId: newSystemId.value,
      n: newN.value, method: 'lhs', backend: newBackend.value,
    })
    message.success(`批次已发起：${r.jobKey}`)
    loadBatches()
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    creating.value = false
  }
}

async function createComparison() {
  cmpCreating.value = true
  try {
    const r = await http.post<{ comparisonKey: string }>('/api/experiments/comparisons', {
      projectId: projectId.value, systemConfigIds: cmpSystems.value,
      n: cmpN.value, method: 'lhs', backend: cmpBackend.value,
    })
    message.success(`对照已发起：${r.comparisonKey}`)
    tab.value = 'comparisons'
    loadComparisons()
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    cmpCreating.value = false
  }
}

async function openBatch(row: Batch) {
  drawerBatch.value = row
  batchDetail.value = null
  batchDrawer.value = true
  try {
    const r = await http.get<Batch & { result?: { aggregates?: Record<string, number>; sensitivity?: { name: string; share: number }[] } }>(
      `/api/experiments/${row.jobKey}`)
    drawerBatch.value = { ...row, ...r, evidenceId: r.evidenceId ?? row.evidenceId }
    batchDetail.value = r
  } catch (e) {
    message.error((e as Error).message)
  }
}

async function openComparison(row: ComparisonRow) {
  try {
    const r = await http.get<ComparisonDetail>(`/api/experiments/comparisons/${row.comparisonKey}`)
    drawerCmp.value = r
    cmpDrawer.value = true
    if (r.status === 'SUCCEEDED') {
      loadComparisons() // 拉取刚摄取的 evidenceId
    }
  } catch (e) {
    message.error((e as Error).message)
  }
}

function statusColor(s: string): string {
  if (s === 'SUCCEEDED') return 'green'
  if (s === 'FAILED' || s === 'TIMEOUT') return 'red'
  return 'blue'
}

function fmtNum(v: unknown): string {
  return typeof v === 'number' ? v.toFixed(4).replace(/\.?0+$/, '') : '-'
}

function fmtCI(arm: Record<string, unknown>): string {
  const ci = (arm.pick_success_rate_ci95_wilson ?? []) as number[]
  return Array.isArray(ci) && ci.length === 2 ? `[${ci[0]}, ${ci[1]}]` : '-'
}
</script>

<style scoped>
.cmp-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.cmp-table th, .cmp-table td { border: 1px solid #e8e8e8; padding: 6px 10px; text-align: left; }
.cmp-table th { background: #fafafa; }
.cmp-table td.good { color: #389e0d; font-weight: 600; }
.cmp-table .ci { font-size: 11px; color: #999; }
</style>
