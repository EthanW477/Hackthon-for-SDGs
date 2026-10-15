import MapPanel from "@/components/MapPanel";
import SidePanel from "@/components/SidePanel";

export default function Home() {
  return (
    <main className="flex h-screen w-screen flex-col md:flex-row">
      <section className="relative min-h-[60vh] flex-1">
        <MapPanel />
      </section>
      <aside className="h-[40vh] w-full border-t md:h-screen md:w-[420px] md:border-l md:border-t-0">
        <SidePanel />
      </aside>
    </main>
  );
}
