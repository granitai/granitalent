import React, { useState, useEffect } from 'react'
import { 
  HiDocumentText, 
  HiUserGroup, 
  HiBriefcase, 
  HiMicrophone,
  HiClock,
  HiCheckCircle,
  HiXCircle,
  HiArrowTrendingUp,
  HiEye,
  HiArrowPath
} from 'react-icons/hi2'
import { useAuth } from '../../contexts/AuthContext'
import { useNavigate, useSearchParams } from 'react-router-dom'
import './DashboardOverview.css'

function DashboardOverview() {
  const { authApi } = useAuth()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)

  const navigateToTab = (tab, filter = null) => {
    const newParams = new URLSearchParams()
    newParams.set('tab', tab)
    if (filter) {
      newParams.set('filter', filter)
    }
    setSearchParams(newParams)
  }

  useEffect(() => {
    loadStats()
    // Refresh stats every 30 seconds
    const interval = setInterval(loadStats, 30000)
    return () => clearInterval(interval)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const loadStats = async () => {
    try {
      const response = await authApi.get('/admin/dashboard/stats')
      setStats(response.data)
    } catch (error) {
      console.error('Error loading dashboard stats:', error)
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="dashboard-loading">
        <HiArrowPath className="spinning" />
        <p>Loading dashboard...</p>
      </div>
    )
  }

  if (!stats) {
    return <div className="dashboard-error">Error loading dashboard data</div>
  }

  const statCards = [
    {
      id: 'applications',
      title: 'Total Applications',
      value: stats.applications.total,
      icon: HiDocumentText,
      color: 'primary',
      onClick: () => navigateToTab('applications')
    },
    {
      id: 'needs-review',
      title: 'Needs Review',
      value: stats.applications.needs_review,
      icon: HiClock,
      color: 'warning',
      onClick: () => navigateToTab('applications', 'needs_review')
    },
    {
      id: 'interviews',
      title: 'Interviews',
      value: stats.interviews.total,
      icon: HiMicrophone,
      color: 'info',
      onClick: () => navigateToTab('interviews')
    },
    {
      id: 'candidates',
      title: 'Candidates',
      value: stats.candidates.total,
      icon: HiUserGroup,
      color: 'success',
      onClick: () => navigateToTab('candidates')
    },
    {
      id: 'job-offers',
      title: 'Job Offers',
      value: stats.job_offers.total,
      icon: HiBriefcase,
      color: 'secondary',
      onClick: () => navigateToTab('job-offers')
    },
    {
      id: 'selected',
      title: 'Selected',
      value: stats.applications.selected,
      icon: HiCheckCircle,
      color: 'success',
      onClick: () => navigateToTab('applications', 'selected')
    }
  ]

  const quickStats = [
    {
      label: 'Pending Interviews',
      value: stats.interviews.pending,
      icon: HiClock,
      color: 'warning'
    },
    {
      label: 'Completed Interviews',
      value: stats.interviews.completed,
      icon: HiCheckCircle,
      color: 'success'
    },
    {
      label: 'AI Approved',
      value: stats.applications.approved,
      icon: HiCheckCircle,
      color: 'info'
    },
    {
      label: 'Rejected',
      value: stats.applications.rejected,
      icon: HiXCircle,
      color: 'error'
    },
    {
      label: 'Recent (7 days)',
      value: stats.applications.recent,
      icon: HiArrowTrendingUp,
      color: 'primary'
    }
  ]

  return (
    <div className="dashboard-overview">
      <div className="dashboard-header">
        <div>
          <h2>Dashboard Overview</h2>
          <p>Welcome back! Here's what's happening with your recruitment pipeline.</p>
        </div>
        <button className="refresh-btn" onClick={loadStats} title="Refresh">
          <HiArrowPath />
        </button>
      </div>

      <div className="stats-grid">
        {statCards.map(card => {
          const Icon = card.icon
          return (
            <div 
              key={card.id} 
              className={`stat-card stat-card-${card.color}`}
              onClick={card.onClick}
            >
              <div className="stat-card-content">
                <div className="stat-card-icon">
                  <Icon />
                </div>
                <div className="stat-card-info">
                  <h3>{card.value}</h3>
                  <p>{card.title}</p>
                </div>
              </div>
              <div className="stat-card-action">
                <HiEye />
              </div>
            </div>
          )
        })}
      </div>

      <div className="dashboard-sections">
        <div className="dashboard-section">
          <h3>Application Status</h3>
          <div className="quick-stats">
            {quickStats.map((stat, idx) => {
              const Icon = stat.icon
              return (
                <div key={idx} className={`quick-stat quick-stat-${stat.color}`}>
                  <div className="quick-stat-content">
                    <span className="quick-stat-value">{stat.value}</span>
                    <span className="quick-stat-label">{stat.label}</span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        <div className="dashboard-section">
          <h3>Quick Actions</h3>
          <div className="quick-actions">
            <button 
              className="action-btn action-primary"
              onClick={() => navigateToTab('applications', 'needs_review')}
            >
              <HiClock />
              <span>Review Applications</span>
            </button>
            <button 
              className="action-btn action-secondary"
              onClick={() => navigateToTab('job-offers')}
            >
              <HiBriefcase />
              <span>Manage Job Offers</span>
            </button>
            <button 
              className="action-btn action-info"
              onClick={() => navigateToTab('interviews')}
            >
              <HiMicrophone />
              <span>View Interviews</span>
            </button>
            <button 
              className="action-btn action-success"
              onClick={() => navigateToTab('candidates')}
            >
              <HiUserGroup />
              <span>Browse Candidates</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default DashboardOverview

