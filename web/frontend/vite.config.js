import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
const BACKEND = process.env.WEB_BACKEND_URL || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true, // 监听所有网络接口，允许 cpolar 等外部隧道访问
    allowedHosts: [
      // 允许 cpolar 生成的二级域名（通配符，域名变化也无需反复改配置）
      ".r10.vip.cpolar.cn",
    ],
    proxy: {
      // 图像篡改检测：API 走相对路径 /api，经代理转发到后端（本地与 cpolar 公网访问均可用）
      "/api": { target: BACKEND, changeOrigin: true },
      // 点位核验：图片/可视化/接口均以相对路径 /smart 访问，经代理转发到后端
      "/smart": { target: BACKEND, changeOrigin: true },
      // 遥感变化核验：子应用挂载在 /rsverify 前缀下
      "/rsverify": { target: BACKEND, changeOrigin: true },
      // 人脸识别：子应用挂载在 /face 前缀下
      "/face": { target: BACKEND, changeOrigin: true },
    },
  },
})
