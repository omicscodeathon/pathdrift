import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { Box, Paper, Typography, TextField, Button, Alert, CircularProgress } from '@mui/material'
import { authApi } from '@/api/client'

export default function RegisterPage() {
  const navigate = useNavigate()
  const [form, setForm] = useState({ email: '', username: '', password: '', full_name: '', institution: '' })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await authApi.register(form)
      navigate('/login')
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Registration failed'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Box sx={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', bgcolor: '#f8fafc', px: 2 }}>
      <Paper sx={{ p: 4, width: '100%', maxWidth: 440 }} elevation={2}>
        <Typography variant="h5" fontWeight={700} mb={0.5}>Create Account</Typography>
        <Typography variant="body2" color="text.secondary" mb={3}>
          Start your PathDrift research project
        </Typography>

        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

        <Box component="form" onSubmit={handleRegister}>
          {[
            { key: 'email', label: 'Institutional Email', type: 'email', required: true },
            { key: 'username', label: 'Username', type: 'text', required: true },
            { key: 'password', label: 'Password (min 8 characters)', type: 'password', required: true },
            { key: 'full_name', label: 'Full Name', type: 'text', required: false },
            { key: 'institution', label: 'Institution / Organisation', type: 'text', required: false },
          ].map(({ key, label, type, required }) => (
            <TextField
              key={key}
              label={label}
              type={type}
              fullWidth
              value={form[key as keyof typeof form]}
              onChange={(e) => setForm(f => ({ ...f, [key]: e.target.value }))}
              sx={{ mb: 2 }}
              required={required}
            />
          ))}
          <Button type="submit" variant="contained" fullWidth disabled={loading} size="large">
            {loading ? <CircularProgress size={22} color="inherit" /> : 'Create Account'}
          </Button>
        </Box>

        <Typography variant="body2" textAlign="center" mt={2.5} color="text.secondary">
          Already have an account? <Link to="/login" style={{ color: '#1565c0' }}>Sign in</Link>
        </Typography>
      </Paper>
    </Box>
  )
}
