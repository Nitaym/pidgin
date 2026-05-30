import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, type Bootstrap, type User, type Workspace } from "../api/client";

type AppContextValue = {
  loading: boolean;
  user: User | null;
  workspace: Workspace | null;
  refresh: () => Promise<void>;
  setWorkspace: (workspace: Workspace) => void;
};

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [user, setUser] = useState<User | null>(null);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);

  const refresh = useCallback(async () => {
    const data: Bootstrap = await api.bootstrap();
    setUser(data.user);
    setWorkspace(data.workspace);
  }, []);

  useEffect(() => {
    refresh()
      .catch(() => {
        setUser(null);
        setWorkspace(null);
      })
      .finally(() => setLoading(false));
  }, [refresh]);

  const value = useMemo(
    () => ({ loading, user, workspace, refresh, setWorkspace }),
    [loading, user, workspace, refresh],
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp() {
  const ctx = useContext(AppContext);
  if (!ctx) {
    throw new Error("useApp must be used within AppProvider");
  }
  return ctx;
}
