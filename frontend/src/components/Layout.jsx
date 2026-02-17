import React from 'react'
import { Outlet, Link, useLocation, useNavigate } from 'react-router-dom'
import { HiSparkles, HiBriefcase, HiCog6Tooth, HiArrowRightOnRectangle, HiDocumentText, HiMicrophone, HiRectangleStack } from 'react-icons/hi2'
import { useAuth } from '../contexts/AuthContext'
import './Layout.css'

function Layout() {
  const location = useLocation()
  const { isAuthenticated, logout, admin } = useAuth()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/candidates')
  }

  return (
    <div className="layout">
      <nav className="navbar">
        <div className="nav-container">
          <Link to="/" className="nav-logo">
            <HiSparkles className="logo-icon" />
            <span className="logo-text">AI Interview</span>
          </Link>
          <div className="nav-links">
            <Link
              to="/candidates"
              className={location.pathname === '/candidates' ? 'active' : ''}
            >
              <HiBriefcase className="nav-icon" />
              <span>Job Offers</span>
            </Link>
            <Link
              to="/my-applications"
              className={location.pathname === '/my-applications' ? 'active' : ''}
            >
              <HiRectangleStack className="nav-icon" />
              <span>All my applications</span>
            </Link>
            {isAuthenticated && (
              <>
                <Link
                  to="/admin"
                  className={location.pathname === '/admin' ? 'active' : ''}
                >
                  <HiCog6Tooth className="nav-icon" />
                  <span>Admin Panel</span>
                </Link>
                <div className="nav-user">
                  <span className="nav-username">{admin?.username}</span>
                  <button
                    onClick={handleLogout}
                    className="logout-button"
                    title="Logout"
                  >
                    <HiArrowRightOnRectangle className="nav-icon" />
                    <span>Logout</span>
                  </button>
                </div>
              </>
            )}
            {!isAuthenticated && (
              <Link
                to="/login"
                className={location.pathname === '/login' ? 'active' : ''}
              >
                <HiCog6Tooth className="nav-icon" />
                <span>Admin Login</span>
              </Link>
            )}
          </div>
        </div>
      </nav>
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  )
}

export default Layout

