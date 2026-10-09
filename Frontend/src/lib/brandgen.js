import { API_URL, api, mediaUrl } from '../campaign/lib/api';

// The owner's brand look, served by apps/api/app/brandgen.py: a generated brand-look image, the owner's own uploaded
// logo, and a short brand-look video. Same host as the page, so the session cookie is sent.
export const getBrandLook = () => api('/brandgen');
export const generateBrandImage = (body) => api('/brandgen/image', { method: 'POST', body: JSON.stringify(body) });
export const generateBrandVideo = (body) => api('/brandgen/video', { method: 'POST', body: JSON.stringify(body) });
export const brandJob = (id) => api(`/jobs/${id}`);
export const brandUrl = (url) => mediaUrl(url);

// Multipart upload: the owner's own logo file. The server checks the magic bytes and the size.
export async function uploadLogo(file) {
  const form = new FormData();
  form.append('file', file);
  let response;
  try {
    response = await fetch(`${API_URL}/brandgen/image/upload`, { method: 'POST', body: form, credentials: 'include' });
  } catch {
    throw new Error('Cannot reach the server. Check that the API is running.');
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    throw new Error((typeof detail === 'string' ? detail : detail?.message) || 'The upload failed.');
  }
  return data;
}
