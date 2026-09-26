import { Chip } from '@mui/material'
import type { JobStatus } from '@/types'

const STATUS_MAP: Record<JobStatus, { color: 'default' | 'info' | 'success' | 'error' | 'warning'; label: string }> = {
  queued:    { color: 'default', label: 'Queued' },
  running:   { color: 'info',    label: 'Running' },
  completed: { color: 'success', label: 'Completed' },
  failed:    { color: 'error',   label: 'Failed' },
  cancelled: { color: 'warning', label: 'Cancelled' },
}

export default function JobStatusBadge({ status }: { status: JobStatus }) {
  const s = STATUS_MAP[status] ?? { color: 'default', label: status }
  return <Chip size="small" color={s.color} label={s.label} />
}
