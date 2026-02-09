import { useEffect, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import type { JobState } from "@/hooks/useJobEvents";

interface JobProgressProps {
  state: JobState;
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export function JobProgress({ state }: JobProgressProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const percent =
    state.totalPages > 0
      ? Math.round((state.pagesCompleted / state.totalPages) * 100)
      : 0;

  // ETA calculation
  const startTime = useRef(Date.now());
  useEffect(() => {
    if (state.pagesCompleted === 1) {
      startTime.current = Date.now();
    }
  }, [state.pagesCompleted]);

  const elapsed = (Date.now() - startTime.current) / 1000;
  const avgPerPage =
    state.pagesCompleted > 1 ? elapsed / (state.pagesCompleted - 1) : 0;
  const remaining = avgPerPage * (state.totalPages - state.pagesCompleted);

  // Auto-scroll to bottom
  useEffect(() => {
    const el = scrollRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [state.pageEvents.length]);

  return (
    <Card className="w-full max-w-2xl mx-auto">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-xl">
            {state.status === "assembling"
              ? "Assembling EPUB..."
              : "Processing PDF"}
          </CardTitle>
          <Badge
            variant={state.status === "assembling" ? "secondary" : "default"}
          >
            {state.status === "assembling" ? "Assembling" : "OCR in progress"}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Progress Bar */}
        <div className="space-y-2">
          <div className="flex justify-between text-sm">
            <span>
              {state.pagesCompleted} / {state.totalPages} pages
            </span>
            <span>{percent}%</span>
          </div>
          <Progress value={percent} />
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>
              {state.pagesSucceeded} succeeded
              {state.pagesFailed > 0 && (
                <span className="text-destructive">
                  {" "}
                  / {state.pagesFailed} failed
                </span>
              )}
            </span>
            {avgPerPage > 0 && state.status === "processing" && (
              <span>~{formatTime(remaining)} remaining</span>
            )}
          </div>
        </div>

        <Separator />

        {/* Live Text Feed */}
        <div className="space-y-2">
          <h3 className="text-sm font-medium">Live OCR Output</h3>
          <ScrollArea className="h-64 rounded-md border p-3">
            <div ref={scrollRef} className="space-y-3">
              {state.pageEvents.length === 0 && (
                <div className="space-y-2">
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-3/4" />
                  <Skeleton className="h-4 w-1/2" />
                </div>
              )}
              {state.pageEvents.map((evt) => (
                <div key={evt.page} className="text-sm">
                  <div className="flex items-center gap-2 mb-1">
                    <Badge
                      variant={
                        evt.status === "success" ? "default" : "destructive"
                      }
                      className="text-xs"
                    >
                      Page {evt.page + 1}
                    </Badge>
                    {evt.status === "failed" && (
                      <span className="text-xs text-destructive">
                        {evt.error}
                      </span>
                    )}
                  </div>
                  {evt.text_preview && (
                    <p
                      className="text-muted-foreground text-xs leading-relaxed pl-2 border-l-2 border-muted"
                      dir="auto"
                    >
                      {evt.text_preview}
                      {evt.text_preview.length >= 200 && "..."}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </ScrollArea>
        </div>
      </CardContent>
    </Card>
  );
}
