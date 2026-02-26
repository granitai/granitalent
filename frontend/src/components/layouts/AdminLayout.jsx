import React from 'react'
import { Outlet, useLocation, Link } from 'react-router-dom'
import AdminSidebar from './AdminSidebar'
import { ChevronRight, Home } from 'lucide-react'

const routeNames = {
  '/admin': 'Dashboard',
  '/admin/applications': 'Applications',
  '/admin/candidates': 'Candidates',
  '/admin/job-offers': 'Job Offers',
  '/admin/job-offers/new': 'New Job Offer',
  '/admin/interviews': 'Interviews',
}

function getBreadcrumbs(pathname) {
  const segments = pathname.split('/').filter(Boolean)
  const crumbs = []
  let path = ''

  for (const segment of segments) {
    path += `/${segment}`
    const name = routeNames[path]
    if (name) {
      crumbs.push({ name, path })
    }
  }

  if (crumbs.length === 0) {
    crumbs.push({ name: 'Dashboard', path: '/admin' })
  }

  return crumbs
}

export default function AdminLayout() {
  const location = useLocation()
  const breadcrumbs = getBreadcrumbs(location.pathname)

  return (
    <div className="min-h-screen bg-slate-50">
      <AdminSidebar />

      <div className="pl-[240px] transition-all duration-300">
        <header className="sticky top-0 z-30 flex h-16 items-center border-b border-slate-200 bg-white/80 px-6 backdrop-blur-sm">
          <nav className="flex items-center gap-1.5 text-sm">
            <Link to="/admin" className="text-slate-400 transition-colors hover:text-slate-600">
              <Home className="h-4 w-4" />
            </Link>
            {breadcrumbs.map((crumb, i) => (
              <React.Fragment key={crumb.path}>
                <ChevronRight className="h-3.5 w-3.5 text-slate-300" />
                {i === breadcrumbs.length - 1 ? (
                  <span className="font-medium text-slate-900">{crumb.name}</span>
                ) : (
                  <Link to={crumb.path} className="text-slate-500 transition-colors hover:text-slate-700">
                    {crumb.name}
                  </Link>
                )}
              </React.Fragment>
            ))}
          </nav>
        </header>

        <main className="p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
