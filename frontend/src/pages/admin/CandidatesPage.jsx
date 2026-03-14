import React, { useState, useMemo } from 'react'
import { useCandidates, useCandidate, useDeleteCandidate, useBulkDeleteCandidates } from '../../hooks/useCandidates'
import PageHeader from '../../components/shared/PageHeader'
import EmptyState from '../../components/shared/EmptyState'
import ConfirmDialog from '../../components/shared/ConfirmDialog'
import Modal from '../../components/shared/Modal'
import StatusBadge from '../../components/shared/StatusBadge'
import { formatDate, formatDateTime } from '../../lib/utils'
import { toast } from 'sonner'
import { Search, Users, Eye, Trash2, Loader2, Mail, Phone, Globe, CheckSquare, Square, MinusSquare } from 'lucide-react'

export default function CandidatesPage() {
  const [search, setSearch] = useState('')
  const [deleteId, setDeleteId] = useState(null)
  const [selectedEmail, setSelectedEmail] = useState(null)
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false)

  const { data: candidates = [], isLoading } = useCandidates(search)
  const { data: candidateDetail } = useCandidate(selectedEmail)
  const deleteMutation = useDeleteCandidate()
  const bulkDeleteMutation = useBulkDeleteCandidates()

  const candidateIds = useMemo(() => candidates.map(c => c.candidate_id), [candidates])

  const handleDelete = async () => {
    if (!deleteId) return
    try {
      await deleteMutation.mutateAsync(deleteId)
      toast.success('Candidate deleted')
      setDeleteId(null)
      setSelectedIds(prev => { const next = new Set(prev); next.delete(deleteId); return next })
    } catch {
      toast.error('Failed to delete candidate')
    }
  }

  // Selection
  const toggleSelect = (id) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleSelectAll = () => {
    if (selectedIds.size === candidateIds.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(candidateIds))
    }
  }

  const allSelected = candidateIds.length > 0 && selectedIds.size === candidateIds.length
  const someSelected = selectedIds.size > 0 && selectedIds.size < candidateIds.length
  const selectionCount = selectedIds.size

  const handleBulkDelete = async () => {
    const ids = [...selectedIds]
    try {
      const result = await bulkDeleteMutation.mutateAsync(ids)
      toast.success(result.message)
      setSelectedIds(new Set())
      setBulkDeleteOpen(false)
    } catch {
      toast.error('Failed to delete candidates')
    }
  }

  const SelectIcon = allSelected ? CheckSquare : someSelected ? MinusSquare : Square

  return (
    <div>
      <PageHeader
        title="Candidates"
        badge={<span className="badge bg-slate-100 text-slate-700">{candidates.length}</span>}
        description="Browse and manage all candidates"
      />

      <div className="card mb-6 p-4">
        <div className="relative max-w-md">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input type="text" placeholder="Search by name or email..." className="input pl-9" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
      </div>

      {/* Bulk action bar */}
      {selectionCount > 0 && (
        <div className="mb-4 flex items-center gap-3 rounded-lg border border-brand-200 bg-brand-50 px-4 py-2.5">
          <span className="text-sm font-medium text-brand-700">{selectionCount} selected</span>
          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={() => setBulkDeleteOpen(true)}
              disabled={bulkDeleteMutation.isPending}
              className="inline-flex items-center gap-1.5 rounded-md bg-red-500 px-3 py-1.5 text-xs font-medium text-white shadow-sm transition-colors hover:bg-red-600"
            >
              <Trash2 className="h-3.5 w-3.5" />
              Delete
            </button>
            <button
              onClick={() => setSelectedIds(new Set())}
              className="ml-1 rounded-md px-2 py-1.5 text-xs text-slate-500 hover:bg-white hover:text-slate-700"
            >
              Clear
            </button>
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="flex h-40 items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-brand-500" /></div>
      ) : candidates.length === 0 ? (
        <EmptyState icon={Users} title="No candidates found" description={search ? 'Try a different search term' : 'Candidates will appear here after they apply'} />
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50/50">
                <th className="w-10 px-3 py-3">
                  <button onClick={toggleSelectAll} className="flex items-center justify-center text-slate-400 hover:text-brand-500 transition-colors">
                    <SelectIcon className="h-4.5 w-4.5" />
                  </button>
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Name</th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Email</th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Phone</th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Applications</th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Last Applied</th>
                <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-slate-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {candidates.map((c) => {
                const isSelected = selectedIds.has(c.candidate_id)
                return (
                  <tr key={c.candidate_id} className={`transition-colors ${isSelected ? 'bg-brand-50/50' : 'hover:bg-slate-50/50'}`}>
                    <td className="w-10 px-3 py-3">
                      <button onClick={() => toggleSelect(c.candidate_id)} className={`flex items-center justify-center transition-colors ${isSelected ? 'text-brand-500' : 'text-slate-300 hover:text-slate-500'}`}>
                        {isSelected ? <CheckSquare className="h-4.5 w-4.5" /> : <Square className="h-4.5 w-4.5" />}
                      </button>
                    </td>
                    <td className="px-4 py-3"><p className="text-sm font-medium text-slate-900">{c.full_name}</p></td>
                    <td className="px-4 py-3"><p className="text-sm text-slate-600">{c.email}</p></td>
                    <td className="px-4 py-3"><p className="text-sm text-slate-500">{c.phone || '-'}</p></td>
                    <td className="px-4 py-3"><span className="badge bg-brand-50 text-brand-700">{c.total_applications}</span></td>
                    <td className="px-4 py-3"><p className="text-sm text-slate-500">{formatDate(c.latest_application)}</p></td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-1">
                        <button onClick={() => setSelectedEmail(c.email)} className="btn-icon" title="View"><Eye className="h-4 w-4" /></button>
                        <button onClick={() => setDeleteId(c.candidate_id)} className="btn-icon text-red-500 hover:bg-red-50 hover:text-red-700" title="Delete"><Trash2 className="h-4 w-4" /></button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <Modal open={!!selectedEmail && !!candidateDetail} onClose={() => setSelectedEmail(null)} title={candidateDetail?.candidate?.full_name || 'Candidate'} size="lg">
        {candidateDetail && (
          <div className="space-y-6">
            <div className="grid grid-cols-2 gap-4">
              <div className="flex items-center gap-2"><Mail className="h-4 w-4 text-slate-400" /><span className="text-sm">{candidateDetail.candidate.email}</span></div>
              <div className="flex items-center gap-2"><Phone className="h-4 w-4 text-slate-400" /><span className="text-sm">{candidateDetail.candidate.phone || 'N/A'}</span></div>
              {candidateDetail.candidate.linkedin && <div className="flex items-center gap-2"><Globe className="h-4 w-4 text-slate-400" /><a href={candidateDetail.candidate.linkedin} target="_blank" rel="noopener noreferrer" className="text-sm text-brand-600 hover:underline">LinkedIn</a></div>}
              {candidateDetail.candidate.portfolio && <div className="flex items-center gap-2"><Globe className="h-4 w-4 text-slate-400" /><a href={candidateDetail.candidate.portfolio} target="_blank" rel="noopener noreferrer" className="text-sm text-brand-600 hover:underline">Portfolio</a></div>}
            </div>
            <div>
              <h4 className="text-sm font-semibold text-slate-900">Applications ({candidateDetail.applications.length})</h4>
              <div className="mt-3 space-y-3">
                {candidateDetail.applications.map(a => (
                  <div key={a.application_id} className="rounded-lg border border-slate-200 p-3">
                    <div className="flex items-center justify-between">
                      <p className="text-sm font-medium text-slate-900">{a.job_offer.title}</p>
                      <div className="flex gap-2"><StatusBadge status={a.ai_status} /><StatusBadge status={a.hr_status} /></div>
                    </div>
                    <p className="mt-1 text-xs text-slate-500">Submitted: {formatDateTime(a.submitted_at)}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </Modal>

      <ConfirmDialog open={!!deleteId} onClose={() => setDeleteId(null)} onConfirm={handleDelete} title="Delete Candidate" description="This will permanently delete this candidate and ALL their applications and interviews." confirmLabel="Delete" loading={deleteMutation.isPending} />
      <ConfirmDialog
        open={bulkDeleteOpen}
        onClose={() => setBulkDeleteOpen(false)}
        onConfirm={handleBulkDelete}
        title={`Delete ${selectionCount} Candidate${selectionCount !== 1 ? 's' : ''}`}
        description={`This will permanently delete ${selectionCount} candidate${selectionCount !== 1 ? 's' : ''} and ALL their applications and interviews. This action cannot be undone.`}
        confirmLabel={`Delete ${selectionCount}`}
        loading={bulkDeleteMutation.isPending}
      />
    </div>
  )
}
