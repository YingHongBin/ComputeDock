import { App as AntApp } from 'antd'
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { AuthProvider } from './auth'
import { NavigationProvider } from './routing'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <NavigationProvider>
      <AuthProvider>
        <AntApp><App /></AntApp>
      </AuthProvider>
    </NavigationProvider>
  </React.StrictMode>,
)
