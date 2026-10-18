import { Button } from "./button";
export function ErrorState({ error, retry }: { error: Error | null; retry?: () => void }) {
  return <div role="alert" className="m-6 rounded-xl border border-destructive/30 bg-destructive/5 p-6"><h2 className="font-semibold">Unable to load this page</h2><p className="mt-2 text-sm text-muted-foreground">{error?.message ?? "Please try again."}</p>{retry && <Button className="mt-4" variant="outline" onClick={retry}>Try again</Button>}</div>;
}
