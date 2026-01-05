import axios from 'axios'

// Utiliser une URL relative qui sera gérée par Nginx en production
// et par le proxy Vite en développement
const API_BASE_URL = '/api'

// Create axios instance for public endpoints
export const publicApi = axios.create({
  baseURL: API_BASE_URL,
})

// Create axios instance for authenticated endpoints
export const createAuthApi = (getAuthHeaders) => {
  const api = axios.create({
    baseURL: API_BASE_URL,
  })

  // Add auth token to all requests
  api.interceptors.request.use((config) => {
    const headers = getAuthHeaders()
    if (headers.Authorization) {
      config.headers.Authorization = headers.Authorization
    }
    return config
  })

  return api
}

// Helper to get auth API instance (to be used in components)
let authApiInstance = null

export const setAuthApiInstance = (instance) => {
  authApiInstance = instance
}

export const getAuthApi = () => {
  if (!authApiInstance) {
    throw new Error('Auth API instance not initialized. Make sure to call setAuthApiInstance first.')
  }
  return authApiInstance
}

