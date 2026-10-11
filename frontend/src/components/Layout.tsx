import { useState } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import {
  Box, Drawer,  AppBar, Toolbar, Typography, List, ListItem,
  ListItemButton, ListItemIcon, ListItemText, IconButton, Avatar,
  Divider, Tooltip, useTheme, useMediaQuery,
} from '@mui/material'
import {
  Dashboard, Dataset, Science, AccountTree, BlurOn, Biotech,
  AutoGraph, VerifiedUser, BubbleChart, Summarize, Hub,
  Menu as MenuIcon, Logout, ChevronLeft, Download, TrendingUp, MonitorHeart,
  Interests as ModuleExplorerIcon, Insights, AccountTree as NetworkIcon,
  DeviceHub,
} from '@mui/icons-material'
import { useAuthStore } from '@/store/authStore'
import { useProjectStore } from '@/store/projectStore'
import RunResultsPrefetcher from '@/components/RunResultsPrefetcher'

const DRAWER_WIDTH = 280

const navGroups = [
  {
    label: 'Dashboard',
    items: [
      { label: 'Dashboard', icon: <Dashboard />, path: '/' },
    ],
  },
  {
    label: 'DATA',
    items: [
      { label: 'Datasets', icon: <Dataset />, path: '/datasets' },
     
      { label: 'Acquisition QC', icon: <Science />, path: '/run-qc' },
    ],
  },

  {
    label: 'Biological Analysis',

    items: [
      { label: 'Differential Expression', icon: <Science />, path: '/deg' },
      { label: 'Gene Networks', icon: <NetworkIcon />, path: '/runs/:runId/networks' },
      { label: 'Run Network Explorer', icon: <AccountTree />, path: '/runs/:runId/network-explorer' },
      { label: 'Modules', icon: <Hub />, path: '/runs/:runId/modules' },
      { label: 'Module Explorer', icon: <ModuleExplorerIcon />, path: '/runs/:runId/module-explorer' },
      { label: 'Integrated Analysis', icon: <Insights />, path: '/runs/:runId/integrated-analysis' },
      { label: 'Cross-Species Comparison', icon: <Biotech />, path: '/runs/:runId/cross-species' },
      { label: 'Orthology', icon: <DeviceHub />, path: '/runs/:runId/orthology' },
      { label: 'Network Drift', icon: <BlurOn />, path: '/runs/:runId/drift' },
      { label: 'Hub Genes', icon: <Hub />, path: '/runs/:runId/hub-genes' },
      { label: 'Biomarker Candidates', icon: <Science />, path: '/runs/:runId/biomarkers' },


    ],

  },
  {
    label: 'BIOLOGY',
    items: [
      { label: 'Pathway Enrichment', icon: <BubbleChart />, path: '/analysis/select?page=pathways' },
      { label: 'Key Drifted Pathways', icon: <TrendingUp />, path: '/analysis/select?page=key-drifted-pathways' },
      { label: 'Gene Loss Risk', icon: <TrendingUp />, path: '/runs/:runId/gene-loss' },
      { label: 'Morphology', icon: <MonitorHeart />, path: '/analysis/select?page=morphology' },
    ],
  },
  {
    label: 'MACHINE LEARNING',
    items: [
     
      { label: 'Run ML Results', icon: <AutoGraph />, path: '/runs/:runId/ml' },
    ],
  },
  
  {
    label: 'VISUALIZATION',
    items: [
     
      { label: 'PPI Network', icon: <Hub />, path: '/runs/:runId/ppi-network' },
    ],
  },
  {
    label: 'RESULTS',
    items: [
      { label: 'Reports', icon: <Summarize />, path: '/reports' },
    ],
  },
  {
    label: 'SYSTEM',
    items: [
      { label: 'Data Sources', icon: <Download />, path: '/data-acquisition' },
    ],
  },
]

