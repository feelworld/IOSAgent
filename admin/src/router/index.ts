import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import AdminLayout from '../components/AdminLayout.vue'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/dashboard',
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/Login.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/',
    component: AdminLayout,
    meta: { requiresAuth: true },
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('../views/Dashboard.vue'),
      },
      {
        path: 'devices',
        name: 'Devices',
        component: () => import('../views/DeviceList.vue'),
      },
      {
        path: 'scripts',
        name: 'Scripts',
        component: () => import('../views/ScriptEditor.vue'),
      },
      {
        path: 'tasks',
        name: 'Tasks',
        component: () => import('../views/TaskMonitor.vue'),
      },
      {
        path: 'strategies',
        name: 'Strategies',
        component: () => import('../views/StrategyManager.vue'),
      },
      {
        path: 'config',
        name: 'Config',
        component: () => import('../views/ConfigPanel.vue'),
      },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, _from, next) => {
  const token = localStorage.getItem('token')
  const requiresAuth = to.matched.some((r) => r.meta.requiresAuth !== false)

  if (requiresAuth && !token) {
    next({ name: 'Login' })
  } else if (to.name === 'Login' && token) {
    next({ name: 'Dashboard' })
  } else {
    next()
  }
})

export default router
