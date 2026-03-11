export const STATUS_CONFIG = {
  approved: {
    label: 'Approved',
    color: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
    dot: 'bg-emerald-500',
  },
  rejected: {
    label: 'Rejected',
    color: 'bg-red-50 text-red-700 ring-red-600/20',
    dot: 'bg-red-500',
  },
  pending: {
    label: 'Pending',
    color: 'bg-slate-50 text-slate-700 ring-slate-600/20',
    dot: 'bg-slate-400',
  },
  selected: {
    label: 'Selected',
    color: 'bg-violet-50 text-violet-700 ring-violet-600/20',
    dot: 'bg-violet-500',
  },
  processing: {
    label: 'Processing',
    color: 'bg-blue-50 text-blue-700 ring-blue-600/20',
    dot: 'bg-blue-500',
  },
  error: {
    label: 'Error',
    color: 'bg-orange-50 text-orange-700 ring-orange-600/20',
    dot: 'bg-orange-500',
  },
  interview_sent: {
    label: 'Interview Sent',
    color: 'bg-amber-50 text-amber-700 ring-amber-600/20',
    dot: 'bg-amber-500',
  },
  completed: {
    label: 'Completed',
    color: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
    dot: 'bg-emerald-500',
  },
  cancelled: {
    label: 'Cancelled',
    color: 'bg-slate-50 text-slate-600 ring-slate-500/20',
    dot: 'bg-slate-400',
  },
  recommended: {
    label: 'Recommended',
    color: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
    dot: 'bg-emerald-500',
  },
  not_recommended: {
    label: 'Not Recommended',
    color: 'bg-red-50 text-red-700 ring-red-600/20',
    dot: 'bg-red-500',
  },
}

export const EVALUATION_CATEGORIES = [
  { key: 'technical_skills', label: 'Technical Skills', description: 'Technical knowledge and abilities' },
  { key: 'communication', label: 'Communication', description: 'Clarity, articulation, and expression' },
  { key: 'problem_solving', label: 'Problem Solving', description: 'Analytical and logical thinking' },
  { key: 'language_proficiency', label: 'Language Proficiency', description: 'Fluency in required languages' },
  { key: 'job_fit', label: 'Job Fit', description: 'Alignment with role requirements' },
  { key: 'experience', label: 'Experience', description: 'Relevant work experience' },
  { key: 'cultural_fit', label: 'Cultural Fit', description: 'Values and team compatibility' },
  { key: 'motivation', label: 'Motivation', description: 'Interest and enthusiasm for the role' },
]

export const LANGUAGES = [
  'English', 'French', 'Spanish', 'German', 'Italian', 'Portuguese', 'Arabic',
  'Chinese', 'Japanese', 'Korean', 'Russian', 'Dutch', 'Swedish', 'Norwegian',
  'Danish', 'Finnish', 'Polish', 'Turkish', 'Hindi', 'Hebrew', 'Greek', 'Czech',
  'Hungarian', 'Romanian', 'Bulgarian', 'Croatian', 'Serbian', 'Slovak', 'Slovenian', 'Ukrainian',
]

export const DATE_PRESETS = [
  { label: 'Today', value: 'today' },
  { label: 'Last 7 Days', value: 'week' },
  { label: 'Last 30 Days', value: 'month' },
  { label: 'All Time', value: 'all' },
]

export function getDateRange(preset) {
  const today = new Date()
  const todayStr = today.toISOString().split('T')[0]

  switch (preset) {
    case 'today':
      return { date_from: todayStr, date_to: todayStr }
    case 'week': {
      const weekAgo = new Date(today)
      weekAgo.setDate(weekAgo.getDate() - 7)
      return { date_from: weekAgo.toISOString().split('T')[0], date_to: todayStr }
    }
    case 'month': {
      const monthAgo = new Date(today)
      monthAgo.setDate(monthAgo.getDate() - 30)
      return { date_from: monthAgo.toISOString().split('T')[0], date_to: todayStr }
    }
    case 'all':
    default:
      return { date_from: '', date_to: '' }
  }
}
