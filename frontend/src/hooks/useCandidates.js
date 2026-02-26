import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../contexts/AuthContext'

export function useCandidates(search = '') {
  const { authApi } = useAuth()

  return useQuery({
    queryKey: ['candidates', search],
    queryFn: async () => {
      const params = new URLSearchParams()
      if (search) params.append('search', search)
      const { data } = await authApi.get(`/admin/candidates?${params}`)
      return data
    },
  })
}

export function useCandidate(email) {
  const { authApi } = useAuth()

  return useQuery({
    queryKey: ['candidate', email],
    queryFn: async () => {
      const { data } = await authApi.get(`/admin/candidates/${email}`)
      return data
    },
    enabled: !!email,
  })
}

export function useDeleteCandidate() {
  const { authApi } = useAuth()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (candidateId) => {
      await authApi.delete(`/admin/candidates/${candidateId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['candidates'] })
    },
  })
}
