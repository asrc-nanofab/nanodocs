// Pages has a 25 MiB static-file limit; hosted PDFs live in R2.
// URL /assets/pdfs/<key> → bucket object <key> (e.g. tools/PECVD_SOP.pdf).
const PREFIX = "/assets/pdfs/";

export async function onRequestGet(context) {
  const url = new URL(context.request.url);
  if (!url.pathname.startsWith(PREFIX)) {
    return new Response("Not found", { status: 404 });
  }

  const key = decodeURIComponent(url.pathname.slice(PREFIX.length));
  if (!key || key.includes("..")) {
    return new Response("Not found", { status: 404 });
  }

  const object = await context.env.PDFS.get(key);
  if (object === null) {
    return new Response("Not found", { status: 404 });
  }

  const headers = new Headers();
  object.writeHttpMetadata(headers);
  headers.set("etag", object.httpEtag);
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/pdf");
  }
  if (!headers.has("Cache-Control")) {
    headers.set("Cache-Control", "public, max-age=86400");
  }
  return new Response(object.body, { headers });
}
