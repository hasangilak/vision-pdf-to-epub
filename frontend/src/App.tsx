import { Button } from "@/components/ui/button";
import { UploadZone } from "@/components/UploadZone";
import { JobProgress } from "@/components/JobProgress";
import { JobResult } from "@/components/JobResult";
import { useJobEvents } from "@/hooks/useJobEvents";

function App() {
  const { state, startUpload, jobCreated, reset, connectSSE } = useJobEvents();

  const handleRetry = () => {
    if (state.jobId) {
      connectSSE(state.jobId);
    }
  };

  return (
    <div className="min-h-screen bg-background">
      <div className="container mx-auto px-4 py-8 max-w-3xl">
        <header className="text-center mb-8">
          <h1 className="text-3xl font-bold tracking-tight">
            Vision PDF to EPUB
          </h1>
          <p className="text-muted-foreground mt-2">
            Convert scanned PDFs to EPUB using AI-powered OCR
          </p>
        </header>

        {state.status === "idle" && (
          <UploadZone onStartUpload={startUpload} onJobCreated={jobCreated} />
        )}

        {state.status === "uploading" && (
          <div className="text-center py-12">
            <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
            <p className="mt-4 text-muted-foreground">Uploading PDF...</p>
          </div>
        )}

        {(state.status === "processing" || state.status === "assembling") && (
          <JobProgress state={state} />
        )}

        {(state.status === "completed" || state.status === "failed") && (
          <JobResult state={state} onRetry={handleRetry} />
        )}

        {state.status !== "idle" && state.status !== "uploading" && (
          <div className="text-center mt-6">
            <Button variant="ghost" onClick={reset}>
              Convert Another PDF
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

export default App;
