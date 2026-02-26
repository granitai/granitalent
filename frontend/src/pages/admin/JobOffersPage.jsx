import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useJobOffers, useDeleteJobOffer } from '../../hooks/useJobOffers'
import PageHeader from '../../components/shared/PageHeader'
import EmptyState from '../../components/shared/EmptyState'
import ConfirmDialog from '../../components/shared/ConfirmDialog'
import { formatDate, truncate, parseJSON } from '../../lib/utils'
import { toast } from 'sonner'
import { Plus, Briefcase, Pencil, Trash2, Eye, Loader2 } from 'lucide-react'

export default function JobOffersPage() {
  const navigate = useNavigate()
  const { data: jobOffers = [], isLoading } = useJobOffers()
  const deleteMutation = useDeleteJobOffer()
  const [deleteId, setDeleteId] = useState(null)

  const handleDelete = async () => {
    if (!deleteId) return
    try {
      await deleteMutation.mutateAsync(deleteId)
      toast.success('Job offer deleted')
      setDeleteId(null)
    } catch {
      toast.error('Failed to delete job offer')
    }
  }

  return (
    <div>
      <PageHeader
        title="Job Offers"
        badge={<span className="badge bg-slate-100 text-slate-700">{jobOffers.length}</span>}
        description="Manage your job listings"
        actions={
          <button onClick={() => navigate('/admin/job-offers/new')} className="btn-primary">
            <Plus className="h-4 w-4" /> New Job Offer
          </button>
        }
      />

      {isLoading ? (
        <div className="flex h-40 items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-brand-500" /></div>
      ) : jobOffers.length === 0 ? (
        <EmptyState icon={Briefcase} title="No job offers yet" description="Create your first job offer to start receiving applications" action={<button onClick={() => navigate('/admin/job-offers/new')} className="btn-primary"><Plus className="h-4 w-4" />Create Job Offer</button>} />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {jobOffers.map(offer => {
            const langs = parseJSON(offer.required_languages, [])
            return (
              <div key={offer.offer_id} className="card flex flex-col overflow-hidden">
                <div className="flex-1 p-5">
                  <h3 className="text-base font-semibold text-slate-900">{offer.title}</h3>
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
    </div>
  )
}
