import React from 'react'
import { STATUS_CONFIG } from '../../lib/constants'
import { cn } from '../../lib/utils'

export default function StatusBadge({ status, className }) {
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.pending

  return (
    <span
      className={cn(
        'badge ring-1 ring-inset',
        config.color,
        className
      )}
    >
      {config.label}
    </span>
  )
}
