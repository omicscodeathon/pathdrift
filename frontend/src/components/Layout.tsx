import { useState } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import {
  Box, Drawer, AppBar, Toolbar, Typography, List, ListItem,
  ListItemButton, ListItemIcon, ListItemText, IconButton, Avatar,
  Divider, Chip, Tooltip, useTheme, useMediaQuery,
} from '@mui/material'
import {
  Dashboard, Dataset, Psychology, Science, AccountTree,
  BlurOn, Biotech, AutoGraph, VerifiedUser, BubbleChart,
  Summarize, Menu as MenuIcon, Logout, ChevronLeft, Download,
  TrendingUp,
} from '@mui/icons-material'
import { useAuthStore } from '@/store/authStore'

const DRAWER_WIDTH = 240

const navItems = [
  { label: 'Dashboard',     icon: <Dashboard />,      path: '/' },
  { label: 'Datasets',      icon: <Dataset />,         path: '/datasets' },
  { label: 'Data Acquisition', icon: <Download />,     path: '/data-acquisition' },
  { label: 'Preprocessing', icon: <Psychology />,      path: '/preprocessing' },
  { label: 'DEG Analysis',  icon: <Science />,         path: '/deg' },
  { label: 'Networks',      icon: <AccountTree />,     path: '/networks' },
  { label: 'Network Drift', icon: <BlurOn />,          path: '/drift' },
  { label: 'Cross-Species', icon: <Biotech />,         path: '/cross-species' },
  { label: 'Prediction',    icon: <AutoGraph />,       path: '/prediction' },
  { label: 'Validation',    icon: <VerifiedUser />,    path: '/validation' },
  { label: 'Pathways',      icon: <BubbleChart />,     path: '/pathways' },
  { label: 'Reports',       icon: <Summarize />,       path: '/reports' },
  { label: 'Gene Loss',     icon: <TrendingUp />,      path: '/gene-loss' },
]

export default function Layout() {
  const theme = useTheme()
  const isMobile = useMediaQuery(theme.breakpoints.down('md'))
  const [drawerOpen, setDrawerOpen] = useState(!isMobile)
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout } = useAuthStore()

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const drawer = (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Logo / Title */}
      <Box sx={{ p: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
        <Box
          sx={{
            width: 36, height: 36, borderRadius: '8px',
            background: 'linear-gradient(135deg, #1565c0 0%, #00acc1 100%)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <Typography sx={{ color: 'white', fontWeight: 900, fontSize: 14 }}>PD</Typography>
        </Box>
        <Box>
          <Typography variant="h6" sx={{ fontWeight: 700, lineHeight: 1, fontSize: 16 }}>
            PathDrift
          </Typography>
          <Typography variant="caption" sx={{ color: 'text.secondary', lineHeight: 1 }}>
            Network Drift Analysis
          </Typography>
        </Box>
        {drawerOpen && isMobile && (
          <IconButton size="small" onClick={() => setDrawerOpen(false)} sx={{ ml: 'auto' }}>
            <ChevronLeft />
          </IconButton>
        )}
      </Box>
      <Divider />

      {/* Navigation */}
      <List dense sx={{ flex: 1, pt: 1 }}>
        {navItems.map((item) => {
          const active = location.pathname === item.path
          return (
            <ListItem key={item.path} disablePadding sx={{ px: 1, mb: 0.25 }}>
              <ListItemButton
                onClick={() => { navigate(item.path); if (isMobile) setDrawerOpen(false) }}
                selected={active}
                sx={{
                  borderRadius: 1,
                  '&.Mui-selected': {
                    bgcolor: 'primary.main',
                    color: 'white',
                    '& .MuiListItemIcon-root': { color: 'white' },
                    '&:hover': { bgcolor: 'primary.dark' },
                  },
                }}
              >
                <ListItemIcon sx={{ minWidth: 36, color: active ? 'white' : 'text.secondary' }}>
                  {item.icon}
                </ListItemIcon>
                <ListItemText
                  primary={item.label}
                  primaryTypographyProps={{ fontSize: 14, fontWeight: active ? 600 : 400 }}
                />
              </ListItemButton>
            </ListItem>
          )
        })}
      </List>

      <Divider />
      {/* User section */}
      <Box sx={{ p: 1.5, display: 'flex', alignItems: 'center', gap: 1 }}>
        <Avatar sx={{ width: 32, height: 32, bgcolor: 'primary.main', fontSize: 13 }}>
          {user?.username?.[0]?.toUpperCase() ?? 'U'}
        </Avatar>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="body2" noWrap sx={{ fontWeight: 500 }}>
            {user?.username ?? 'Researcher'}
          </Typography>
          <Typography variant="caption" noWrap sx={{ color: 'text.secondary' }}>
            {user?.institution ?? user?.email}
          </Typography>
        </Box>
        <Tooltip title="Log out">
          <IconButton size="small" onClick={handleLogout}>
            <Logout fontSize="small" />
          </IconButton>
        </Tooltip>
      </Box>
    </Box>
  )

  return (
    <Box sx={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      {/* Sidebar */}
      {isMobile ? (
        <Drawer
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          variant="temporary"
          sx={{ '& .MuiDrawer-paper': { width: DRAWER_WIDTH } }}
        >
          {drawer}
        </Drawer>
      ) : (
        <Drawer
          variant="permanent"
          open={drawerOpen}
          sx={{
            width: drawerOpen ? DRAWER_WIDTH : 0,
            flexShrink: 0,
            '& .MuiDrawer-paper': {
              width: DRAWER_WIDTH,
              borderRight: '1px solid',
              borderColor: 'divider',
              bgcolor: 'background.paper',
              transition: theme.transitions.create('width'),
              overflowX: 'hidden',
            },
          }}
        >
          {drawer}
        </Drawer>
      )}

      {/* Main content */}
      <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* Top bar (mobile only) */}
        {isMobile && (
          <AppBar position="static" elevation={0} sx={{ borderBottom: '1px solid', borderColor: 'divider' }}>
            <Toolbar variant="dense">
              <IconButton edge="start" onClick={() => setDrawerOpen(true)}>
                <MenuIcon />
              </IconButton>
              <Typography variant="h6" sx={{ fontWeight: 700, ml: 1 }}>PathDrift</Typography>
            </Toolbar>
          </AppBar>
        )}

        <Box sx={{ flex: 1, overflow: 'auto', p: { xs: 2, md: 3 } }}>
          <Outlet />
        </Box>
      </Box>
    </Box>
  )
}
