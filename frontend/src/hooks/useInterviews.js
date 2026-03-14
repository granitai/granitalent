import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../contexts/AuthContext'

export function useInterviews(filters = {}) {
  const { authApi } = useAuth()

  return useQuery({
    queryKey: ['interviews', filters],
    queryFn: async () => {
      const params = new URLSearchParams()
      if (filters.status) params.append('status', filters.status)
      if (filters.job_offer_id) params.append('job_offer_id', filters.job_offer_id)
      if (filters.date_from) params.append('date_from', filters.date_from)
      if (filters.date_to) params.append('date_to', filters.date_to)
      if (filters.show_archived) params.append('show_archived', 'true')
      const { data } = await authApi.get(`/admin/interviews?${params}`)
      return data
    },
  })
}

export function useInterview(id) {
  const { authApi } = useAuth()

  return useQuery({
    queryKey: ['interview', id],
    queryFn: async () => {
      const { data } = await authApi.get(`/admin/interviews/${id}`)
      return data
    },
    enabled: !!id,
  })
}

export function useArchiveInterview() {
  const { authApi } = useAuth()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ id, isArchived }) => {
      const action = isArchived ? 'unarchive' : 'archive'
      await authApi.post(`/admin/interviews/${id}/${action}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['interviews'] })
    },
  })
}

export function useDeleteInterview() {
  const { authApi } = useAuth()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (id) => {
      await authApi.delete(`/admin/interviews/${id}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['interviews'] })
    },
  })
}

export function useBulkDeleteInterviews() {
  const { authApi } = useAuth()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (ids) => {
      const { data } = await authApi.post('/admin/interviews/bulk-delete', { interview_ids: ids })
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['interviews'] })
    },
  })
}

export function useBulkArchiveInterviews() {
  const { authApi } = useAuth()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ ids, archive }) => {
      const { data } = await authApi.post('/admin/interviews/bulk-archive', { interview_ids: ids, archive })
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['interviews'] })
    },
  })
}

export function useRegenerateAssessment() {
  const { authApi } = useAuth()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (id) => {
      const { data } = await authApi.post(`/admin/interviews/${id}/regenerate-assessment`)
      return data
    },
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: ['interview', id] })
      queryClient.invalidateQueries({ queryKey: ['interviews'] })
    },
  })
}

export function useInterviewRecording(interviewId) {
  const { authApi } = useAuth()

  return useQuery({
    queryKey: ['interview-recording', interviewId],
    queryFn: async () => {
      const { data } = await authApi.get(`/admin/interviews/${interviewId}/recording`)
      return data
    },
    enabled: false,
  })
}
