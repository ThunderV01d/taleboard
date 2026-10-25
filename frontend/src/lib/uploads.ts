/**
 * Uploading an image straight from the browser to S3.
 *
 * The API hands out a one-off presigned form (POST /projects/{id}/uploads); the file then goes directly to S3, which
 * enforces the form's limits (key, type, size). The bytes never pass through the API.
 */
import { api, unwrap } from "@/lib/api"

/** The image types the API accepts for uploads */
export const UPLOAD_TYPES = ["image/png", "image/jpeg"] as const
type UploadType = (typeof UPLOAD_TYPES)[number]

function isUploadType(type: string): type is UploadType {
  return (UPLOAD_TYPES as readonly string[]).includes(type)
}

/**
 * Uploads an image, returning its S3 key (what an image layer's `image` is set to).
 *
 * Throws, with a message to show, if the file isn't a PNG or JPEG, is too big, or the upload fails.
 */
export async function uploadImage(
  projectId: string,
  file: File
): Promise<string> {
  if (!isUploadType(file.type)) {
    throw new Error("Only PNG and JPEG images can be uploaded.")
  }
  const form = unwrap(
    await api.POST("/projects/{project_id}/uploads", {
      params: { path: { project_id: projectId } },
      body: { content_type: file.type },
    })
  )
  if (file.size > form.max_bytes) {
    throw new Error(
      `That image is ${(file.size / 1e6).toFixed(1)} MB -- the limit is ${(form.max_bytes / 1e6).toFixed(0)} MB.`
    )
  }
  const body = new FormData()
  for (const [name, value] of Object.entries(form.fields)) {
    body.append(name, value)
  }
  body.append("file", file) // Must come last -- S3 ignores fields after the file
  const response = await fetch(form.url, { method: "POST", body })
  if (!response.ok) {
    throw new Error(`The upload failed (HTTP ${response.status}).`)
  }
  return form.key
}

/**
 * An image's size in pixels, read from the file without uploading it.
 */
export async function imageSize(
  file: File
): Promise<{ width: number; height: number }> {
  const bitmap = await createImageBitmap(file)
  const size = { width: bitmap.width, height: bitmap.height }
  bitmap.close()
  return size
}
