"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

// The running backend's release version, fetched once per page load. Renders nothing if
// the API is unreachable, so the header never shows a broken value.
export default function AppVersion() {
  const [version, setVersion] = useState<string | null>(null);

  useEffect(() => {
    api.version().then((v) => setVersion(v.version)).catch(() => setVersion(null));
  }, []);

  if (!version) return null;
  return <span className="app-version" title="Running backend version">v{version}</span>;
}
