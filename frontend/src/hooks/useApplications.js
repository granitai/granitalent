import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../contexts/AuthContext'

export function useApplications(filters = {}) {
  const { authApi } = useAuth()

  return useQuery({
    queryKey: ['applications', filters],
    queryFn: async () => {
      const params = new URLSearchParams()
      if (filters.job_offer_id) params.append('job_offer_id', filters.job_offer_id)
      if (filters.ai_status) params.append('ai_status', filters.ai_status)
      if (filters.hr_status) params.append('hr_status', filters.hr_status)
      if (filters.search) params.append('search', filters.search)
      if (filters.date_from) params.append('date_from', filters.date_from)
      if (filters.date_to) params.append('date_to', filters.date_to)
      if (filters.show_archived) params.append('show_archived', 'true')
      const { data } = await authApi.get(`/admin/applications?${params}`)
      return data
    },
  })
}

export function useApplication(id) {
  const { authApi } = useAuth()

  return useQuery({
    queryKey: ['application', id],
    queryFn: async () => {
      const { data } = await authApi.get(`/admin/applications/${id}`)
      return data
    },
    enabled: !!id,
  })
}

export function useArchiveApplication() {
  const { authApi } = useAuth()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ id, isArchived }) => {
      const action = isArchived ? 'unarchive' : 'archive'
      await authApi.post(`/admin/applications/${id}/${action}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['applications'] })
    },
  })
}

export function useDeleteApplication() {
  const { authApi } = useAuth()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (id) => {
      await authApi.delete(`/admin/applications/${id}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['applications'] })
    },
  })
}

export function useSelectApplication() {
  const { authApi } = useAuth()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (id) => {
      await authApi.post(`/admin/applications/${id}/select`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['applications'] })
      queryClient.invalidateQueries({ queryKey: ['application'] })
    },
  })
}

export function useRejectApplication() {
  const { authApi } = useAuth()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ id, reason }) => {
      await authApi.post(`/admin/applications/${id}/reject`, null, { params: { reason } })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['applications'] })
      queryClient.invalidateQueries({ queryKey: ['application'] })
    },
  })
}

export function useOverrideApplication() {
  const { authApi } = useAuth()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ id, reason }) => {
      await authApi.post(`/admin/applications/${id}/override`, { hr_status: 'selected', reason })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['applications'] })
      queryClient.invalidateQueries({ queryKey: ['application'] })
    },
  })
}

export function useSendInterview() {
  const { authApi } = useAuth()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ id, interview_date, notes }) => {
      await authApi.post(`/admin/applications/${id}/send-interview`, { interview_date: interview_date || null, notes })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['applications'] })
      queryClient.invalidateQueries({ queryKey: ['application'] })
    },
  })
}
