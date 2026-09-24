export function rewriteStorageUrl(url: string | null | undefined): string {
  if (!url) return "";
  const minioHost = process.env.NEXT_PUBLIC_MINIO_HOST || "http://localhost:9000";
  return url
    .replace("http://minio:9000", minioHost)
    .replace("https://minio:9000", minioHost.replace("http", "https"));
}
