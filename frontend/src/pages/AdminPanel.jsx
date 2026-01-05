import React, { useState } from 'react'
import { HiDocumentText, HiUserGroup, HiBriefcase, HiMicrophone, HiSquares2X2, HiBars3 } from 'react-icons/hi2'
import ApplicationsView from '../components/admin/ApplicationsView'
import CandidatesView from '../components/admin/CandidatesView'
import JobOffersView from '../components/admin/JobOffersView'
import InterviewsView from '../components/admin/InterviewsView'
import './AdminPanel.css'

function AdminPanel() {
  const [activeTab, setActiveTab] = useState('applications')
  const [viewMode, setViewMode] = useState('card') // 'card' or 'row'

  const tabs = [
    { id: 'applications', label: 'Applications', icon: HiDocumentText },
    { id: 'candidates', label: 'Candidates', icon: HiUserGroup },
    { id: 'job-offers', label: 'Job Offers', icon: HiBriefcase },
    { id: 'interviews', label: 'Interviews', icon: HiMicrophone }
  ]

  return (
    <div className="admin-panel">
      <div className="admin-header">
        <div>
          <h1>Admin Panel</h1>
          <p>Manage applications, candidates, job offers, and interviews</p>
        </div>
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
      </div>

      <div className="admin-tabs">
        {tabs.map(tab => {
          const Icon = tab.icon
          return (
            <button
              key={tab.id}
              className={`admin-tab ${activeTab === tab.id ? 'active' : ''}`}
              onClick={() => setActiveTab(tab.id)}
            >
              <Icon className="tab-icon" />
              <span className="tab-label">{tab.label}</span>
            </button>
          )
        })}
      </div>

      <div className="admin-content">
        {activeTab === 'applications' && <ApplicationsView viewMode={viewMode} />}
        {activeTab === 'candidates' && <CandidatesView viewMode={viewMode} />}
        {activeTab === 'job-offers' && <JobOffersView viewMode={viewMode} />}
        {activeTab === 'interviews' && <InterviewsView viewMode={viewMode} />}
      </div>
    </div>
  )
}

export default AdminPanel
