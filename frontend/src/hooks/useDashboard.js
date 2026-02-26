import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../contexts/AuthContext'

export function useDashboardStats() {
  const { authApi } = useAuth()

  return useQuery({
    queryKey: ['dashboard', 'stats'],
    queryFn: async () => {
      const { data } = await authApi.get('/admin/dashboard/stats')
      return data
    },
    refetchInterval: 30000,
  })
}
