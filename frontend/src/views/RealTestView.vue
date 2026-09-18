<template>
  <div>
    <a-typography-title :level="4">真机测试 Real Test</a-typography-title>

    <a-space style="margin-bottom: 16px" wrap>
      <a-select v-model:value="projectId" style="width: 260px" placeholder="选择项目"
                :options="projectOptions" @change="onProjectChange" />
      <a-button :disabled="!projectId" @click="refresh">刷新</a-button>
    </a-space>

    <a-tabs v-model:activeKey="tab">
      <!-- ==================== 会话 ==================== -->
      <a-tab-pane key="sessions" tab="会话">
        <a-table :data-source="sessions" row-key="id" size="small"
                 :pagination="{ pageSize: 10 }" :loading="loadingSessions">
          <a-table-column title="会话" data-index="id" :width="150">
            <template #default="{ text }">
              <a style="font-family: monospace" @click="openSession(text)">{{ short(text) }}</a>
            </template>
          </a-table-column>
          <a-table-column title="来源" data-index="source" :width="110" />
          <a-table-column title="备注" data-index="note" :ellipsis="true" />
          <a-table-column title="externalKey" data-index="externalKey" :ellipsis="true">
            <template #default="{ text }">
              <span style="font-family: monospace; font-size: 12px">{{ text || '-' }}</span>
            </template>
          </a-table-column>
          <a-table-column title="遥测行" data-index="nRows" :width="90" />
          <a-table-column title="指标数" data-index="nMetrics" :width="90" />
          <a-table-column title="导入时间" data-index="createdAt" :width="200" />
          <a-table-column :width="80">
            <template #default="{ record }">
              <a @click="openSession(record.id)">详情</a>
            </template>
          </a-table-column>
        </a-table>
      </a-tab-pane>

      <!-- ==================== 模型版本 ==================== -->
      <a-tab-pane key="models" tab="模型版本">
        <a-table :data-source="models" row-key="id" size="small"
                 :pagination="{ pageSize: 10 }" :loading="loadingModels">
          <a-table-column title="ID" data-index="id" :width="150">
            <template #default="{ text }">
              <span style="font-family: monospace">{{ short(text) }}</span>
            </template>
          </a-table-column>
          <a-table-column title="类型" data-index="modelType" :width="130" />
          <a-table-column title="目标资产" data-index="targetAsset" :width="150" />
          <a-table-column title="版本" data-index="version" :width="170">
            <template #default="{ text }">
              <span style="font-family: monospace">{{ text }}</span>
            </template>
          </a-table-column>
          <a-table-column title="状态" data-index="lifecycle" :width="120">
            <template #default="{ text }">
              <a-tag :color="lifecycleColor(text)">{{ text }}</a-tag>
            </template>
          </a-table-column>
          <a-table-column title="创建时间" data-index="createdAt" :width="200" />
          <a-table-column :width="90">
            <template #default="{ record }">
              <a-popconfirm title="激活该版本？（旧 ACTIVE 自动 DEPRECATED）"
                            @confirm="activateModel(record.id)">
                <a :style="{ visibility: record.lifecycle === 'ACTIVE' ? 'hidden' : 'visible' }">激活</a>
              </a-popconfirm>
            </template>
          </a-table-column>
        </a-table>
      </a-tab-pane>
    </a-tabs>

    <!-- ==================== 会话详情 Drawer ==================== -->
    <a-drawer v-model:open="drawerOpen" width="720" :title="`会话 ${short(activeSessionId)}`">
      <template v-if="summary">
        <b>指标聚合（与 runtime summarize 同形）</b>
        <table class="stat-table">
          <thead>
            <tr><th>指标</th><th>样本</th><th>mean</th><th>P50</th><th>P95</th></tr>
          </thead>
          <tbody>
            <tr v-for="(stats, metric) in summary" :key="metric">
              <td>{{ metric }}</td>
              <td>{{ stats.samples }}</td>
              <td>{{ stats.mean.toFixed(4) }}</td>
              <td>{{ stats.P50.toFixed(4) }}</td>
              <td>{{ stats.P95.toFixed(4) }}</td>
            </tr>
          </tbody>
        </table>
      </template>
      <a-empty v-else-if="activeSessionId" description="该会话暂无遥测数据" />

      <template v-if="activeSessionId">
        <a-divider />
        <a-space style="margin-bottom: 8px">
          <b>Sim2Real Gap</b>
          <a-button size="small" :loading="loadingGap" @click="loadGap">计算 Gap</a-button>
        </a-space>
        <p v-if="gapResult?.simSource" style="color: #888; font-size: 12px">
          sim 来源：{{ gapResult.simSource }}
        </p>
        <table v-if="gapResult?.gap" class="stat-table">
          <thead>
            <tr><th>指标</th><th>sim</th><th>real mean</th><th>gap %</th><th>verdict</th></tr>
          </thead>
          <tbody>
            <tr v-for="(entry, metric) in gapResult.gap" :key="metric">
              <td>{{ metric }}</td>
              <td>{{ entry.sim?.toFixed(4) ?? '-' }}</td>
              <td>{{ entry.real?.mean?.toFixed(4) ?? '-' }}</td>
              <td>{{ entry.gap_percent ?? '-' }}</td>
              <td>
                <a-tag v-if="entry.verdict === 'within_20pct'" color="green">±20% 内</a-tag>
                <a-tag v-else-if="entry.verdict === 'exceeds_20pct'" color="red">超 20%</a-tag>
                <a-tag v-else-if="entry.status === 'no_sim_counterpart'" color="orange">无仿真对照</a-tag>
                <a-tag v-else color="default">-</a-tag>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else-if="gapResult?.note" style="color: #888">
          {{ gapResult.note }}
        </p>
      </template>
    </a-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'
