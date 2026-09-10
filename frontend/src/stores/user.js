import { defineStore } from 'pinia'
import api from '@/api'

export const useUserStore = defineStore('user', {
  state: () => ({
    token: localStorage.getItem('token') || '',
    username: localStorage.getItem('username') || '',
    role: localStorage.getItem('role') || '',
    displayName: localStorage.getItem('displayName') || ''
  }),

  getters: {
    isLoggedIn: state => !!state.token,
    isAdmin: state => state.role === 'admin'
  },

  actions: {
    async login(username, password) {
      const data = await api.post('/auth/login', { username, password })
      this.token = data.token
      this.username = data.user.username
      this.role = data.user.role
      this.displayName = data.user.display_name
      localStorage.setItem('token', data.token)
      localStorage.setItem('username', data.user.username)
      localStorage.setItem('role', data.user.role)
      localStorage.setItem('displayName', data.user.display_name || '')
      return data
    },

    async fetchMe() {
      const data = await api.get('/auth/me')
      this.username = data.username
      this.role = data.role
      this.displayName = data.display_name
      return data
    },

    logout() {
      this.token = ''
      this.username = ''
      this.role = ''
      this.displayName = ''
      localStorage.removeItem('token')
      localStorage.removeItem('username')
      localStorage.removeItem('role')
      localStorage.removeItem('displayName')
    }
  }
})
