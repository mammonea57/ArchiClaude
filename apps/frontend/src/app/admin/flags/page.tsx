import { FlagsTable } from "@/components/admin/FlagsTable";

export default function AdminFlagsPage() {
  return (
    <section>
      <h2 className="text-xl mb-4">Feature flags</h2>
      <FlagsTable />
    </section>
  );
}
