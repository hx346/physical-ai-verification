<template>
  <a-layout style="min-height: 100vh">
    <a-layout-sider theme="dark" width="220">
      <div class="logo">RoboVerify</div>
      <a-menu v-model:selectedKeys="selected" theme="dark" mode="inline" @click="onMenu">
        <a-menu-item key="/projects">
          <AppstoreOutlined /><span>项目</span>
        </a-menu-item>
        <a-menu-item key="/matrix">
          <TableOutlined /><span>验证矩阵</span>
        </a-menu-item>
      </a-menu>
    </a-layout-sider>
    <a-layout>
      <a-layout-header class="header">
        <span>物理智能验证平台 · P0</span>
        <a-button type="link" @click="logout">退出（{{ auth.username || '未登录' }}）</a-button>
      </a-layout-header>
      <a-layout-content class="content">
        <router-view />
      </a-layout-content>
    </a-layout>
  </a-layout>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { AppstoreOutlined, TableOutlined } from '@ant-design/icons-vue'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const selected = ref<string[]>([router.currentRoute.value.path])

function onMenu({ key }: { key: string }) {
  router.push(key)
}

function logout() {
  auth.logout()
  router.push('/login')
}
</script>

<style scoped>
.logo {
  height: 48px;
  color: #fff;
  font-weight: 700;
  font-size: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.header {
  background: #fff;
  padding: 0 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.content {
  margin: 16px;
  padding: 24px;
  background: #fff;
  min-height: 360px;
}
</style>
