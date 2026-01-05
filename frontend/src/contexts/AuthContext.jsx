import React, { createContext, useContext, useState, useEffect, useMemo } from 'react'
import axios from 'axios'
import { createAuthApi, setAuthApiInstance } from '../utils/api'

// Utiliser une URL relative qui sera gérée par Nginx en production
// et par le proxy Vite en développement
const API_BASE_URL = '/api'

const AuthContext = createContext(null)

export const useAuth = () => {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}

export const AuthProvider = ({ children }) => {
  const [admin, setAdmin] = useState(null)
  const [loading, setLoading] = useState(true)

  const getAuthHeaders = () => {
    const token = localStorage.getItem('admin_token')
    return token ? { Authorization: `Bearer ${token}` } : {}
  }

  // Create auth API instance that updates when token changes
  const authApi = useMemo(() => {
    const api = createAuthApi(getAuthHeaders)
    setAuthApiInstance(api)
    return api
  }, [admin]) // Recreate when admin state changes (login/logout)

  // Check if user is authenticated on mount
  useEffect(() => {
    checkAuth()
  }, [])

  const checkAuth = async () => {
    const token = localStorage.getItem('admin_token')
    if (!token) {
      setLoading(false)
      return
    }

    try {
      const response = await axios.get(`${API_BASE_URL}/auth/me`, {
        headers: {
          Authorization: `Bearer ${token}`
        }
      })
      setAdmin(response.data)
    } catch (error) {
      // Token is invalid, remove it
      localStorage.removeItem('admin_token')
      setAdmin(null)
    } finally {
      setLoading(false)
    }
  }

  const login = async (username, password) => {
    try {
      const response = await axios.post(`${API_BASE_URL}/auth/login`, {
        username,
        password
      })
      const { access_token, username: adminUsername } = response.data
      localStorage.setItem('admin_token', access_token)
      
      // Get admin info
      const adminResponse = await axios.get(`${API_BASE_URL}/auth/me`, {
        headers: {
          Authorization: `Bearer ${access_token}`
        }
      })
      setAdmin(adminResponse.data)
      return { success: true }
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.detail || 'Login failed'
      }
    }
  }

  const logout = () => {
    localStorage.removeItem('admin_token')
    setAdmin(null)
  }

  return (
    <AuthContext.Provider
      value={{
        admin,
        loading,
        login,
        logout,
        isAuthenticated: !!admin,
        getAuthHeaders,
        authApi
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

