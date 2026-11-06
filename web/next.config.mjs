import { ChildProcess } from "node:child_process";

// Next's cleanupWorkers calls child.kill() after the build finishes; on ARC runners
// (and some sandboxes) that throws EACCES and fails an otherwise good build. The
// workers are exiting anyway, so swallow only that error.
const kill = ChildProcess.prototype.kill;
ChildProcess.prototype.kill = function (...args) {
  try {
    return kill.apply(this, args);
  } catch (e) {
    if (e?.code === "EACCES") return false;
    throw e;
  }
};

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  // The API base is injected at runtime via NEXT_PUBLIC_API_URL.
};

export default nextConfig;
