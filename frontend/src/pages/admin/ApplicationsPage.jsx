import React, { useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApplications, useArchiveApplication, useDeleteApplication, useBulkDeleteApplications, useBulkArchiveApplications } from '../../hooks/useApplications'
import { useJobOffers } from '../../hooks/useJobOffers'
import PageHeader from '../../components/shared/PageHeader'
import StatusBadge from '../../components/shared/StatusBadge'
import EmptyState from '../../components/shared/EmptyState'
import ConfirmDialog from '../../components/shared/ConfirmDialog'
import { formatDate, truncate } from '../../lib/utils'
import { DATE_PRESETS, getDateRange } from '../../lib/constants'
import { toast } from 'sonner'
import {
  Search, FileText, Eye, Archive, ArchiveRestore, Trash2,
  RefreshCw, Loader2, CheckSquare, Square, MinusSquare,
} from 'lucide-react'

export default function ApplicationsPage() {
  const navigate = useNavigate()
  const [filters, setFilters] = useState({
    job_offer_id: '', ai_status: '', hr_status: '', search: '',
    date_from: '', date_to: '', date_preset: 'all', show_archived: false,
  })
  const [deleteId, setDeleteId] = useState(null)
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false)

  const { data: applications = [], isLoading, refetch } = useApplications(filters)
  const { data: jobOffers = [] } = useJobOffers()
  const archiveMutation = useArchiveApplication()
  const deleteMutation = useDeleteApplication()
  const bulkDeleteMutation = useBulkDeleteApplications()
  const bulkArchiveMutation = useBulkArchiveApplications()

  const applicationIds = useMemo(() => applications.map(a => a.application_id), [applications])

  const handleFilterChange = (key, value) => {
    if (key === 'date_from' || key === 'date_to') {
      setFilters(prev => ({ ...prev, [key]: value, date_preset: 'custom' }))
    } else {
      setFilters(prev => ({ ...prev, [key]: value }))
    }
  }

  const handleDatePreset = (preset) => {
    const range = getDateRange(preset)
    setFilters(prev => ({ ...prev, date_preset: preset, ...range }))
  }

  const handleArchive = async (id, isArchived) => {
    try {
      await archiveMutation.mutateAsync({ id, isArchived })
      toast.success(isArchived ? 'Application restored' : 'Application archived')
      setSelectedIds(prev => { const next = new Set(prev); next.delete(id); return next })
    } catch {
      toast.error('Failed to update application')
    }
  }

  const handleDelete = async () => {
    if (!deleteId) return
    try {
      await deleteMutation.mutateAsync(deleteId)
      toast.success('Application deleted')
      setDeleteId(null)
      setSelectedIds(prev => { const next = new Set(prev); next.delete(deleteId); return next })
    } catch {
      toast.error('Failed to delete application')
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
    if (selectedIds.size === applicationIds.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(applicationIds))
    }
  }

  const allSelected = applicationIds.length > 0 && selectedIds.size === applicationIds.length
  const someSelected = selectedIds.size > 0 && selectedIds.size < applicationIds.length
  const selectionCount = selectedIds.size

  // Bulk actions
  const handleBulkDelete = async () => {
    const ids = [...selectedIds]
    try {
      const result = await bulkDeleteMutation.mutateAsync(ids)
      toast.success(result.message)
      setSelectedIds(new Set())
      setBulkDeleteOpen(false)
    } catch {
      toast.error('Failed to delete applications')
    }
  }

  const handleBulkArchive = async (archive) => {
    const ids = [...selectedIds]
    try {
      const result = await bulkArchiveMutation.mutateAsync({ ids, archive })
      toast.success(result.message)
      setSelectedIds(new Set())
    } catch {
      toast.error(`Failed to ${archive ? 'archive' : 'restore'} applications`)
    }
  }

  const SelectIcon = allSelected ? CheckSquare : someSelected ? MinusSquare : Square

  return (
    <div>
      <PageHeader
        title="Applications"
        badge={<span className="badge bg-slate-100 text-slate-700">{applications.length}</span>}
        description="Manage all candidate applications"
        actions={
          <button onClick={() => refetch()} className="btn-ghost">
            <RefreshCw className="h-4 w-4" />
            Refresh
          </button>
        }
      />

      <div className="card mb-6 p-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[200px] flex-1">
            <label className="label">Search</label>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                placeholder="Name or email..."
                className="input pl-9"
                value={filters.search}
                onChange={(e) => handleFilterChange('search', e.target.value)}
              />
            </div>
          </div>
          <div className="w-[180px]">
            <label className="label">Job Offer</label>
            <select className="select" value={filters.job_offer_id} onChange={(e) => handleFilterChange('job_offer_id', e.target.value)}>
              <option value="">All Offers</option>
              {jobOffers.map(o => <option key={o.offer_id} value={o.offer_id}>{o.title}</option>)}
            </select>
          </div>
          <div className="w-[140px]">
            <label className="label">AI Status</label>
            <select className="select" value={filters.ai_status} onChange={(e) => handleFilterChange('ai_status', e.target.value)}>
              <option value="">All</option>
              <option value="approved">Approved</option>
              <option value="rejected">Rejected</option>
              <option value="pending">Pending</option>
            </select>
          </div>
          <div className="w-[160px]">
            <label className="label">HR Status</label>
            <select className="select" value={filters.hr_status} onChange={(e) => handleFilterChange('hr_status', e.target.value)}>
              <option value="">All</option>
              <option value="pending">Pending</option>
              <option value="selected">Selected</option>
              <option value="rejected">Rejected</option>
              <option value="interview_sent">Interview Sent</option>
            </select>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-slate-500">Period:</span>
          {DATE_PRESETS.map(p => (
            <button
              key={p.value}
              onClick={() => handleDatePreset(p.value)}
              className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                filters.date_preset === p.value
                  ? 'bg-brand-500 text-white'
                  : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
              }`}
            >
              {p.label}
            </button>
          ))}
          <div className="ml-auto flex items-center gap-2">
            <label className="flex items-center gap-2 text-xs text-slate-500">
              <input
                type="checkbox"
                checked={filters.show_archived}
                onChange={(e) => handleFilterChange('show_archived', e.target.checked)}
                className="rounded border-slate-300 text-brand-500 focus:ring-brand-500"
              />
              Show archived
            </label>
          </div>
        </div>
      </div>

      {/* Bulk action bar */}
      {selectionCount > 0 && (
        <div className="mb-4 flex items-center gap-3 rounded-lg border border-brand-200 bg-brand-50 px-4 py-2.5">
          <span className="text-sm font-medium text-brand-700">{selectionCount} selected</span>
          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={() => handleBulkArchive(!filters.show_archived)}
              disabled={bulkArchiveMutation.isPending}
              className="inline-flex items-center gap-1.5 rounded-md bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm ring-1 ring-slate-200 transition-colors hover:bg-slate-50"
            >
              {filters.show_archived ? <ArchiveRestore className="h-3.5 w-3.5" /> : <Archive className="h-3.5 w-3.5" />}
              {filters.show_archived ? 'Restore' : 'Archive'}
            </button>
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
        <div className="flex h-40 items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
        </div>
      ) : applications.length === 0 ? (
        <EmptyState icon={FileText} title="No applications found" description="Try adjusting your filters" />
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
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Candidate</th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Job Offer</th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">AI Status</th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">HR Status</th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Date</th>
                <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-slate-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {applications.map((app) => {
                const isSelected = selectedIds.has(app.application_id)
                return (
                  <tr key={app.application_id} className={`transition-colors ${isSelected ? 'bg-brand-50/50' : 'hover:bg-slate-50/50'}`}>
                    <td className="w-10 px-3 py-3">
                      <button onClick={() => toggleSelect(app.application_id)} className={`flex items-center justify-center transition-colors ${isSelected ? 'text-brand-500' : 'text-slate-300 hover:text-slate-500'}`}>
                        {isSelected ? <CheckSquare className="h-4.5 w-4.5" /> : <Square className="h-4.5 w-4.5" />}
                      </button>
                    </td>
                    <td className="px-4 py-3">
                      <div>
                        <p className="text-sm font-medium text-slate-900">{app.candidate.full_name}</p>
                        <p className="text-xs text-slate-500">{app.candidate.email}</p>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <p className="text-sm text-slate-700">{truncate(app.job_offer.title, 30)}</p>
                    </td>
                    <td className="px-4 py-3"><StatusBadge status={app.ai_status} /></td>
                    <td className="px-4 py-3"><StatusBadge status={app.hr_status} /></td>
                    <td className="px-4 py-3">
                      <p className="text-sm text-slate-500">{formatDate(app.submitted_at)}</p>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-1">
                        <button onClick={() => navigate(`/admin/applications/${app.application_id}`)} className="btn-icon" title="View details">
                          <Eye className="h-4 w-4" />
                        </button>
                        <button onClick={() => handleArchive(app.application_id, app.is_archived)} className="btn-icon" title={app.is_archived ? 'Restore' : 'Archive'}>
                          {app.is_archived ? <ArchiveRestore className="h-4 w-4" /> : <Archive className="h-4 w-4" />}
                        </button>
                        <button onClick={() => setDeleteId(app.application_id)} className="btn-icon text-red-500 hover:bg-red-50 hover:text-red-700" title="Delete">
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <ConfirmDialog
        open={!!deleteId}
        onClose={() => setDeleteId(null)}
        onConfirm={handleDelete}
        title="Delete Application"
        description="This will permanently delete the application. This action cannot be undone."
        confirmLabel="Delete"
        loading={deleteMutation.isPending}
      />
      <ConfirmDialog
        open={bulkDeleteOpen}
        onClose={() => setBulkDeleteOpen(false)}
        onConfirm={handleBulkDelete}
        title={`Delete ${selectionCount} Application${selectionCount !== 1 ? 's' : ''}`}
        description={`This will permanently delete ${selectionCount} application${selectionCount !== 1 ? 's' : ''}. This action cannot be undone.`}
        confirmLabel={`Delete ${selectionCount}`}
        loading={bulkDeleteMutation.isPending}
      />
    </div>
  )
}
