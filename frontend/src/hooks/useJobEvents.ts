import { useCallback, useEffect, useReducer, useRef } from "react";

export interface PageEvent {
  page: number;
  total_pages: number;
  status: "success" | "failed";
  text_preview?: string;
  error?: string;
}

export interface JobState {
  jobId: string | null;
  status: "idle" | "uploading" | "processing" | "assembling" | "completed" | "failed";
  totalPages: number;
  pagesCompleted: number;
  pagesSucceeded: number;
  pagesFailed: number;
  failedPages: number[];
  pageEvents: PageEvent[];
  downloadUrl: string | null;
  durationSeconds: number | null;
  error: string | null;
}

type Action =
  | { type: "UPLOAD_START" }
  | { type: "JOB_CREATED"; jobId: string; totalPages: number }
  | { type: "JOB_STARTED"; totalPages: number }
  | { type: "PAGE_COMPLETED"; event: PageEvent }
  | { type: "JOB_ASSEMBLING"; pagesSucceeded: number; pagesFailed: number }
  | {
      type: "JOB_COMPLETED";
      downloadUrl: string;
      durationSeconds: number;
      pagesSucceeded: number;
      failedPages: number[];
    }
  | { type: "JOB_FAILED"; error: string }
  | { type: "RESET" };

const initialState: JobState = {
  jobId: null,
  status: "idle",
  totalPages: 0,
  pagesCompleted: 0,
  pagesSucceeded: 0,
  pagesFailed: 0,
  failedPages: [],
  pageEvents: [],
  downloadUrl: null,
  durationSeconds: null,
  error: null,
};

function reducer(state: JobState, action: Action): JobState {
  switch (action.type) {
    case "UPLOAD_START":
      return { ...initialState, status: "uploading" };
    case "JOB_CREATED":
      return {
        ...state,
        jobId: action.jobId,
        totalPages: action.totalPages,
        status: "processing",
      };
    case "JOB_STARTED":
      return { ...state, totalPages: action.totalPages, status: "processing" };
    case "PAGE_COMPLETED": {
      const events = [...state.pageEvents, action.event];
      const succeeded =
        state.pagesSucceeded + (action.event.status === "success" ? 1 : 0);
      const failed =
        state.pagesFailed + (action.event.status === "failed" ? 1 : 0);
      return {
        ...state,
        pageEvents: events,
        pagesCompleted: succeeded + failed,
        pagesSucceeded: succeeded,
        pagesFailed: failed,
        failedPages:
          action.event.status === "failed"
            ? [...state.failedPages, action.event.page]
            : state.failedPages,
      };
    }
    case "JOB_ASSEMBLING":
      return {
        ...state,
        status: "assembling",
        pagesSucceeded: action.pagesSucceeded,
        pagesFailed: action.pagesFailed,
      };
    case "JOB_COMPLETED":
      return {
        ...state,
        status: "completed",
        downloadUrl: action.downloadUrl,
        durationSeconds: action.durationSeconds,
        pagesSucceeded: action.pagesSucceeded,
        failedPages: action.failedPages,
        pagesFailed: action.failedPages.length,
        pagesCompleted: action.pagesSucceeded + action.failedPages.length,
      };
    case "JOB_FAILED":
      return { ...state, status: "failed", error: action.error };
    case "RESET":
      return initialState;
    default:
      return state;
  }
}

export function useJobEvents() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const eventSourceRef = useRef<EventSource | null>(null);

  const connectSSE = useCallback((jobId: string) => {
    eventSourceRef.current?.close();

    const es = new EventSource(`/api/jobs/${jobId}/events`);
    eventSourceRef.current = es;

    es.addEventListener("job.started", (e) => {
      const data = JSON.parse(e.data);
      dispatch({ type: "JOB_STARTED", totalPages: data.total_pages });
    });

    es.addEventListener("page.completed", (e) => {
      const data = JSON.parse(e.data);
      dispatch({ type: "PAGE_COMPLETED", event: data });
    });

    es.addEventListener("job.assembling", (e) => {
      const data = JSON.parse(e.data);
      dispatch({
        type: "JOB_ASSEMBLING",
        pagesSucceeded: data.pages_succeeded,
        pagesFailed: data.pages_failed,
      });
    });

    es.addEventListener("job.completed", (e) => {
      const data = JSON.parse(e.data);
      dispatch({
        type: "JOB_COMPLETED",
        downloadUrl: data.download_url,
        durationSeconds: data.duration_seconds,
        pagesSucceeded: data.pages_succeeded,
        failedPages: data.failed_pages,
      });
      es.close();
    });

    es.addEventListener("job.failed", (e) => {
      const data = JSON.parse(e.data);
      dispatch({ type: "JOB_FAILED", error: data.error });
      es.close();
    });

    es.onerror = () => {
      // EventSource auto-reconnects, but if the connection is closed
      // permanently (readyState === CLOSED), we don't retry.
      if (es.readyState === EventSource.CLOSED) {
        es.close();
      }
    };
  }, []);

  useEffect(() => {
    return () => {
      eventSourceRef.current?.close();
    };
  }, []);

  const startUpload = useCallback(() => {
    dispatch({ type: "UPLOAD_START" });
  }, []);

  const jobCreated = useCallback(
    (jobId: string, totalPages: number) => {
      dispatch({ type: "JOB_CREATED", jobId, totalPages });
      connectSSE(jobId);
    },
    [connectSSE]
  );

  const reset = useCallback(() => {
    eventSourceRef.current?.close();
    dispatch({ type: "RESET" });
  }, []);

  return { state, startUpload, jobCreated, reset, connectSSE };
}
