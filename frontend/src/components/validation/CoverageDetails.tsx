import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { ValidationCoverage } from "@/types";
export function CoverageDetails({ coverage }: { coverage: ValidationCoverage }) {
  const missing = coverage.missingDocuments ?? [], unchecked = coverage.uncheckedDocuments ?? [];
  return <div className="grid gap-4 md:grid-cols-2">
    {missing.length > 0 && <Card className="border-amber-300"><CardHeader><CardTitle className="text-sm">Missing supporting documents</CardTitle></CardHeader><CardContent className="space-y-3">{missing.map((doc, index) => <div key={doc.doc_type + index}><div className="flex items-center gap-2"><p className="text-sm font-medium">{doc.doc_type.replace(/_/g, " ")}</p><Badge variant="warning">{doc.severity}</Badge></div><p className="mt-1 text-xs text-muted-foreground">{doc.reason}</p></div>)}</CardContent></Card>}
    {unchecked.length > 0 && <Card className="border-amber-300"><CardHeader><CardTitle className="text-sm">Documents not checked</CardTitle></CardHeader><CardContent className="space-y-3">{unchecked.map(doc => <div key={doc.document_id}><p className="break-all text-sm font-medium">{doc.filename}</p><p className="mt-1 text-xs text-muted-foreground">{doc.reason}{doc.error_code ? " · " + doc.error_code : ""}</p></div>)}</CardContent></Card>}
    {(coverage.singleSourceFields?.length ?? 0) > 0 && <Card><CardHeader><CardTitle className="text-sm">Only one supporting source</CardTitle></CardHeader><CardContent><p className="mb-2 text-xs text-muted-foreground">These values cannot be verified across documents.</p><div className="flex flex-wrap gap-1">{coverage.singleSourceFields?.map(field => <Badge key={field.field_key} variant="muted">{field.label}</Badge>)}</div></CardContent></Card>}
    {(coverage.outOfScope?.length ?? 0) > 0 && <Card><CardHeader><CardTitle className="text-sm">Outside the checks performed</CardTitle></CardHeader><CardContent className="space-y-2">{coverage.outOfScope?.map(field => <div key={field.key}><p className="text-sm font-medium">{field.label}</p><p className="text-xs text-muted-foreground">{field.reason}</p></div>)}</CardContent></Card>}
  </div>;
}
