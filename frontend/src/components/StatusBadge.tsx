import { Badge } from '@chakra-ui/react'
import type { ReviewStatus } from '../types'

const BOOK_COLORS: Record<string, string> = {
  not_started: 'gray',
  processing: 'blue',
  needs_correction: 'orange',
  awaiting_approval: 'purple',
  approved: 'green',
  failed: 'red',
}

const REVIEW_LABELS: Record<ReviewStatus, string> = {
  pending: 'Not checked yet',
  corrected: 'Corrected, awaiting approval',
  approved: 'Approved',
}

const REVIEW_COLORS: Record<ReviewStatus, string> = {
  pending: 'gray',
  corrected: 'purple',
  approved: 'green',
}

export function BookStatusBadge({ status, label }: { status: string; label: string }) {
  return <Badge colorScheme={BOOK_COLORS[status] ?? 'gray'}>{label}</Badge>
}

export function ReviewStatusBadge({ status }: { status: ReviewStatus }) {
  return <Badge colorScheme={REVIEW_COLORS[status]}>{REVIEW_LABELS[status]}</Badge>
}
