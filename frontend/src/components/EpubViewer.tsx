import { useState } from "react";
import { ReactReader } from "react-reader";
import { Button } from "@/components/ui/button";

interface EpubViewerProps {
  url: string;
}

export function EpubViewer({ url }: EpubViewerProps) {
  const [location, setLocation] = useState<string | number>(0);
  const [show, setShow] = useState(false);

  if (!show) {
    return (
      <Button variant="outline" className="w-full" onClick={() => setShow(true)}>
        Preview EPUB in Browser
      </Button>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex justify-between items-center">
        <h3 className="text-sm font-medium">EPUB Preview</h3>
        <Button variant="ghost" size="sm" onClick={() => setShow(false)}>
          Close Preview
        </Button>
      </div>
      <div className="h-[600px] border rounded-lg overflow-hidden">
        <ReactReader
          url={url}
          location={location}
          locationChanged={(loc: string) => setLocation(loc)}
          epubOptions={{
            allowPopups: true,
            allowScriptedContent: true,
          }}
        />
      </div>
    </div>
  );
}
