"use client";

import { TransactionProvider } from "./context/TransactionContext";

export function Providers({ children }: { children: React.ReactNode }) {
  return <TransactionProvider>{children}</TransactionProvider>;
}
