import React, { useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useJobOffers, useDeleteJobOffer, useBulkDeleteJobOffers } from '../../hooks/useJobOffers'
import PageHeader from '../../components/shared/PageHeader'
import EmptyState from '../../components/shared/EmptyState'
import ConfirmDialog from '../../components/shared/ConfirmDialog'
import { formatDate, truncate, parseJSON } from '../../lib/utils'
import { toast } from 'sonner'
import { Plus, Briefcase, Pencil, Trash2, Eye, Loader2, CheckSquare, Square, MinusSquare } from 'lucide-react'

export default function JobOffersPage() {
  const navigate = useNavigate()
  const { data: jobOffers = [], isLoading } = useJobOffers()
  const deleteMutation = useDeleteJobOffer()
  const bulkDeleteMutation = useBulkDeleteJobOffers()
  const [deleteId, setDeleteId] = useState(null)
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false)

  const offerIds = useMemo(() => jobOffers.map(o => o.offer_id), [jobOffers])

  const handleDelete = async () => {
    if (!deleteId) return
    try {
      await deleteMutation.mutateAsync(deleteId)
      toast.success('Job offer deleted')
      setDeleteId(null)
      setSelectedIds(prev => { const next = new Set(prev); next.delete(deleteId); return next })
    } catch {
      toast.error('Failed to delete job offer')
    }
  }

  // Selection
  const toggleSelect = (id, e) => {
    e.stopPropagation()
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleSelectAll = () => {
    if (selectedIds.size === offerIds.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(offerIds))
    }
  }

  const allSelected = offerIds.length > 0 && selectedIds.size === offerIds.length
  const someSelected = selectedIds.size > 0 && selectedIds.size < offerIds.length
  const selectionCount = selectedIds.size

  const handleBulkDelete = async () => {
    const ids = [...selectedIds]
    try {
      const result = await bulkDeleteMutation.mutateAsync(ids)
      toast.success(result.message)
      setSelectedIds(new Set())
      setBulkDeleteOpen(false)
    } catch {
      toast.error('Failed to delete job offers')
    }
  }

  const SelectAllIcon = allSelected ? CheckSquare : someSelected ? MinusSquare : Square

  return (
    <div>
      <PageHeader
        title="Job Offers"
        badge={<span className="badge bg-slate-100 text-slate-700">{jobOffers.length}</span>}
        description="Manage your job listings"
        actions={
          <div className="flex items-center gap-2">
            {offerIds.length > 0 && (
              <button onClick={toggleSelectAll} className="btn-ghost" title={allSelected ? 'Deselect all' : 'Select all'}>
                <SelectAllIcon className="h-4 w-4" />
                {allSelected ? 'Deselect' : 'Select all'}
              </button>
            )}
            <button onClick={() => navigate('/admin/job-offers/new')} className="btn-primary">
              <Plus className="h-4 w-4" /> New Job Offer
            </button>
          </div>
        }
      />

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
      ) : jobOffers.length === 0 ? (
        <EmptyState icon={Briefcase} title="No job offers yet" description="Create your first job offer to start receiving applications" action={<button onClick={() => navigate('/admin/job-offers/new')} className="btn-primary"><Plus className="h-4 w-4" />Create Job Offer</button>} />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {jobOffers.map(offer => {
            const langs = parseJSON(offer.required_languages, [])
            const isSelected = selectedIds.has(offer.offer_id)
            return (
              <div key={offer.offer_id} className={`card flex flex-col overflow-hidden transition-colors ${isSelected ? 'ring-2 ring-brand-500 bg-brand-50/30' : ''}`}>
                <div className="flex-1 p-5">
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="text-base font-semibold text-slate-900">{offer.title}</h3>
                    <button
                      onClick={(e) => toggleSelect(offer.offer_id, e)}
                      className={`flex-shrink-0 transition-colors ${isSelected ? 'text-brand-500' : 'text-slate-300 hover:text-slate-500'}`}
                    >
                      {isSelected ? <CheckSquare className="h-5 w-5" /> : <Square className="h-5 w-5" />}
                    </button>
                  </div>
                  <p className="mt-2 text-sm text-slate-500 line-clamp-3">{offer.description}</p>
                  {offer.required_skills && (
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {offer.required_skills.split(/[,;]/).filter(s => s.trim()).slice(0, 3).map((skill, i) => (
                        <span key={i} className="badge bg-slate-100 text-slate-600">{skill.trim()}</span>
                      ))}
                      {offer.required_skills.split(/[,;]/).filter(s => s.trim()).length > 3 && (
                        <span className="badge bg-slate-100 text-slate-600">+{offer.required_skills.split(/[,;]/).filter(s => s.trim()).length - 3}</span>
                      )}
                    </div>
                  )}
                  {langs.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {langs.map(l => <span key={l} className="badge bg-violet-50 text-violet-700">{l}</span>)}
                    </div>
                  )}
                  <div className="mt-3 flex items-center gap-3 text-xs text-slate-400">
                    {offer.experience_level && <span>{offer.experience_level}</span>}
                    {offer.interview_mode && <span className="capitalize">{offer.interview_mode}</span>}
                    {offer.created_at && <span>{formatDate(offer.created_at)}</span>}
                  </div>
                </div>
                <div className="flex items-center justify-end gap-1 border-t border-slate-100 px-4 py-3">
                  <button onClick={() => navigate(`/admin/job-offers/${offer.offer_id}/edit`)} className="btn-icon" title="Edit"><Pencil className="h-4 w-4" /></button>
                  <button onClick={() => setDeleteId(offer.offer_id)} className="btn-icon text-red-500 hover:bg-red-50 hover:text-red-700" title="Delete"><Trash2 className="h-4 w-4" /></button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      <ConfirmDialog open={!!deleteId} onClose={() => setDeleteId(null)} onConfirm={handleDelete} title="Delete Job Offer" description="This will permanently delete this job offer." confirmLabel="Delete" loading={deleteMutation.isPending} />
      <ConfirmDialog
        open={bulkDeleteOpen}
        onClose={() => setBulkDeleteOpen(false)}
        onConfirm={handleBulkDelete}
        title={`Delete ${selectionCount} Job Offer${selectionCount !== 1 ? 's' : ''}`}
        description={`This will permanently delete ${selectionCount} job offer${selectionCount !== 1 ? 's' : ''}. This action cannot be undone.`}
        confirmLabel={`Delete ${selectionCount}`}
        loading={bulkDeleteMutation.isPending}
      />
    </div>
  )
}
