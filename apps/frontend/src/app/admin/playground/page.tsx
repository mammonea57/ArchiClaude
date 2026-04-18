import { Playground } from "@/components/admin/Playground";

export default function PlaygroundPage() {
  return (
    <section>
      <h2 className="text-xl font-serif mb-2">Playground extraction PLU</h2>
      <p className="text-sm text-slate-500 mb-6">
        Testez l&apos;extraction de règles PLU pour n&apos;importe quelle commune et zone,
        avec ou sans URL PDF fournie.
      </p>
      <div className="max-w-2xl rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <Playground />
      </div>
    </section>
  );
}
