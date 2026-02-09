import { type DragEvent, useCallback, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { uploadPdf } from "@/lib/api";

interface UploadZoneProps {
  onStartUpload: () => void;
  onJobCreated: (jobId: string, totalPages: number) => void;
}

export function UploadZone({ onStartUpload, onJobCreated }: UploadZoneProps) {
  const [file, setFile] = useState<File | null>(null);
  const [language, setLanguage] = useState("fa");
  const [ocrPrompt, setOcrPrompt] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback((f: File) => {
    if (f.type !== "application/pdf" && !f.name.toLowerCase().endsWith(".pdf")) {
      setError("Please select a PDF file");
      return;
    }
    setFile(f);
    setError(null);
  }, []);

  const handleDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const f = e.dataTransfer.files[0];
      if (f) handleFile(f);
    },
    [handleFile]
  );

  const handleSubmit = useCallback(async () => {
    if (!file) return;
    setUploading(true);
    setError(null);
    onStartUpload();
    try {
      const res = await uploadPdf(file, language, ocrPrompt || undefined);
      onJobCreated(res.job_id, res.total_pages);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
      setUploading(false);
    }
  }, [file, language, ocrPrompt, onStartUpload, onJobCreated]);

  return (
    <Card className="w-full max-w-2xl mx-auto">
      <CardHeader>
        <CardTitle className="text-2xl">PDF to EPUB Converter</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Drop Zone */}
        <div
          className={`border-2 border-dashed rounded-lg p-12 text-center transition-colors cursor-pointer ${
            dragOver
              ? "border-primary bg-primary/5"
              : file
                ? "border-green-500 bg-green-50"
                : "border-muted-foreground/25 hover:border-primary/50"
          }`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) handleFile(f);
            }}
          />
          {file ? (
            <div>
              <p className="font-medium text-lg">{file.name}</p>
              <p className="text-muted-foreground text-sm mt-1">
                {(file.size / (1024 * 1024)).toFixed(1)} MB
              </p>
              <p className="text-sm text-muted-foreground mt-2">
                Click or drop to replace
              </p>
            </div>
          ) : (
            <div>
              <p className="text-lg font-medium">
                Drop your scanned PDF here
              </p>
              <p className="text-muted-foreground mt-1">
                or click to browse
              </p>
            </div>
          )}
        </div>

        {/* Language Selector */}
        <div className="space-y-2">
          <label className="text-sm font-medium">Language</label>
          <Select value={language} onValueChange={setLanguage}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="fa">Persian (فارسی)</SelectItem>
              <SelectItem value="ar">Arabic (العربية)</SelectItem>
              <SelectItem value="en">English</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Custom OCR Prompt */}
        <div className="space-y-2">
          <label className="text-sm font-medium">
            Custom OCR Prompt{" "}
            <span className="text-muted-foreground font-normal">
              (optional)
            </span>
          </label>
          <Textarea
            placeholder="Leave empty to use the default prompt. You can customize the instructions given to the vision model for text extraction."
            value={ocrPrompt}
            onChange={(e) => setOcrPrompt(e.target.value)}
            rows={3}
          />
        </div>

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <Button
          onClick={handleSubmit}
          disabled={!file || uploading}
          className="w-full"
          size="lg"
        >
          {uploading ? "Uploading..." : "Start Conversion"}
        </Button>
      </CardContent>
    </Card>
  );
}
