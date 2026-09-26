import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface AuthState {
  token: string | null
  user: { id: string; email: string; username: string; full_name?: string; institution?: string } | null
  setToken: (token: string) => void
  setUser: (user: AuthState['user']) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      setToken: (token) => {
        localStorage.setItem('pathdrift_token', token)
        set({ token })
      },
      setUser: (user) => set({ user }),
      logout: () => {
        localStorage.removeItem('pathdrift_token')
        set({ token: null, user: null })
      },
    }),
    {
      name: 'pathdrift-auth',
      partialize: (state) => ({ token: state.token, user: state.user }),
    }
  )
)
