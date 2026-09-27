import { readFile } from "node:fs/promises";
import path from "node:path";
import { diagrams } from "../diagrams";

// Read on each request, so an edited diagram shows without a rebuild; only the listed files.
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
