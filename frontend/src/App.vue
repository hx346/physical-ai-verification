<template>
  <a-config-provider :locale="zhCN" :theme="{ token: { colorPrimary: '#1668dc' } }">
    <router-view />
  </a-config-provider>
</template>

<script setup lang="ts">
import zhCN from 'ant-design-vue/es/locale/zh_CN'
</script>
