import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { GraphList } from "./components/GraphList";
import { GraphEditor } from "./components/GraphEditor";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 10_000 } },
});

export default function App() {
  const [openGraphId, setOpenGraphId] = useState<string | null>(null);

  return (
    <QueryClientProvider client={queryClient}>
      <div style={{ fontFamily: "system-ui, sans-serif", background: "#f9fafb", minHeight: "100vh" }}>
        {openGraphId ? (
          <GraphEditor graphId={openGraphId} onBack={() => setOpenGraphId(null)} />
        ) : (
          <>
            <div
              style={{
                background: "#1e293b",
                color: "#fff",
                padding: "12px 24px",
                display: "flex",
                alignItems: "center",
                gap: 12,
              }}
            >
              <span style={{ fontWeight: 800, fontSize: 18, letterSpacing: "-0.02em" }}>
                Agent Platform
              </span>
              <span style={{ color: "#94a3b8", fontSize: 13 }}>demo</span>
            </div>
            <GraphList onOpen={(id) => setOpenGraphId(id)} />
          </>
        )}
      </div>
    </QueryClientProvider>
  );
}
