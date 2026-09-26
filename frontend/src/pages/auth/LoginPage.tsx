import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import {
  Box, Paper, Typography, TextField, Button, Alert, CircularProgress,
} from '@mui/material'
import { useSnackbar } from 'notistack'
import { authApi } from '@/api/client'
import { useAuthStore } from '@/store/authStore'

export default function LoginPage() {
  const navigate = useNavigate()
  const { setToken, setUser } = useAuthStore()
  const { enqueueSnackbar } = useSnackbar()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await authApi.login(username, password)
      const token = res.data.access_token
      setToken(token)
      const me = await authApi.getMe()
      setUser(me.data)
      navigate('/')
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Login failed'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Box sx={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      bgcolor: '#f8fafc', px: 2,
    }}>
      <Paper sx={{ p: 4, width: '100%', maxWidth: 400 }} elevation={2}>
        <Box sx={{ mb: 3, textAlign: 'center' }}>
          <Box sx={{
            width: 56, height: 56, borderRadius: 2, mx: 'auto', mb: 2,
            background: 'linear-gradient(135deg, #1565c0 0%, #00acc1 100%)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <Typography sx={{ color: 'white', fontWeight: 900, fontSize: 20 }}>PD</Typography>
          </Box>
          <Typography variant="h5" fontWeight={700}>PathDrift</Typography>
          <Typography variant="body2" color="text.secondary" mt={0.5}>
            Sign in to your research account
          </Typography>
        </Box>

        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

        <Box component="form" onSubmit={handleLogin}>
          <TextField
            label="Email or Username"
            fullWidth
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            sx={{ mb: 2 }}
            required
            autoComplete="username"
          />
          <TextField
            label="Password"
            type="password"
            fullWidth
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            sx={{ mb: 3 }}
            required
            autoComplete="current-password"
          />
          <Button
            type="submit"
            variant="contained"
            fullWidth
            disabled={loading}
            size="large"
          >
            {loading ? <CircularProgress size={22} color="inherit" /> : 'Sign In'}
          </Button>
        </Box>

        <Typography variant="body2" textAlign="center" mt={2.5} color="text.secondary">
          Don't have an account?{' '}
          <Link to="/register" style={{ color: '#1565c0' }}>Create one</Link>
        </Typography>
      </Paper>
    </Box>
  )
}
