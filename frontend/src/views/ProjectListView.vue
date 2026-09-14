<template>
  <div>
    <a-typography-title :level="4">项目</a-typography-title>
    <a-button type="primary" style="margin-bottom: 16px" @click="showCreate = true">新建项目</a-button>
    <a-table :columns="columns" :data-source="projects" :loading="loading" row-key="id">
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'status'">
          <a-tag :color="record.status === 'ACTIVE' ? 'blue' : 'default'">{{ record.status }}</a-tag>
        </template>
        <template v-else-if="column.key === 'actions'">
          <a-button size="small" @click="seedDemo(record)">导入演示数据</a-button>
        </template>
      </template>
    </a-table>

    <a-modal v-model:open="showCreate" title="新建项目" @ok="create">
      <a-form layout="vertical">
        <a-form-item label="项目名" required>
          <a-input v-model:value="newName" placeholder="发动机零件自动抓取" />
        </a-form-item>
        <a-form-item label="描述">
          <a-textarea v-model:value="newDesc" :rows="3" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'
import { http } from '../api/http'

interface Project {
  id: string
  name: string
  description?: string
  status: string
}

const columns = [
  { title: 'ID', dataIndex: 'id', key: 'id', ellipsis: true },
  { title: '项目名', dataIndex: 'name', key: 'name' },
  { title: '描述', dataIndex: 'description', key: 'description' },
  { title: '状态', dataIndex: 'status', key: 'status' },
  { title: '操作', key: 'actions', width: 140 },
]

const projects = ref<Project[]>([])
const loading = ref(false)
const showCreate = ref(false)
const newName = ref('')
const newDesc = ref('')

onMounted(load)

async function load() {
  loading.value = true
  try {
    projects.value = await http.get<Project[]>('/api/projects')
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    loading.value = false
  }
}

async function create() {
  try {
    await http.post<Project>('/api/projects', { name: newName.value, description: newDesc.value })
    message.success('创建成功')
    showCreate.value = false
    newName.value = ''
    newDesc.value = ''
    await load()
  } catch (e) {
    message.error((e as Error).message)
  }
}

async function seedDemo(project: Project) {
  try {
    const r = await http.post<{ requirements: number; systems: number }>(
      `/api/projects/${project.id}/seed-demo`, {})
    message.success(`已导入演示数据：${r.requirements} 条需求 + ${r.systems} 个系统配置（幂等）`)
  } catch (e) {
    message.error((e as Error).message)
  }
}
</script>
