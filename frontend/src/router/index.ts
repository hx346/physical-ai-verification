import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/LoginView.vue'),
    },
    {
      path: '/',
      component: () => import('../layouts/MainLayout.vue'),
      children: [
        { path: '', redirect: '/matrix' },
        {
          path: 'projects',
          name: 'projects',
          component: () => import('../views/ProjectListView.vue'),
        },
        {
          path: 'matrix',
          name: 'matrix',
          component: () => import('../views/VerificationMatrixView.vue'),
        },
        {
          path: 'experiment',
          name: 'experiment',
          component: () => import('../views/ExperimentView.vue'),
        },
        {
          path: 'realtest',
          name: 'realtest',
          component: () => import('../views/RealTestView.vue'),
        },
      ],
    },
  ],
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.name !== 'login' && !auth.token) {
    return { name: 'login' }
  }
})

export default router
