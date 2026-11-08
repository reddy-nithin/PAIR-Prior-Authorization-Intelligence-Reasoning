import { redirect } from "next/navigation";

/** /case/{id} opens the first case step. */
export default async function CaseIndex({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  redirect(`/case/${encodeURIComponent(decodeURIComponent(id))}/why`);
}
