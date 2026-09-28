// Attachments go straight from the browser to object storage (decision 7):
//   1. POST …/attachments       the API records the file and signs a PUT for exactly this
//                               name, type and size
//   2. PUT <signed url>         the bytes go to storage, never through the API
//   3. POST …/confirm           the API queues the check (type sniffing, virus scan)
//   4. GET  attachments/{id}    until READY or REJECTED

import { ApiError, get, idempotencyKey, post } from "./api";
import type { Attachment, AttachmentCreated } from "./types";

export const MAX_BYTES = 10 * 1024 * 1024;
export const TYPES = ["application/pdf", "image/jpeg", "image/png"];

export type Problem = "size" | "type";

export function check(file: File): Problem | null {
  if (!TYPES.includes(file.type)) return "type";
  if (file.size > MAX_BYTES || file.size === 0) return "size";
  return null;
}

function put(url: string, headers: Record<string, string>, file: File, onProgress: (f: number) => void) {
  return new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    for (const [k, v] of Object.entries(headers)) {
      // The browser sets Content-Length itself and refuses to be told.
      if (k.toLowerCase() !== "content-length") xhr.setRequestHeader(k, v);
    }
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => (xhr.status < 300 ? resolve() : reject(new ApiError(xhr.status, "UPLOAD_FAILED", "")));
    xhr.onerror = () => reject(new ApiError(0, "NETWORK", ""));
    xhr.send(file);
  });
}

export async function upload(
  requestId: string,
  file: File,
  onProgress: (fraction: number) => void,
): Promise<Attachment> {
  const created = await post<AttachmentCreated>(
    `requests/${requestId}/attachments`,
    { file_name: file.name, content_type: file.type, size: file.size },
    { headers: { "Idempotency-Key": idempotencyKey() } },
  );
  await put(created.upload.url, { "Content-Type": file.type, ...created.upload.headers }, file, onProgress);
  return post<Attachment>(`attachments/${created.id}/confirm`);
}

/** Poll until the checker has decided (or give up after about a minute). */
export async function settled(id: string, tries = 30): Promise<Attachment> {
  let last = await get<Attachment>(`attachments/${id}`);
  for (let i = 0; i < tries && (last.status === "PENDING" || last.status === "VERIFYING"); i++) {
    await new Promise((r) => setTimeout(r, 2000));
    last = await get<Attachment>(`attachments/${id}`);
  }
  return last;
}
