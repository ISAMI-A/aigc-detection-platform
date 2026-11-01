import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './i18n/index.js'
import './index.css'
import App from './components/common/App.jsx'
import { AuthProvider } from './auth/AuthContext.jsx'
import { applyTheme, loadTheme } from './theme.js'

// 启动即应用已保存的主题（深浅色 + 主色），避免刷新后闪回浅色
applyTheme(loadTheme())

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <AuthProvider>
      <App />
    </AuthProvider>
  </StrictMode>,
)
