<template>
  <div>
    <a-typography-title :level="4">验证矩阵 Verification Matrix</a-typography-title>
    <a-alert
      type="info"
      show-icon
      message="M0 占位数据（对应 schemas/examples/bin-picking-rgb 演示第一幕）；M1 接入真实内核结果"
      style="margin-bottom: 16px"
    />
    <a-table :columns="columns" :data-source="rows" :pagination="false" row-key="reqId">
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'status'">
          <a-tag :color="statusColor(record.status)">{{ record.status }}</a-tag>
        </template>
        <template v-else-if="column.key === 'evidence'">
          <a>{{ record.evidence }}</a>
        </template>
      </template>
    </a-table>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { http } from '../api/http'

interface MatrixRow {
  reqId: string
  metric: string
  observed: string
  required: string
  status: 'PASS' | 'FAIL' | 'UNKNOWN'
  evidence: string
}

const columns = [
  { title: '需求', dataIndex: 'reqId', key: 'reqId' },
  { title: '指标', dataIndex: 'metric', key: 'metric' },
  { title: '现值', dataIndex: 'observed', key: 'observed' },
  { title: '要求', dataIndex: 'required', key: 'required' },
  { title: '判定', dataIndex: 'status', key: 'status' },
  { title: '证据', dataIndex: 'evidence', key: 'evidence' },
]

// M0 静态占位（README Demo 第一幕数值）；M1 由 /api/verification/runs 结果替换
const rows = ref<MatrixRow[]>([
  { reqId: 'R001', metric: '定位精度（P95）', observed: '7.1 mm', required: '≤ 3 mm', status: 'FAIL', evidence: 'E102' },
  { reqId: 'R002', metric: '可达范围', observed: '1.1 m', required: '≥ 1.0 m', status: 'PASS', evidence: 'E103' },
  { reqId: 'R003', metric: '节拍（P95）', observed: '5.4 s', required: '≤ 6 s', status: 'PASS', evidence: 'E104' },
  { reqId: 'R004', metric: '抓取成功率', observed: '94 %', required: '≥ 98 %', status: 'FAIL', evidence: 'E105' },
  { reqId: 'R005', metric: '端到端时延（P95）', observed: '—', required: '≤ 100 ms', status: 'UNKNOWN', evidence: '—' },
])

function statusColor(status: MatrixRow['status']): string {
  if (status === 'PASS') return 'green'
  if (status === 'FAIL') return 'red'
  return 'orange'
}

// 预留：拉取真实项目列表（backend 就绪后启用）
void http
</script>

<style scoped></style>
