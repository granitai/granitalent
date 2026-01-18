import React, { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { 
  HiDocumentText, 
  HiUserGroup, 
  HiBriefcase, 
  HiMicrophone, 
  HiSquares2X2, 
  HiBars3,
  HiHome,
  HiArrowRightOnRectangle,
  HiUser
} from 'react-icons/hi2'
import { useAuth } from '../contexts/AuthContext'
import ApplicationsView from '../components/admin/ApplicationsView'
import CandidatesView from '../components/admin/CandidatesView'
import JobOffersView from '../components/admin/JobOffersView'
import InterviewsView from '../components/admin/InterviewsView'
import DashboardOverview from '../components/admin/DashboardOverview'
import './AdminPanel.css'

function AdminPanel() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [activeTab, setActiveTab] = useState('dashboard')
  const [viewMode, setViewMode] = useState('card') // 'card' or 'row'
  const { admin, logout } = useAuth()
  const navigate = useNavigate()

  // Check URL params for tab and filters
  useEffect(() => {
    const tab = searchParams.get('tab')
    if (tab) {
      setActiveTab(tab)
    }
  }, [searchParams])

  const handleTabChange = (tabId) => {
    setActiveTab(tabId)
    const newParams = new URLSearchParams(searchParams)
    newParams.set('tab', tabId)
    setSearchParams(newParams)
  }

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const tabs = [
    { id: 'dashboard', label: 'Dashboard', icon: HiHome },
    { id: 'applications', label: 'Applications', icon: HiDocumentText },
    { id: 'candidates', label: 'Candidates', icon: HiUserGroup },
    { id: 'job-offers', label: 'Job Offers', icon: HiBriefcase },
    { id: 'interviews', label: 'Interviews', icon: HiMicrophone }
  ]

  return (
    <div className="admin-panel">
      <div className="admin-header">
        <div>
          <h1>Recruiter Dashboard</h1>
          <p>Manage applications, candidates, job offers, and interviews</p>
        </div>
        <div className="admin-header-actions">
          {admin && (
            <div className="admin-user-info">
              <HiUser className="user-icon" />
              <span className="user-name">{admin.username}</span>
            </div>
          )}
          {activeTab !== 'dashboard' && (
            <div className="view-toggle">
              <button
                className={`view-toggle-btn ${viewMode === 'card' ? 'active' : ''}`}
                onClick={() => setViewMode('card')}
                title="Card View"
              >
                <HiSquares2X2 />
              </button>
              <button
                className={`view-toggle-btn ${viewMode === 'row' ? 'active' : ''}`}
                onClick={() => setViewMode('row')}
                title="Row View"
              >
                <HiBars3 />
              </button>
            </div>
          )}
          <button className="logout-btn" onClick={handleLogout} title="Logout">
            <HiArrowRightOnRectangle />
            <span>Logout</span>
          </button>
        </div>
      </div>

      <div className="admin-tabs">
        {tabs.map(tab => {
          const Icon = tab.icon
          return (
            <button
              key={tab.id}
              className={`admin-tab ${activeTab === tab.id ? 'active' : ''}`}
              onClick={() => handleTabChange(tab.id)}
            >
              <Icon className="tab-icon" />
              <span className="tab-label">{tab.label}</span>
            </button>
          )
        })}
      </div>

      <div className="admin-content">
        {activeTab === 'dashboard' && <DashboardOverview />}
        {activeTab === 'applications' && <ApplicationsView viewMode={viewMode} />}
        {activeTab === 'candidates' && <CandidatesView viewMode={viewMode} />}
        {activeTab === 'job-offers' && <JobOffersView viewMode={viewMode} />}
        {activeTab === 'interviews' && <InterviewsView viewMode={viewMode} />}
      </div>
    </div>
  )
}

export default AdminPanel
