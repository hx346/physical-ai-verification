<template>
  <div>
    <a-typography-title :level="4">验证矩阵 Verification Matrix</a-typography-title>

    <a-space style="margin-bottom: 16px" wrap>
      <a-select v-model:value="projectId" style="width: 260px" placeholder="选择项目" :loading="loadingProjects"
                :options="projectOptions" @change="loadSystems" />
      <a-select v-model:value="systemConfigId" style="width: 260px" placeholder="选择系统配置"
                :options="systemOptions" :disabled="!projectId" />
      <a-button type="primary" :loading="running" :disabled="!projectId || !systemConfigId" @click="runVerification">
        运行验证
      </a-button>
      <a-button v-if="lastRunId" @click="downloadReport">下载报告 (Markdown)</a-button>
    </a-space>

    <a-alert v-if="runMeta" type="info" show-icon style="margin-bottom: 16px"
             :message="`run ${runMeta.runId} · kernel ${runMeta.kernelVersion} · traceId ${runMeta.traceId}`" />

    <a-table :columns="columns" :data-source="rows" :pagination="false" row-key="requirementId"
             :loading="running" size="middle">
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'status'">
          <a-tag :color="statusColor(record.status)">{{ record.status }}</a-tag>
        </template>
        <template v-else-if="column.key === 'observed'">
          {{ record.observed ?? '—' }} {{ record.unit ?? '' }}
        </template>
        <template v-else-if="column.key === 'evidenceId'">
          <a @click="showDetail(record)">{{ record.evidenceId ?? '—' }}</a>
        </template>
      </template>
    </a-table>

    <a-drawer v-model:open="drawerOpen" width="560" :title="detailTitle">
      <template v-if="detail">
        <p><b>判定：</b><a-tag :color="statusColor(detail.status)">{{ detail.status }}</a-tag></p>
        <p><b>详情：</b>{{ detail.detail }}</p>
        <template v-if="contributors.length">
          <p><b>贡献度：</b></p>
          <div v-for="c in contributors" :key="c.name" style="margin: 2px 0">
            <a-progress :percent="Math.round(c.share * 100)" size="small" style="width: 300px"
                        :format="() => c.name" />
          </div>
        </template>
        <template v-if="assumptions.length">
          <p style="margin-top: 12px"><b>假设清单（provenance）：</b></p>
          <ul>
            <li v-for="(a, i) in assumptions" :key="i">
              <a-tag color="orange">{{ a.provenance }}</a-tag> {{ a.name }}：{{ a.note }}
            </li>
          </ul>
        </template>
        <template v-if="simEvidences.length">
          <p style="margin-top: 12px"><b>关联仿真证据（gz-sim）：</b></p>
          <div v-for="ev in simEvidences" :key="ev.evidenceId"
               style="border: 1px solid #f0f0f0; border-radius: 6px; padding: 8px; margin-bottom: 8px">
            <p style="margin: 0 0 4px">
              <a-tag color="purple">{{ ev.evidenceId }}</a-tag>
              <a-tag v-if="ev.ir?.simulationVerdict"
                     :color="simVerdictColor(ev.ir.simulationVerdict.status)">
                {{ ev.ir.simulationVerdict.status }}
              </a-tag>
              <span style="color: #888; font-size: 12px">{{ ev.ir?.adapter }} · {{ ev.createdAt }}</span>
            </p>
            <p v-if="ev.ir?.simulationVerdict" style="margin: 0 0 4px; font-size: 12px">
              仿真判定：{{ ev.ir.simulationVerdict.detail ?? ev.ir.simulationVerdict.reason }}
            </p>
            <div v-for="(v, k) in ev.ir?.metrics ?? {}" :key="k" style="font-size: 12px">
              {{ k }}: {{ typeof v === 'number' ? v.toFixed(3) : v }}
            </div>
            <div v-for="art in ev.ir?.artifacts ?? []" :key="art.key" style="font-size: 12px; color: #888; margin-top: 4px">
              artifact: {{ art.name }} [{{ art.store }}] {{ art.key }}
            </div>
          </div>
        </template>
      </template>
    </a-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'
import { http } from '../api/http'

