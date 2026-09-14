import { defineStore } from 'pinia'
import { http } from '../api/http'

interface LoginResp {
  token: string
  username: string
  role: string
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('rv_token') ?? '',
    username: localStorage.getItem('rv_username') ?? '',
  }),
  actions: {
    async login(username: string, password: string) {
      const resp = await http.post<LoginResp>('/api/auth/login', { username, password })
      this.token = resp.token
      this.username = resp.username
      localStorage.setItem('rv_token', resp.token)
      localStorage.setItem('rv_username', resp.username)
    },
    logout() {
      this.token = ''
      this.username = ''
      localStorage.removeItem('rv_token')
      localStorage.removeItem('rv_username')
    },
  },
})
