import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useInterviews, useArchiveInterview, useDeleteInterview } from '../../hooks/useInterviews'
import { useJobOffers } from '../../hooks/useJobOffers'
import PageHeader from '../../components/shared/PageHeader'
import StatusBadge from '../../components/shared/StatusBadge'
import EmptyState from '../../components/shared/EmptyState'
import ConfirmDialog from '../../components/shared/ConfirmDialog'
import { formatDate } from '../../lib/utils'
import { DATE_PRESETS, getDateRange } from '../../lib/constants'
import { toast } from 'sonner'
import { Mic, Eye, Archive, ArchiveRestore, Trash2, RefreshCw, Loader2 } from 'lucide-react'

export default function InterviewsPage() {
  const navigate = useNavigate()
  const [filters, setFilters] = useState({ status: '', job_offer_id: '', date_from: '', date_to: '', date_preset: 'all', show_archived: false })
  const [deleteId, setDeleteId] = useState(null)

  const { data: interviews = [], isLoading, refetch } = useInterviews(filters)
  const { data: jobOffers = [] } = useJobOffers()
  const archiveMutation = useArchiveInterview()
  const deleteMutation = useDeleteInterview()

  const handleFilterChange = (key, value) => {
    if (key === 'date_from' || key === 'date_to') setFilters(p => ({ ...p, [key]: value, date_preset: 'custom' }))
    else setFilters(p => ({ ...p, [key]: value }))
  }
  const handleDatePreset = (preset) => { const range = getDateRange(preset); setFilters(p => ({ ...p, date_preset: preset, ...range })) }
  const handleArchive = async (id, isArchived) => { try { await archiveMutation.mutateAsync({ id, isArchived }); toast.success(isArchived ? 'Restored' : 'Archived') } catch { toast.error('Failed') } }
  const handleDelete = async () => { if (!deleteId) return; try { await deleteMutation.mutateAsync(deleteId); toast.success('Deleted'); setDeleteId(null) } catch { toast.error('Failed') } }

  return (
    <div>
      <PageHeader title="Interviews" badge={<span className="badge bg-slate-100 text-slate-700">{interviews.length}</span>} description="Manage interview sessions" actions={<button onClick={() => refetch()} className="btn-ghost"><RefreshCw className="h-4 w-4" />Refresh</button>} />

      <div className="card mb-6 p-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="w-[160px]"><label className="label">Status</label><select className="select" value={filters.status} onChange={e => handleFilterChange('status', e.target.value)}><option value="">All</option><option value="pending">Pending</option><option value="completed">Completed</option><option value="cancelled">Cancelled</option></select></div>
          <div className="w-[200px]"><label className="label">Job Offer</label><select className="select" value={filters.job_offer_id} onChange={e => handleFilterChange('job_offer_id', e.target.value)}><option value="">All Offers</option>{jobOffers.map(o => <option key={o.offer_id} value={o.offer_id}>{o.title}</option>)}</select></div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-slate-500">Period:</span>
          {DATE_PRESETS.map(p => (<button key={p.value} onClick={() => handleDatePreset(p.value)} className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${filters.date_preset === p.value ? 'bg-brand-500 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}>{p.label}</button>))}
          <label className="ml-auto flex items-center gap-2 text-xs text-slate-500"><input type="checkbox" checked={filters.show_archived} onChange={e => handleFilterChange('show_archived', e.target.checked)} className="rounded border-slate-300 text-brand-500 focus:ring-brand-500" />Show archived</label>
        </div>
      </div>

      {isLoading ? <div className="flex h-40 items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-brand-500" /></div>
      : interviews.length === 0 ? <EmptyState icon={Mic} title="No interviews found" description="Interviews will appear here after candidates are invited" />
      : (
        <div className="card overflow-hidden">
          <table className="w-full">
            <thead><tr className="border-b border-slate-200 bg-slate-50/50">
              <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Candidate</th>
              <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Job</th>
              <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Status</th>
              <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Created</th>
              <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Completed</th>
              <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-slate-500">Actions</th>
            </tr></thead>
            <tbody className="divide-y divide-slate-100">
              {interviews.map(i => (
                <tr key={i.interview_id} className="transition-colors hover:bg-slate-50/50">
                  <td className="px-4 py-3"><p className="text-sm font-medium text-slate-900">{i.candidate.name}</p><p className="text-xs text-slate-500">{i.candidate.email || ''}</p></td>
                  <td className="px-4 py-3 text-sm text-slate-700">{i.job_offer.title}</td>
                  <td className="px-4 py-3"><div className="flex gap-1.5"><StatusBadge status={i.status} />{i.recommendation && <StatusBadge status={i.recommendation} />}</div></td>
                  <td className="px-4 py-3 text-sm text-slate-500">{formatDate(i.created_at)}</td>
                  <td className="px-4 py-3 text-sm text-slate-500">{formatDate(i.completed_at)}</td>
                  <td className="px-4 py-3"><div className="flex items-center justify-end gap-1">
                    <button onClick={() => navigate(`/admin/interviews/${i.interview_id}`)} className="btn-icon" title="View"><Eye className="h-4 w-4" /></button>
                    <button onClick={() => handleArchive(i.interview_id, i.is_archived)} className="btn-icon" title={i.is_archived ? 'Restore' : 'Archive'}>{i.is_archived ? <ArchiveRestore className="h-4 w-4" /> : <Archive className="h-4 w-4" />}</button>
                    <button onClick={() => setDeleteId(i.interview_id)} className="btn-icon text-red-500 hover:bg-red-50 hover:text-red-700" title="Delete"><Trash2 className="h-4 w-4" /></button>
                  </div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <ConfirmDialog open={!!deleteId} onClose={() => setDeleteId(null)} onConfirm={handleDelete} title="Delete Interview" description="This will permanently delete this interview." confirmLabel="Delete" loading={deleteMutation.isPending} />
    </div>
  )
}