interface Project { id: string; name: string }
interface SystemConf { id: string; name?: string; ir?: { id?: string; name?: string } }
interface Item {
  requirementId: string
  metric: string
  status: 'PASS' | 'FAIL' | 'UNKNOWN'
  observed?: number | null
  unit?: string | null
  percentile?: string | null
  detail?: string | null
  evidenceId?: string | null
  evidence?: { result?: { contributors?: { name: string; share: number }[]; minProvenance?: string }, assumptions?: { name: string; provenance: string; note: string }[] }
}

const columns = [
  { title: '需求', dataIndex: 'requirementId', key: 'requirementId' },
  { title: '指标', dataIndex: 'metric', key: 'metric' },
  { title: '现值', key: 'observed' },
  { title: '分位', dataIndex: 'percentile', key: 'percentile' },
  { title: '判定', key: 'status' },
  { title: '证据', key: 'evidenceId' },
]

const projects = ref<Project[]>([])
const systems = ref<SystemConf[]>([])
const projectId = ref<string>('')
const systemConfigId = ref<string>('')
const rows = ref<Item[]>([])
const running = ref(false)
const loadingProjects = ref(false)
const lastRunId = ref('')
const runMeta = ref<{ runId: string; kernelVersion: string; traceId: string } | null>(null)
const drawerOpen = ref(false)
const detail = ref<Item | null>(null)
interface SimEvidence {
  evidenceId: string
  createdAt?: string
  ir?: {
    adapter?: string
    metrics?: Record<string, number>
    artifacts?: { name: string; store: string; key: string }[]
    simulationVerdict?: { status?: string; detail?: string; reason?: string }
  }
}
const simEvidences = ref<SimEvidence[]>([])

const projectOptions = computed(() => projects.value.map((p) => ({ value: p.id, label: p.name })))
const systemOptions = computed(() =>
  systems.value.map((s, i) => ({ value: s.id, label: s.ir?.name || s.name || `system-${i + 1}` })),
)
const contributors = computed(() => detail.value?.evidence?.result?.contributors ?? [])
const assumptions = computed(() => detail.value?.evidence?.assumptions ?? [])
const detailTitle = computed(() =>
  detail.value ? `${detail.value.requirementId} · ${detail.value.metric}` : '')

onMounted(async () => {
  loadingProjects.value = true
  try {
    projects.value = await http.get<Project[]>('/api/projects')
  } finally {
    loadingProjects.value = false
  }
})

async function loadSystems() {
  systemConfigId.value = ''
  systems.value = []
  if (!projectId.value) return
  systems.value = await http.get<SystemConf[]>(`/api/projects/${projectId.value}/systems`)
}

async function runVerification() {
  running.value = true
  try {
    const result = await http.post<{ runId: string; kernelVersion: string; traceId: string; items: Item[] }>(
      '/api/verification/runs', { projectId: projectId.value, systemConfigId: systemConfigId.value })
    lastRunId.value = result.runId
    runMeta.value = result
    rows.value = result.items
    const failed = result.items.filter((i) => i.status === 'FAIL').length
    message.info(`验证完成：${result.items.length} 项，FAIL ${failed} 项`)
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    running.value = false
  }
}

async function showDetail(item: Item) {
  if (!item.evidence && lastRunId.value) {
    const items = await http.get<Item[]>(`/api/verification/runs/${lastRunId.value}/items`)
    const full = items.find((i) => i.requirementId === item.requirementId)
    detail.value = full ?? item
  } else {
    detail.value = item
  }
  drawerOpen.value = true
  // 关联仿真证据（该需求无仿真证据时静默不显示）
  try {
    simEvidences.value = await http.get<SimEvidence[]>(`/api/simulations/requirements/${item.requirementId}`)
  } catch {
    simEvidences.value = []
  }
}

async function downloadReport() {
  const token = localStorage.getItem('rv_token') ?? ''
  const resp = await fetch(`/api/verification/runs/${lastRunId.value}/report`, {
    headers: { Authorization: token },
  })
  const blob = await resp.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `verification-report-${lastRunId.value}.md`
  a.click()
  URL.revokeObjectURL(url)
}

function statusColor(status: Item['status']): string {
  if (status === 'PASS') return 'green'
  if (status === 'FAIL') return 'red'
  return 'orange'
}

// W3 仿真判定链：SIM_PASS/SIM_FAIL/SIM_UNKNOWN（provenance=simulation，与解析维度并列）
function simVerdictColor(status: string | undefined): string {
  if (status === 'SIM_PASS') return 'green'
  if (status === 'SIM_FAIL') return 'red'
  return 'default'
}
</script>
