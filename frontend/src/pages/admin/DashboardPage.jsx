import React from 'react'
import { useNavigate } from 'react-router-dom'
import { useDashboardStats } from '../../hooks/useDashboard'
import PageHeader from '../../components/shared/PageHeader'
import {
  FileText,
  Clock,
  Mic,
  Users,
  Briefcase,
  CheckCircle2,
  XCircle,
  TrendingUp,
  ArrowRight,
  RefreshCw,
  Loader2,
} from 'lucide-react'
import { cn } from '../../lib/utils'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell
} from 'recharts'

const CHART_COLORS = ['#0d9488', '#7c3aed', '#f59e0b', '#ef4444', '#3b82f6']

export default function DashboardPage() {
  const navigate = useNavigate()
  const { data: stats, isLoading, refetch } = useDashboardStats()

  if (isLoading) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
      </div>
    )
  }

  if (!stats) {
    return (
      <div className="flex h-[60vh] flex-col items-center justify-center gap-4">
        <p className="text-slate-500">Failed to load dashboard data</p>
        <button onClick={() => refetch()} className="btn-secondary">
          <RefreshCw className="h-4 w-4" />
          Retry
        </button>
      </div>
    )
  }

  const statCards = [
    { title: 'Total Applications', value: stats.applications.total, icon: FileText, color: 'bg-blue-50 text-blue-600', onClick: () => navigate('/admin/applications') },
    { title: 'Needs Review', value: stats.applications.needs_review, icon: Clock, color: 'bg-amber-50 text-amber-600', onClick: () => navigate('/admin/applications?hr_status=pending') },
    { title: 'Interviews', value: stats.interviews.total, icon: Mic, color: 'bg-violet-50 text-violet-600', onClick: () => navigate('/admin/interviews') },
    { title: 'Candidates', value: stats.candidates.total, icon: Users, color: 'bg-emerald-50 text-emerald-600', onClick: () => navigate('/admin/candidates') },
    { title: 'Job Offers', value: stats.job_offers.total, icon: Briefcase, color: 'bg-brand-50 text-brand-600', onClick: () => navigate('/admin/job-offers') },
    { title: 'Selected', value: stats.applications.selected, icon: CheckCircle2, color: 'bg-green-50 text-green-600', onClick: () => navigate('/admin/applications?hr_status=selected') },
  ]

  const statusData = [
    { name: 'AI Approved', value: stats.applications.approved },
    { name: 'AI Rejected', value: stats.applications.rejected },
    { name: 'Pending', value: stats.applications.needs_review },
    { name: 'Selected', value: stats.applications.selected },
  ].filter(d => d.value > 0)

  const quickStats = [
    { label: 'Pending Interviews', value: stats.interviews.pending, icon: Clock, color: 'text-amber-600' },
    { label: 'Completed Interviews', value: stats.interviews.completed, icon: CheckCircle2, color: 'text-emerald-600' },
    { label: 'AI Approved', value: stats.applications.approved, icon: CheckCircle2, color: 'text-blue-600' },
    { label: 'Rejected', value: stats.applications.rejected, icon: XCircle, color: 'text-red-600' },
    { label: 'Recent (7 days)', value: stats.applications.recent, icon: TrendingUp, color: 'text-violet-600' },
  ]

  return (
    <div>
      <PageHeader
        title="Dashboard"
        description="Overview of your recruitment pipeline"
        actions={
          <button onClick={() => refetch()} className="btn-ghost">
            <RefreshCw className="h-4 w-4" />
            Refresh
          </button>
        }
      />

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        {statCards.map((card) => (
          <button
            key={card.title}
            onClick={card.onClick}
            className="card group flex flex-col items-start p-4 text-left transition-shadow hover:shadow-md"
          >
            <div className={cn('flex h-10 w-10 items-center justify-center rounded-lg', card.color)}>
              <card.icon className="h-5 w-5" />
            </div>
            <p className="mt-3 text-2xl font-bold text-slate-900">{card.value}</p>
            <p className="text-xs font-medium text-slate-500">{card.title}</p>
          </button>
        ))}
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <div className="card p-6 lg:col-span-2">
          <h3 className="text-sm font-semibold text-slate-900">Application Status</h3>
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {quickStats.map((stat) => (
              <div key={stat.label} className="rounded-lg bg-slate-50 p-3">
                <div className="flex items-center gap-2">
                  <stat.icon className={cn('h-4 w-4', stat.color)} />
                  <span className="text-xl font-bold text-slate-900">{stat.value}</span>
                </div>
                <p className="mt-1 text-xs text-slate-500">{stat.label}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="card p-6">
          <h3 className="text-sm font-semibold text-slate-900">Status Breakdown</h3>
          {statusData.length > 0 ? (
            <div className="mt-2">
              <ResponsiveContainer width="100%" height={180}>
                <PieChart>
                  <Pie
                    data={statusData}
                    cx="50%"
                    cy="50%"
                    innerRadius={50}
                    outerRadius={75}
                    paddingAngle={3}
                    dataKey="value"
                  >
                    {statusData.map((_, i) => (
                      <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
              <div className="mt-2 flex flex-wrap gap-3">
                {statusData.map((item, i) => (
                  <div key={item.name} className="flex items-center gap-1.5 text-xs">
                    <div className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: CHART_COLORS[i % CHART_COLORS.length] }} />
                    <span className="text-slate-600">{item.name}</span>
                    <span className="font-medium text-slate-900">{item.value}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <p className="mt-4 text-sm text-slate-500">No application data yet</p>
          )}
        </div>
      </div>

      <div className="mt-6">
        <div className="card p-6">
          <h3 className="text-sm font-semibold text-slate-900">Quick Actions</h3>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <button onClick={() => navigate('/admin/applications?hr_status=pending')} className="flex items-center justify-between rounded-lg border border-slate-200 bg-white p-4 text-left transition-all hover:border-brand-300 hover:shadow-sm">
              <div className="flex items-center gap-3">
                <Clock className="h-5 w-5 text-amber-500" />
                <span className="text-sm font-medium text-slate-700">Review Applications</span>
              </div>
              <ArrowRight className="h-4 w-4 text-slate-400" />
            </button>
            <button onClick={() => navigate('/admin/job-offers/new')} className="flex items-center justify-between rounded-lg border border-slate-200 bg-white p-4 text-left transition-all hover:border-brand-300 hover:shadow-sm">
              <div className="flex items-center gap-3">
                <Briefcase className="h-5 w-5 text-brand-500" />
                <span className="text-sm font-medium text-slate-700">Create Job Offer</span>
              </div>
              <ArrowRight className="h-4 w-4 text-slate-400" />
            </button>
            <button onClick={() => navigate('/admin/interviews')} className="flex items-center justify-between rounded-lg border border-slate-200 bg-white p-4 text-left transition-all hover:border-brand-300 hover:shadow-sm">
              <div className="flex items-center gap-3">
                <Mic className="h-5 w-5 text-violet-500" />
                <span className="text-sm font-medium text-slate-700">View Interviews</span>
              </div>
              <ArrowRight className="h-4 w-4 text-slate-400" />
            </button>
            <button onClick={() => navigate('/admin/candidates')} className="flex items-center justify-between rounded-lg border border-slate-200 bg-white p-4 text-left transition-all hover:border-brand-300 hover:shadow-sm">
              <div className="flex items-center gap-3">
                <Users className="h-5 w-5 text-emerald-500" />
                <span className="text-sm font-medium text-slate-700">Browse Candidates</span>
              </div>
              <ArrowRight className="h-4 w-4 text-slate-400" />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