export default function Layout() {
  const theme = useTheme()
  const isMobile = useMediaQuery(theme.breakpoints.down('md'))
  const [drawerOpen, setDrawerOpen] = useState(!isMobile)
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout } = useAuthStore()
  const currentRunId = useProjectStore((state) => state.currentRunId)

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const drawer = (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column', background: 'linear-gradient(180deg, #0f172a 0%, #111827 100%)', color: '#e2e8f0' }}>
      <Box sx={{ px: 2.5, py: 2.5 }}>
        <Typography
          variant="caption"
          sx={{
            display: 'block',
            color: '#7dd3fc',
            textTransform: 'none',
            letterSpacing: '0.04em',
            fontWeight: 700,
            mb: 1,
          }}
        >
          Cross-Species Breast Cancer Analysis
        </Typography>
        <Typography
          variant="h6"
          sx={{
            fontWeight: 800,
            lineHeight: 1.2,
            color: '#f8fafc',
            letterSpacing: '0.04em',
          }}
        >
          PATHDRIFT
        </Typography>
        <Box
          sx={{
            mt: 1.75,
            borderTop: '1px solid rgba(148, 163, 184, 0.35)',
            pt: 1.25,
            fontSize: '0.72rem',
            letterSpacing: '0.2em',
            color: '#cbd5e1',
            opacity: 0.9,
          }}
        >

        </Box>
        {drawerOpen && isMobile && (
          <IconButton size="small" onClick={() => setDrawerOpen(false)} sx={{ ml: 'auto', color: '#e2e8f0', display: 'flex' }}>
            <ChevronLeft />
          </IconButton>
        )}
      </Box>

      <List dense sx={{ flex: 1, px: 1.25, py: 0.5, overflowY: 'auto' }}>
        {navGroups.map((group) => (
          <Box key={group.label} sx={{ mb: 1.25 }}>
            {group.label === 'Dashboard' ? null : (
              <Box sx={{ px: 1.25, py: 0.8 }}>
                <Typography
                  variant="overline"
                  sx={{ color: '#7dd3fc', letterSpacing: '0.14em', fontWeight: 700, display: 'block', lineHeight: 1.4 }}
                >
                  {group.label}
                </Typography>
                {'subtitle' in group && (
                  <Typography variant="caption" sx={{ color: '#cbd5e1', display: 'block', mt: 0.25 }}>
                    {String(group.subtitle)}
                  </Typography>
                )}
              </Box>
            )}

            {group.items.map((item) => {
              const analysisPage = item.path.startsWith('/runs/:runId/')
                ? item.path.slice('/runs/:runId/'.length)
                : null
              const active = item.path === '/'
                ? location.pathname === '/'
                : item.path === '/deg'
                  ? location.pathname === '/deg' || /^\/runs\/[^/]+\/(deg|differential-expression)$/.test(location.pathname)
                  : analysisPage
                    ? new RegExp(`^/runs/[^/]+/${analysisPage}$`).test(location.pathname) ||
                      (location.pathname === '/analysis/select' && new URLSearchParams(location.search).get('page') === analysisPage)
                    : location.pathname.startsWith(item.path)
              return (
                <ListItem key={`${group.label}-${item.label}`} disablePadding sx={{ mb: 0.15 }}>
                  <ListItemButton
                    onClick={() => {
                      const target = analysisPage && currentRunId
                        ? item.path.replace(':runId', currentRunId)
                        : analysisPage
                          ? `/analysis/select?page=${analysisPage}`
                          : item.path
                      navigate(target)
                      if (isMobile) setDrawerOpen(false)
                    }}
                    selected={active}
                    sx={{
                      borderRadius: 1,
                      py: 0.55,
                      pl: 1.25,
                      pr: 1,
                      color: active ? '#f8fafc' : '#cbd5e1',
                      backgroundColor: active ? 'rgba(59, 130, 246, 0.22)' : 'transparent',
                      '&:hover': {
                        backgroundColor: active ? 'rgba(59, 130, 246, 0.28)' : 'rgba(148, 163, 184, 0.08)',
                      },
                      '&.Mui-selected': {
                        backgroundColor: 'rgba(59, 130, 246, 0.22)',
                        color: '#f8fafc',
                        '& .MuiListItemIcon-root': { color: '#f8fafc' },
                        '& .MuiListItemText-primary': { color: '#f8fafc' },
                      },
                    }}
                  >
                    <ListItemIcon
                      sx={{
                        minWidth: 22,
                        mr: 0.5,
                        color: active ? '#f8fafc' : '#93c5fd',
                      }}
                    >
                      {item.icon}
                    </ListItemIcon>
                    <ListItemText
                      primary={item.label}
                      primaryTypographyProps={{
                        fontSize: 13,
                        fontWeight: active ? 700 : 500,
                        letterSpacing: '0.01em',
                      }}
                    />
                    <Box
                      sx={{
                        width: 6,
                        height: 6,
                        borderRadius: '50%',
                        backgroundColor: active ? '#7dd3fc' : 'rgba(148, 163, 184, 0.7)',
                        ml: 1,
                      }}
                    />
                  </ListItemButton>
                </ListItem>
              )
            })}
          </Box>
        ))}
      </List>

      <Divider sx={{ borderColor: 'rgba(148, 163, 184, 0.24)' }} />
      <Box sx={{ p: 1.5, display: 'flex', alignItems: 'center', gap: 1 }}>
        <Avatar sx={{ width: 32, height: 32, bgcolor: '#2563eb', fontSize: 13, color: '#f8fafc' }}>
          {user?.username?.[0]?.toUpperCase() ?? 'U'}
        </Avatar>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="body2" noWrap sx={{ fontWeight: 600, color: '#f8fafc' }}>
            {user?.username ?? 'Researcher'}
          </Typography>
          <Typography variant="caption" noWrap sx={{ color: '#cbd5e1' }}>
            {user?.institution ?? user?.email}
          </Typography>
        </Box>
        <Tooltip title="Log out">
          <IconButton size="small" onClick={handleLogout} sx={{ color: '#e2e8f0' }}>
            <Logout fontSize="small" />
          </IconButton>
        </Tooltip>
      </Box>
    </Box>
  )

  return (
    <Box sx={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      <RunResultsPrefetcher />
      {isMobile ? (
        <Drawer
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          variant="temporary"
          sx={{ '& .MuiDrawer-paper': { width: DRAWER_WIDTH, backgroundColor: '#0f172a' } }}
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
              borderRight: '1px solid rgba(148, 163, 184, 0.15)',
              bgcolor: '#0f172a',
              transition: theme.transitions.create('width'),
              overflowX: 'hidden',
            },
          }}
        >
          {drawer}
        </Drawer>
      )}

      <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
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
