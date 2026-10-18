import { useMutation, useQueryClient } from "@tanstack/react-query";
import { shipmentService } from "@/services/shipmentService";
import { DOC_LABELS } from "@/services/backendAdapter";
import type { components } from "@/types/backend.generated";
import type { ShipmentDocument } from "@/types";
export function DocumentTypeSelect({ shipmentId, document, disabled }: { shipmentId: string; document: ShipmentDocument; disabled?: boolean }) {
  const queryClient = useQueryClient();
  const change = useMutation({ mutationFn: (type: components["schemas"]["DocType"]) => shipmentService.updateDocumentType(shipmentId, document.id, type),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["shipments"] }); queryClient.invalidateQueries({ queryKey: ["document-library"] }); queryClient.invalidateQueries({ queryKey: ["results", shipmentId] }); } });
  return <div><select aria-label={"Document type for " + document.filename} value={document.type.toUpperCase()} disabled={disabled || change.isPending} onChange={event => change.mutate(event.target.value as components["schemas"]["DocType"])} className="mt-1 h-8 max-w-full rounded border bg-background px-2 text-xs">{Object.entries(DOC_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>{change.error && <p role="alert" className="mt-1 text-xs text-destructive">{change.error.message}</p>}</div>;
}
