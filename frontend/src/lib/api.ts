export interface CreateJobResponse {
  job_id: string;
  total_pages: number;
}

export interface JobStatus {
  id: string;
  status: "pending" | "processing" | "assembling" | "completed" | "failed";
  total_pages: number;
  pages_succeeded: number;
  pages_failed: number;
  pages_completed: number;
  failed_pages: number[];
  pdf_filename: string;
  language: string;
  created_at: number;
  started_at: number | null;
  completed_at: number | null;
  error: string | null;
}

export interface RetryResponse {
  job_id: string;
  retrying_pages: number[];
}

export async function uploadPdf(
  file: File,
  language: string,
  ocrPrompt?: string
): Promise<CreateJobResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("language", language);
  if (ocrPrompt) {
    form.append("ocr_prompt", ocrPrompt);
  }
  const res = await fetch("/api/jobs", { method: "POST", body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Upload failed");
  }
  return res.json();
}

export async function getJobStatus(jobId: string): Promise<JobStatus> {
  const res = await fetch(`/api/jobs/${jobId}`);
  if (!res.ok) throw new Error("Failed to fetch job status");
  return res.json();
}

export async function retryPages(jobId: string): Promise<RetryResponse> {
  const res = await fetch(`/api/jobs/${jobId}/retry`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Retry failed");
  }
  return res.json();
}

export function getDownloadUrl(jobId: string): string {
  return `/api/jobs/${jobId}/result`;
}
