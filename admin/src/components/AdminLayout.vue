<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  DataBoard,
  Iphone,
  Document,
  Monitor,
  TrendCharts,
  Setting,
  User,
} from '@element-plus/icons-vue'
import { getMe, logout } from '../api/auth'

const router = useRouter()
const username = ref('')

onMounted(async () => {
  try {
    const user = await getMe()
    username.value = user.username
  } catch {
    username.value = 'Admin'
  }
})

function handleLogout() {
  logout()
  router.push('/login')
}

const menuItems = [
  { index: '/dashboard', title: 'Dashboard', icon: DataBoard },
  { index: '/devices', title: '设备管理', icon: Iphone },
  { index: '/scripts', title: '脚本编辑', icon: Document },
  { index: '/tasks', title: '任务监控', icon: Monitor },
  { index: '/accounts', title: '账号池', icon: User },
  { index: '/strategies', title: '策略管理', icon: TrendCharts },
  { index: '/config', title: '系统配置', icon: Setting },
]
</script>

<template>
  <el-container style="height: 100%">
    <el-aside width="220px" style="background-color: #001529">
      <div
        style="
          height: 60px;
          display: flex;
          align-items: center;
          justify-content: center;
          color: #fff;
          font-size: 18px;
          font-weight: 600;
        "
      >
        iOS Ranking
      </div>
      <el-menu
        :default-active="$route.path"
        router
        background-color="#001529"
        text-color="#ffffffa6"
        active-text-color="#fff"
      >
        <el-menu-item v-for="item in menuItems" :key="item.index" :index="item.index">
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.title }}</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header
        style="
          display: flex;
          align-items: center;
          justify-content: flex-end;
          border-bottom: 1px solid #e4e7ed;
          gap: 16px;
        "
      >
        <span style="font-size: 14px; color: #606266">{{ username }}</span>
        <el-button type="danger" text @click="handleLogout">退出</el-button>
      </el-header>

      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>