import { http } from '../api/http'

// V0.8 W2：真机数据可见化（会话/聚合/Gap/模型版本）。
// 诚实边界：no_sim_counterpart 分支只有 status 键无 verdict——如实渲染"无仿真对照"。
interface Project { id: string; name: string }
interface RealTestSession {
  id: string; source: string; note: string | null
  externalKey: string | null; createdAt: string; nRows: number; nMetrics: number
}
interface MetricStats { samples: number; mean: number; P50: number; P95: number }
interface GapEntry {
  real?: MetricStats; sim?: number
  gap_ratio?: number; gap_percent?: number
  verdict?: string; status?: string
}
interface SessionGap {
  sessionId: string; simSource: string | null
  note?: string; gap: Record<string, GapEntry> | null
}
interface ModelVersion {
  id: string; modelType: string; targetAsset: string
  version: string; lifecycle: string; createdAt: string
}

const tab = ref('sessions')
const projectId = ref('')
const projects = ref<Project[]>([])
const sessions = ref<RealTestSession[]>([])
const models = ref<ModelVersion[]>([])
const loadingSessions = ref(false)
const loadingModels = ref(false)
const loadingGap = ref(false)

const drawerOpen = ref(false)
const activeSessionId = ref('')
const summary = ref<Record<string, MetricStats> | null>(null)
const gapResult = ref<SessionGap | null>(null)

const projectOptions = computed(() => projects.value.map((p) => ({ value: p.id, label: p.name })))

onMounted(async () => {
  projects.value = await http.get<Project[]>('/api/projects')
  refresh()
})

async function onProjectChange() {
  refresh()
}

async function refresh() {
  if (!projectId.value) return
  loadingSessions.value = true
  loadingModels.value = true
  try {
    sessions.value = await http.get<RealTestSession[]>(
      `/api/realtest/sessions?projectId=${projectId.value}`)
    models.value = await http.get<ModelVersion[]>('/api/realtest/models')
  } finally {
    loadingSessions.value = false
    loadingModels.value = false
  }
}

async function openSession(id: string) {
  activeSessionId.value = id
  gapResult.value = null
  drawerOpen.value = true
  const resp = await http.get<{ sessionId: string; metrics: Record<string, MetricStats> }>(
    `/api/realtest/sessions/${id}/summary`)
  summary.value = Object.keys(resp.metrics).length ? resp.metrics : null
}

async function loadGap() {
  loadingGap.value = true
  try {
    gapResult.value = await http.get<SessionGap>(
      `/api/realtest/sessions/${activeSessionId.value}/gap`)
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    loadingGap.value = false
  }
}

async function activateModel(id: string) {
  await http.post(`/api/realtest/models/${id}/activate`)
  message.success('已激活（旧 ACTIVE 自动 DEPRECATED）')
  models.value = await http.get<ModelVersion[]>('/api/realtest/models')
}

function lifecycleColor(lifecycle: string): string {
  if (lifecycle === 'ACTIVE') return 'green'
  if (lifecycle === 'TESTING') return 'blue'
  if (lifecycle === 'DEPRECATED') return 'default'
  return 'orange'
}

function short(id: string): string {
  return id.length > 8 ? id.slice(0, 8) : id
}
</script>

<style scoped>
.stat-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  margin-top: 8px;
}
.stat-table th,
.stat-table td {
  border: 1px solid #f0f0f0;
  padding: 4px 8px;
  text-align: left;
}
.stat-table th {
  background: #fafafa;
}
</style>
