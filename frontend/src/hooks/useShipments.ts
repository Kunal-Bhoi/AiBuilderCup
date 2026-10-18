import {
  useQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query"
import { shipmentService } from "@/services/shipmentService"
import type {
  CreateShipmentPayload,
  ReviewFindingPayload,
} from "@/types"

// ─── Query Keys ───────────────────────────────────────────────────────────────

export const queryKeys = {
  shipments: ["shipments"] as const,
  shipment: (id: string) => ["shipments", id] as const,
  dashboardStats: ["dashboard-stats"] as const,
  processingStatus: (id: string) => ["processing", id] as const,
  validationResults: (id: string) => ["results", id] as const,
  report: (id: string) => ["report", id] as const,
}

// ─── Shipment Queries ─────────────────────────────────────────────────────────

export function useShipments() {
  return useQuery({
    queryKey: queryKeys.shipments,
    queryFn: shipmentService.listShipments.bind(shipmentService),
    refetchInterval: 5000,
  })
}

export function useShipment(id: string) {
  return useQuery({
    queryKey: queryKeys.shipment(id),
    queryFn: () => shipmentService.getShipment(id),
    enabled: !!id,
  })
}

export function useDashboardStats() {
  return useQuery({
    queryKey: queryKeys.dashboardStats,
    queryFn: shipmentService.getDashboardStats.bind(shipmentService),
    refetchInterval: 5000,
  })
}

// ─── Processing Queries ───────────────────────────────────────────────────────

export function useProcessingStatus(id: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.processingStatus(id),
    queryFn: () => shipmentService.getProcessingStatus(id),
    enabled: !!id && enabled,
    refetchInterval: (query) => ["queued", "processing"].includes(query.state.data?.shipmentStatus ?? "") ? 1000 : false,
  })
}

// ─── Validation Results ───────────────────────────────────────────────────────

export function useValidationResults(id: string) {
  return useQuery({
    queryKey: queryKeys.validationResults(id),
    queryFn: () => shipmentService.getValidationResults(id),
    enabled: !!id,
  })
}

// ─── Report ───────────────────────────────────────────────────────────────────

export function useReport(id: string) {
  return useQuery({
    queryKey: queryKeys.report(id),
    queryFn: () => shipmentService.getReport(id),
    enabled: !!id,
  })
}

// ─── Mutations ────────────────────────────────────────────────────────────────

export function useCreateShipment() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: CreateShipmentPayload) =>
      shipmentService.createShipment(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.shipments })
      qc.invalidateQueries({ queryKey: queryKeys.dashboardStats })
    },
  })
}

export function useUploadDocuments(shipmentId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: File[] | { files: File[]; onProgress?: import("@/types").UploadProgress }) =>
      shipmentService.uploadDocuments(shipmentId, Array.isArray(input) ? input : input.files, Array.isArray(input) ? undefined : input.onProgress),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.shipment(shipmentId) })
      qc.invalidateQueries({ queryKey: queryKeys.processingStatus(shipmentId) })
      qc.invalidateQueries({ queryKey: ["document-library"] })
    },
  })
}

export function useRemoveDocument(shipmentId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (documentId: string) =>
      shipmentService.removeDocument(shipmentId, documentId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.shipment(shipmentId) })
      qc.invalidateQueries({ queryKey: queryKeys.processingStatus(shipmentId) })
      qc.invalidateQueries({ queryKey: ["document-library"] })
    },
  })
}

export function useStartValidation(shipmentId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => shipmentService.startValidation(shipmentId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.shipment(shipmentId) })
      qc.invalidateQueries({ queryKey: queryKeys.processingStatus(shipmentId) })
      qc.invalidateQueries({ queryKey: ["document-library"] })
      qc.invalidateQueries({ queryKey: queryKeys.shipments })
      qc.invalidateQueries({ queryKey: queryKeys.dashboardStats })
    },
  })
}

export function useReviewFinding(shipmentId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      findingId,
      payload,
    }: {
      findingId: string
      payload: ReviewFindingPayload
    }) => shipmentService.reviewFinding(shipmentId, findingId, payload),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: queryKeys.validationResults(shipmentId) })
      qc.invalidateQueries({ queryKey: queryKeys.shipment(shipmentId) })
      qc.invalidateQueries({ queryKey: queryKeys.processingStatus(shipmentId) })
      qc.invalidateQueries({ queryKey: ["document-library"] })
      qc.invalidateQueries({ queryKey: queryKeys.report(shipmentId) })
    },
  })
}

export function useFinalizeReview(shipmentId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => shipmentService.finalizeReview(shipmentId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.shipment(shipmentId) })
      qc.invalidateQueries({ queryKey: queryKeys.processingStatus(shipmentId) })
      qc.invalidateQueries({ queryKey: ["document-library"] })
      qc.invalidateQueries({ queryKey: queryKeys.shipments })
      qc.invalidateQueries({ queryKey: queryKeys.dashboardStats })
      qc.invalidateQueries({ queryKey: queryKeys.report(shipmentId) })
      qc.invalidateQueries({ queryKey: queryKeys.validationResults(shipmentId) })
    },
  })
}

export function useDocumentLibrary() { return useQuery({ queryKey: ["document-library"], queryFn: () => shipmentService.listDocuments() }); }
