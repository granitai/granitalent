import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { usePublicJobOffers } from '../../hooks/useJobOffers'
import EmptyState from '../../components/shared/EmptyState'
import { parseJSON, truncate } from '../../lib/utils'
import { Briefcase, Search, MapPin, Clock, ChevronRight, Loader2, Sparkles } from 'lucide-react'

export default function JobListPage() {
  const { data: jobs = [], isLoading } = usePublicJobOffers()
  const [search, setSearch] = useState('')

  const filtered = jobs.filter(j =>
    j.title.toLowerCase().includes(search.toLowerCase()) ||
    (j.description || '').toLowerCase().includes(search.toLowerCase()) ||
    (j.required_skills || '').toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div>
      <div className="bg-white border-b border-slate-200">
        <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
          <div className="max-w-2xl">
            <div className="flex items-center gap-2 text-brand-600">
              <Sparkles className="h-5 w-5" />
              <span className="text-sm font-semibold">AI-Powered Recruitment</span>
            </div>
            <h1 className="mt-3 text-4xl font-bold tracking-tight text-slate-900">Find your next opportunity</h1>
            <p className="mt-3 text-lg text-slate-500">Browse open positions and apply with your CV. Our AI evaluates your profile and conducts smart interviews.</p>
          </div>
          <div className="relative mt-8 max-w-lg">
            <Search className="absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              placeholder="Search positions, skills..."
              className="w-full rounded-xl border border-slate-200 bg-slate-50 py-3.5 pl-12 pr-4 text-base text-slate-900 placeholder:text-slate-400 focus:border-brand-500 focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-500/20"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <p className="mt-3 text-sm text-slate-400">{filtered.length} position{filtered.length !== 1 ? 's' : ''} available</p>
        </div>
      </div>

      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        {isLoading ? (
          <div className="flex h-40 items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-brand-500" /></div>
        ) : filtered.length === 0 ? (
          <EmptyState icon={Briefcase} title="No positions found" description={search ? 'Try a different search term' : 'Check back later for new opportunities'} />
        ) : (
          <div className="space-y-3">
            {filtered.map(job => {
              const skills = job.required_skills ? job.required_skills.split(/[,;]/).filter(s => s.trim()).slice(0, 4) : []
              const langs = parseJSON(job.required_languages, [])

              return (
                <Link
                  key={job.offer_id}
                  to={`/jobs/${job.offer_id}`}
                  className="group flex items-center justify-between rounded-xl border border-slate-200 bg-white p-5 transition-all hover:border-brand-200 hover:shadow-md"
                >
                  <div className="min-w-0 flex-1">
                    <h3 className="text-base font-semibold text-slate-900 group-hover:text-brand-700">{job.title}</h3>
                    <p className="mt-1 text-sm text-slate-500 line-clamp-2">{truncate(job.description, 150)}</p>
                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      {skills.map((s, i) => <span key={i} className="badge bg-slate-100 text-slate-600">{s.trim()}</span>)}
                      {langs.map(l => <span key={l} className="badge bg-violet-50 text-violet-700">{l}</span>)}
                      {job.experience_level && (
                        <span className="flex items-center gap-1 text-xs text-slate-400">
                          <Clock className="h-3 w-3" />{job.experience_level}
                        </span>
                      )}
                    </div>
                  </div>
                  <ChevronRight className="ml-4 h-5 w-5 shrink-0 text-slate-300 transition-colors group-hover:text-brand-500" />
                </Link>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
