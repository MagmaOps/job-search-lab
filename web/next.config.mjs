/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  // The API base is injected at runtime via NEXT_PUBLIC_API_URL.
  experimental: {
    // Use worker threads instead of child processes: avoids `kill EACCES`
    // in cleanupWorkers on ARC runners.
    workerThreads: true,
  },
};

export default nextConfig;
