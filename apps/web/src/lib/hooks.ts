import { useEffect, useState } from "react";

export function useTheme() {
  const [dark, setDark] = useState<boolean>(() => {
    const stored = localStorage.getItem("distill-theme");
    if (stored) return stored === "dark";
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
  });

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("dark", dark);
    localStorage.setItem("distill-theme", dark ? "dark" : "light");
  }, [dark]);

  return { dark, toggle: () => setDark((value) => !value) };
}

export function useJobStream(
  jobId: string | null | undefined,
  onUpdate: (job: any) => void,
) {
  useEffect(() => {
    if (!jobId) return;
    const source = new EventSource(`/api/v1/jobs/${jobId}/events`);
    source.onmessage = (event) => {
      try {
        onUpdate(JSON.parse(event.data));
      } catch {
        // Ignore malformed keep-alive frames.
      }
    };
    source.addEventListener("end", () => source.close());
    return () => source.close();
  }, [jobId, onUpdate]);
}
