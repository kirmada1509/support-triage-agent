import { readFile } from "node:fs/promises";
import path from "node:path";
import { diagrams } from "../diagrams";

// Prerendered at build time, so a deployment needs ../planning only while it builds; `pnpm dev`
// still reads on each request. Only the listed files are served.
export const dynamic = "force-static";
export const dynamicParams = false;

export function generateStaticParams() {
  return diagrams.map((d) => ({ slug: d.slug }));
}

export async function GET(_request: Request, { params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const diagram = diagrams.find((d) => d.slug === slug);
  if (!diagram) return new Response("Not found", { status: 404 });
  try {
    const html = await readFile(path.join(process.cwd(), "..", "planning", diagram.file), "utf8");
    return new Response(html, { headers: { "content-type": "text/html; charset=utf-8" } });
  } catch {
    return new Response("Diagram file missing", { status: 404 });
  }
}
