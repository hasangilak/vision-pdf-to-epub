import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Separator } from "@/components/ui/separator";
import { getDownloadUrl, retryPages } from "@/lib/api";
import { EpubViewer } from "@/components/EpubViewer";
import type { JobState } from "@/hooks/useJobEvents";

interface JobResultProps {
  state: JobState;
  onRetry: () => void;
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m === 0) return `${s} seconds`;
  return `${m} min ${s} sec`;
}

export function JobResult({ state, onRetry }: JobResultProps) {
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);

  const handleRetry = async () => {
    if (!state.jobId) return;
    setRetrying(true);
    setRetryError(null);
    try {
      await retryPages(state.jobId);
      onRetry();
    } catch (err) {
      setRetryError(err instanceof Error ? err.message : "Retry failed");
      setRetrying(false);
    }
  };

  const isCompleted = state.status === "completed";
  const isFailed = state.status === "failed";

  return (
    <Card className="w-full max-w-2xl mx-auto">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-xl">
            {isCompleted ? "Conversion Complete" : "Conversion Failed"}
          </CardTitle>
          <Badge variant={isCompleted ? "default" : "destructive"}>
            {isCompleted ? "Done" : "Failed"}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Summary */}
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div className="space-y-1">
            <p className="text-muted-foreground">Pages Succeeded</p>
            <p className="text-2xl font-semibold">{state.pagesSucceeded}</p>
          </div>
          <div className="space-y-1">
            <p className="text-muted-foreground">Pages Failed</p>
            <p className="text-2xl font-semibold text-destructive">
              {state.pagesFailed}
            </p>
          </div>
          {state.durationSeconds && (
            <div className="col-span-2 space-y-1">
              <p className="text-muted-foreground">Duration</p>
              <p className="font-medium">
                {formatDuration(state.durationSeconds)}
              </p>
            </div>
          )}
        </div>

        <Separator />

        {/* Download */}
        {isCompleted && state.downloadUrl && (
          <>
            <Button asChild size="lg" className="w-full">
              <a href={getDownloadUrl(state.jobId!)}>Download EPUB</a>
            </Button>
            <EpubViewer url={getDownloadUrl(state.jobId!)} />
          </>
        )}

        {/* Error */}
        {isFailed && state.error && (
          <Alert variant="destructive">
            <AlertDescription>{state.error}</AlertDescription>
          </Alert>
        )}

        {/* Failed Pages + Retry */}
        {state.failedPages.length > 0 && (
          <div className="space-y-3">
            <h3 className="text-sm font-medium">Failed Pages</h3>
            <div className="flex flex-wrap gap-2">
              {state.failedPages.map((p) => (
                <Badge key={p} variant="destructive">
                  Page {p + 1}
                </Badge>
              ))}
            </div>
            <Button
              variant="outline"
              onClick={handleRetry}
              disabled={retrying}
              className="w-full"
            >
              {retrying ? "Retrying..." : "Retry Failed Pages"}
            </Button>
            {retryError && (
              <Alert variant="destructive">
                <AlertDescription>{retryError}</AlertDescription>
              </Alert>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
