import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../contexts/AuthContext'
import axios from 'axios'

export function useJobOffers() {
  const { authApi } = useAuth()

  return useQuery({
    queryKey: ['job-offers'],
    queryFn: async () => {
      const { data } = await authApi.get('/admin/job-offers')
      return data
    },
  })
}

export function usePublicJobOffers() {
  return useQuery({
    queryKey: ['public-job-offers'],
    queryFn: async () => {
      const { data } = await axios.get('/api/job-offers')
      return data
    },
  })
}

export function useJobOffer(id) {
  const { authApi } = useAuth()

  return useQuery({
    queryKey: ['job-offer', id],
    queryFn: async () => {
      const { data } = await authApi.get(`/admin/job-offers/${id}`)
      return data
    },
    enabled: !!id,
  })
}

export function useCreateJobOffer() {
  const { authApi } = useAuth()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (offerData) => {
      const { data } = await authApi.post('/admin/job-offers', offerData)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['job-offers'] })
      queryClient.invalidateQueries({ queryKey: ['public-job-offers'] })
    },
  })
}

export function useUpdateJobOffer() {
  const { authApi } = useAuth()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ id, data: offerData }) => {
      const { data } = await authApi.put(`/admin/job-offers/${id}`, offerData)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['job-offers'] })
      queryClient.invalidateQueries({ queryKey: ['public-job-offers'] })
    },
  })
}

export function useDeleteJobOffer() {
  const { authApi } = useAuth()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (id) => {
      await authApi.delete(`/admin/job-offers/${id}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['job-offers'] })
      queryClient.invalidateQueries({ queryKey: ['public-job-offers'] })
    },
  })
}

export function useBulkDeleteJobOffers() {
  const { authApi } = useAuth()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (ids) => {
      const { data } = await authApi.post('/admin/job-offers/bulk-delete', { offer_ids: ids })
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['job-offers'] })
      queryClient.invalidateQueries({ queryKey: ['public-job-offers'] })
    },
  })
}

export function useJobOfferApplications(offerId) {
  const { authApi } = useAuth()

  return useQuery({
    queryKey: ['job-offer-applications', offerId],
    queryFn: async () => {
      const { data } = await authApi.get(`/admin/job-offers/${offerId}/applications`)
      return data
    },
    enabled: !!offerId,
  })
}
